import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { NetworkStack } from '../lib/network-stack';

test('creates a VPC with public and private subnets across 2 AZs', () => {
  const app = new cdk.App();
  const stack = new NetworkStack(app, 'TestNetwork');
  const t = Template.fromStack(stack);

  t.resourceCountIs('AWS::EC2::VPC', 1);
  // 2 AZs × (public + private) = 4 subnets.
  t.resourceCountIs('AWS::EC2::Subnet', 4);
  t.resourceCountIs('AWS::EC2::NatGateway', 1);
});

test('exposes vpc as a public property', () => {
  const app = new cdk.App();
  const stack = new NetworkStack(app, 'TestNetwork');
  expect(stack.vpc).toBeDefined();
});
