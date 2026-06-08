import * as cdk from 'aws-cdk-lib';
import * as amplify from 'aws-cdk-lib/aws-amplify';
import { Construct } from 'constructs';
import { ApiStack } from './api-stack';

export interface FrontendStackProps extends cdk.StackProps {
  readonly api: ApiStack;
}

export class FrontendStack extends cdk.Stack {
  public readonly appId: string;
  public readonly defaultDomain: string;

  constructor(scope: Construct, id: string, props: FrontendStackProps) {
    super(scope, id, props);

    const app = new amplify.CfnApp(this, 'App', {
      name: 'chronos2-demo',
      // No SourceCodeUrl — manual zip deploys via `aws amplify start-deployment`.
      // These env-vars are informational only: the SPA is built LOCALLY with a
      // `.env.production` (VITE_* baked in by Vite) and zip-deployed, so Amplify
      // never runs this build. We deliberately do NOT wire them to
      // props.api.apiUrl / props.api.streamUrl — that created a CloudFormation
      // cross-stack export Frontend imports, which deadlocks any change to the
      // Api streamUrl ("Cannot delete export … in use by Frontend"). Same lesson
      // as ApiSharedLayer: don't share churn-prone exports across stacks. The
      // real URLs come from the runbook's local .env.production at build time.
      environmentVariables: [
        { name: 'VITE_API_URL', value: 'set-at-build-time-via-.env.production' },
        { name: 'VITE_STREAM_URL', value: 'set-at-build-time-via-.env.production' },
      ],
      buildSpec: [
        'version: 1',
        'frontend:',
        '  phases:',
        '    preBuild:',
        '      commands:',
        '        - cd frontend && npm ci',
        '    build:',
        '      commands:',
        '        - npm run build',
        '  artifacts:',
        '    baseDirectory: frontend/dist',
        '    files:',
        '      - "**/*"',
        '  cache:',
        '    paths:',
        '      - frontend/node_modules/**/*',
      ].join('\n'),
      customRules: [
        // SPA: route all unknown paths to index.html
        {
          source: '</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json)$)([^.]+$)/>',
          target: '/index.html',
          status: '200',
        },
      ],
    });

    const main = new amplify.CfnBranch(this, 'MainBranch', {
      appId: app.attrAppId,
      branchName: 'main',
      stage: 'PRODUCTION',
      enableAutoBuild: false,
    });
    main.addDependency(app);

    this.appId = app.attrAppId;
    this.defaultDomain = app.attrDefaultDomain;

    new cdk.CfnOutput(this, 'AmplifyAppIdOut', { value: this.appId });
    new cdk.CfnOutput(this, 'AmplifyDomainOut', {
      value: `https://main.${this.defaultDomain}`,
    });
  }
}
