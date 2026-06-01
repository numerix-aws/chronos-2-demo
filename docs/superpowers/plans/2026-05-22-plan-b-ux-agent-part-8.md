# Plan B — Part 8 (Stage 8: Frontend stack + observability + deploy)

> Continuation of `2026-05-22-plan-b-ux-agent.md`. Re-read the Executor's Contract there before starting.

---

## Stage 8 — Frontend stack + observability + deploy

### Task 23: FrontendStack — Amplify Hosting + build wiring

**Files:**
- Create: `infra/lib/frontend-stack.ts`
- Create: `infra/test/frontend-stack.test.ts`
- Modify: `infra/bin/app.ts` — instantiate `FrontendStack`
- Create: `frontend/.env.production.template`

The SPA is hosted on **AWS Amplify Hosting** because it gives us atomic deploys, branch-per-environment, env-var management for Vite, and a sane CDN out of the box. CDK provisions the Amplify app with manual-deploy mode (we upload a zipped build artifact); the env vars `VITE_API_URL`, `VITE_STREAM_URL`, and `VITE_API_KEY` come from the API and Tools stacks.

> **Why manual deploy, not GitHub-hosted Amplify:** the repo is not a GitHub repo from Amplify's POV (it's local + internal). The runbook (Task 26) shows the `aws amplify start-deployment` upload step.

- [ ] **Step 1: Write the failing snapshot test**

`infra/test/frontend-stack.test.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { FrontendStack } from '../lib/frontend-stack';
import { ApiStack } from '../lib/api-stack';
import { ToolsStack } from '../lib/tools-stack';
import { StorageStack } from '../lib/storage-stack';
import { NetworkStack } from '../lib/network-stack';
import { AgentStack } from '../lib/agent-stack';

function build() {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
  });
  const agent = new AgentStack(app, 'Agent', { tools });
  const api = new ApiStack(app, 'Api', { tools, agent });
  const fe = new FrontendStack(app, 'Frontend', { api });
  return { fe, t: Template.fromStack(fe) };
}

test('creates one Amplify app + one main branch', () => {
  const { t } = build();
  t.resourceCountIs('AWS::Amplify::App', 1);
  t.resourceCountIs('AWS::Amplify::Branch', 1);
});

test('main branch is set to manual deploy', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Amplify::Branch', {
    BranchName: 'main',
    Stage: 'PRODUCTION',
  });
});

test('environment variables include VITE_API_URL and VITE_STREAM_URL', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Amplify::App', {
    EnvironmentVariables: Match.arrayWith([
      Match.objectLike({ Name: 'VITE_API_URL' }),
      Match.objectLike({ Name: 'VITE_STREAM_URL' }),
    ]),
  });
});

test('exposes appId and defaultDomain', () => {
  const { fe } = build();
  expect(fe.appId).toBeDefined();
  expect(fe.defaultDomain).toBeDefined();
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd infra && npm test -- frontend-stack
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `infra/lib/frontend-stack.ts`**

```typescript
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
      environmentVariables: [
        { name: 'VITE_API_URL', value: props.api.apiUrl },
        { name: 'VITE_STREAM_URL', value: props.api.streamUrl },
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
```

- [ ] **Step 4: Wire into `infra/bin/app.ts`**

```typescript
import { FrontendStack } from '../lib/frontend-stack';

const frontendStack = new FrontendStack(app, 'Chronos2DemoFrontend', {
  env,
  api: apiStack,
});
frontendStack.addDependency(apiStack);
```

- [ ] **Step 5: Create `frontend/.env.production.template`**

```
# Filled at deploy time by Amplify environment variables.
# Local dev: copy to .env.local and override.
VITE_API_URL=https://placeholder.execute-api.us-east-1.amazonaws.com/prod/
VITE_STREAM_URL=https://placeholder.lambda-url.us-east-1.on.aws/
```

- [ ] **Step 6: Run tests, confirm pass**

```bash
cd infra && npm test -- frontend-stack
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add infra/lib/frontend-stack.ts infra/test/frontend-stack.test.ts infra/bin/app.ts frontend/.env.production.template
git commit -m "feat(infra): Amplify Hosting frontend stack with SPA rewrites

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 24: ObservabilityStack — CloudWatch dashboard + alarms

**Files:**
- Create: `infra/lib/observability-stack.ts`
- Create: `infra/test/observability-stack.test.ts`
- Modify: `infra/bin/app.ts` — instantiate `ObservabilityStack`

A single dashboard surfaces what Numerix's reviewer needs to see during the demo:
- API Gateway 5xx rate
- Each tool Lambda's `Errors` and `Duration p95`
- Bedrock agent invocation count + token usage (via the `bedrock:InvokeAgent` log group)
- Fargate baseline-MC task duration
- SageMaker endpoint `Invocations` + `ModelLatency`

Alarms at sensible thresholds page if anything blows up during the demo. The stack is intentionally read-only — no log retention rules here; those live on each Lambda construct.

- [ ] **Step 1: Write the failing snapshot test**

`infra/test/observability-stack.test.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { ObservabilityStack } from '../lib/observability-stack';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';
import { AgentStack } from '../lib/agent-stack';
import { ApiStack } from '../lib/api-stack';

function build() {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
  });
  const agent = new AgentStack(app, 'Agent', { tools });
  const api = new ApiStack(app, 'Api', { tools, agent });
  const obs = new ObservabilityStack(app, 'Obs', { tools, api });
  return { obs, t: Template.fromStack(obs) };
}

test('creates one CloudWatch dashboard', () => {
  const { t } = build();
  t.resourceCountIs('AWS::CloudWatch::Dashboard', 1);
});

test('creates a 5xx alarm for the REST API', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::CloudWatch::Alarm', Match.objectLike({
    Namespace: 'AWS/ApiGateway',
    MetricName: '5XXError',
  }));
});

test('creates one error alarm per tool Lambda', () => {
  const { t } = build();
  // 8 Python tool Lambdas (load_data, blend_paths, price_book, plot,
  // lookup_use_case, run_chronos2, run_baseline_mc, check_baseline_mc)
  // each get an Errors alarm = at least 8 tool alarms.
  const alarms = t.findResources('AWS::CloudWatch::Alarm');
  const lambdaErrorAlarms = Object.values(alarms).filter(
    (r: any) => r.Properties?.Namespace === 'AWS/Lambda' && r.Properties?.MetricName === 'Errors',
  );
  expect(lambdaErrorAlarms.length).toBeGreaterThanOrEqual(8);
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd infra && npm test -- observability-stack
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `infra/lib/observability-stack.ts`**

```typescript
import * as cdk from 'aws-cdk-lib';
import * as cw from 'aws-cdk-lib/aws-cloudwatch';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import { ToolsStack } from './tools-stack';
import { ApiStack } from './api-stack';

export interface ObservabilityStackProps extends cdk.StackProps {
  readonly tools: ToolsStack;
  readonly api: ApiStack;
}

export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);

    const apiName = 'chronos2-demo';

    // ---- API Gateway 5xx alarm.
    new cw.Alarm(this, 'Api5xxAlarm', {
      metric: new cw.Metric({
        namespace: 'AWS/ApiGateway',
        metricName: '5XXError',
        dimensionsMap: { ApiName: apiName, Stage: 'prod' },
        statistic: 'Sum',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 5,
      evaluationPeriods: 1,
      comparisonOperator: cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'API 5xx > 5 in 5 minutes',
    });

    // ---- Per-Lambda error + p95 duration alarm.
    const tool: Record<string, lambda.IFunction> = {
      load_data: props.tools.fnLoadData,
      blend_paths: props.tools.fnBlendPaths,
      price_book: props.tools.fnPriceBook,
      plot: props.tools.fnPlot,
      lookup_use_case: props.tools.fnLookupUseCase,
      run_chronos2: props.tools.fnRunChronos2,
      run_baseline_mc: props.tools.fnRunBaselineMc,
      check_baseline_mc: props.tools.fnCheckBaselineMc,
    };

    const dashboardWidgets: cw.IWidget[] = [];

    for (const [name, fn] of Object.entries(tool)) {
      new cw.Alarm(this, `Errors-${name}`, {
        metric: fn.metricErrors({ period: cdk.Duration.minutes(5), statistic: 'Sum' }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator: cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        alarmDescription: `${name} Lambda error`,
      });

      dashboardWidgets.push(
        new cw.GraphWidget({
          title: `${name} — invocations & errors`,
          left: [fn.metricInvocations({ statistic: 'Sum' })],
          right: [fn.metricErrors({ statistic: 'Sum' })],
          width: 12,
          height: 4,
        }),
      );
      dashboardWidgets.push(
        new cw.GraphWidget({
          title: `${name} — p95 duration`,
          left: [fn.metricDuration({ statistic: 'p95' })],
          width: 12,
          height: 4,
        }),
      );
    }

    // ---- SageMaker endpoint widgets (only useful if endpoint name is fixed).
    const endpointName =
      (this.node.tryGetContext('chronos2EndpointName') as string | undefined) ??
      'chronos2-endpoint';
    dashboardWidgets.push(
      new cw.GraphWidget({
        title: 'SageMaker — Chronos-2 invocations',
        left: [
          new cw.Metric({
            namespace: 'AWS/SageMaker',
            metricName: 'Invocations',
            dimensionsMap: { EndpointName: endpointName, VariantName: 'AllTraffic' },
            statistic: 'Sum',
          }),
        ],
        right: [
          new cw.Metric({
            namespace: 'AWS/SageMaker',
            metricName: 'ModelLatency',
            dimensionsMap: { EndpointName: endpointName, VariantName: 'AllTraffic' },
            statistic: 'p95',
          }),
        ],
        width: 24,
        height: 4,
      }),
    );

    new cw.Dashboard(this, 'Dashboard', {
      dashboardName: 'chronos2-demo',
      widgets: [dashboardWidgets],
    });

    new cdk.CfnOutput(this, 'DashboardUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=chronos2-demo`,
    });
  }
}
```

- [ ] **Step 4: Wire into `infra/bin/app.ts`**

```typescript
import { ObservabilityStack } from '../lib/observability-stack';

const obsStack = new ObservabilityStack(app, 'Chronos2DemoObservability', {
  env,
  tools,
  api: apiStack,
});
obsStack.addDependency(apiStack);
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd infra && npm test
```

Expected: every snapshot test green across all stacks.

- [ ] **Step 6: Full synth check**

```bash
cd infra && npx cdk synth --all > /dev/null
```

Expected: all 7 stacks synth without error.

- [ ] **Step 7: Commit**

```bash
git add infra/lib/observability-stack.ts infra/test/observability-stack.test.ts infra/bin/app.ts
git commit -m "feat(infra): observability stack with dashboard and per-Lambda alarms

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-9.md` (Stage 9 — Playwright E2E + runbook, Tasks 25–26)._
