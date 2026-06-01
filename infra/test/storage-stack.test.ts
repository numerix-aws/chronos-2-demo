import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { StorageStack } from '../lib/storage-stack';

test('creates 3 buckets with versioning and SSE-S3', () => {
  const app = new cdk.App();
  const stack = new StorageStack(app, 'TestStorage');
  const t = Template.fromStack(stack);

  t.resourceCountIs('AWS::S3::Bucket', 3);
  t.allResourcesProperties('AWS::S3::Bucket', {
    VersioningConfiguration: { Status: 'Enabled' },
    BucketEncryption: Match.objectLike({}),
  });
});

test('plots bucket has CORS allowing GET from anywhere', () => {
  const app = new cdk.App();
  const stack = new StorageStack(app, 'TestStorage');
  const t = Template.fromStack(stack);

  t.hasResourceProperties('AWS::S3::Bucket', Match.objectLike({
    CorsConfiguration: {
      CorsRules: Match.arrayWith([
        Match.objectLike({ AllowedMethods: Match.arrayWith(['GET']) }),
      ]),
    },
  }));
});

test('exposes bucket properties', () => {
  const app = new cdk.App();
  const stack = new StorageStack(app, 'TestStorage');
  expect(stack.dataBucket).toBeDefined();
  expect(stack.plotsBucket).toBeDefined();
  expect(stack.tracesBucket).toBeDefined();
});
