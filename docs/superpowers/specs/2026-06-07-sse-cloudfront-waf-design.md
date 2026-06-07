# Re-enable SSE Streaming Behind CloudFront + WAF — Design

**Date:** 2026-06-07
**Status:** Approved (design phase)
**Author:** Claude (Opus 4.8) with muffadalq
**Scope:** Plan B infra (`infra/`), frontend env wiring, runbook. No Plan A / quant-core changes.

> **ARCC note.** This work touches network exposure, CloudFront, WAF, Lambda
> Function URLs, and IAM. Per `~/.claude/rules/arcc-governance.md` the first step
> would be `search_arcc`, but the ARCC MCP server is **not connected** in this
> environment (see memory `reference-arcc-unavailable`). Applying the governance
> fallback: standard AWS security practices (least-privilege resource policies,
> AWS Managed WAF rule groups, CloudFront Origin Access Control), with each
> security-sensitive decision called out explicitly below.

## 1. Problem

The demo's token-by-token streamed headline run uses an SSE relay Lambda
(`SseRelayFn`) exposed via a **Lambda Function URL** with
`AuthType: NONE` + `InvokeMode: RESPONSE_STREAM`. On 2026-06-06 corporate
security **Palisade** flagged that Function URL as **world-accessible**; **Epoxy
Mitigations** auto-revoked the public `lambda:InvokeFunctionUrl` grant and opened
a Talos risk ticket. The URL now returns **403**, so streaming is broken and the
demo falls back to the synchronous `POST /invoke` path — which hits API
Gateway's 29 s integration cap (504) on the multi-minute headline chain.

The user's decision (memory `project-sse-relay-security-flag`) was to **respect**
the mitigation — do **not** re-open the public Function URL — and, if streaming is
needed again, **harden it behind CloudFront + WAF**. This spec is that hardening.

### Why the Function URL exists at all (don't "fix" these — Plan B invariants)
- Streaming needs a Function URL with `RESPONSE_STREAM`; API Gateway REST buffers
  responses and breaks SSE.
- The browser consumes the stream with `fetch` + `ReadableStream` (not
  `EventSource`, which cannot send the `x-api-key` header) and **cannot SigV4-sign**
  its requests — so `AuthType: AWS_IAM` directly from the browser is infeasible.
- Compensating control today: an **app-layer `x-api-key` check** inside the relay
  (`tools/lambda/sse_relay/index.mjs`) validated against the API key secret.

## 2. Goal & non-goals

**Goal:** Restore streaming for the demo while resolving Palisade's finding *at
the source* — the Function URL must stop being publicly invocable — and add an
edge security layer (WAF) in front of it.

**Non-goals:**
- Not unifying the SPA + stream behind one distribution (stream-only edge; SPA
  stays on Amplify). Decided with the user.
- Not changing the relay's streaming logic, the agent, or any Plan A code.
- Not changing the synchronous `POST /invoke` path — it remains as a fallback.

## 3. Architecture (stream-only edge)

```
Browser (Amplify SPA)
  │  fetch(VITE_STREAM_URL, header x-api-key)     ← repointed to the CloudFront domain
  ▼
CloudFront distribution  ──── WAF WebACL (scope = CLOUDFRONT, us-east-1)
  │   • OAC signs every origin request with SigV4 (SIGV4_ALWAYS)
  │   • CachePolicy = CACHING_DISABLED          → SSE body passes through unbuffered
  │   • OriginRequestPolicy = ALL_VIEWER_EXCEPT_HOST_HEADER → forwards x-api-key + Origin
  ▼
Lambda Function URL  (AuthType: NONE → AWS_IAM)
  │   resource policy: lambda:InvokeFunctionUrl allowed ONLY for
  │   Principal = cloudfront.amazonaws.com, Condition aws:SourceArn = this distribution
  ▼
SseRelayFn (UNCHANGED) → app-layer x-api-key check → bedrock-agentcore:InvokeAgentRuntime (RESPONSE_STREAM)
```

### Layered access control (defense in depth)
1. **Edge / network:** WAF WebACL on the distribution — AWS Managed Rules
   (`AWSManagedRulesCommonRuleSet` + `AWSManagedRulesKnownBadInputsRuleSet`) plus a
   **rate-based rule** (100 requests / 5 min per source IP, `Block`).
2. **Origin authn:** Function URL flips to `AWS_IAM`; only CloudFront (via OAC,
   scoped by `aws:SourceArn`) can SigV4-sign a valid invoke. The public internet
   can no longer call the Function URL directly → Palisade's finding is resolved.
3. **Application authn:** the relay's existing `x-api-key` check stays as-is — the
   real per-user credential. WAF/OAC gate *who can reach* the relay; `x-api-key`
   gates *who is authorized*.

## 4. Components & changes

### 4.1 `infra/lib/api-stack.ts` (modify)
- **Flip the Function URL auth:** `authType: FunctionUrlAuthType.NONE` →
  `FunctionUrlAuthType.AWS_IAM`. Keep `invokeMode: RESPONSE_STREAM` and the CORS
  block (Function URL CORS still applies under `AWS_IAM`; it answers the browser
  preflight forwarded by CloudFront).
- **New CloudFront distribution** (`aws-cloudfront`) with a single default behavior:
  - origin = `FunctionUrlOrigin.withOriginAccessControl(sseUrl)` — CDK creates the
    OAC (SigV4, signing `ALWAYS`) and wires the `lambda:InvokeFunctionUrl`
    resource policy scoped to the distribution automatically.
  - `cachePolicy: CachePolicy.CACHING_DISABLED`
  - `originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER`
  - `allowedMethods: ALLOW_GET_HEAD_OPTIONS`
  - `viewerProtocolPolicy: REDIRECT_TO_HTTPS`
  - `webAclId` = the WAF WebACL ARN (below).
- **New WAF WebACL** (`aws-wafv2.CfnWebACL`, `scope: 'CLOUDFRONT'` — valid because
  the stack deploys in `us-east-1`). Rules: the two managed rule groups (override
  `none`, vendor `AWS`) + one rate-based rule; default action `Allow`;
  `visibilityConfig` with CloudWatch metrics enabled.
- **Output change:** `streamUrl` (and `StreamUrlOut`) now emit
  `https://<distribution-domain>/` instead of the raw Function URL. The browser
  only ever sees the CloudFront domain.

> **CORS subtlety (flagged at design time).** The browser request is cross-origin
> (Amplify domain → CloudFront domain) and carries a custom `x-api-key` header, so
> it triggers a CORS preflight. `ALL_VIEWER_EXCEPT_HOST_HEADER` forwards `Origin`
> and `x-api-key` to the origin, and the Function URL's own CORS config answers the
> preflight. If preflight ever fails in practice, the fallback is a CloudFront
> `ResponseHeadersPolicy` with an explicit CORS config — noted in the runbook, not
> built pre-emptively (YAGNI).

### 4.2 `infra/test/api-stack.test.ts` (modify)
- The existing test `'exposes a Lambda Function URL for SSE streaming'` asserts
  `AuthType: 'NONE'` — **flip to `'AWS_IAM'`** (keep `InvokeMode: 'RESPONSE_STREAM'`).
- Add assertions: one `AWS::CloudFront::Distribution`, one `AWS::WAFv2::WebACL`
  (scope `CLOUDFRONT`), one `AWS::CloudFront::OriginAccessControl`, and the
  distribution references the WebACL.
- `streamUrl` output still defined (now the CloudFront URL).

### 4.3 Frontend (`frontend/`) — no code change
`stream.ts` / `App.tsx` already consume `VITE_STREAM_URL` via `fetch` +
`ReadableStream` and send `x-api-key`. The only change is the **value** of
`VITE_STREAM_URL` (now the CloudFront domain), injected by `FrontendStack` from
`props.api.streamUrl` — which already happens. No edits to frontend source.

### 4.4 `docs/runbook.md` (modify)
- Update the §2 / teardown SSE security note: streaming is **re-enabled behind
  CloudFront + WAF**; the Function URL is `AWS_IAM` + OAC (no longer public).
- Add the new resources to the architecture/output list (`StreamUrlOut` now a
  CloudFront URL; new WAF + distribution).
- Update the troubleshooting table: the "504 at ~29s / use streaming" row is no
  longer "expected"; add rows for "stream 403 via CloudFront" (OAC policy / WAF
  block) and the CORS-preflight fallback.
- Note `scope: CLOUDFRONT` WAF must be `us-east-1` (already are).
- Re-tag note: the distribution + WebACL carry `chronos2-demo:teardown=on`.

## 5. Security review (fallback for absent ARCC)

| Concern | Mitigation |
| --- | --- |
| Function URL world-accessible (the Palisade finding) | Flipped to `AWS_IAM`; only CloudFront via OAC (`aws:SourceArn`-scoped) can invoke. Public direct invoke → 403. |
| DDoS / common web exploits at the edge | WAF managed Common + Known-Bad-Inputs rule groups. |
| Abuse / brute force of `x-api-key` | WAF rate-based rule (100 / 5 min / IP). |
| Unauthorized users | App-layer `x-api-key` check unchanged (real authn). |
| Least privilege | OAC resource policy scoped to the single distribution ARN; WAF scoped to CLOUDFRONT; no wildcards added. |
| Secret handling | Unchanged — relay reads the API key from Secrets Manager. |

## 6. Testing & verification

- `cd infra && npm test` — jest snapshot + the updated/added assertions
  (`CDK_DOCKER=finch` required for ToolsStack bundling per memory
  `reference-infra-test-docker`).
- `npx cdk synth Chronos2DemoApi` — confirm the distribution, OAC, WebACL, and the
  `AWS_IAM` Function URL render.
- Post-deploy (manual, in runbook): `curl` the raw Function URL → expect 403;
  `curl` the CloudFront URL with a valid `x-api-key` → expect an SSE stream;
  browser headline run streams token-by-token.

## 7. Rollback

Revert the `api-stack.ts` change (Function URL back to `NONE`, drop the
distribution + WebACL) and redeploy. Because Epoxy already revoked the public
grant, rolling back returns to the current (streaming-disabled) state — no new
exposure. The synchronous `/invoke` path is unaffected throughout.

## 8. Out of scope / future
- Single-origin CloudFront (SPA + stream same-origin, CORS eliminated) — larger
  change, deferred.
- Custom domain + ACM cert on the distribution — uses the default
  `*.cloudfront.net` domain for the demo.
