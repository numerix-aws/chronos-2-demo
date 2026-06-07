import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as nodejs from 'aws-cdk-lib/aws-lambda-nodejs';
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

    const sessionsFn = new lambda.Function(this, 'SessionsFn', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'sessions.handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'tools', 'lambda')),
      layers: [props.tools.lightLayer],
      environment: { SESSIONS_TABLE: sessionsTable.tableName },
      timeout: cdk.Duration.seconds(15),
    });
    sessionsTable.grantReadWriteData(sessionsFn);

    const invokeFn = new lambda.Function(this, 'InvokeFn', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'invoke_agent.handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'tools', 'lambda')),
      layers: [props.tools.lightLayer],
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
      authType: lambda.FunctionUrlAuthType.NONE,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        allowedOrigins: [allowedOrigin],
        allowedHeaders: ['*'],
        allowedMethods: [lambda.HttpMethod.GET],
      },
    });
    this.streamUrl = sseUrl.url;

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
