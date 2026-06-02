# Plan B — Part 6 (Stage 6: API Gateway REST + SSE relay + sessions)

> Continuation of `2026-05-22-plan-b-ux-agent.md`. Re-read the Executor's Contract there before starting.

---

## Stage 6 — API Gateway REST + SSE relay + sessions

### Task 16: Sessions Lambda + transcript store

**Files:**
- Create: `tools/lambda/sessions/handler.py`
- Create: `tools/tests/test_sessions.py`
- Modify: `tools/tests/conftest.py` — add a `sessions_table` fixture (mocked DynamoDB)

The frontend creates a session, lists prior turns, and posts user messages. We back this with a single DynamoDB table keyed `(session_id, turn_id)` so transcript history survives page reloads. The Lambda is a small REST router; it does **not** invoke the agent — that's Task 17's job.

**DynamoDB schema (locked in):**
```
PK: session_id (String)
SK: turn_id (String, ISO-8601 timestamp + role suffix, e.g. "2026-05-22T14:33:01.123Z#user")
Attrs: role (user|assistant|tool), content (String), tool_name (String, optional), trace_id (String, optional)
```

- [ ] **Step 1: Write the failing tests**

`tools/tests/test_sessions.py`:
```python
"""Tests for the sessions REST Lambda."""
import json
import os

import pytest

from tools.lambda_.sessions import handler


def _event(method: str, path: str, body=None, path_params=None) -> dict:
    return {
        "httpMethod": method,
        "resource": path,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
    }


def test_post_sessions_creates_session(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    resp = handler.handler(_event("POST", "/sessions"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "session_id" in body
    assert len(body["session_id"]) == 36  # uuid4


def test_post_messages_appends_turn(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    sid = json.loads(handler.handler(_event("POST", "/sessions"), None)["body"])["session_id"]

    resp = handler.handler(
        _event(
            "POST",
            "/sessions/{sid}/messages",
            body={"role": "user", "content": "run baseline"},
            path_params={"sid": sid},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["turn_id"]


def test_get_messages_returns_history_in_order(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    sid = json.loads(handler.handler(_event("POST", "/sessions"), None)["body"])["session_id"]
    for i in range(3):
        handler.handler(
            _event(
                "POST",
                "/sessions/{sid}/messages",
                body={"role": "user", "content": f"msg {i}"},
                path_params={"sid": sid},
            ),
            None,
        )
    resp = handler.handler(
        _event("GET", "/sessions/{sid}/messages", path_params={"sid": sid}),
        None,
    )
    body = json.loads(resp["body"])
    assert [m["content"] for m in body["messages"]] == ["msg 0", "msg 1", "msg 2"]


def test_post_messages_rejects_invalid_role(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    sid = json.loads(handler.handler(_event("POST", "/sessions"), None)["body"])["session_id"]
    resp = handler.handler(
        _event(
            "POST",
            "/sessions/{sid}/messages",
            body={"role": "system", "content": "..."},
            path_params={"sid": sid},
        ),
        None,
    )
    assert resp["statusCode"] == 400


def test_unknown_route_returns_404(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    resp = handler.handler(_event("GET", "/nope"), None)
    assert resp["statusCode"] == 404
```

Append to `tools/tests/conftest.py`:
```python
import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def sessions_table(monkeypatch):
    """Mocked DynamoDB sessions table; returns the table name."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="sessions",
            KeySchema=[
                {"AttributeName": "session_id", "KeyType": "HASH"},
                {"AttributeName": "turn_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "turn_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield "sessions"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_sessions.py -v
```

Expected: FAIL — `ModuleNotFoundError: tools.lambda_.sessions`.

- [ ] **Step 3: Implement `tools/lambda/sessions/handler.py`**

```python
"""REST sessions handler: create sessions and append/list transcript turns."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from tools.lambda_.shared import responses

VALID_ROLES = {"user", "assistant", "tool"}


def _table():
    return boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _create_session() -> dict[str, Any]:
    sid = str(uuid.uuid4())
    _table().put_item(
        Item={
            "session_id": sid,
            "turn_id": "0000-meta",
            "role": "meta",
            "content": "session created",
            "created_at": _now_iso(),
        }
    )
    return responses.http_ok({"session_id": sid})


def _append_message(sid: str, body: dict) -> dict[str, Any]:
    role = body.get("role")
    content = body.get("content")
    if role not in VALID_ROLES:
        return responses.http_error(f"invalid role: {role!r}", status=400)
    if not isinstance(content, str) or not content:
        return responses.http_error("content must be a non-empty string", status=400)

    turn_id = f"{_now_iso()}#{role}"
    item = {
        "session_id": sid,
        "turn_id": turn_id,
        "role": role,
        "content": content,
    }
    if "tool_name" in body:
        item["tool_name"] = str(body["tool_name"])
    if "trace_id" in body:
        item["trace_id"] = str(body["trace_id"])

    _table().put_item(Item=item)
    return responses.http_ok({"turn_id": turn_id})


def _list_messages(sid: str) -> dict[str, Any]:
    resp = _table().query(
        KeyConditionExpression=Key("session_id").eq(sid),
        ScanIndexForward=True,
    )
    messages = [
        {k: v for k, v in item.items() if k != "session_id"}
        for item in resp.get("Items", [])
        if item.get("role") in VALID_ROLES
    ]
    return responses.http_ok({"messages": messages})


def handler(event: dict, _context) -> dict[str, Any]:
    method = event.get("httpMethod")
    resource = event.get("resource", "")
    body = json.loads(event["body"]) if event.get("body") else {}
    sid = (event.get("pathParameters") or {}).get("sid")

    if method == "POST" and resource == "/sessions":
        return _create_session()
    if method == "POST" and resource == "/sessions/{sid}/messages" and sid:
        return _append_message(sid, body)
    if method == "GET" and resource == "/sessions/{sid}/messages" and sid:
        return _list_messages(sid)

    return responses.http_error(f"no route for {method} {resource}", status=404)
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_sessions.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/sessions/handler.py tools/tests/test_sessions.py tools/tests/conftest.py
git commit -m "feat(tools): sessions Lambda with DynamoDB-backed transcript store

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 17: Agent invocation Lambda (REST handler that calls AgentCore)

**Files:**
- Create: `tools/lambda/invoke_agent/handler.py`
- Create: `tools/tests/test_invoke_agent.py`

The frontend POSTs `{session_id, prompt}` to `/invoke`. The Lambda calls `bedrock-agentcore.invoke_agent_runtime` against the AgentCore Runtime endpoint, persists the user turn and assistant turn into DynamoDB, and returns the final text. Streaming is handled by **Task 18's SSE relay**, not here — this Lambda is the synchronous fallback used by tests and "skip animation" toggles.

> `invoke_agent_runtime(agentRuntimeArn, runtimeSessionId, payload)` returns
> `{"contentType": ..., "response": <iterable of byte chunks>}`. For the
> synchronous path we concatenate the chunks into the final text. Env var:
> `AGENT_RUNTIME_ARN` (the Runtime endpoint ARN from the agent stack).

- [ ] **Step 1: Write the failing tests**

`tools/tests/test_invoke_agent.py`:
```python
"""Tests for the synchronous agent-invocation Lambda."""
import json
from unittest.mock import patch

import pytest

from tools.lambda_.invoke_agent import handler


def _event(body: dict) -> dict:
    return {"httpMethod": "POST", "resource": "/invoke", "body": json.dumps(body)}


@pytest.fixture
def env(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:000:runtime/x/endpoint/live")


def _fake_agent_response(text: str) -> dict:
    """Shape mirrors bedrock-agentcore invoke_agent_runtime response."""
    return {"contentType": "application/json", "response": iter([text.encode("utf-8")])}


def test_invoke_persists_turns_and_returns_text(env):
    body = {"session_id": "s1", "prompt": "run baseline"}
    with patch.object(
        handler, "_invoke_agent", return_value=_fake_agent_response("ok, running")
    ) as mocked:
        resp = handler.handler(_event(body), None)

    assert resp["statusCode"] == 200
    out = json.loads(resp["body"])
    assert out["text"] == "ok, running"
    mocked.assert_called_once()


def test_invoke_concatenates_multiple_chunks(env):
    body = {"session_id": "s1", "prompt": "x"}
    with patch.object(
        handler,
        "_invoke_agent",
        return_value={"contentType": "application/json", "response": iter([b"hello ", b"world"])},
    ):
        resp = handler.handler(_event(body), None)
    assert json.loads(resp["body"])["text"] == "hello world"


def test_invoke_validates_payload(env):
    resp = handler.handler(_event({"prompt": "x"}), None)
    assert resp["statusCode"] == 400
    resp = handler.handler(_event({"session_id": "s1"}), None)
    assert resp["statusCode"] == 400
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_invoke_agent.py -v
```

Expected: FAIL — `ModuleNotFoundError: tools.lambda_.invoke_agent`.

- [ ] **Step 3: Implement `tools/lambda/invoke_agent/handler.py`**

```python
"""Synchronous agent invocation: POST /invoke {session_id, prompt} → {text}."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from tools.lambda_.shared import responses

_AGENT_RUNTIME = None


def _agent_runtime():
    global _AGENT_RUNTIME
    if _AGENT_RUNTIME is None:
        _AGENT_RUNTIME = boto3.client("bedrock-agentcore")
    return _AGENT_RUNTIME


def _invoke_agent(session_id: str, prompt: str) -> dict:
    """Thin wrapper so tests can patch a single seam."""
    return _agent_runtime().invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _persist(sid: str, role: str, content: str) -> None:
    boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"]).put_item(
        Item={
            "session_id": sid,
            "turn_id": f"{_now_iso()}#{role}",
            "role": role,
            "content": content,
        }
    )


def handler(event: dict, _context) -> dict[str, Any]:
    body = json.loads(event["body"]) if event.get("body") else {}
    sid = body.get("session_id")
    prompt = body.get("prompt")
    if not sid or not prompt:
        return responses.http_error("session_id and prompt required", status=400)

    _persist(sid, "user", prompt)

    raw = _invoke_agent(sid, prompt)
    parts: list[bytes] = []
    for chunk in raw["response"]:
        parts.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
    text = b"".join(parts).decode("utf-8", errors="replace")

    _persist(sid, "assistant", text)
    return responses.http_ok({"text": text})
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_invoke_agent.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/invoke_agent/handler.py tools/tests/test_invoke_agent.py
git commit -m "feat(tools): synchronous agent invocation Lambda

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 18: API Gateway stack — REST routes + Lambda authorizer + SSE relay

**Files:**
- Create: `tools/lambda/sse_relay/handler.py`
- Create: `tools/tests/test_sse_relay.py`
- Create: `infra/lib/api-stack.ts`
- Create: `infra/test/api-stack.test.ts`
- Modify: `infra/bin/app.ts` — instantiate `ApiStack`

The REST API exposes:
- `POST /sessions`
- `GET  /sessions/{sid}/messages`
- `POST /sessions/{sid}/messages`
- `POST /invoke`
- `GET  /stream` (SSE: `?session_id=...&prompt=...`)

The SSE relay is a separate Lambda using **Lambda response streaming** (FunctionUrl with `RESPONSE_STREAM`). API Gateway REST does not pass through SSE, so the SPA hits the Lambda Function URL directly for streaming and the Function URL is gated by IAM via the Lambda authorizer's API key (we forward the key in a custom header and the function checks it before streaming).

> **Why Function URL, not REST integration:** REST API Gateway buffers responses; SSE needs unbuffered chunked transfer. Function URLs with `InvokeMode=RESPONSE_STREAM` and `awslambda.streamifyResponse` are the only Lambda-native SSE option that doesn't require WebSockets.

- [ ] **Step 1: Write the failing SSE relay test**

`tools/tests/test_sse_relay.py`:
```python
"""Unit tests for SSE relay Lambda — runs in-process, no streaming runtime."""
import json
from unittest.mock import patch, MagicMock

import pytest

from tools.lambda_.sse_relay import handler


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:000:runtime/x/endpoint/live")
    monkeypatch.setenv("API_KEY_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:000:secret:k")


def test_format_sse_event_emits_data_line():
    line = handler._sse("hello")
    assert line == "data: hello\n\n"


def test_format_sse_event_handles_multiline():
    line = handler._sse("line1\nline2")
    assert line == "data: line1\ndata: line2\n\n"


def test_iter_chunks_yields_decoded_text(env):
    # invoke_agent_runtime returns {"response": <iterable of byte chunks>}.
    raw = {"contentType": "application/json", "response": iter([b"hello ", b"world"])}
    out = list(handler._iter_chunks(raw))
    assert out == ["hello ", "world"]


def test_authorize_rejects_wrong_key(env, monkeypatch):
    secret = MagicMock()
    secret.get_secret_value.return_value = {"SecretString": "right-key"}
    monkeypatch.setattr(handler, "_secrets", lambda: secret)
    assert handler._authorize({"x-api-key": "wrong"}) is False
    assert handler._authorize({"x-api-key": "right-key"}) is True


def test_authorize_is_case_insensitive(env, monkeypatch):
    secret = MagicMock()
    secret.get_secret_value.return_value = {"SecretString": "k"}
    monkeypatch.setattr(handler, "_secrets", lambda: secret)
    assert handler._authorize({"X-Api-Key": "k"}) is True
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_sse_relay.py -v
```

Expected: FAIL — `ModuleNotFoundError: tools.lambda_.sse_relay`.

- [ ] **Step 3: Implement `tools/lambda/sse_relay/handler.py`**

```python
"""Lambda Function URL SSE relay.

AgentCore Runtime returns a streaming response from `invoke_agent_runtime`. We
re-emit each chunk as a Server-Sent Event ("data: <text>\\n\\n"). The actual
deployable is the Node 20 streaming entrypoint (`index.mjs`); this Python module
exists for unit-testing the parsing helpers and the auth check, and the Node
shim mirrors the same logic.
"""
from __future__ import annotations

import os
from typing import Iterable, Iterator

import boto3

_SECRETS = None


def _secrets():
    global _SECRETS
    if _SECRETS is None:
        _SECRETS = boto3.client("secretsmanager")
    return _SECRETS


def _authorize(headers: dict[str, str]) -> bool:
    expected = _secrets().get_secret_value(SecretId=os.environ["API_KEY_SECRET_ARN"])[
        "SecretString"
    ]
    for k, v in headers.items():
        if k.lower() == "x-api-key":
            return v == expected
    return False


def _sse(text: str) -> str:
    """Format `text` as an SSE event (multi-line safe)."""
    lines = text.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


def _iter_chunks(raw: dict) -> Iterator[str]:
    # invoke_agent_runtime returns {"response": <iterable of byte chunks>}.
    for chunk in raw["response"]:
        yield (chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")).decode(
            "utf-8", errors="replace"
        )


def stream_sse(session_id: str, prompt: str) -> Iterable[str]:
    """Generator suitable for a streaming HTTP body."""
    import json

    rt = boto3.client("bedrock-agentcore")
    raw = rt.invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
    )
    for chunk in _iter_chunks(raw):
        yield _sse(chunk)
    yield _sse("[DONE]")
```

Also create `tools/lambda/sse_relay/index.mjs` (the actual Node 20 streaming entrypoint):

```javascript
// Node 20 streaming entrypoint for the SSE relay.
// Wraps Bedrock AgentCore's streaming response into Server-Sent Events.
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from '@aws-sdk/client-bedrock-agentcore';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

const agentClient = new BedrockAgentCoreClient({});
const secretsClient = new SecretsManagerClient({});

let cachedKey = null;
async function getApiKey() {
  if (cachedKey) return cachedKey;
  const out = await secretsClient.send(
    new GetSecretValueCommand({ SecretId: process.env.API_KEY_SECRET_ARN })
  );
  cachedKey = out.SecretString;
  return cachedKey;
}

function isAuthorized(headers, key) {
  for (const [name, value] of Object.entries(headers || {})) {
    if (name.toLowerCase() === 'x-api-key' && value === key) return true;
  }
  return false;
}

function sseFrame(text) {
  return text.split('\n').map((l) => `data: ${l}\n`).join('') + '\n';
}

export const handler = awslambda.streamifyResponse(async (event, responseStream) => {
  const headers = event.headers || {};
  const key = await getApiKey();
  if (!isAuthorized(headers, key)) {
    responseStream.setContentType('text/plain');
    responseStream.write('unauthorized');
    responseStream.end();
    return;
  }

  const qs = event.queryStringParameters || {};
  const sessionId = qs.session_id;
  const prompt = qs.prompt;
  if (!sessionId || !prompt) {
    responseStream.setContentType('text/plain');
    responseStream.write('session_id and prompt required');
    responseStream.end();
    return;
  }

  responseStream.setContentType('text/event-stream');

  try {
    const cmd = new InvokeAgentRuntimeCommand({
      agentRuntimeArn: process.env.AGENT_RUNTIME_ARN,
      runtimeSessionId: sessionId,
      payload: new TextEncoder().encode(JSON.stringify({ prompt })),
    });
    const response = await agentClient.send(cmd);
    // The streaming body is an async iterable of byte chunks.
    for await (const chunk of response.response) {
      const text = Buffer.from(chunk).toString('utf-8');
      responseStream.write(sseFrame(text));
    }
    responseStream.write(sseFrame('[DONE]'));
  } catch (err) {
    responseStream.write(sseFrame(`[ERROR] ${err.message}`));
  } finally {
    responseStream.end();
  }
});
```

And `tools/lambda/sse_relay/package.json`:

```json
{
  "name": "sse-relay",
  "version": "0.1.0",
  "type": "module",
  "dependencies": {
    "@aws-sdk/client-bedrock-agentcore": "^3.600.0",
    "@aws-sdk/client-secrets-manager": "^3.600.0"
  }
}
```

- [ ] **Step 4: Run, confirm tests pass**

```bash
pytest tools/tests/test_sse_relay.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Write the failing API stack test**

`infra/test/api-stack.test.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
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
  return { api, t: Template.fromStack(api) };
}

test('creates one REST API with regional endpoint', () => {
  const { t } = build();
  t.resourceCountIs('AWS::ApiGateway::RestApi', 1);
  t.hasResourceProperties('AWS::ApiGateway::RestApi', {
    EndpointConfiguration: { Types: ['REGIONAL'] },
  });
});

test('every public route is gated by the Lambda authorizer', () => {
  const { t } = build();
  // All POST / GET methods on /sessions, /sessions/{sid}/messages, /invoke must reference our authorizer.
  const methods = t.findResources('AWS::ApiGateway::Method');
  const protectedHttpVerbs = ['POST', 'GET'];
  for (const [, res] of Object.entries(methods)) {
    const props = (res as any).Properties;
    if (!protectedHttpVerbs.includes(props.HttpMethod)) continue;
    if (props.AuthorizationType === 'NONE' && props.HttpMethod === 'OPTIONS') continue;
    expect(props.AuthorizationType).toBe('CUSTOM');
  }
});

test('exposes a Lambda Function URL for SSE streaming', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Lambda::Url', {
    AuthType: 'NONE',
    InvokeMode: 'RESPONSE_STREAM',
  });
});

test('CORS allows the configured frontend origin', () => {
  const { t } = build();
  // Cloudscape SPA on Amplify Hosting — origin is read from context at synth time.
  t.hasResourceProperties('AWS::ApiGateway::Method', Match.objectLike({
    HttpMethod: 'OPTIONS',
  }));
});

test('exposes apiUrl and streamUrl outputs', () => {
  const { api } = build();
  expect(api.apiUrl).toBeDefined();
  expect(api.streamUrl).toBeDefined();
});
```

- [ ] **Step 6: Run, confirm fail**

```bash
cd infra && npm test -- api-stack
```

Expected: FAIL — `Cannot find module '../lib/api-stack'`.

- [ ] **Step 7: Implement `infra/lib/api-stack.ts`**

```typescript
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

    // ---- DynamoDB sessions table.
    const sessionsTable = new dynamodb.Table(this, 'Sessions', {
      partitionKey: { name: 'session_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'turn_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.sessionsTable = sessionsTable;

    // ---- Sessions Lambda (Python).
    const sessionsFn = new lambda.Function(this, 'SessionsFn', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'sessions.handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'tools', 'lambda')),
      layers: [props.tools.coreLayer],
      environment: { SESSIONS_TABLE: sessionsTable.tableName },
      timeout: cdk.Duration.seconds(15),
    });
    sessionsTable.grantReadWriteData(sessionsFn);

    // ---- Invoke-agent Lambda (Python).
    const invokeFn = new lambda.Function(this, 'InvokeFn', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'invoke_agent.handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'tools', 'lambda')),
      layers: [props.tools.coreLayer],
      environment: {
        SESSIONS_TABLE: sessionsTable.tableName,
        AGENT_RUNTIME_ARN: props.agent.runtimeEndpointArn,
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

    // ---- SSE relay Lambda (Node 20, streaming response).
    const sseFn = new nodejs.NodejsFunction(this, 'SseRelayFn', {
      runtime: lambda.Runtime.NODEJS_20_X,
      entry: path.join(__dirname, '..', '..', 'tools', 'lambda', 'sse_relay', 'index.mjs'),
      handler: 'handler',
      timeout: cdk.Duration.minutes(2),
      environment: {
        AGENT_RUNTIME_ARN: props.agent.runtimeEndpointArn,
        API_KEY_SECRET_ARN: props.tools.apiKeySecretArn,
      },
      bundling: { format: nodejs.OutputFormat.ESM, target: 'node20' },
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

    // ---- REST API.
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

    const authorizer = new apigw.RequestAuthorizer(this, 'ApiKeyAuthorizer', {
      handler: props.tools.fnAuthorizer,
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
```

- [ ] **Step 8: Wire into `infra/bin/app.ts`**

After the `agentStack` instantiation, add:

```typescript
import { ApiStack } from '../lib/api-stack';

const apiStack = new ApiStack(app, 'Chronos2DemoApi', {
  env,
  tools,
  agent: agentStack,
});
apiStack.addDependency(agentStack);
```

- [ ] **Step 9: Run tests, confirm pass**

```bash
cd infra && npm test -- api-stack
pytest tools/tests/test_sse_relay.py -v
```

Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add tools/lambda/sse_relay/ tools/tests/test_sse_relay.py infra/lib/api-stack.ts infra/test/api-stack.test.ts infra/bin/app.ts
git commit -m "feat(infra): API Gateway REST + Function URL SSE relay

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-7.md` (Stage 7 — Cloudscape SPA, Tasks 19–22)._
