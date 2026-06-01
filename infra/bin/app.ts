#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1' };
const demoTag = app.node.tryGetContext('demoTag') ?? 'chronos2-demo';

cdk.Tags.of(app).add('Project', demoTag);
cdk.Tags.of(app).add('chronos2-demo:teardown', 'on');

// Stacks added in Stage 1 onward.

app.synth();
