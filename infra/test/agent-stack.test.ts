import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { AgentStack } from '../lib/agent-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';
import { NetworkStack } from '../lib/network-stack';

const IMAGE_TAG = '0123456789abcdef0123456789abcdef01234567';
const PROVENANCE = {
  market_snapshot_id: 'market-v1',
  market_sha256: 'a'.repeat(64),
  covariate_snapshot_id: 'covariates-v1',
  covariate_sha256: 'b'.repeat(64),
  chronos_endpoint: 'chronos2-demo-ep',
  chronos_model_version: 'chronos-2',
  baseline_image_digest: `sha256:${'c'.repeat(64)}`,
  chronos_image_digest: `sha256:${'d'.repeat(64)}`,
  agent_image_digest: `sha256:${'e'.repeat(64)}`,
  book_version: 'cross_asset_demo_v1',
  blend_version: 'importance_weight_v1',
  pricing_version: 'cross_asset_v1',
  tool_bundle_version: `git:${IMAGE_TAG}`,
  strands_version: '1.30.0',
};

beforeAll(() => {
  jest.spyOn(lambda.Code, 'fromAsset').mockImplementation(
    () => lambda.Code.fromCfnParameters() as unknown as ReturnType<typeof lambda.Code.fromAsset>,
  );
});

afterAll(() => jest.restoreAllMocks());

function build(): { agent: AgentStack; t: Template } {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
    baselineImageTag: IMAGE_TAG,
    chronosImageTag: IMAGE_TAG,
  });
  const agent = new AgentStack(app, 'Agent', {
    tools,
    agentImageTag: IMAGE_TAG,
    provenance: PROVENANCE,
  });
  return { agent, t: Template.fromStack(agent) };
}

function resourceByPrefix(t: Template, type: string, prefix: string): any {
  const resource = Object.entries(t.findResources(type))
    .find(([logicalId]) => logicalId.startsWith(prefix));
  expect(resource).toBeDefined();
  return resource![1];
}

test('creates one AgentCore Gateway (MCP)', () => {
  const { t } = build();
  t.resourceCountIs('AWS::BedrockAgentCore::Gateway', 1);
  t.hasResourceProperties('AWS::BedrockAgentCore::Gateway', {
    ProtocolType: 'MCP',
  });
});

test('creates one gateway target per tool (9)', () => {
  const { t } = build();
  t.resourceCountIs('AWS::BedrockAgentCore::GatewayTarget', 9);
});

test('creates a containerized Runtime + endpoint', () => {
  const { t } = build();
  t.resourceCountIs('AWS::BedrockAgentCore::Runtime', 1);
  t.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 1);
});

test('runtime role can invoke the model and the gateway', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::IAM::Policy', {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({ Action: Match.arrayWith(['bedrock:InvokeModel']) }),
      ]),
    },
  });
});

test('runtime role can only read and create immutable run manifests in data runs prefix', () => {
  const { t } = build();
  const policy = resourceByPrefix(
    t,
    'AWS::IAM::Policy',
    'RuntimeRoleDefaultPolicy',
  );
  const statements = policy.Properties.PolicyDocument.Statement;
  const runStatement = statements.find(
    (statement: any) => JSON.stringify(statement.Resource).includes('/runs/*'),
  );

  expect(runStatement).toBeDefined();
  expect([...runStatement.Action].sort()).toEqual(['s3:GetObject', 's3:PutObject']);
  expect(JSON.stringify(statements)).not.toContain('s3:HeadObject');
});

test('runtime receives complete pinned provenance and the data bucket', () => {
  const { t } = build();
  const runtime = resourceByPrefix(t, 'AWS::BedrockAgentCore::Runtime', 'Runtime');
  const environment = runtime.Properties.EnvironmentVariables;

  expect(environment.DATA_BUCKET).toBeDefined();
  expect(environment.STRANDS_VERSION).toBe('1.30.0');
  expect(environment.POLL_MAX_ATTEMPTS).toBe('300');
  expect(environment.POLL_INTERVAL_SECONDS).toBe('2');
  expect(environment.POLL_BUDGET_SECONDS).toBe('600');
  expect(environment.GATEWAY_READ_TIMEOUT_SECONDS).toBe('90');
  expect(environment.BASELINE_IMAGE_DIGEST).toBe(PROVENANCE.baseline_image_digest);
  expect(environment.CHRONOS_IMAGE_DIGEST).toBe(PROVENANCE.chronos_image_digest);
  expect(environment.AGENT_IMAGE_DIGEST).toBe(PROVENANCE.agent_image_digest);
  for (const value of Object.values(environment)) {
    expect(value).not.toBe('');
  }
});

test('uses the selected immutable tag for the AgentCore image', () => {
  const { t } = build();
  const runtime = resourceByPrefix(t, 'AWS::BedrockAgentCore::Runtime', 'Runtime');
  const image = JSON.stringify(
    runtime.Properties.AgentRuntimeArtifact.ContainerConfiguration.ContainerUri,
  );

  expect(image).toContain(IMAGE_TAG);
  expect(JSON.stringify(t.toJSON())).not.toContain(':latest');
});

test('exposes gatewayUrl, runtimeArn, runtimeEndpointArn', () => {
  const { agent } = build();
  expect(agent.gatewayUrl).toBeDefined();
  expect(agent.runtimeArn).toBeDefined();
  expect(agent.runtimeEndpointArn).toBeDefined();
});
