import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as path from 'path';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import { ToolsStack } from './tools-stack';

export interface AgentStackProps extends cdk.StackProps {
  readonly tools: ToolsStack;
}

const MODEL_ID = 'anthropic.claude-3-5-sonnet-20241022-v2:0';

const TOOL_OPERATIONS: Array<{ name: string; opId: string; getFn: (t: ToolsStack) => lambda.IFunction }> = [
  { name: 'LoadData', opId: 'load_data', getFn: (t) => t.fnLoadData },
  { name: 'RunBaselineMc', opId: 'run_baseline_mc', getFn: (t) => t.fnRunBaselineMc },
  { name: 'CheckBaselineMc', opId: 'check_baseline_mc', getFn: (t) => t.fnCheckBaselineMc },
  { name: 'RunChronos2', opId: 'run_chronos2', getFn: (t) => t.fnRunChronos2 },
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
      const target = new agentcore.CfnGatewayTarget(this, `Target${name}`, {
        name: opId,
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

    const agentRepo = new ecr.Repository(this, 'AgentRuntimeRepo', {
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });

    const runtimeRole = new iam.Role(this, 'RuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [`arn:aws:bedrock:${this.region}::foundation-model/${MODEL_ID}`],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeGateway', 'bedrock-agentcore:GetGateway'],
      resources: [gateway.attrGatewayArn],
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
