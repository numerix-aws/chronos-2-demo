# SSE Streaming Behind CloudFront + WAF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-enable the demo's SSE streaming path by fronting the `SseRelayFn` Lambda Function URL with a CloudFront distribution (Origin Access Control + SigV4) and an AWS WAF WebACL, flipping the Function URL from public (`AuthType: NONE`) to `AWS_IAM` so it is no longer world-accessible.

**Architecture:** Stream-only edge. CloudFront fronts only the SSE Function URL; the SPA stays on Amplify. The Function URL flips to `AWS_IAM`; a CloudFront OAC (`SIGV4_ALWAYS`) signs each origin request, and CDK scopes a `lambda:InvokeFunctionUrl` resource policy to the distribution. A WAF WebACL (CLOUDFRONT scope, us-east-1) adds AWS Managed Rules + a rate-based rule. Caching is disabled so the streamed body passes through unbuffered; `x-api-key` is forwarded via `ALL_VIEWER_EXCEPT_HOST_HEADER`. The relay's app-layer `x-api-key` check is unchanged. `streamUrl` now emits the CloudFront domain; the frontend needs no code change (it already reads `VITE_STREAM_URL`).

**Tech Stack:** AWS CDK 2.257.0 (TypeScript), `aws-cloudfront`, `aws-cloudfront-origins` (`FunctionUrlOrigin.withOriginAccessControl`), `aws-wafv2` (`CfnWebACL`), jest snapshot tests. Container engine is **finch** (`export CDK_DOCKER=finch` for `npm test`).

**Reference:** Design spec `docs/superpowers/specs/2026-06-07-sse-cloudfront-waf-design.md`.

---

## Notes for the executor (read first)

- **All work is in `infra/` and `docs/`.** Do NOT touch `frontend/`, `tools/`, `agent/`, or any Plan A code. The frontend already streams via `VITE_STREAM_URL`; only the value changes (handled by existing `FrontendStack` wiring).
- **`CDK_DOCKER=finch` is mandatory** for `npm test` / `cdk synth` — without it ToolsStack Lambda-layer bundling fails ~22 tests (memory `reference-infra-test-docker`). `docker` is only a shell alias to `finch`.
- **One commit per task**, message exactly as written, including the `Co-Authored-By` trailer.
- The CDK APIs used here all exist in 2.257.0 — verified: `FunctionUrlOrigin.withOriginAccessControl`, `CachePolicy.CACHING_DISABLED`, `OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER`, `wafv2.CfnWebACL`, `Distribution.webAclId`.

## File Structure

- **Modify** `infra/lib/api-stack.ts` — flip Function URL to `AWS_IAM`; add WAF WebACL, CloudFront distribution (OAC origin, caching disabled, x-api-key forwarded, WAF attached); repoint `streamUrl` to the distribution domain.
- **Modify** `infra/test/api-stack.test.ts` — flip the Function URL auth assertion; add distribution + WebACL + OAC assertions.
- **Modify** `docs/runbook.md` — SSE re-enabled note, new resources/outputs, troubleshooting rows, teardown tag note.

---

### Task 1: Flip the Function URL to AWS_IAM (test-first)

**Files:**
- Modify: `infra/test/api-stack.test.ts` (the `exposes a Lambda Function URL for SSE streaming` test)
- Modify: `infra/lib/api-stack.ts:118-120`

- [ ] **Step 1: Update the failing test**

In `infra/test/api-stack.test.ts`, change the existing test to assert `AWS_IAM`:

```typescript
test('exposes a Lambda Function URL for SSE streaming (AWS_IAM, fronted by CloudFront)', () => {
  const { t } = build();
  t.hasResourceProperties('AWS::Lambda::Url', {
    AuthType: 'AWS_IAM',
    InvokeMode: 'RESPONSE_STREAM',
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd infra && CDK_DOCKER=finch npx jest api-stack -t "exposes a Lambda Function URL"`
Expected: FAIL — template still has `AuthType: 'NONE'`.

- [ ] **Step 3: Flip the auth type in the stack**

In `infra/lib/api-stack.ts`, in the `sseFn.addFunctionUrl({...})` call, change:

```typescript
    const sseUrl = sseFn.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.AWS_IAM,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        allowedOrigins: [allowedOrigin],
        allowedHeaders: ['*'],
        allowedMethods: [lambda.HttpMethod.GET],
      },
    });
```

(Only `authType` changes: `NONE` → `AWS_IAM`. Leave `invokeMode` and `cors` as-is. Do NOT change `this.streamUrl` yet — that moves to the CloudFront domain in Task 3.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd infra && CDK_DOCKER=finch npx jest api-stack -t "exposes a Lambda Function URL"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/muffadal/code/chronos-2-demo
git add infra/lib/api-stack.ts infra/test/api-stack.test.ts
git commit -m "feat(infra): flip SSE Function URL to AWS_IAM (no longer public)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Add the WAF WebACL (test-first)

**Files:**
- Modify: `infra/test/api-stack.test.ts` (add a test)
- Modify: `infra/lib/api-stack.ts` (add import + WebACL construct)

- [ ] **Step 1: Write the failing test**

Append to `infra/test/api-stack.test.ts`:

```typescript
test('creates a CLOUDFRONT-scoped WAF WebACL with managed + rate rules', () => {
  const { t } = build();
  t.resourceCountIs('AWS::WAFv2::WebACL', 1);
  t.hasResourceProperties('AWS::WAFv2::WebACL', {
    Scope: 'CLOUDFRONT',
    DefaultAction: { Allow: {} },
    Rules: Match.arrayWith([
      Match.objectLike({
        Name: 'CommonRuleSet',
        Statement: { ManagedRuleGroupStatement: { Name: 'AWSManagedRulesCommonRuleSet', VendorName: 'AWS' } },
      }),
      Match.objectLike({
        Name: 'KnownBadInputs',
        Statement: { ManagedRuleGroupStatement: { Name: 'AWSManagedRulesKnownBadInputsRuleSet', VendorName: 'AWS' } },
      }),
      Match.objectLike({
        Name: 'RateLimit',
        Statement: { RateBasedStatement: { Limit: 100, AggregateKeyType: 'IP' } },
      }),
    ]),
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd infra && CDK_DOCKER=finch npx jest api-stack -t "WAF WebACL"`
Expected: FAIL — no `AWS::WAFv2::WebACL` in the template.

- [ ] **Step 3: Add the WebACL to the stack**

In `infra/lib/api-stack.ts`, add the import near the other CDK imports (after the `nodejs` import line):

```typescript
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
```

Then, immediately after the `const sseUrl = sseFn.addFunctionUrl({...});` block (and before `this.streamUrl = ...`), add:

```typescript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd infra && CDK_DOCKER=finch npx jest api-stack -t "WAF WebACL"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/muffadal/code/chronos-2-demo
git add infra/lib/api-stack.ts infra/test/api-stack.test.ts
git commit -m "feat(infra): add CLOUDFRONT-scoped WAF WebACL for the stream edge

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Add the CloudFront distribution + OAC and repoint streamUrl (test-first)

**Files:**
- Modify: `infra/test/api-stack.test.ts` (add tests)
- Modify: `infra/lib/api-stack.ts` (distribution, OAC origin, WAF attach, streamUrl)

- [ ] **Step 1: Write the failing tests**

Append to `infra/test/api-stack.test.ts`:

```typescript
test('fronts the Function URL with a CloudFront distribution using OAC and no caching', () => {
  const { t } = build();
  t.resourceCountIs('AWS::CloudFront::Distribution', 1);
  t.resourceCountIs('AWS::CloudFront::OriginAccessControl', 1);
  // OAC signs requests to the Lambda origin with SigV4, always.
  t.hasResourceProperties('AWS::CloudFront::OriginAccessControl', {
    OriginAccessControlConfig: Match.objectLike({
      OriginAccessControlType: 'lambda',
      SigningBehavior: 'always',
      SigningProtocol: 'sigv4',
    }),
  });
  // Distribution is attached to the WAF WebACL.
  t.hasResourceProperties('AWS::CloudFront::Distribution', {
    DistributionConfig: Match.objectLike({
      WebACLId: Match.anyValue(),
    }),
  });
});

test('streamUrl output is still defined (now the CloudFront domain)', () => {
  const { api } = build();
  expect(api.streamUrl).toBeDefined();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd infra && CDK_DOCKER=finch npx jest api-stack -t "CloudFront distribution"`
Expected: FAIL — no `AWS::CloudFront::Distribution` in the template.

- [ ] **Step 3: Add the distribution and repoint streamUrl**

In `infra/lib/api-stack.ts`, immediately after the `streamWebAcl` block from Task 2, add the distribution:

```typescript
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
```

Then **delete** the old `this.streamUrl = sseUrl.url;` line (the one right after the `addFunctionUrl` block — it is now replaced by the CloudFront domain assignment above).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd infra && CDK_DOCKER=finch npx jest api-stack -t "CloudFront distribution"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/muffadal/code/chronos-2-demo
git add infra/lib/api-stack.ts infra/test/api-stack.test.ts
git commit -m "feat(infra): front SSE Function URL with CloudFront + OAC, repoint streamUrl

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Full infra test + synth regression

**Files:**
- Modify: `infra/test/api-stack.test.ts` only if the snapshot needs an intentional update (see Step 2).

- [ ] **Step 1: Run the full infra test suite**

Run: `cd infra && CDK_DOCKER=finch npm test`
Expected: All tests pass. The api-stack snapshot test (if present) will report a diff because the template now has a distribution + WebACL.

- [ ] **Step 2: Update the snapshot if (and only if) the diff is the expected new resources**

Inspect the diff. If it shows ONLY the new CloudFront distribution, OAC, WebACL, the `AWS_IAM` Function URL, and the changed `StreamUrlOut`, update the snapshot:

Run: `cd infra && CDK_DOCKER=finch npx jest -u`
Expected: snapshot updated, all green. If the diff shows anything unexpected (other stacks changed, resources removed), STOP and investigate — do not blanket-update.

- [ ] **Step 3: Synth the Api stack to confirm it renders**

Run: `cd infra && CDK_DOCKER=finch npx cdk synth Chronos2DemoApi > /dev/null && echo SYNTH_OK`
Expected: `SYNTH_OK` (no synth errors).

- [ ] **Step 4: Commit (only if files changed)**

```bash
cd /Users/muffadal/code/chronos-2-demo
git add infra/test
git commit -m "test(infra): update api-stack snapshot for CloudFront+WAF stream edge

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

If `git status` shows no changes (no snapshot file existed), skip the commit and note that in the task summary.

---

### Task 5: Update the runbook

**Files:**
- Modify: `docs/runbook.md`

- [ ] **Step 1: Update the first-deploy SSE note**

In `docs/runbook.md`, the first-deploy notes block (~line 27-29) currently says the headline chain "was designed to stream over SSE (see the SSE security note in §2/teardown)." Replace that sentence's tail so it reads:

```
> - **finch** is the container engine here: export `CDK_DOCKER=finch`; build images
>   `--platform` explicitly. The full headline chain exceeds API GW's 29s sync cap —
>   it streams over SSE, now **re-enabled behind CloudFront + WAF** (the SSE Function
>   URL is `AWS_IAM` + Origin Access Control, no longer public — see §6 streaming).
```

- [ ] **Step 2: Update the outputs list**

In the "Capture these outputs" list (~line 60-66), update the `StreamUrlOut` line to note it is now a CloudFront URL:

```
- `Chronos2DemoApi.StreamUrlOut` → `STREAM_URL` (CloudFront domain fronting the SSE relay)
```

- [ ] **Step 3: Update the troubleshooting table**

In the troubleshooting table, replace the row:

```
| Headline `/invoke` 504 at ~29s | API GW sync cap vs multi-minute Fargate | Expected without SSE; use streaming path or a poll UI |
```

with:

```
| Headline `/invoke` 504 at ~29s | API GW sync cap vs multi-minute Fargate | Use the streaming path (SSE via CloudFront) — `/invoke` is the non-streaming fallback only |
| Stream returns 403 via CloudFront | OAC policy not applied, or WAF blocked the request | Confirm the Function URL is `AWS_IAM` + the OAC `lambda:InvokeFunctionUrl` policy is present; check the `chronos2StreamWebAcl` WAF metrics for blocks |
| Stream CORS preflight fails | Custom `x-api-key` header not reaching origin | Verify the distribution uses `ALL_VIEWER_EXCEPT_HOST_HEADER`; fallback is a CloudFront `ResponseHeadersPolicy` with explicit CORS |
```

- [ ] **Step 4: Add a streaming section and teardown note**

Add a new section before "## 7. Teardown" (renumber is not required — call it §6 streaming verification or append under the demo script). Insert:

```markdown
## 6b. Streaming edge (CloudFront + WAF) verification

The SSE relay Function URL is `AWS_IAM` and fronted by a CloudFront distribution
(Origin Access Control, SigV4) with a WAF WebACL (AWS Managed Common +
Known-Bad-Inputs rule groups + a 100-req/5-min per-IP rate rule). The browser
talks only to the CloudFront domain (`STREAM_URL`); the raw Function URL is not
publicly invocable.

```bash
# Raw Function URL must NOT be publicly invocable (expect 403):
curl -s -o /dev/null -w '%{http_code}\n' "<RAW_FUNCTION_URL>?session_id=x&prompt=hi"   # 403

# CloudFront URL with a valid key streams SSE (expect text/event-stream frames):
curl -N -H "x-api-key: $DEMO_API_KEY" \
  "$STREAM_URL?session_id=demo&prompt=hello"
```

The CloudFront distribution and WAF WebACL are tagged `chronos2-demo:teardown=on`
and are removed by `cdk destroy --all`.
```

- [ ] **Step 5: Commit**

```bash
cd /Users/muffadal/code/chronos-2-demo
git add docs/runbook.md
git commit -m "docs(runbook): SSE re-enabled behind CloudFront+WAF; new outputs + troubleshooting

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification (after all tasks)

- [ ] `cd infra && CDK_DOCKER=finch npm test` — full suite green.
- [ ] `cd infra && CDK_DOCKER=finch npx cdk synth Chronos2DemoApi > /dev/null && echo OK` — renders.
- [ ] `git log --oneline -6` — one commit per task, messages as written.
- [ ] Spec coverage: Function URL `AWS_IAM` (T1) ✓, WAF (T2) ✓, CloudFront+OAC+caching-disabled+x-api-key-forward (T3) ✓, tests (T1-T4) ✓, runbook (T5) ✓. Frontend intentionally unchanged (value-only via existing FrontendStack wiring).
