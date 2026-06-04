# Plan B — Part 5 (Stage 5: AgentCore Gateway + Runtime agent)

> Continuation of `2026-05-22-plan-b-ux-agent.md`. Re-read the Executor's Contract there before starting.

---

## Stage 5 — AgentCore Gateway + Runtime agent

### Task 14: System prompt + tool schemas

**Files:**
- Create: `agent/system_prompt.md`
- Create: `agent/action_groups.json`
- Create: `agent/tests/test_action_groups.py`
- Modify: `pyproject.toml` — add `jsonschema>=4.21` to dev deps (for schema validation in tests)

The agent reasons over Claude Sonnet using a fixed system prompt that names the nine tools, the headline narrative, and the safety rails. `action_groups.json` holds the per-tool input/output JSON schemas; Task 15 turns each entry into an AgentCore Gateway MCP **tool schema** (`toolSchema.inlinePayload`). It must mirror the input/output JSON envelopes already locked in by Tasks 5–11. (The filename is retained for continuity; despite the historical name it is no longer a classic Bedrock action-group OpenAPI doc consumed by `CfnAgent`.)

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
    "check_chronos2",
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
2. **Chronos-2 augmentation** — call `run_chronos2` to *launch* the Fargate task that draws augmenting paths from the Chronos-2 endpoint. Like the baseline, it returns a `task_arn` + the `paths_uri` where the result will land. Then poll `check_chronos2(task_arn, paths_uri)` until `ready` is true before using `paths_uri`.
3. **Blend** — call `blend_paths` with the parametric `paths_uri`, the chronos2 `paths_uri`, and a `w_stress` the user supplies (or defaults to 0.5 in stress regimes).
4. **Price + exposure** — call `price_book` on the parametric PathSet and on the blended PathSet (each returns a `metrics_uri`), then `plot spec=pfe_overlay` with the two `metrics_uri`s to surface the delta.
5. **What-if** — accept new `w_stress` or `as_of` and re-run from step 3.

## Tools

You have nine tools, exposed to you as MCP tools through the AgentCore Gateway. Always call them with the schemas your tools advertise — never invent fields:

- `load_data(session_id, as_of_date, lookback_days)` → `{panel_uri}`
- `run_baseline_mc(session_id, panel_uri, as_of, horizon, n_paths, [n_components], [seed])` → `{task_arn, paths_uri}` *(async — launches Fargate)*
- `check_baseline_mc(session_id, task_arn, paths_uri)` → `{task_status, ready, paths_uri}` *(poll until `ready`)*
- `run_chronos2(session_id, panel_uri, as_of, horizon, n_paths, [covariates_uri])` → `{task_arn, paths_uri}` *(async — launches Fargate)*
- `check_chronos2(session_id, task_arn, paths_uri)` → `{task_status, ready, paths_uri}` *(poll until `ready`)*
- `blend_paths(session_id, parametric_uri, chronos2_uri, w_stress)` → `{blended_uri, w_stress, n_paths}`
- `price_book(session_id, paths_uri)` → `{ee, pfe_975, es_975, dates, metrics_uri}`
- `plot(session_id, spec, ...)` → `{image_uri}` — `spec=pfe_overlay` takes `baseline_uri` + `augmented_uri` (each a `metrics_uri` from `price_book`); `spec=path_fan` takes `paths_uri` + `series`; `spec=regime_ribbon` takes `regimes_uri` + `threshold`.
- `lookup_use_case(topic)` → `{topic, summary, markdown}`

## Operating rules

- **Always carry `session_id` through the chain** — every tool needs it. Fabricate one (`uuid4`) only on the very first turn.
- **Baseline MC and Chronos-2 are both asynchronous.** After `run_baseline_mc`, poll `check_baseline_mc`; after `run_chronos2`, poll `check_chronos2` (each every ~15-30s) until `ready` is true. Never price or blend a `paths_uri` before its poll reports ready. If a `check_*` tool errors, that task failed — surface it.
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
        "summary": "Launch the Chronos-2 augmenting-paths job as an async Fargate task (AutoGluon Cloud endpoint). Returns immediately with a task handle; poll with check_chronos2.",
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
            "description": "Fargate task launched; PathSet lands at paths_uri when ready",
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
    "/check_chronos2": {
      "post": {
        "operationId": "check_chronos2",
        "summary": "Poll the launched Chronos-2 Fargate task. Call repeatedly until ready is true, then use paths_uri.",
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

Expected: 14 passed (5 named + 9 parametrized — one per operation incl. check_baseline_mc and check_chronos2).

- [ ] **Step 7: Commit**

```bash
git add agent/system_prompt.md agent/action_groups.json agent/tests/test_action_groups.py pyproject.toml
git commit -m "feat(agent): system prompt and tool schemas for 9 tools

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15: Agent stack — AgentCore Gateway + Runtime (Strands)

**Files:**
- Create: `infra/lib/agent-stack.ts`
- Create: `infra/test/agent-stack.test.ts`
- Create: `agent/runtime/Dockerfile`
- Create: `agent/runtime/agent.py`
- Create: `agent/runtime/requirements.txt`
- Modify: `infra/bin/app.ts` — instantiate `AgentStack`

The agent layer is built on **Amazon Bedrock AgentCore primitives** (not classic
Bedrock Agents). Two pieces:

1. **Gateway + 9 GatewayTargets** (`AWS::BedrockAgentCore::Gateway` /
   `GatewayTarget`) — each of the 9 tools is exposed as an MCP tool. The
   per-tool `toolSchema.inlinePayload` is derived from `agent/action_groups.json`
   (the request body's `properties`/`required` → `inputSchema`; the 200 response
   body → `outputSchema`).
2. **Runtime + RuntimeEndpoint** (`AWS::BedrockAgentCore::Runtime` /
   `RuntimeEndpoint`) — a containerized **Strands Agents** app that reasons with
   Claude Sonnet, connects to the Gateway as its MCP tool source, and is invoked
   via `bedrock-agentcore:InvokeAgentRuntime` (Tasks 17/18).

> **CDK note:** the AgentCore L1 constructs live in `aws-cdk-lib/aws-bedrockagentcore`
> (verified present in the installed CDK 2.257.0): `CfnGateway`, `CfnGatewayTarget`,
> `CfnRuntime`, `CfnRuntimeEndpoint`. The legacy `aws-cdk-lib/aws-bedrock` `CfnAgent`
> path is NOT used — classic action-group resources don't exist in this CDK.

> **Container image (out-of-band, like Fargate baseline_mc):** the agent image is
> referenced by `<ecrRepo>:latest`; it is built and pushed by the runbook (Task 26),
> NOT bundled during synth. So the snapshot test does not need Docker for the agent
> image — only the `CoreLayer` (via ToolsStack in the build helper) needs `CDK_DOCKER=finch`.

> **Gateway → Lambda contract:** Gateway invokes each tool Lambda with the flat
> tool-argument event our handlers already accept; the `@bedrock_action`
> pass-through (Task 5) keeps the handler import sites stable. Auth from the
> Runtime to the Gateway uses the Gateway's `AWS_IAM` authorizer (the Runtime role
> is granted `bedrock-agentcore` access); the container SigV4-signs MCP calls.

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

test('creates one AgentCore Gateway (MCP)', () => {
  const { t } = build();
  t.resourceCountIs('AWS::BedrockAgentCore::Gateway', 1);
  t.hasResourceProperties('AWS::BedrockAgentCore::Gateway', {
    ProtocolType: 'MCP',
  });
});

test('creates one gateway target per tool (9)', () => {
  const { t } = build();
  t.resourceCountIs('AWS::BedrockAgentCore::GatewayTarget', 9);
});

test('creates a containerized Runtime + endpoint', () => {
  const { t } = build();
  t.resourceCountIs('AWS::BedrockAgentCore::Runtime', 1);
  t.resourceCountIs('AWS::BedrockAgentCore::RuntimeEndpoint', 1);
});

test('runtime role can invoke the model and the gateway', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::IAM::Policy', {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({ Action: Match.arrayWith(['bedrock:InvokeModel']) }),
      ]),
    },
  });
});

test('exposes gatewayUrl, runtimeArn, runtimeEndpointArn', () => {
  const { agent } = build();
  expect(agent.gatewayUrl).toBeDefined();
  expect(agent.runtimeArn).toBeDefined();
  expect(agent.runtimeEndpointArn).toBeDefined();
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd infra && CDK_DOCKER=finch npm test -- agent-stack
```

Expected: FAIL — `Cannot find module '../lib/agent-stack'`.

- [ ] **Step 3: Create the agent container (`agent/runtime/`)**

`agent/runtime/requirements.txt`:
```
bedrock-agentcore>=0.1
strands-agents>=0.1
mcp>=1.2
boto3>=1.34
```

`agent/runtime/agent.py`:
```python
"""AgentCore Runtime entrypoint: a Strands agent fronting the Chronos-2 tools.

The agent reasons with Claude Sonnet and calls the demo's 9 tools through the
AgentCore Gateway (MCP). The Gateway uses AWS_IAM auth, so MCP calls are
SigV4-signed with the Runtime's execution-role credentials.
"""
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client

app = BedrockAgentCoreApp()

_HERE = os.path.dirname(__file__)
SYSTEM_PROMPT = open(os.path.join(_HERE, "system_prompt.md"), encoding="utf-8").read()
GATEWAY_URL = os.environ["GATEWAY_URL"]
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")


def _gateway() -> MCPClient:
    # SigV4-signed streamable-HTTP transport to the AWS_IAM gateway.
    return MCPClient(lambda: streamablehttp_client(GATEWAY_URL))


@app.entrypoint
def invoke(payload: dict) -> str:
    prompt = payload.get("prompt", "")
    with _gateway() as gateway:
        tools = gateway.list_tools_sync()
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )
        return str(agent(prompt))


if __name__ == "__main__":
    app.run()
```

`agent/runtime/Dockerfile`:
```dockerfile
FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY agent/runtime/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY agent/runtime/agent.py /app/agent.py
COPY agent/system_prompt.md /app/system_prompt.md

# AgentCore Runtime serves the agent on port 8080 (/invocations + /ping).
EXPOSE 8080
CMD ["python", "/app/agent.py"]
```

> The container's Gateway/MCP/SigV4 wiring is exercised by the container smoke
> build (Task 26 runbook) and the deploy-time E2E (Task 25) — not by unit tests.
> If the Strands MCP transport needs an explicit SigV4 auth callback in this SDK
> version, adjust `_gateway()` at that point and log it.

- [ ] **Step 4: Implement `infra/lib/agent-stack.ts`**

```typescript
import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as path from 'path';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as ecr from 'aws-cdk-lib/aws-ecr';
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
  { name: 'CheckChronos2', opId: 'check_chronos2', getFn: (t) => t.fnCheckChronos2 },
  { name: 'BlendPaths', opId: 'blend_paths', getFn: (t) => t.fnBlendPaths },
  { name: 'PriceBook', opId: 'price_book', getFn: (t) => t.fnPriceBook },
  { name: 'Plot', opId: 'plot', getFn: (t) => t.fnPlot },
  { name: 'LookupUseCase', opId: 'lookup_use_case', getFn: (t) => t.fnLookupUseCase },
];

// Map an action_groups.json path's request body to an MCP inline tool schema.
function toolSchemaFor(opId: string, openapi: any) {
  const op = openapi.paths[`/${opId}`].post;
  const input = op.requestBody.content['application/json'].schema;
  const ok = op.responses['200']?.content?.['application/json']?.schema;
  const tool: any = {
    name: opId,
    description: op.summary ?? opId,
    inputSchema: input,
  };
  if (ok) tool.outputSchema = ok;
  return tool;
}

export class AgentStack extends cdk.Stack {
  public readonly gatewayUrl: string;
  public readonly runtimeArn: string;
  public readonly runtimeEndpointArn: string;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '..', '..');
    const openapi = JSON.parse(
      fs.readFileSync(path.join(repoRoot, 'agent', 'action_groups.json'), 'utf-8'),
    );

    // ---- Gateway role: invoke the tool Lambdas.
    const gatewayRole = new iam.Role(this, 'GatewayRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });
    for (const { getFn } of TOOL_OPERATIONS) {
      getFn(props.tools).grantInvoke(gatewayRole);
    }

    // ---- Gateway (MCP, AWS_IAM inbound auth).
    const gateway = new agentcore.CfnGateway(this, 'Gateway', {
      name: 'chronos2-demo-gateway',
      protocolType: 'MCP',
      authorizerType: 'AWS_IAM',
      roleArn: gatewayRole.roleArn,
    });

    // ---- One MCP Lambda target per tool.
    for (const { name, opId, getFn } of TOOL_OPERATIONS) {
      const fn = getFn(props.tools);
      const target = new agentcore.CfnGatewayTarget(this, `Target${name}`, {
        name: opId,
        gatewayIdentifier: gateway.attrGatewayIdentifier,
        targetConfiguration: {
          mcp: {
            lambda: {
              lambdaArn: fn.functionArn,
              toolSchema: { inlinePayload: [toolSchemaFor(opId, openapi)] },
            },
          },
        },
        credentialProviderConfigurations: [
          { credentialProviderType: 'GATEWAY_IAM_ROLE' },
        ],
      });
      target.addDependency(gateway);
    }

    // ---- Agent container image (built + pushed out of band; see runbook).
    const agentRepo = new ecr.Repository(this, 'AgentRuntimeRepo', {
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });

    // ---- Runtime execution role: invoke the model + reach the gateway.
    const runtimeRole = new iam.Role(this, 'RuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [`arn:aws:bedrock:${this.region}::foundation-model/${MODEL_ID}`],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeGateway', 'bedrock-agentcore:GetGateway'],
      resources: [gateway.attrGatewayArn],
    }));

    // ---- Runtime + endpoint.
    const runtime = new agentcore.CfnRuntime(this, 'Runtime', {
      agentRuntimeName: 'chronos2_demo_copilot',
      roleArn: runtimeRole.roleArn,
      networkConfiguration: { networkMode: 'PUBLIC' },
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: `${agentRepo.repositoryUri}:latest`,
        },
      },
      environmentVariables: {
        GATEWAY_URL: gateway.attrGatewayUrl,
        MODEL_ID,
      },
    });
    runtime.addDependency(gateway);

    const endpoint = new agentcore.CfnRuntimeEndpoint(this, 'RuntimeEndpoint', {
      agentRuntimeId: runtime.attrAgentRuntimeId,
      name: 'live',
    });
    endpoint.addDependency(runtime);

    this.gatewayUrl = gateway.attrGatewayUrl;
    this.runtimeArn = runtime.attrAgentRuntimeArn;
    this.runtimeEndpointArn = endpoint.ref;

    new cdk.CfnOutput(this, 'GatewayUrlOut', { value: this.gatewayUrl });
    new cdk.CfnOutput(this, 'RuntimeArnOut', { value: this.runtimeArn });
    new cdk.CfnOutput(this, 'AgentRepoUriOut', { value: agentRepo.repositoryUri });
  }
}
```

- [ ] **Step 5: Wire into `infra/bin/app.ts`**

Below the `ToolsStack` instantiation, add:

```typescript
import { AgentStack } from '../lib/agent-stack';

const agentStack = new AgentStack(app, 'Chronos2DemoAgent', {
  env,
  tools,
});
agentStack.addDependency(tools);
```

- [ ] **Step 6: Run tests, confirm pass**

```bash
cd infra && CDK_DOCKER=finch npm test -- agent-stack
```

Expected: 5 passed. (Bundles the `CoreLayer` via finch — slow first run.)

- [ ] **Step 7: Synth check**

```bash
cd infra && CDK_DOCKER=finch npx cdk synth Chronos2DemoAgent > /dev/null
```

Expected: no errors.

> If a `CfnGatewayTarget` / `CfnRuntime` property name or enum (e.g.
> `credentialProviderType`, `networkMode`, `protocolType`) is rejected by the
> installed CDK's typings, STOP and reconcile against the construct's `.d.ts`
> before guessing — these L1 prop shapes are version-specific.

- [ ] **Step 8: Commit**

```bash
git add infra/lib/agent-stack.ts infra/test/agent-stack.test.ts \
        agent/runtime/ infra/bin/app.ts
git commit -m "feat(infra): agent stack on AgentCore Gateway + Runtime (Strands)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-6.md` (Stage 6 — API Gateway REST + SSE relay + sessions, Tasks 16–18)._
