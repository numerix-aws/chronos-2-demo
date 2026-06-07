import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import { execFileSync } from 'child_process';
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
  public readonly fnCheckChronos2: lambda.IFunction;
  public readonly fnRunBaselineMc: lambda.IFunction;
  public readonly fnCheckBaselineMc: lambda.IFunction;
  public readonly fnAuthorizer: lambda.IFunction;
  public readonly baselineMcTaskDef: ecs.FargateTaskDefinition;
  public readonly baselineMcCluster: ecs.ICluster;
  public readonly chronos2TaskDef: ecs.FargateTaskDefinition;
  // AgentCore runtime image repo. Lives here (not AgentStack) so the image can
  // be pushed after Tools deploys but before AgentStack creates the Runtime,
  // which validates the image exists at create time.
  public readonly agentRuntimeRepo: ecr.IRepository;
  public readonly apiKeySecret: secrets.ISecret;
  // Consumer stacks (Api, Agent) need the layer + secret ARN directly.
  public readonly coreLayer: lambda.ILayerVersion;
  public readonly apiKeySecretArn: string;

  constructor(scope: Construct, id: string, props: ToolsStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '..', '..');
    const chronos2EndpointName = props.chronos2EndpointName ?? 'chronos2-demo-ep';

    // Lambda layer with chronos2_demo source + shared helpers + the demo book.
    // The book is bundled into the layer (it resolves under /opt at runtime, so
    // handlers read BOOK_PATH rather than book.DEFAULT_BOOK_PATH).
    // Lambda layers are capped at 250 MB unzipped (code + all layers, summed).
    // The full scientific stack (numpy+scipy+pandas+sklearn+matplotlib+pyarrow)
    // is ~608 MB, so we split into three trimmed layers and attach only what
    // each function imports:
    //   - light: chronos2_demo source + shared + book only (ECS launcher/poll
    //     Lambdas + lookup_use_case; boto3 comes from the Lambda runtime).
    //   - base:  light + numpy/pandas/pyarrow (load_data, blend_paths,
    //     price_book). scipy/sklearn are NOT imported by any Lambda — they live
    //     in the Fargate workers — so they are excluded.
    //   - plot:  base + matplotlib (plot only).
    // Each build strips tests/__pycache__/dist-info and the unused heavy pyarrow
    // Arrow libs (flight/substrait/gandiva/acero/dataset), keeping core+parquet,
    // to land under the 250 MB cap.
    const SRC_COPY = [
      'mkdir -p /asset-output/python',
      'cp -r src/chronos2_demo /asset-output/python/',
      'mkdir -p /asset-output/python/tools/lambda_',
      'cp tools/__init__.py /asset-output/python/tools/__init__.py || touch /asset-output/python/tools/__init__.py',
      'touch /asset-output/python/tools/lambda_/__init__.py',
      'cp -r tools/lambda/shared /asset-output/python/tools/lambda_/shared',
      'mkdir -p /asset-output/python/data',
      'cp data/sample_book.json /asset-output/python/data/sample_book.json',
    ];
    // --only-binary=:all: forces manylinux wheels (the build image's GCC can't
    // compile the numpy sdist for cp311).
    const PIP = (pkgs: string) =>
      `pip install --only-binary=:all: --target /asset-output/python ${pkgs}`;
    const TRIM = [
      'cd /asset-output/python',
      "find . -type d \\( -name tests -o -name test -o -name __pycache__ -o -name '*.dist-info' -o -name include \\) -prune -exec rm -rf {} + || true",
      "if [ -d pyarrow ]; then cd pyarrow && rm -f libarrow_flight* libarrow_substrait* libgandiva* libarrow_acero* libarrow_dataset* lib*flight* _flight* _substrait* _gandiva* _acero* _dataset* 2>/dev/null || true; cd /asset-output/python; fi",
      "rm -rf matplotlib/mpl-data/sample_data matplotlib/tests 2>/dev/null || true",
    ];
    const layerCode = (pipPkgs: string | null) =>
      lambda.Code.fromAsset(repoRoot, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          platform: 'linux/amd64',
          command: [
            'bash', '-c',
            [...SRC_COPY, ...(pipPkgs ? [PIP(pipPkgs)] : []), ...TRIM].join(' && '),
          ],
        },
      });

    const lightLayer = new lambda.LayerVersion(this, 'LightLayer', {
      code: layerCode(null),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'chronos2_demo + tools.lambda_.shared + demo book (no sci deps)',
    });
    const baseLayer = new lambda.LayerVersion(this, 'BaseLayer', {
      code: layerCode('numpy pandas pyarrow'),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'light + numpy/pandas/pyarrow (load_data, blend_paths, price_book)',
    });
    const plotLayer = new lambda.LayerVersion(this, 'PlotLayer', {
      code: layerCode('numpy pandas pyarrow matplotlib'),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'base + matplotlib (plot)',
    });
    // Public handle kept for downstream stacks/tests; base is the canonical core.
    this.coreLayer = baseLayer;

    // The book lands at /opt/python/data/sample_book.json inside any function
    // that attaches the layer.
    const BOOK_PATH = '/opt/python/data/sample_book.json';

    const commonEnv = {
      DATA_BUCKET: props.dataBucket.bucketName,
      PLOTS_BUCKET: props.plotsBucket.bucketName,
    };

    // Attach the smallest layer each function needs (250 MB cap is code + layers).
    const py = (
      id: string,
      dir: string,
      layer: lambda.ILayerVersion,
      env: Record<string, string> = {},
    ) =>
      new lambda.Function(this, id, {
        runtime: lambda.Runtime.PYTHON_3_11,
        architecture: lambda.Architecture.X86_64,
        handler: 'handler.handler',
        code: lambda.Code.fromAsset(path.join(repoRoot, 'tools', 'lambda', dir)),
        layers: [layer],
        memorySize: 1024,
        timeout: cdk.Duration.seconds(30),
        environment: { ...commonEnv, ...env },
        logRetention: logs.RetentionDays.ONE_WEEK,
      });

    this.fnLoadData = py('LoadData', 'load_data', baseLayer);
    this.fnBlendPaths = py('BlendPaths', 'blend_paths', baseLayer, { BOOK_PATH });
    this.fnPriceBook = py('PriceBook', 'price_book', baseLayer, { BOOK_PATH });
    this.fnPlot = py('Plot', 'plot', plotLayer);
    this.fnLookupUseCase = py('LookupUseCase', 'lookup_use_case', lightLayer, {
      KNOWLEDGE_DIR: '/var/task/knowledge',
    });

    // S3 perms — least-privilege per Lambda. (run_chronos2 is a Fargate
    // launcher, wired below alongside the chronos2 task definition.)
    props.dataBucket.grantReadWrite(this.fnLoadData);
    props.dataBucket.grantReadWrite(this.fnBlendPaths);
    props.dataBucket.grantReadWrite(this.fnPriceBook);
    props.dataBucket.grantRead(this.fnPlot);
    props.plotsBucket.grantReadWrite(this.fnPlot);

    // Authorizer (Node 20).
    this.apiKeySecret = new secrets.Secret(this, 'ApiKey', {
      description: 'Demo-grade API key for AgentCore endpoints',
      generateSecretString: { excludePunctuation: true, passwordLength: 32 },
    });
    this.apiKeySecretArn = this.apiKeySecret.secretArn;
    this.fnAuthorizer = new lambda.Function(this, 'Authorizer', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'handler.handler',
      // handler.ts must be compiled to handler.js before packaging — esbuild
      // bundles it to CommonJS, leaving @aws-sdk/* external (provided by the
      // Node 20 runtime). Without this, the asset would ship only the .ts and
      // Lambda fails with "Cannot find module 'handler'". Bundle on the host via
      // a local hook (finch bind-mounts aren't writable under CDK's -u uid:gid,
      // which breaks in-container esbuild); fall back to the container image.
      code: lambda.Code.fromAsset(path.join(repoRoot, 'tools', 'lambda', 'authorizer'), {
        bundling: {
          image: lambda.Runtime.NODEJS_20_X.bundlingImage,
          command: [
            'bash', '-c',
            'export HOME=/tmp && npx --yes esbuild handler.ts --bundle --platform=node ' +
            '--target=node20 "--external:@aws-sdk/*" --outfile=/asset-output/handler.js',
          ],
          local: {
            tryBundle(outputDir: string): boolean {
              const src = path.join(repoRoot, 'tools', 'lambda', 'authorizer');
              try {
                execFileSync('npx', [
                  '--yes', 'esbuild', path.join(src, 'handler.ts'),
                  '--bundle', '--platform=node', '--target=node20',
                  '--external:@aws-sdk/*',
                  `--outfile=${path.join(outputDir, 'handler.js')}`,
                ], { stdio: 'inherit' });
                return true;
              } catch {
                return false; // fall back to container bundling
              }
            },
          },
        },
      }),
      timeout: cdk.Duration.seconds(5),
      memorySize: 256,
      environment: {
        // Authorizer fetches the key value from this secret at runtime.
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
    this.fnRunBaselineMc = py('RunBaselineMc', 'run_baseline_mc', lightLayer, {
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
    this.fnCheckBaselineMc = py('CheckBaselineMc', 'check_baseline_mc', lightLayer, {
      CLUSTER_ARN: cluster.clusterArn,
    });
    this.fnCheckBaselineMc.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:DescribeTasks'],
      resources: ['*'],
    }));

    // Fargate chronos2 — same shared cluster, its own ECR repo + task def.
    // The AutoGluon Cloud endpoint call (autogluon-cloud, heavy) runs here, not
    // in a Lambda. The task role invokes the SageMaker endpoint under the hood.
    const chronos2Repo = new ecr.Repository(this, 'Chronos2Repo', {
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });
    // AgentCore runtime image repo (consumed by AgentStack). Created here so the
    // image can be pushed before AgentStack's Runtime validates it at create time.
    this.agentRuntimeRepo = new ecr.Repository(this, 'AgentRuntimeRepo', {
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });
    const chronos2Sg = new ec2.SecurityGroup(this, 'Chronos2Sg', {
      vpc: props.vpc,
      description: 'Egress-only SG for the chronos2 Fargate task',
    });
    this.chronos2TaskDef = new ecs.FargateTaskDefinition(this, 'Chronos2TaskDef', {
      cpu: 4096,
      memoryLimitMiB: 8192,
    });
    this.chronos2TaskDef.addContainer('App', {
      image: ecs.ContainerImage.fromEcrRepository(chronos2Repo, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'chronos2',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
      environment: {
        DATA_BUCKET: props.dataBucket.bucketName,
        CHRONOS2_ENDPOINT: chronos2EndpointName,
      },
    });
    props.dataBucket.grantReadWrite(this.chronos2TaskDef.taskRole);
    // AutoGluon's TimeSeriesEndpoint.predict invokes the SageMaker runtime.
    this.chronos2TaskDef.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['sagemaker:InvokeEndpoint'],
      resources: [
        `arn:${this.partition}:sagemaker:${this.region}:${this.account}:endpoint/${chronos2EndpointName}`,
      ],
    }));

    // run_chronos2 launcher Lambda (starts the chronos2 Fargate task).
    this.fnRunChronos2 = py('RunChronos2', 'run_chronos2', lightLayer, {
      CLUSTER_ARN: cluster.clusterArn,
      TASK_DEFINITION_ARN: this.chronos2TaskDef.taskDefinitionArn,
      CONTAINER_NAME: 'App',
      SUBNET_IDS: cdk.Fn.join(',', privateSubnetIds),
      SECURITY_GROUP_IDS: chronos2Sg.securityGroupId,
      CHRONOS2_ENDPOINT: chronos2EndpointName,
    });
    props.dataBucket.grantRead(this.fnRunChronos2);
    this.fnRunChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:RunTask'],
      resources: [this.chronos2TaskDef.taskDefinitionArn],
    }));
    this.fnRunChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iam:PassRole'],
      resources: [
        this.chronos2TaskDef.taskRole.roleArn,
        this.chronos2TaskDef.executionRole!.roleArn,
      ],
    }));

    // check_chronos2 poll Lambda (DescribeTasks on the cluster).
    this.fnCheckChronos2 = py('CheckChronos2', 'check_chronos2', lightLayer, {
      CLUSTER_ARN: cluster.clusterArn,
    });
    this.fnCheckChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:DescribeTasks'],
      resources: ['*'],
    }));

    new cdk.CfnOutput(this, 'ApiKeySecretArnOut', { value: this.apiKeySecretArn });

    cdk.Tags.of(this).add('chronos2-demo:teardown', 'on');
  }
}
