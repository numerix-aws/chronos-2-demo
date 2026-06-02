import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { FrontendStack } from '../lib/frontend-stack';
import { ApiStack } from '../lib/api-stack';
import { ToolsStack } from '../lib/tools-stack';
import { StorageStack } from '../lib/storage-stack';
import { NetworkStack } from '../lib/network-stack';
import { AgentStack } from '../lib/agent-stack';

function build() {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
  });
  const agent = new AgentStack(app, 'Agent', { tools });
  const api = new ApiStack(app, 'Api', { tools, agent });
  const fe = new FrontendStack(app, 'Frontend', { api });
  return { fe, t: Template.fromStack(fe) };
}

test('creates one Amplify app + one main branch', () => {
  const { t } = build();
  t.resourceCountIs('AWS::Amplify::App', 1);
  t.resourceCountIs('AWS::Amplify::Branch', 1);
});

test('main branch is set to manual deploy', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Amplify::Branch', {
    BranchName: 'main',
    Stage: 'PRODUCTION',
  });
});

test('environment variables include VITE_API_URL and VITE_STREAM_URL', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Amplify::App', {
    EnvironmentVariables: Match.arrayWith([
      Match.objectLike({ Name: 'VITE_API_URL' }),
      Match.objectLike({ Name: 'VITE_STREAM_URL' }),
    ]),
  });
});

test('exposes appId and defaultDomain', () => {
  const { fe } = build();
  expect(fe.appId).toBeDefined();
  expect(fe.defaultDomain).toBeDefined();
});
