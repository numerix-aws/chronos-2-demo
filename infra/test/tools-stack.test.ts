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
    chronos2EndpointName: 'chronos2-demo-ep',
  });
  return Template.fromStack(tools);
}

test('creates 9 Python Lambdas + 1 Node authorizer', () => {
  const t = build();
  // 9 Python tool Lambdas (load_data, blend_paths, price_book, plot,
  // lookup_use_case, run_chronos2 launcher, check_chronos2, run_baseline_mc
  // launcher, check_baseline_mc) + 1 Node authorizer = 10. Allow >= 10 to
  // absorb CDK custom-resource Lambdas.
  const fns = t.findResources('AWS::Lambda::Function');
  expect(Object.keys(fns).length).toBeGreaterThanOrEqual(10);
});

test('creates one ECS cluster + two Fargate task definitions', () => {
  const t = build();
  t.resourceCountIs('AWS::ECS::Cluster', 1);
  // baseline_mc + chronos2
  t.resourceCountIs('AWS::ECS::TaskDefinition', 2);
});

test('creates two ECR repositories with image scan on push', () => {
  const t = build();
  t.resourceCountIs('AWS::ECR::Repository', 2);
  t.hasResourceProperties('AWS::ECR::Repository', Match.objectLike({
    ImageScanningConfiguration: { ScanOnPush: true },
  }));
});

test('creates the three tiered Lambda layers for chronos2_demo', () => {
  const t = build();
  // light (source-only), base (+numpy/pandas/pyarrow), plot (+matplotlib).
  // Split to stay under Lambda's 250 MB code+layers unzipped cap.
  t.resourceCountIs('AWS::Lambda::LayerVersion', 3);
});

test('exposes lambda function references', () => {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
    chronos2EndpointName: 'chronos2-demo-ep',
  });
  expect(tools.fnLoadData).toBeDefined();
  expect(tools.fnBlendPaths).toBeDefined();
  expect(tools.fnPriceBook).toBeDefined();
  expect(tools.fnPlot).toBeDefined();
  expect(tools.fnLookupUseCase).toBeDefined();
  expect(tools.fnRunChronos2).toBeDefined();
  expect(tools.fnCheckChronos2).toBeDefined();
  expect(tools.fnRunBaselineMc).toBeDefined();
  expect(tools.fnCheckBaselineMc).toBeDefined();
  expect(tools.fnAuthorizer).toBeDefined();
  expect(tools.coreLayer).toBeDefined();
  expect(tools.apiKeySecretArn).toBeDefined();
  expect(tools.baselineMcTaskDef).toBeDefined();
  expect(tools.baselineMcCluster).toBeDefined();
  expect(tools.chronos2TaskDef).toBeDefined();
});
