# Plan B — Numerix x Chronos-2 UX & Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the Plan A `chronos2_demo` Python core in an analyst-facing demo: AWS-deployed agent (Bedrock AgentCore + Claude Sonnet) with action-group tools, REST+SSE API, and a Cloudscape SPA on Amplify Hosting that walks the §3 narrative end-to-end.

**Architecture:** TypeScript CDK app provisioning seven stacks (network, storage, tools, agent, api, frontend, observability). Heavy quant tools (`run_baseline_mc`, `run_chronos2`) run as ECS Fargate tasks behind thin launcher + poll Lambdas — `run_chronos2` is Fargate because the Chronos-2 endpoint is served via AutoGluon Cloud, whose SDK is too heavy for a Lambda. Glue tools (`load_data`, `blend_paths`, `price_book`, `plot`, `lookup_use_case`) run as Lambdas with `chronos2_demo` packaged as a Lambda layer. Agent reasoning is Bedrock AgentCore with Claude Sonnet, surfaced via API Gateway REST endpoints + SSE for token streaming. SPA is React + Cloudscape with chat, inline image rendering, and a what-if parameter form.

**Tech Stack:** AWS CDK (TypeScript) for IaC. Python 3.11 for tool handlers (reuses Plan A package). Node 20 for Lambda authorizer + SSE relay. React 18 + Cloudscape Design System + AWS Amplify Hosting for the SPA. Playwright for one E2E happy-path. Bedrock AgentCore + Claude Sonnet. SageMaker (already provisioned by Plan A Stage 3).

**Reference spec:** `docs/superpowers/specs/2026-05-22-numerix-chronos2-poc-design.md`. **Depends on:** Plan A complete and `chronos2_demo` installable from the repo root.

---

## Executor's Contract

Plan B inherits the project-wide **Engineering Discipline** from `CLAUDE.md`. Re-read it before Task 1. Plan-B-specific reinforcements:

- **CDK is code.** Snapshot tests catch drift; resource construct properties are typed. Don't write `cdk.aws_iam.PolicyStatement` from memory — let the typed props guide you, copy from this plan's code blocks.
- **Tool contracts are the integration points.** Once a tool's input/output JSON schema lands in this plan, every later task — agent action groups, frontend rendering — depends on it being stable. Don't widen schemas mid-plan; if a real need surfaces, stop and ask.
- **No live AWS calls in unit tests.** All Lambda handlers test against `moto` or hand-rolled fakes. The single Playwright E2E is the only test that hits a deployed stack, and it runs against `dev`, never `prod`.
- **Cost discipline.** SageMaker endpoint and Fargate service are stoppable. Every CDK construct that costs money is tagged `chronos2-demo:teardown=on`; the runbook (Task 25) documents the teardown command.

---

## File Structure (locked in before tasks)

```
chronos-2-demo/
├── src/chronos2_demo/                # Plan A (existing) — installable Python pkg
├── infra/                            # Plan B — CDK TypeScript app
│   ├── package.json
│   ├── tsconfig.json
│   ├── cdk.json
│   ├── jest.config.js
│   ├── bin/
│   │   └── app.ts                    # CDK app entry — wires all stacks
│   ├── lib/
│   │   ├── network-stack.ts          # VPC, subnets, security groups
│   │   ├── storage-stack.ts          # S3 buckets (panel, plots, traces)
│   │   ├── tools-stack.ts            # Lambdas + Fargate task + ECR repo
│   │   ├── agent-stack.ts            # AgentCore agent + action groups
│   │   ├── api-stack.ts              # API Gateway REST + SSE relay
│   │   ├── frontend-stack.ts         # Amplify Hosting + custom domain hook
│   │   └── observability-stack.ts    # CloudWatch dashboards + alarms
│   └── test/
│       ├── network-stack.test.ts
│       ├── storage-stack.test.ts
│       ├── tools-stack.test.ts
│       ├── agent-stack.test.ts
│       ├── api-stack.test.ts
│       └── frontend-stack.test.ts
├── tools/                            # Plan B — handler source
│   ├── lambda/
│   │   ├── shared/
│   │   │   ├── __init__.py
│   │   │   ├── responses.py          # JSON response envelope helpers
│   │   │   └── s3_io.py              # upload/download Parquet + PNG
│   │   ├── load_data/
│   │   │   ├── __init__.py
│   │   │   └── handler.py
│   │   ├── blend_paths/
│   │   │   └── handler.py
│   │   ├── price_book/
│   │   │   └── handler.py
│   │   ├── plot/
│   │   │   └── handler.py
│   │   ├── lookup_use_case/
│   │   │   └── handler.py
│   │   ├── run_chronos2/             # Fargate launcher (async ECS RunTask)
│   │   │   └── handler.py
│   │   ├── check_chronos2/           # Fargate poll (ECS DescribeTasks)
│   │   │   └── handler.py
│   │   └── authorizer/
│   │       └── handler.ts            # API key check (Node 20)
│   ├── fargate/
│   │   ├── baseline_mc/
│   │   │   ├── Dockerfile
│   │   │   ├── entrypoint.py
│   │   │   └── requirements.txt
│   │   └── run_chronos2/             # AutoGluon Cloud endpoint call (heavy dep)
│   │       ├── Dockerfile
│   │       ├── entrypoint.py
│   │       └── requirements.txt
│   └── tests/
│       ├── conftest.py               # shared moto + fake-event fixtures
│       ├── test_load_data.py
│       ├── test_blend_paths.py
│       ├── test_price_book.py
│       ├── test_plot.py
│       ├── test_lookup_use_case.py
│       ├── test_run_chronos2.py            # launcher Lambda
│       ├── test_check_chronos2.py          # poll Lambda
│       ├── test_run_chronos2_entrypoint.py # Fargate entrypoint
│       ├── test_authorizer.test.ts
│       └── test_baseline_mc_entrypoint.py
├── agent/                            # Plan B — agent declarative config
│   ├── system_prompt.md              # Claude system prompt
│   ├── action_groups.json            # OpenAPI-style schemas for each tool
│   └── knowledge/                    # Curated use-case briefs (§10)
│       ├── stress_test_design.md
│       ├── im_vm_forecasting.md
│       ├── frtb_ima_es.md
│       ├── market_data_gap_filling.md
│       ├── scenario_limits.md
│       ├── long_context_windows.md
│       └── temporal_hierarchies.md
├── frontend/                         # Plan B — Cloudscape SPA
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx                   # Cloudscape AppLayout
│   │   ├── api/
│   │   │   ├── client.ts             # fetch wrapper + API key
│   │   │   └── stream.ts             # SSE consumer
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── ImageViewer.tsx       # renders S3 PNG URIs
│   │   │   └── WhatIfForm.tsx        # what-if parameter form
│   │   └── state/
│   │       └── session.ts            # session id + transcript state
│   └── tests/
│       ├── App.test.tsx
│       ├── ChatPanel.test.tsx
│       ├── WhatIfForm.test.tsx
│       └── e2e/
│           └── happy_path.spec.ts    # Playwright
└── docs/superpowers/                 # existing
    ├── specs/2026-05-22-numerix-chronos2-poc-design.md
    └── plans/                        # Plan A files + this plan
```

**Ownership boundaries:**
- `infra/` is CDK only — no business logic.
- `tools/lambda/<name>/handler.py` is the *only* file that knows about Lambda event shapes; it imports from `chronos2_demo` for math.
- `agent/` is declarative config; no Python.
- `frontend/` has zero AWS SDK usage — it talks to API Gateway over HTTPS only.

---

## Stages

- **Stage 0 — Repo bootstrap & CDK app skeleton** (Tasks 1–2)
- **Stage 1 — Storage + curated knowledge briefs** (Tasks 3–4)
- **Stage 2 — Lambda glue tools** (Tasks 5–9)
- **Stage 3 — Fargate baseline MC + Chronos-2** (Tasks 10–11, both async-Fargate with launcher/poll pairs: 11a/11b baseline, 11c/11d chronos2)
- **Stage 4 — Tools stack wiring & IAM** (Task 13)
- **Stage 5 — AgentCore agent + action groups** (Tasks 14–15)
- **Stage 6 — API Gateway REST + SSE + authorizer** (Tasks 16–18)
- **Stage 7 — Cloudscape SPA** (Tasks 19–22)
- **Stage 8 — Frontend + observability stacks, deploy** (Tasks 23–24)
- **Stage 9 — Playwright E2E + runbook** (Tasks 25–26)
- **Stage 10 — Wire what-if conditioning end-to-end + cross-asset price_book** (Tasks 27–31) — *part-10 (2026-06-04 scope extension; see `2026-05-22-plan-b-ux-agent-part-10.md`)*

---

## Stage 0 — Repo bootstrap & CDK app skeleton

### Task 1: Initialize the CDK TypeScript app

**Files:**
- Create: `infra/package.json`
- Create: `infra/tsconfig.json`
- Create: `infra/cdk.json`
- Create: `infra/jest.config.js`
- Create: `infra/bin/app.ts`
- Create: `infra/.gitignore`
- Modify: root `.gitignore` — add `infra/cdk.out/`, `infra/node_modules/`

This task has **no failing test**. It bootstraps tooling so subsequent CDK tasks can build and snapshot-test.

- [ ] **Step 1: Create `infra/package.json`**

```json
{
  "name": "chronos2-demo-infra",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "build": "tsc",
    "test": "jest",
    "synth": "cdk synth",
    "diff": "cdk diff"
  },
  "devDependencies": {
    "@types/jest": "^29.5.12",
    "@types/node": "^20.11.0",
    "aws-cdk": "^2.140.0",
    "jest": "^29.7.0",
    "ts-jest": "^29.1.2",
    "ts-node": "^10.9.2",
    "typescript": "^5.4.0"
  },
  "dependencies": {
    "aws-cdk-lib": "^2.140.0",
    "constructs": "^10.3.0"
  }
}
```

- [ ] **Step 2: Create `infra/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "lib": ["ES2022"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "declaration": true,
    "outDir": "dist",
    "rootDir": "."
  },
  "include": ["bin/**/*", "lib/**/*", "test/**/*"],
  "exclude": ["node_modules", "cdk.out", "dist"]
}
```

- [ ] **Step 3: Create `infra/cdk.json`**

```json
{
  "app": "npx ts-node --prefer-ts-exts bin/app.ts",
  "context": {
    "@aws-cdk/core:bootstrapQualifier": "chronos2demo",
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    "@aws-cdk/core:newStyleStackSynthesis": true,
    "demoTag": "chronos2-demo"
  },
  "watch": {
    "include": ["**"],
    "exclude": ["README.md", "cdk.out/**", "dist/**", "node_modules/**"]
  }
}
```

- [ ] **Step 4: Create `infra/jest.config.js`**

```javascript
module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/test'],
  testMatch: ['**/*.test.ts'],
  transform: { '^.+\\.tsx?$': 'ts-jest' },
};
```

- [ ] **Step 5: Create `infra/bin/app.ts` — empty app, stacks added in later tasks**

```typescript
#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1' };
const demoTag = app.node.tryGetContext('demoTag') ?? 'chronos2-demo';

cdk.Tags.of(app).add('Project', demoTag);
cdk.Tags.of(app).add('chronos2-demo:teardown', 'on');

// Stacks added in Stage 1 onward.

app.synth();
```

- [ ] **Step 6: Create `infra/.gitignore`**

```gitignore
node_modules/
cdk.out/
dist/
*.tsbuildinfo
.DS_Store
```

- [ ] **Step 7: Append to repo-root `.gitignore`**

Append these lines:
```
infra/cdk.out/
infra/node_modules/
infra/dist/
frontend/node_modules/
frontend/dist/
```

- [ ] **Step 8: Install + smoke-test**

```bash
cd infra && npm install && npx cdk synth
```

Expected: `Successfully synthesized to ...cdk.out` with no stacks (empty app).

- [ ] **Step 9: Commit**

```bash
git add infra/ .gitignore
git commit -m "chore(infra): bootstrap CDK TypeScript app

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Network stack — VPC for Fargate + private subnets

**Files:**
- Create: `infra/lib/network-stack.ts`
- Create: `infra/test/network-stack.test.ts`
- Modify: `infra/bin/app.ts` — instantiate `NetworkStack`

The Fargate baseline MC task and any future internal services need a VPC. SageMaker endpoints stay on the AWS-managed network. Two AZs (cost minimization), one NAT gateway shared.

- [ ] **Step 1: Write the failing snapshot test**

`infra/test/network-stack.test.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { NetworkStack } from '../lib/network-stack';

test('creates a VPC with public and private subnets across 2 AZs', () => {
  const app = new cdk.App();
  const stack = new NetworkStack(app, 'TestNetwork');
  const t = Template.fromStack(stack);

  t.resourceCountIs('AWS::EC2::VPC', 1);
  // 2 AZs × (public + private) = 4 subnets.
  t.resourceCountIs('AWS::EC2::Subnet', 4);
  t.resourceCountIs('AWS::EC2::NatGateway', 1);
});

test('exposes vpc as a public property', () => {
  const app = new cdk.App();
  const stack = new NetworkStack(app, 'TestNetwork');
  expect(stack.vpc).toBeDefined();
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd infra && npm test -- network-stack
```

Expected: FAIL — `Cannot find module '../lib/network-stack'`.

- [ ] **Step 3: Implement `infra/lib/network-stack.ts`**

```typescript
import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.IVpc;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    this.vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
    });
  }
}
```

- [ ] **Step 4: Wire into `infra/bin/app.ts`**

Replace the `// Stacks added in Stage 1 onward.` line with:

```typescript
import { NetworkStack } from '../lib/network-stack';

const network = new NetworkStack(app, 'Chronos2DemoNetwork', { env });
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd infra && npm test
```

Expected: 2 passed.

- [ ] **Step 6: Synth check**

```bash
cd infra && npx cdk synth Chronos2DemoNetwork > /dev/null
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add infra/lib/network-stack.ts infra/test/network-stack.test.ts infra/bin/app.ts
git commit -m "feat(infra): network stack with 2-AZ VPC and one NAT

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-2.md` (Stages 1–2 — Storage, knowledge briefs, Lambda glue tools, Tasks 3–9)._
