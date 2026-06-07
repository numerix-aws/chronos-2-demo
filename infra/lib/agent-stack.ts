import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as path from 'path';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import { ToolsStack } from './tools-stack';

export interface AgentStackProps extends cdk.StackProps {
  readonly tools: ToolsStack;
}

const MODEL_ID = 'us.anthropic.claude-sonnet-4-6';

const TOOL_OPERATIONS: Array<{ name: string; opId: string; getFn: (t: ToolsStack) => lambda.IFunction }> = [
  { name: 'LoadData', opId: 'load_data', getFn: (t) => t.fnLoadData },
  { name: 'RunBaselineMc', opId: 'run_baseline_mc', getFn: (t) => t.fnRunBaselineMc },
  { name: 'CheckBaselineMc', opId: 'check_baseline_mc', getFn: (t) => t.fnCheckBaselineMc },
  { name: 'RunChronos2', opId: 'run_chronos2', getFn: (t) => t.fnRunChronos2 },
  { name: 'CheckChronos2', opId: 'check_chronos2', getFn: (t) => t.fnCheckChronos2 },
  { name: 'BlendPaths', opId: 'blend_paths', getFn: (t) => t.fnBlendPaths },
  { name: 'PriceBook', opId: 'price_book', getFn: (t) => t.fnPriceBook },
  { name: 'Plot', opId: 'plot', getFn: (t) => t.fnPlot },
  { name: 'LookupUseCase', opId: 'lookup_use_case', getFn: (t) => t.fnLookupUseCase },
];

function toolSchemaFor(opId: string, openapi: any) {
  const op = openapi.paths[`/${opId}`].post;
  const input = op.requestBody.content['application/json'].schema;
  const ok = op.responses['200']?.content?.['application/json']?.schema;
  const tool: any = { name: opId, description: op.summary ?? opId, inputSchema: input };
  if (ok) tool.outputSchema = ok;
  return tool;
}

export class AgentStack extends cdk.Stack {
  public readonly gatewayUrl: string;
  public readonly runtimeArn: string;
  public readonly runtimeEndpointArn: string;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '..', '..');
    const openapi = JSON.parse(
      fs.readFileSync(path.join(repoRoot, 'agent', 'action_groups.json'), 'utf-8'),
    );

    const gatewayRole = new iam.Role(this, 'GatewayRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });
    for (const { getFn } of TOOL_OPERATIONS) {
      getFn(props.tools).grantInvoke(gatewayRole);
    }

    const gateway = new agentcore.CfnGateway(this, 'Gateway', {
      name: 'chronos2-demo-gateway',
      protocolType: 'MCP',
      authorizerType: 'AWS_IAM',
      roleArn: gatewayRole.roleArn,
    });

    for (const { name, opId, getFn } of TOOL_OPERATIONS) {
      const fn = getFn(props.tools);
      // GatewayTarget Name must match ^([0-9a-zA-Z][-]?){1,100}$ (no underscores),
      // so hyphenate the opId for the resource name. The MCP tool the agent calls
      // is the inline-schema `name` (still the underscored opId) — unaffected.
      const target = new agentcore.CfnGatewayTarget(this, `Target${name}`, {
        name: opId.replace(/_/g, '-'),
        gatewayIdentifier: gateway.attrGatewayIdentifier,
        targetConfiguration: {
          mcp: {
            lambda: {
              lambdaArn: fn.functionArn,
              toolSchema: { inlinePayload: [toolSchemaFor(opId, openapi)] },
            },
          },
        },
        credentialProviderConfigurations: [
          { credentialProviderType: 'GATEWAY_IAM_ROLE' },
        ],
      });
      target.addDependency(gateway);
    }

    // The runtime image repo lives in ToolsStack so the image can be pushed
    // before this stack's Runtime validates it at create time.
    const agentRepo = props.tools.agentRuntimeRepo;

    const runtimeRole = new iam.Role(this, 'RuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });
    // AgentCore pulls the runtime container image under this role.
    agentRepo.grantPull(runtimeRole);
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ecr:GetAuthorizationToken'],
      resources: ['*'], // GetAuthorizationToken does not support resource scoping
    }));
    // MODEL_ID is a cross-region inference profile (us.anthropic.claude-sonnet-4-6).
    // Invoking it requires both the profile ARN (account-scoped) and the underlying
    // foundation-model ARNs in every region the profile can route to.
    const FM_ID = MODEL_ID.replace(/^us\./, ''); // anthropic.claude-sonnet-4-6
    const PROFILE_REGIONS = ['us-east-1', 'us-east-2', 'us-west-2'];
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [
        `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/${MODEL_ID}`,
        ...PROFILE_REGIONS.map((r) => `arn:aws:bedrock:${r}::foundation-model/${FM_ID}`),
      ],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeGateway', 'bedrock-agentcore:GetGateway'],
      resources: [gateway.attrGatewayArn],
    }));
    // Standard AgentCore Runtime execution-role permissions (per the AgentCore
    // runtime-permissions guide). Without the workload-access-token grant the
    // runtime 500s on every invoke; without the logs grant it emits no logs.
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'bedrock-agentcore:GetWorkloadAccessToken',
        'bedrock-agentcore:GetWorkloadAccessTokenForJWT',
        'bedrock-agentcore:GetWorkloadAccessTokenForUserId',
      ],
      resources: [
        `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
        `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/*`,
      ],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents',
        'logs:DescribeLogStreams', 'logs:DescribeLogGroups',
      ],
      resources: [
        `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`,
        `arn:aws:logs:${this.region}:${this.account}:log-group:*`,
      ],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'xray:PutTraceSegments', 'xray:PutTelemetryRecords',
        'xray:GetSamplingRules', 'xray:GetSamplingTargets',
      ],
      resources: ['*'],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['cloudwatch:PutMetricData'],
      resources: ['*'],
      conditions: { StringEquals: { 'cloudwatch:namespace': 'bedrock-agentcore' } },
    }));

    const runtime = new agentcore.CfnRuntime(this, 'Runtime', {
      agentRuntimeName: 'chronos2_demo_copilot',
      roleArn: runtimeRole.roleArn,
      networkConfiguration: { networkMode: 'PUBLIC' },
      agentRuntimeArtifact: {
        containerConfiguration: { containerUri: `${agentRepo.repositoryUri}:latest` },
      },
      environmentVariables: { GATEWAY_URL: gateway.attrGatewayUrl, MODEL_ID },
    });
    runtime.addDependency(gateway);
    // The Runtime validates its ECR image at create time by assuming the
    // RuntimeRole, so the role's inline pull policy (RuntimeRole/DefaultPolicy)
    // must exist first. Without this, CFN races them and the Runtime fails with
    // an ECR AccessDenied. node.addDependency waits for the role + its policies.
    runtime.node.addDependency(runtimeRole);

    const endpoint = new agentcore.CfnRuntimeEndpoint(this, 'RuntimeEndpoint', {
      agentRuntimeId: runtime.attrAgentRuntimeId,
      name: 'live',
    });
    endpoint.addDependency(runtime);

    this.gatewayUrl = gateway.attrGatewayUrl;
    this.runtimeArn = runtime.attrAgentRuntimeArn;
    this.runtimeEndpointArn = endpoint.ref;

    new cdk.CfnOutput(this, 'GatewayUrlOut', { value: this.gatewayUrl });
    new cdk.CfnOutput(this, 'RuntimeArnOut', { value: this.runtimeArn });
    new cdk.CfnOutput(this, 'AgentRepoUriOut', { value: agentRepo.repositoryUri });
  }
}
