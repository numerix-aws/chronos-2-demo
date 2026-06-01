# Plan B — Part 5 (Stage 5: AgentCore agent + action groups)

> Continuation of `2026-05-22-plan-b-ux-agent.md`. Re-read the Executor's Contract there before starting.

---

## Stage 5 — AgentCore agent + action groups

### Task 14: System prompt + action group OpenAPI schemas

**Files:**
- Create: `agent/system_prompt.md`
- Create: `agent/action_groups.json`
- Create: `agent/tests/test_action_groups.py`
- Modify: `pyproject.toml` — add `jsonschema>=4.21` to dev deps (for schema validation in tests)

The agent reasons over Claude Sonnet using a fixed system prompt that names the seven tools, the headline narrative, and the safety rails. `action_groups.json` is the OpenAPI 3.0 contract Bedrock AgentCore consumes when it registers each tool. It must mirror the input/output JSON envelopes already locked in by Tasks 5–11.

- [ ] **Step 1: Write the failing schema test**

`agent/tests/test_action_groups.py`:
```python
"""Validate that action_groups.json matches the locked tool contracts."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
ACTION_GROUPS = ROOT / "action_groups.json"

EXPECTED_OPERATIONS = {
    "load_data",
    "run_baseline_mc",
    "check_baseline_mc",
    "run_chronos2",
    "blend_paths",
    "price_book",
    "plot",
    "lookup_use_case",
}


def _load() -> dict:
    return json.loads(ACTION_GROUPS.read_text())


def test_file_is_valid_openapi_3_0():
    spec = _load()
    assert spec["openapi"].startswith("3.0"), spec["openapi"]
    assert "paths" in spec and spec["paths"], "no paths defined"


def test_every_required_tool_has_a_path():
    spec = _load()
    op_ids = {
        op["operationId"]
        for path in spec["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    }
    missing = EXPECTED_OPERATIONS - op_ids
    assert not missing, f"missing tool operations: {sorted(missing)}"


def test_each_request_schema_is_valid():
    spec = _load()
    for path, methods in spec["paths"].items():
        for verb, op in methods.items():
            if not isinstance(op, dict) or "requestBody" not in op:
                continue
            schema = op["requestBody"]["content"]["application/json"]["schema"]
            # Will raise if schema itself is malformed.
            Draft202012Validator.check_schema(schema)


def test_load_data_envelope_matches_lambda_contract():
    spec = _load()
    schema = spec["paths"]["/load_data"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    required = set(schema.get("required", []))
    assert required == {"session_id", "as_of_date", "lookback_days"}, required


def test_blend_paths_w_stress_constrained_to_unit_interval():
    spec = _load()
    schema = spec["paths"]["/blend_paths"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    w = schema["properties"]["w_stress"]
    assert w["minimum"] == 0.0
    assert w["maximum"] == 1.0


@pytest.mark.parametrize("op_id", sorted(EXPECTED_OPERATIONS))
def test_every_operation_documents_responses(op_id):
    spec = _load()
    found = False
    for path, methods in spec["paths"].items():
        for op in methods.values():
            if isinstance(op, dict) and op.get("operationId") == op_id:
                assert "200" in op["responses"], f"{op_id} missing 200 response"
                found = True
    assert found, f"{op_id} not found in spec"
```

- [ ] **Step 2: Add `jsonschema` to dev deps**

In `pyproject.toml`, under `[project.optional-dependencies] dev = [`, append:
```
  "jsonschema>=4.21",
```

Then:
```bash
pip install -e ".[dev]"
```

- [ ] **Step 3: Run, confirm fail**

```bash
pytest agent/tests/test_action_groups.py -v
```

Expected: FAIL — `FileNotFoundError: agent/action_groups.json`.

- [ ] **Step 4: Write `agent/system_prompt.md`**

```markdown
# Numerix × Chronos-2 Demo Copilot — System Prompt

You are a quantitative analyst's copilot built for Numerix. Your role is to demonstrate how Amazon Chronos-2, a time-series foundation model, **augments** Numerix's existing parametric Monte Carlo framework for PFE/XVA exposure calculation. You never replace the parametric pipeline — you reweight or supplement it.

## Narrative arc you support

The user follows §3 of the design spec, beat-by-beat:

1. **Baseline parametric MC** — call `load_data`, then `run_baseline_mc` to *launch* the Fargate task. It returns a `task_arn` + the `paths_uri` where the result will land. Then poll `check_baseline_mc(task_arn, paths_uri)` until `ready` is true before using `paths_uri`.
2. **Chronos-2 augmentation** — call `run_chronos2` to draw augmenting paths from the SageMaker endpoint (returns `paths_uri` immediately).
3. **Blend** — call `blend_paths` with the parametric `paths_uri`, the chronos2 `paths_uri`, and a `w_stress` the user supplies (or defaults to 0.5 in stress regimes).
4. **Price + exposure** — call `price_book` on the parametric PathSet and on the blended PathSet (each returns a `metrics_uri`), then `plot spec=pfe_overlay` with the two `metrics_uri`s to surface the delta.
5. **What-if** — accept new `w_stress` or `as_of` and re-run from step 3.

## Tools

You have eight action group tools. Always call them with the schemas in your action group spec — never invent fields:

- `load_data(session_id, as_of_date, lookback_days)` → `{panel_uri}`
- `run_baseline_mc(session_id, panel_uri, as_of, horizon, n_paths, [n_components], [seed])` → `{task_arn, paths_uri}` *(async — launches Fargate)*
- `check_baseline_mc(session_id, task_arn, paths_uri)` → `{task_status, ready, paths_uri}` *(poll until `ready`)*
- `run_chronos2(session_id, panel_uri, as_of, horizon, n_paths, [covariates_uri])` → `{paths_uri, n_paths, horizon}`
- `blend_paths(session_id, parametric_uri, chronos2_uri, w_stress)` → `{blended_uri, w_stress, n_paths}`
- `price_book(session_id, paths_uri)` → `{ee, pfe_975, es_975, dates, metrics_uri}`
- `plot(session_id, spec, ...)` → `{image_uri}` — `spec=pfe_overlay` takes `baseline_uri` + `augmented_uri` (each a `metrics_uri` from `price_book`); `spec=path_fan` takes `paths_uri` + `series`; `spec=regime_ribbon` takes `regimes_uri` + `threshold`.
- `lookup_use_case(topic)` → `{topic, summary, markdown}`

## Operating rules

- **Always carry `session_id` through the chain** — every tool needs it. Fabricate one (`uuid4`) only on the very first turn.
- **Baseline MC is asynchronous.** After `run_baseline_mc`, poll `check_baseline_mc` (every ~15-30s) until `ready` is true. Never price or blend the parametric `paths_uri` before it is ready. If `check_baseline_mc` errors, the task failed — surface it.
- **Thread `as_of` consistently.** Use the same `as_of` date for `run_baseline_mc` and `run_chronos2` as you passed to `load_data` (its `as_of_date`).
- **Plot every quantitative result.** After pricing both PathSets, call `plot spec=pfe_overlay` with the baseline and augmented `metrics_uri`s.
- **Never call `run_baseline_mc` or `run_chronos2` with `n_paths > 5000`** in this demo — it overruns Fargate budget. If asked, run two stages and explain the limit.
- **If a tool errors, surface the error verbatim to the user.** Don't retry silently.
- **For "what does Chronos-2 do for X?" questions, prefer `lookup_use_case` over speculation.** The curated briefs are authoritative.
- **For diagnostics questions** (regime-conditional coverage, joint-tail dependence, distribution distance — see spec §8), call `price_book` on each PathSet (parametric, chronos2, blended) and then `plot spec=pfe_overlay` so the audience can compare the bands directly. Do **not** invent numbers; if the diagnostic isn't reachable through the tool surface, say so.

## What you never do

- You never make up market data, prices, or exposures. If you don't have a `paths_uri`, you call the right tool to produce one.
- You never claim Chronos-2 replaces the Numerix MC pipeline. Your job is to demonstrate augmentation.
- You never invoke tools outside this list, even if asked.

## Tone

You are concise, technically precise, and audience-aware: the user is a senior quant. Use Numerix-native vocabulary (PFE, EE, ES, regime, w_stress). Avoid hedging language. When you produce a chart, name what beat in the narrative it represents.
```

- [ ] **Step 5: Write `agent/action_groups.json`**

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "Chronos2 Demo Action Groups",
    "version": "0.1.0",
    "description": "Tool surface for the Numerix × Chronos-2 PoC agent."
  },
  "paths": {
    "/load_data": {
      "post": {
        "operationId": "load_data",
        "summary": "Slice a curated market data panel and stage it in S3.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["session_id", "as_of_date", "lookback_days"],
                "properties": {
                  "session_id": { "type": "string" },
                  "as_of_date": { "type": "string", "format": "date" },
                  "lookback_days": { "type": "integer", "minimum": 1, "maximum": 5000 }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Panel ready",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["panel_uri"],
                  "properties": {
                    "panel_uri": { "type": "string", "format": "uri" }
                  }
                }
              }
            }
          },
          "400": { "description": "Validation error" }
        }
      }
    },
    "/run_baseline_mc": {
      "post": {
        "operationId": "run_baseline_mc",
        "summary": "Launch the parametric Monte Carlo (PCA + factor dynamics) as an async Fargate task. Returns immediately with a task handle; poll with check_baseline_mc.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["session_id", "panel_uri", "as_of", "horizon", "n_paths"],
                "properties": {
                  "session_id": { "type": "string" },
                  "panel_uri": { "type": "string", "format": "uri" },
                  "as_of": { "type": "string", "format": "date" },
                  "horizon": { "type": "integer", "minimum": 1, "maximum": 1000 },
                  "n_paths": { "type": "integer", "minimum": 1, "maximum": 50000 },
                  "n_components": { "type": "integer", "minimum": 1, "maximum": 20 },
                  "seed": { "type": "integer" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Fargate task launched",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["task_arn", "paths_uri"],
                  "properties": {
                    "task_arn": { "type": "string" },
                    "paths_uri": { "type": "string", "format": "uri" }
                  }
                }
              }
            }
          },
          "400": { "description": "Validation error" },
          "500": { "description": "Fargate RunTask failed" }
        }
      }
    },
    "/check_baseline_mc": {
      "post": {
        "operationId": "check_baseline_mc",
        "summary": "Poll the launched baseline-MC Fargate task. Call repeatedly until ready is true, then use paths_uri.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["session_id", "task_arn", "paths_uri"],
                "properties": {
                  "session_id": { "type": "string" },
                  "task_arn": { "type": "string" },
                  "paths_uri": { "type": "string", "format": "uri" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Task status",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["task_status", "ready", "paths_uri"],
                  "properties": {
                    "task_status": { "type": "string" },
                    "ready": { "type": "boolean" },
                    "paths_uri": { "type": "string", "format": "uri" }
                  }
                }
              }
            }
          },
          "400": { "description": "Validation error" },
          "500": { "description": "Fargate task failed" }
        }
      }
    },
    "/run_chronos2": {
      "post": {
        "operationId": "run_chronos2",
        "summary": "Sample augmenting paths from the Chronos-2 SageMaker endpoint.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["session_id", "panel_uri", "as_of", "horizon", "n_paths"],
                "properties": {
                  "session_id": { "type": "string" },
                  "panel_uri": { "type": "string", "format": "uri" },
                  "as_of": { "type": "string", "format": "date" },
                  "horizon": { "type": "integer", "minimum": 1, "maximum": 1000 },
                  "n_paths": { "type": "integer", "minimum": 1, "maximum": 20000 },
                  "covariates_uri": { "type": "string", "format": "uri" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "PathSet staged in S3",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["paths_uri", "n_paths", "horizon"],
                  "properties": {
                    "paths_uri": { "type": "string", "format": "uri" },
                    "n_paths": { "type": "integer" },
                    "horizon": { "type": "integer" }
                  }
                }
              }
            }
          },
          "400": { "description": "Validation error" },
          "502": { "description": "SageMaker endpoint failure" }
        }
      }
    },
    "/blend_paths": {
      "post": {
        "operationId": "blend_paths",
        "summary": "Importance-weight parametric and Chronos-2 PathSets into one blended PathSet.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["session_id", "parametric_uri", "chronos2_uri", "w_stress"],
                "properties": {
                  "session_id": { "type": "string" },
                  "parametric_uri": { "type": "string", "format": "uri" },
                  "chronos2_uri": { "type": "string", "format": "uri" },
                  "w_stress": { "type": "number", "minimum": 0.0, "maximum": 1.0 }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Blended PathSet staged in S3",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["blended_uri", "w_stress", "n_paths"],
                  "properties": {
                    "blended_uri": { "type": "string", "format": "uri" },
                    "w_stress": { "type": "number" },
                    "n_paths": { "type": "integer" }
                  }
                }
              }
            }
          },
          "400": { "description": "Validation error" }
        }
      }
    },
    "/price_book": {
      "post": {
        "operationId": "price_book",
        "summary": "Price the demo XCCY book on a PathSet and compute EE/PFE/ES.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["session_id", "paths_uri"],
                "properties": {
                  "session_id": { "type": "string" },
                  "paths_uri": { "type": "string", "format": "uri" },
                  "book_id": { "type": "string" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Exposure metrics",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["ee", "pfe_975", "es_975", "dates", "metrics_uri"],
                  "properties": {
                    "ee": { "type": "array", "items": { "type": "number" } },
                    "pfe_975": { "type": "array", "items": { "type": "number" } },
                    "es_975": { "type": "array", "items": { "type": "number" } },
                    "dates": { "type": "array", "items": { "type": "string", "format": "date" } },
                    "metrics_uri": { "type": "string", "format": "uri" }
                  }
                }
              }
            }
          },
          "400": { "description": "Validation error" }
        }
      }
    },
    "/plot": {
      "post": {
        "operationId": "plot",
        "summary": "Render a chart (pfe_overlay | path_fan | regime_ribbon) and return a presigned PNG URL.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["session_id", "spec"],
                "properties": {
                  "session_id": { "type": "string" },
                  "spec": {
                    "type": "string",
                    "enum": ["pfe_overlay", "path_fan", "regime_ribbon"]
                  },
                  "baseline_uri": { "type": "string", "format": "uri" },
                  "augmented_uri": { "type": "string", "format": "uri" },
                  "paths_uri": { "type": "string", "format": "uri" },
                  "regimes_uri": { "type": "string", "format": "uri" },
                  "series": { "type": "string" },
                  "threshold": { "type": "number" },
                  "title": { "type": "string" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Presigned PNG URL",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["image_uri"],
                  "properties": {
                    "image_uri": { "type": "string", "format": "uri" },
                    "spec": { "type": "string" }
                  }
                }
              }
            }
          },
          "400": { "description": "Validation error" }
        }
      }
    },
    "/lookup_use_case": {
      "post": {
        "operationId": "lookup_use_case",
        "summary": "Fetch a curated brief on an adjacent Chronos-2 use case.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["topic"],
                "properties": {
                  "topic": { "type": "string" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Brief content",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "required": ["topic", "summary", "markdown"],
                  "properties": {
                    "topic": { "type": "string" },
                    "summary": { "type": "string" },
                    "markdown": { "type": "string" }
                  }
                }
              }
            }
          },
          "404": { "description": "Topic not in catalog" }
        }
      }
    }
  }
}
```

- [ ] **Step 6: Run, confirm pass**

```bash
pytest agent/tests/test_action_groups.py -v
```

Expected: 12 passed (4 named + 8 parametrized — one per operation incl. check_baseline_mc).

- [ ] **Step 7: Commit**

```bash
git add agent/system_prompt.md agent/action_groups.json agent/tests/test_action_groups.py pyproject.toml
git commit -m "feat(agent): system prompt and OpenAPI action groups for 7 tools

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15: Agent stack — AgentCore agent + action groups + IAM

**Files:**
- Create: `infra/lib/agent-stack.ts`
- Create: `infra/test/agent-stack.test.ts`
- Modify: `infra/bin/app.ts` — instantiate `AgentStack`

The agent stack provisions the Bedrock AgentCore agent itself, binds each action group to the matching Lambda function from the tools stack, and grants the agent's runtime role `bedrock:InvokeModel` (Claude Sonnet) plus `lambda:InvokeFunction` on the tool Lambdas.

> **CDK note:** `aws-cdk-lib` 2.140 ships L1 constructs `CfnAgent` and `CfnAgentActionGroup` under `aws-cdk-lib/aws-bedrock`. We use L1 explicitly because L2 constructs for AgentCore are still preview-only.

> **Bedrock event bridging:** Bedrock invokes each action-group Lambda with a *nested* event (`{messageVersion, actionGroup, apiPath, requestBody:{...}}`) and expects a `{response:{...}}` wrapper. Each tool handler is decorated with `@bedrock_action` (from `tools.lambda_.shared.bedrock`, Task 5), which unpacks the nested params into the flat dict the handler expects and re-wraps the `{status,result}` envelope into Bedrock's response shape. The decorator passes flat events through unchanged, so the handlers' unit tests (Tasks 6–11) still exercise them directly. There are **8** action groups now — the async baseline flow adds `check_baseline_mc` alongside `run_baseline_mc`.

- [ ] **Step 1: Write the failing snapshot test**

`infra/test/agent-stack.test.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { AgentStack } from '../lib/agent-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';
import { NetworkStack } from '../lib/network-stack';

function build(): { agent: AgentStack; t: Template } {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
  });
  const agent = new AgentStack(app, 'Agent', { tools });
  return { agent, t: Template.fromStack(agent) };
}

test('creates exactly one Bedrock agent', () => {
  const { t } = build();
  t.resourceCountIs('AWS::Bedrock::Agent', 1);
});

test('agent uses Claude Sonnet', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Bedrock::Agent', {
    FoundationModel: Match.stringLikeRegexp('anthropic\\.claude.*sonnet'),
  });
});

test('every tool gets an action group', () => {
  const { t } = build();
  t.resourceCountIs('AWS::Bedrock::AgentActionGroup', 8);
});

test('agent role can invoke Bedrock and Lambda', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::IAM::Policy', {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: Match.arrayWith(['bedrock:InvokeModel']),
        }),
        Match.objectLike({
          Action: 'lambda:InvokeFunction',
        }),
      ]),
    },
  });
});

test('exposes agentId and agentAliasId', () => {
  const { agent } = build();
  expect(agent.agentId).toBeDefined();
  expect(agent.agentAliasId).toBeDefined();
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd infra && npm test -- agent-stack
```

Expected: FAIL — `Cannot find module '../lib/agent-stack'`.

- [ ] **Step 3: Implement `infra/lib/agent-stack.ts`**

```typescript
import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as path from 'path';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import { ToolsStack } from './tools-stack';

export interface AgentStackProps extends cdk.StackProps {
  readonly tools: ToolsStack;
}

const MODEL_ID = 'anthropic.claude-3-5-sonnet-20241022-v2:0';

const TOOL_OPERATIONS: Array<{ name: string; opId: string; getFn: (t: ToolsStack) => lambda.IFunction }> = [
  { name: 'LoadData', opId: 'load_data', getFn: (t) => t.fnLoadData },
  { name: 'RunBaselineMc', opId: 'run_baseline_mc', getFn: (t) => t.fnRunBaselineMc },
  { name: 'CheckBaselineMc', opId: 'check_baseline_mc', getFn: (t) => t.fnCheckBaselineMc },
  { name: 'RunChronos2', opId: 'run_chronos2', getFn: (t) => t.fnRunChronos2 },
  { name: 'BlendPaths', opId: 'blend_paths', getFn: (t) => t.fnBlendPaths },
  { name: 'PriceBook', opId: 'price_book', getFn: (t) => t.fnPriceBook },
  { name: 'Plot', opId: 'plot', getFn: (t) => t.fnPlot },
  { name: 'LookupUseCase', opId: 'lookup_use_case', getFn: (t) => t.fnLookupUseCase },
];

export class AgentStack extends cdk.Stack {
  public readonly agentId: string;
  public readonly agentAliasId: string;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);

    const systemPrompt = fs.readFileSync(
      path.join(__dirname, '..', '..', 'agent', 'system_prompt.md'),
      'utf-8',
    );
    const actionGroupsSpec = fs.readFileSync(
      path.join(__dirname, '..', '..', 'agent', 'action_groups.json'),
      'utf-8',
    );
    const openapi = JSON.parse(actionGroupsSpec);

    // Runtime role assumed by the agent itself.
    const agentRole = new iam.Role(this, 'AgentRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
    });

    agentRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [`arn:aws:bedrock:${this.region}::foundation-model/${MODEL_ID}`],
      }),
    );

    for (const { getFn } of TOOL_OPERATIONS) {
      agentRole.addToPolicy(
        new iam.PolicyStatement({
          actions: ['lambda:InvokeFunction'],
          resources: [getFn(props.tools).functionArn],
        }),
      );
    }

    const agent = new bedrock.CfnAgent(this, 'Agent', {
      agentName: 'chronos2-demo-copilot',
      agentResourceRoleArn: agentRole.roleArn,
      foundationModel: MODEL_ID,
      instruction: systemPrompt,
      idleSessionTtlInSeconds: 1800,
      autoPrepare: true,
    });

    // One action group per tool. Each binds a Lambda + the slice of OpenAPI for that path.
    for (const { name, opId, getFn } of TOOL_OPERATIONS) {
      const fn = getFn(props.tools);

      // Permit the agent to invoke this Lambda.
      fn.addPermission(`AgentInvoke${name}`, {
        principal: new iam.ServicePrincipal('bedrock.amazonaws.com'),
        sourceArn: cdk.Fn.sub(
          'arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:agent/${AgentId}',
          { AgentId: agent.attrAgentId },
        ),
      });

      const slice = {
        openapi: openapi.openapi,
        info: openapi.info,
        paths: { [`/${opId}`]: openapi.paths[`/${opId}`] },
      };

      new bedrock.CfnAgentActionGroup(this, `Ag${name}`, {
        agentId: agent.attrAgentId,
        agentVersion: 'DRAFT',
        actionGroupName: opId,
        actionGroupExecutor: { lambda: fn.functionArn },
        apiSchema: { payload: JSON.stringify(slice) },
        actionGroupState: 'ENABLED',
      });
    }

    const alias = new bedrock.CfnAgentAlias(this, 'Alias', {
      agentId: agent.attrAgentId,
      agentAliasName: 'live',
    });
    alias.addDependency(agent);

    this.agentId = agent.attrAgentId;
    this.agentAliasId = alias.attrAgentAliasId;

    new cdk.CfnOutput(this, 'AgentIdOut', { value: this.agentId });
    new cdk.CfnOutput(this, 'AgentAliasIdOut', { value: this.agentAliasId });
  }
}
```

- [ ] **Step 4: Wire into `infra/bin/app.ts`**

Below the `ToolsStack` instantiation, add:

```typescript
import { AgentStack } from '../lib/agent-stack';

const agentStack = new AgentStack(app, 'Chronos2DemoAgent', {
  env,
  tools,
});
agentStack.addDependency(tools);
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd infra && npm test -- agent-stack
```

Expected: 5 passed.

- [ ] **Step 6: Synth check**

```bash
cd infra && npx cdk synth Chronos2DemoAgent > /dev/null
```

Expected: no errors. (CDK will resolve cross-stack references to `tools.<fn>` ARNs as `Fn::ImportValue` exports.)

- [ ] **Step 7: Commit**

```bash
git add infra/lib/agent-stack.ts infra/test/agent-stack.test.ts infra/bin/app.ts
git commit -m "feat(infra): agent stack with Bedrock AgentCore + 7 action groups

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-6.md` (Stage 6 — API Gateway REST + SSE relay + sessions, Tasks 16–18)._
