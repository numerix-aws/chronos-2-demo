import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';

const IMAGE_TAG = '0123456789abcdef0123456789abcdef01234567';

beforeAll(() => {
  jest.spyOn(lambda.Code, 'fromAsset').mockImplementation(
    () => lambda.Code.fromCfnParameters() as unknown as ReturnType<typeof lambda.Code.fromAsset>,
  );
});

afterAll(() => jest.restoreAllMocks());

let cachedTemplate: Template | undefined;

function build() {
  if (cachedTemplate) return cachedTemplate;
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
    chronos2EndpointName: 'chronos2-demo-ep',
    baselineImageTag: IMAGE_TAG,
    chronosImageTag: IMAGE_TAG,
  });
  cachedTemplate = Template.fromStack(tools);
  return cachedTemplate;
}

function resourceByPrefix(t: Template, type: string, prefix: string): any {
  const resource = Object.entries(t.findResources(type))
    .find(([logicalId]) => logicalId.startsWith(prefix));
  expect(resource).toBeDefined();
  return resource![1];
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

test('creates three ECR repositories with image scan on push', () => {
  const t = build();
  // baseline_mc, chronos2, and the AgentCore runtime repo (moved here from
  // AgentStack so the image can be pushed before the Runtime validates it).
  t.resourceCountIs('AWS::ECR::Repository', 3);
  t.hasResourceProperties('AWS::ECR::Repository', Match.objectLike({
    ImageScanningConfiguration: { ScanOnPush: true },
    ImageTagMutability: 'IMMUTABLE',
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
    baselineImageTag: IMAGE_TAG,
    chronosImageTag: IMAGE_TAG,
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
  expect(tools.dataBucket).toBe(storage.dataBucket);
});

test('uses the selected immutable tag for both quantitative images', () => {
  const t = build();
  const taskDefinitions = Object.values(t.findResources('AWS::ECS::TaskDefinition'));
  const images = taskDefinitions.flatMap(
    (resource: any) => resource.Properties.ContainerDefinitions.map(
      (container: any) => JSON.stringify(container.Image),
    ),
  );

  expect(images).toHaveLength(2);
  expect(images.every((image) => image.includes(IMAGE_TAG))).toBe(true);
  expect(JSON.stringify(t.toJSON())).not.toContain(':latest');
});

test('preserves lookup_use_case Lambda packaging', () => {
  const t = build();
  const lookup = resourceByPrefix(t, 'AWS::Lambda::Function', 'LookupUseCase');

  expect(lookup).toBeDefined();
});

test('configures both Fargate poll Lambdas with the App container name', () => {
  const t = build();
  const baseline = resourceByPrefix(t, 'AWS::Lambda::Function', 'CheckBaselineMc');
  const chronos = resourceByPrefix(t, 'AWS::Lambda::Function', 'CheckChronos2');

  expect(baseline.Properties.Environment.Variables.CONTAINER_NAME).toBe('App');
  expect(chronos.Properties.Environment.Variables.CONTAINER_NAME).toBe('App');
});

test('grants both Fargate poll Lambdas read access to run artifacts', () => {
  const t = build();
  const baselinePolicy = resourceByPrefix(
    t,
    'AWS::IAM::Policy',
    'CheckBaselineMcServiceRoleDefaultPolicy',
  );
  const chronosPolicy = resourceByPrefix(
    t,
    'AWS::IAM::Policy',
    'CheckChronos2ServiceRoleDefaultPolicy',
  );

  for (const policy of [baselinePolicy, chronosPolicy]) {
    expect(policy.Properties.PolicyDocument.Statement).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          Action: expect.arrayContaining(['s3:GetObject*']),
          Effect: 'Allow',
        }),
      ]),
    );
  }
});
