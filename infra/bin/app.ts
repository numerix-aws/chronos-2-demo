#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';
import { AgentStack } from '../lib/agent-stack';
import { ApiStack } from '../lib/api-stack';
import { FrontendStack } from '../lib/frontend-stack';
import { ObservabilityStack } from '../lib/observability-stack';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1' };
const demoTag = app.node.tryGetContext('demoTag') ?? 'chronos2-demo';
const chronos2EndpointName = process.env.CHRONOS2_ENDPOINT_NAME ?? 'chronos2-demo-ep';
const imageTag = app.node.tryGetContext('imageTag') ?? process.env.IMAGE_TAG;
if (!imageTag || !/^[0-9a-f]{7,40}$/.test(imageTag)) {
  throw new Error('Pass an immutable git SHA with -c imageTag=<git-sha> or IMAGE_TAG');
}

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Set required deployment provenance ${name}`);
  return value;
}

function requiredSha256(name: string): string {
  const value = requiredEnv(name);
  if (!/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${name} must be a lowercase SHA-256 hex value`);
  }
  return value;
}

function requiredImageDigest(name: string): string {
  const value = requiredEnv(name);
  if (!/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${name} must be an immutable sha256 image digest`);
  }
  return value;
}

const provenance = {
  market_snapshot_id: requiredEnv('MARKET_SNAPSHOT_ID'),
  market_sha256: requiredSha256('MARKET_SHA256'),
  covariate_snapshot_id: requiredEnv('COVARIATE_SNAPSHOT_ID'),
  covariate_sha256: requiredSha256('COVARIATE_SHA256'),
  chronos_endpoint: chronos2EndpointName,
  chronos_model_version: requiredEnv('CHRONOS_MODEL_VERSION'),
  baseline_image_digest: requiredImageDigest('BASELINE_IMAGE_DIGEST'),
  chronos_image_digest: requiredImageDigest('CHRONOS_IMAGE_DIGEST'),
  agent_image_digest: requiredImageDigest('AGENT_IMAGE_DIGEST'),
  book_version: requiredEnv('BOOK_VERSION'),
  blend_version: requiredEnv('BLEND_VERSION'),
  pricing_version: requiredEnv('PRICING_VERSION'),
  tool_bundle_version: requiredEnv('TOOL_BUNDLE_VERSION'),
  strands_version: '1.30.0',
};

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
  baselineImageTag: imageTag,
  chronosImageTag: imageTag,
});

const agentStack = new AgentStack(app, 'Chronos2DemoAgent', {
  env,
  tools,
  agentImageTag: imageTag,
  provenance,
});
agentStack.addDependency(tools);

const apiStack = new ApiStack(app, 'Chronos2DemoApi', {
  env,
  tools,
  agent: agentStack,
});
apiStack.addDependency(agentStack);

const frontendStack = new FrontendStack(app, 'Chronos2DemoFrontend', {
  env,
  api: apiStack,
});
frontendStack.addDependency(apiStack);

const obsStack = new ObservabilityStack(app, 'Chronos2DemoObservability', {
  env,
  tools,
  api: apiStack,
});
obsStack.addDependency(apiStack);

app.synth();
