import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';

function build() {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
    chronos2EndpointName: 'chronos2-demo-endpoint',
  });
  return Template.fromStack(tools);
}

test('creates 8 Python Lambdas + 1 Node authorizer', () => {
  const t = build();
  // 8 Python tool Lambdas (load_data, blend_paths, price_book, plot,
  // lookup_use_case, run_chronos2, run_baseline_mc launcher, check_baseline_mc)
  // + 1 Node authorizer = 9. Allow >= 9 to absorb CDK custom-resource Lambdas.
  const fns = t.findResources('AWS::Lambda::Function');
  expect(Object.keys(fns).length).toBeGreaterThanOrEqual(9);
});

test('creates an ECS cluster + Fargate task definition', () => {
  const t = build();
  t.resourceCountIs('AWS::ECS::Cluster', 1);
  t.resourceCountIs('AWS::ECS::TaskDefinition', 1);
});

test('creates an ECR repository with image scan on push', () => {
  const t = build();
  t.hasResourceProperties('AWS::ECR::Repository', Match.objectLike({
    ImageScanningConfiguration: { ScanOnPush: true },
  }));
});

test('creates the Lambda layer for chronos2_demo', () => {
  const t = build();
  t.resourceCountIs('AWS::Lambda::LayerVersion', 1);
});

test('exposes lambda function references', () => {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
    chronos2EndpointName: 'chronos2-demo-endpoint',
  });
  expect(tools.fnLoadData).toBeDefined();
  expect(tools.fnBlendPaths).toBeDefined();
  expect(tools.fnPriceBook).toBeDefined();
  expect(tools.fnPlot).toBeDefined();
  expect(tools.fnLookupUseCase).toBeDefined();
  expect(tools.fnRunChronos2).toBeDefined();
  expect(tools.fnRunBaselineMc).toBeDefined();
  expect(tools.fnCheckBaselineMc).toBeDefined();
  expect(tools.fnAuthorizer).toBeDefined();
  expect(tools.coreLayer).toBeDefined();
  expect(tools.apiKeySecretArn).toBeDefined();
  expect(tools.baselineMcTaskDef).toBeDefined();
  expect(tools.baselineMcCluster).toBeDefined();
});
