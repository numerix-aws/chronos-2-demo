import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { AgentStack } from '../lib/agent-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';
import { NetworkStack } from '../lib/network-stack';

function build(): { agent: AgentStack; t: Template } {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
  });
  const agent = new AgentStack(app, 'Agent', { tools });
  return { agent, t: Template.fromStack(agent) };
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

test('exposes gatewayUrl, runtimeArn, runtimeEndpointArn', () => {
  const { agent } = build();
  expect(agent.gatewayUrl).toBeDefined();
  expect(agent.runtimeArn).toBeDefined();
  expect(agent.runtimeEndpointArn).toBeDefined();
});
