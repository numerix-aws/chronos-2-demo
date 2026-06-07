import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as nodejs from 'aws-cdk-lib/aws-lambda-nodejs';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';
import { ToolsStack } from './tools-stack';
import { AgentStack } from './agent-stack';

export interface ApiStackProps extends cdk.StackProps {
  readonly tools: ToolsStack;
  readonly agent: AgentStack;
}

export class ApiStack extends cdk.Stack {
  public readonly apiUrl: string;
  public readonly streamUrl: string;
  public readonly sessionsTable: dynamodb.ITable;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const allowedOrigin =
      (this.node.tryGetContext('frontendOrigin') as string | undefined) ?? '*';

    const sessionsTable = new dynamodb.Table(this, 'Sessions', {
      partitionKey: { name: 'session_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'turn_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.sessionsTable = sessionsTable;

    // Self-contained shared layer: just tools.lambda_.shared (pure stdlib+boto3).
    // Built here rather than imported from ToolsStack so ApiStack carries NO
    // cross-stack import of a Tools layer export — that coupling deadlocked CFN
    // whenever a Tools layer's version changed (Cannot update/delete in-use
    // export). SessionsFn/InvokeFn need only boto3 (runtime) + this shared code.
    const repoRoot = path.join(__dirname, '..', '..');
    const sharedLayer = new lambda.LayerVersion(this, 'ApiSharedLayer', {
      code: lambda.Code.fromAsset(repoRoot, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: ['bash', '-c', [
            'mkdir -p /asset-output/python/tools/lambda_',
            'cp tools/__init__.py /asset-output/python/tools/__init__.py || touch /asset-output/python/tools/__init__.py',
            'touch /asset-output/python/tools/lambda_/__init__.py',
            'cp -r tools/lambda/shared /asset-output/python/tools/lambda_/shared',
          ].join(' && ')],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'tools.lambda_.shared only (Api session/invoke Lambdas)',
    });

    const sessionsFn = new lambda.Function(this, 'SessionsFn', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'sessions.handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'tools', 'lambda')),
      layers: [sharedLayer],
      environment: { SESSIONS_TABLE: sessionsTable.tableName },
      timeout: cdk.Duration.seconds(15),
    });
    sessionsTable.grantReadWriteData(sessionsFn);

    const invokeFn = new lambda.Function(this, 'InvokeFn', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'invoke_agent.handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'tools', 'lambda')),
      layers: [sharedLayer],
      environment: {
        SESSIONS_TABLE: sessionsTable.tableName,
        // The runtime ARN + the endpoint name as a separate qualifier (not the
        // full endpoint ARN — invoke_agent_runtime would default qualifier to
        // 'DEFAULT' and 404).
        AGENT_RUNTIME_ARN: props.agent.runtimeArn,
        AGENT_QUALIFIER: 'live',
      },
      timeout: cdk.Duration.minutes(2),
    });
    sessionsTable.grantReadWriteData(invokeFn);
    invokeFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [props.agent.runtimeArn, `${props.agent.runtimeArn}/*`],
      }),
    );

    const sseFn = new nodejs.NodejsFunction(this, 'SseRelayFn', {
      runtime: lambda.Runtime.NODEJS_20_X,
      entry: path.join(__dirname, '..', '..', 'tools', 'lambda', 'sse_relay', 'index.mjs'),
      projectRoot: path.join(__dirname, '..', '..'),
      depsLockFilePath: path.join(__dirname, '..', 'package-lock.json'),
      handler: 'handler',
      timeout: cdk.Duration.minutes(2),
      environment: {
        AGENT_RUNTIME_ARN: props.agent.runtimeArn,
        AGENT_QUALIFIER: 'live',
        API_KEY_SECRET_ARN: props.tools.apiKeySecretArn,
      },
      bundling: { format: nodejs.OutputFormat.ESM, target: 'node20', externalModules: ['@aws-sdk/*'] },
    });
    sseFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [props.agent.runtimeArn, `${props.agent.runtimeArn}/*`],
      }),
    );
    sseFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['secretsmanager:GetSecretValue'],
        resources: [props.tools.apiKeySecretArn],
      }),
    );

    const sseUrl = sseFn.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.AWS_IAM,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        allowedOrigins: [allowedOrigin],
        allowedHeaders: ['*'],
        allowedMethods: [lambda.HttpMethod.GET],
      },
    });

    // WAF in front of the streaming edge: AWS Managed common + known-bad-inputs
    // rule groups, plus a per-IP rate limit. CLOUDFRONT scope requires us-east-1
    // (this stack already deploys there). The relay's x-api-key check remains the
    // real authn; WAF gates who can reach the edge at all.
    const streamWebAcl = new wafv2.CfnWebACL(this, 'StreamWebAcl', {
      scope: 'CLOUDFRONT',
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        sampledRequestsEnabled: true,
        metricName: 'chronos2StreamWebAcl',
      },
      rules: [
        {
          name: 'CommonRuleSet',
          priority: 0,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: { vendorName: 'AWS', name: 'AWSManagedRulesCommonRuleSet' },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            sampledRequestsEnabled: true,
            metricName: 'commonRuleSet',
          },
        },
        {
          name: 'KnownBadInputs',
          priority: 1,
          overrideAction: { none: {} },
          statement: {
            managedRuleGroupStatement: { vendorName: 'AWS', name: 'AWSManagedRulesKnownBadInputsRuleSet' },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            sampledRequestsEnabled: true,
            metricName: 'knownBadInputs',
          },
        },
        {
          name: 'RateLimit',
          priority: 2,
          action: { block: {} },
          statement: {
            rateBasedStatement: { limit: 100, aggregateKeyType: 'IP' },
          },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            sampledRequestsEnabled: true,
            metricName: 'rateLimit',
          },
        },
      ],
    });

    // CloudFront fronts ONLY the streaming Function URL. OAC (SIGV4_ALWAYS) lets
    // CloudFront sign the AWS_IAM Function URL; CDK adds the scoped
    // lambda:InvokeFunctionUrl resource policy automatically. Caching is disabled
    // so the SSE body streams through unbuffered, and x-api-key + Origin are
    // forwarded to the relay via ALL_VIEWER_EXCEPT_HOST_HEADER.
    const streamDistribution = new cloudfront.Distribution(this, 'StreamDistribution', {
      defaultBehavior: {
        origin: origins.FunctionUrlOrigin.withOriginAccessControl(sseUrl),
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
      webAclId: streamWebAcl.attrArn,
      comment: 'chronos2-demo SSE stream edge',
    });

    // The browser only ever talks to the CloudFront domain, never the raw
    // Function URL (which is now AWS_IAM and not publicly invocable).
    this.streamUrl = `https://${streamDistribution.distributionDomainName}/`;

    const api = new apigw.RestApi(this, 'Api', {
      restApiName: 'chronos2-demo',
      deployOptions: { stageName: 'prod' },
      endpointConfiguration: { types: [apigw.EndpointType.REGIONAL] },
      defaultCorsPreflightOptions: {
        allowOrigins: [allowedOrigin],
        allowMethods: ['GET', 'POST', 'OPTIONS'],
        allowHeaders: ['Content-Type', 'x-api-key'],
      },
    });

    // Import the authorizer by ARN so CDK scopes the API-Gateway invoke
    // permission to THIS stack. Referencing props.tools.fnAuthorizer directly
    // makes CDK add that permission in ToolsStack pointing at this RestApi,
    // creating a Tools<->Api dependency cycle.
    const authorizerFn = lambda.Function.fromFunctionAttributes(this, 'ImportedAuthorizerFn', {
      functionArn: props.tools.fnAuthorizer.functionArn,
      sameEnvironment: true,
    });

    const authorizer = new apigw.RequestAuthorizer(this, 'ApiKeyAuthorizer', {
      handler: authorizerFn,
      identitySources: [apigw.IdentitySource.header('x-api-key')],
      resultsCacheTtl: cdk.Duration.minutes(5),
    });

    const guarded: apigw.MethodOptions = {
      authorizationType: apigw.AuthorizationType.CUSTOM,
      authorizer,
    };

    const sessions = api.root.addResource('sessions');
    sessions.addMethod('POST', new apigw.LambdaIntegration(sessionsFn), guarded);

    const sessionRes = sessions.addResource('{sid}');
    const messagesRes = sessionRes.addResource('messages');
    messagesRes.addMethod('GET', new apigw.LambdaIntegration(sessionsFn), guarded);
    messagesRes.addMethod('POST', new apigw.LambdaIntegration(sessionsFn), guarded);

    const invoke = api.root.addResource('invoke');
    invoke.addMethod('POST', new apigw.LambdaIntegration(invokeFn), guarded);

    this.apiUrl = api.url;

    new cdk.CfnOutput(this, 'ApiUrlOut', { value: this.apiUrl });
    new cdk.CfnOutput(this, 'StreamUrlOut', { value: this.streamUrl });
    new cdk.CfnOutput(this, 'SessionsTableOut', { value: sessionsTable.tableName });
  }
}
