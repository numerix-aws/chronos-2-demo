#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';
import { AgentStack } from '../lib/agent-stack';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1' };
const demoTag = app.node.tryGetContext('demoTag') ?? 'chronos2-demo';
const chronos2EndpointName = process.env.CHRONOS2_ENDPOINT_NAME ?? 'chronos2-demo-endpoint';

cdk.Tags.of(app).add('Project', demoTag);
cdk.Tags.of(app).add('chronos2-demo:teardown', 'on');

const network = new NetworkStack(app, 'Chronos2DemoNetwork', { env });
const storage = new StorageStack(app, 'Chronos2DemoStorage', { env });
const tools = new ToolsStack(app, 'Chronos2DemoTools', {
  env,
  vpc: network.vpc,
  dataBucket: storage.dataBucket,
  plotsBucket: storage.plotsBucket,
  chronos2EndpointName,
});

const agentStack = new AgentStack(app, 'Chronos2DemoAgent', {
  env,
  tools,
});
agentStack.addDependency(tools);

app.synth();
