import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secrets from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export interface ToolsStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  dataBucket: s3.IBucket;
  plotsBucket: s3.IBucket;
  // Optional: the Plan A SageMaker endpoint name. Defaults so consumer-stack
  // tests can construct ToolsStack without threading it through.
  chronos2EndpointName?: string;
}

export class ToolsStack extends cdk.Stack {
  public readonly fnLoadData: lambda.IFunction;
  public readonly fnBlendPaths: lambda.IFunction;
  public readonly fnPriceBook: lambda.IFunction;
  public readonly fnPlot: lambda.IFunction;
  public readonly fnLookupUseCase: lambda.IFunction;
  public readonly fnRunChronos2: lambda.IFunction;
  public readonly fnRunBaselineMc: lambda.IFunction;
  public readonly fnCheckBaselineMc: lambda.IFunction;
  public readonly fnAuthorizer: lambda.IFunction;
  public readonly baselineMcTaskDef: ecs.FargateTaskDefinition;
  public readonly baselineMcCluster: ecs.ICluster;
  public readonly apiKeySecret: secrets.ISecret;
  // Consumer stacks (Api, Agent) need the layer + secret ARN directly.
  public readonly coreLayer: lambda.ILayerVersion;
  public readonly apiKeySecretArn: string;

  constructor(scope: Construct, id: string, props: ToolsStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '..', '..');
    const chronos2EndpointName = props.chronos2EndpointName ?? 'chronos2-demo-endpoint';

    // Lambda layer with chronos2_demo source + shared helpers + the demo book.
    // The book is bundled into the layer (it resolves under /opt at runtime, so
    // handlers read BOOK_PATH rather than book.DEFAULT_BOOK_PATH).
    const coreLayer = new lambda.LayerVersion(this, 'CoreLayer', {
      code: lambda.Code.fromAsset(repoRoot, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          platform: 'linux/amd64',
          command: [
            'bash', '-c', [
              'mkdir -p /asset-output/python',
              'cp -r src/chronos2_demo /asset-output/python/',
              'mkdir -p /asset-output/python/tools/lambda_',
              'cp tools/__init__.py /asset-output/python/tools/__init__.py || touch /asset-output/python/tools/__init__.py',
              'touch /asset-output/python/tools/lambda_/__init__.py',
              'cp -r tools/lambda/shared /asset-output/python/tools/lambda_/shared',
              'mkdir -p /asset-output/python/data',
              'cp data/sample_book.json /asset-output/python/data/sample_book.json',
              'pip install --only-binary=:all: --target /asset-output/python numpy scipy pandas scikit-learn matplotlib pyarrow boto3',
            ].join(' && '),
          ],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'chronos2_demo + tools.lambda_.shared + demo book + scientific deps',
    });
    this.coreLayer = coreLayer;

    // The book lands at /opt/python/data/sample_book.json inside any function
    // that attaches the layer.
    const BOOK_PATH = '/opt/python/data/sample_book.json';

    const commonEnv = {
      DATA_BUCKET: props.dataBucket.bucketName,
      PLOTS_BUCKET: props.plotsBucket.bucketName,
    };

    const py = (id: string, dir: string, env: Record<string, string> = {}) =>
      new lambda.Function(this, id, {
        runtime: lambda.Runtime.PYTHON_3_11,
        architecture: lambda.Architecture.X86_64,
        handler: 'handler.handler',
        code: lambda.Code.fromAsset(path.join(repoRoot, 'tools', 'lambda', dir)),
        layers: [coreLayer],
        memorySize: 1024,
        timeout: cdk.Duration.seconds(30),
        environment: { ...commonEnv, ...env },
        logRetention: logs.RetentionDays.ONE_WEEK,
      });

    this.fnLoadData = py('LoadData', 'load_data');
    this.fnBlendPaths = py('BlendPaths', 'blend_paths', { BOOK_PATH });
    this.fnPriceBook = py('PriceBook', 'price_book', { BOOK_PATH });
    this.fnPlot = py('Plot', 'plot');
    this.fnLookupUseCase = py('LookupUseCase', 'lookup_use_case', {
      KNOWLEDGE_DIR: '/var/task/knowledge',
    });
    this.fnRunChronos2 = py('RunChronos2', 'run_chronos2', {
      CHRONOS2_ENDPOINT: chronos2EndpointName,
    });

    // S3 perms — least-privilege per Lambda.
    props.dataBucket.grantReadWrite(this.fnLoadData);
    props.dataBucket.grantReadWrite(this.fnBlendPaths);
    props.dataBucket.grantReadWrite(this.fnPriceBook);
    props.dataBucket.grantReadWrite(this.fnRunChronos2);
    props.dataBucket.grantRead(this.fnPlot);
    props.plotsBucket.grantReadWrite(this.fnPlot);

    // SageMaker invoke perm for chronos2 proxy.
    this.fnRunChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['sagemaker:InvokeEndpoint'],
      resources: [
        `arn:${this.partition}:sagemaker:${this.region}:${this.account}:endpoint/${chronos2EndpointName}`,
      ],
    }));

    // Authorizer (Node 20).
    this.apiKeySecret = new secrets.Secret(this, 'ApiKey', {
      description: 'Demo-grade API key for AgentCore endpoints',
      generateSecretString: { excludePunctuation: true, passwordLength: 32 },
    });
    this.apiKeySecretArn = this.apiKeySecret.secretArn;
    this.fnAuthorizer = new lambda.Function(this, 'Authorizer', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(repoRoot, 'tools', 'lambda', 'authorizer')),
      timeout: cdk.Duration.seconds(5),
      memorySize: 256,
      environment: {
        // Resolve at runtime via SecretsManager extension or directly read.
        API_KEY_SECRET_ARN: this.apiKeySecret.secretArn,
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });
    this.apiKeySecret.grantRead(this.fnAuthorizer);

    // Fargate baseline_mc.
    const repo = new ecr.Repository(this, 'BaselineMcRepo', {
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });
    const cluster = new ecs.Cluster(this, 'BaselineMcCluster', {
      vpc: props.vpc,
    });
    this.baselineMcCluster = cluster;
    const baselineMcSg = new ec2.SecurityGroup(this, 'BaselineMcSg', {
      vpc: props.vpc,
      description: 'Egress-only SG for the baseline-MC Fargate task',
    });
    this.baselineMcTaskDef = new ecs.FargateTaskDefinition(this, 'BaselineMcTaskDef', {
      cpu: 4096,
      memoryLimitMiB: 8192,
    });
    this.baselineMcTaskDef.addContainer('App', {
      image: ecs.ContainerImage.fromEcrRepository(repo, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'baseline-mc',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
      environment: { DATA_BUCKET: props.dataBucket.bucketName },
    });
    props.dataBucket.grantReadWrite(this.baselineMcTaskDef.taskRole);

    // run_baseline_mc launcher Lambda (starts the Fargate task; returns a handle).
    const privateSubnetIds = props.vpc.selectSubnets({
      subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
    }).subnetIds;
    this.fnRunBaselineMc = py('RunBaselineMc', 'run_baseline_mc', {
      CLUSTER_ARN: cluster.clusterArn,
      TASK_DEFINITION_ARN: this.baselineMcTaskDef.taskDefinitionArn,
      CONTAINER_NAME: 'App',
      SUBNET_IDS: cdk.Fn.join(',', privateSubnetIds),
      SECURITY_GROUP_IDS: baselineMcSg.securityGroupId,
    });
    props.dataBucket.grantRead(this.fnRunBaselineMc);
    this.fnRunBaselineMc.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:RunTask'],
      resources: [this.baselineMcTaskDef.taskDefinitionArn],
    }));
    this.fnRunBaselineMc.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iam:PassRole'],
      resources: [
        this.baselineMcTaskDef.taskRole.roleArn,
        this.baselineMcTaskDef.executionRole!.roleArn,
      ],
    }));

    // check_baseline_mc poll Lambda (DescribeTasks on the cluster).
    this.fnCheckBaselineMc = py('CheckBaselineMc', 'check_baseline_mc', {
      CLUSTER_ARN: cluster.clusterArn,
    });
    this.fnCheckBaselineMc.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:DescribeTasks'],
      resources: ['*'],
    }));

    cdk.Tags.of(this).add('chronos2-demo:teardown', 'on');
  }
}
