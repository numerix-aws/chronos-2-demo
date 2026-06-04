# Numerix × Chronos-2 Demo — Runbook

Operational guide for deploying, demoing, and tearing down the PoC. Read once
end-to-end before running anything. Steps assume `us-east-1` and an AWS
profile named `chronos2-demo` with admin in the demo account.

## Prerequisites

- Plan A merged: `pip install -e ".[dev]" && pytest` is green.
- Plan A SageMaker endpoint deployed: `chronos2_demo.infra.sagemaker_endpoint.deploy_demo_endpoint()` returns an endpoint name (record it).
- Local toolchain: Node 20+, Python 3.11, Docker (for CDK Lambda layer bundling), AWS CLI v2.
- Bedrock model access: Claude 3.5 Sonnet enabled in the target account/region.
- CDK bootstrap: `cd infra && npx cdk bootstrap aws://ACCOUNT/us-east-1` (one-time).

## 1. Deploy infrastructure

```bash
export AWS_PROFILE=chronos2-demo
export AWS_REGION=us-east-1
export CHRONOS2_ENDPOINT=$(aws sagemaker list-endpoints \
  --query 'Endpoints[?starts_with(EndpointName,`chronos2`)].EndpointName | [0]' \
  --output text)

# Synth + deploy all 7 stacks. First deploy is ~12 minutes.
cd infra
npm install
npm test                      # snapshot tests must be green
npx cdk synth --all > /dev/null
npx cdk deploy --all \
  --context chronos2EndpointName=$CHRONOS2_ENDPOINT \
  --require-approval never
```

Capture these outputs (printed at the end of `cdk deploy`):
- `Chronos2DemoApi.ApiUrlOut` → `API_URL`
- `Chronos2DemoApi.StreamUrlOut` → `STREAM_URL`
- `Chronos2DemoTools.ApiKeySecretArnOut` → `API_KEY_SECRET_ARN`
- `Chronos2DemoFrontend.AmplifyAppIdOut` → `AMPLIFY_APP_ID`
- `Chronos2DemoFrontend.AmplifyDomainOut` → `APP_URL`

Fetch the API key from Secrets Manager:
```bash
export API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id $API_KEY_SECRET_ARN --query SecretString --output text)
```

## 2. Build and deploy the SPA

```bash
cd frontend
echo "VITE_API_URL=$API_URL"        >  .env.production
echo "VITE_STREAM_URL=$STREAM_URL"  >> .env.production
echo "VITE_API_KEY=$API_KEY"        >> .env.production
npm install
npm run build

cd dist
zip -r ../app.zip .
cd ..

DEPLOY=$(aws amplify create-deployment \
  --app-id $AMPLIFY_APP_ID --branch-name main --output json)
JOB_ID=$(echo $DEPLOY | jq -r .jobId)
URL=$(echo $DEPLOY | jq -r .zipUploadUrl)
curl -T app.zip "$URL"
aws amplify start-deployment \
  --app-id $AMPLIFY_APP_ID --branch-name main --job-id $JOB_ID
```

Wait until `aws amplify get-job --app-id $AMPLIFY_APP_ID --branch-name main --job-id $JOB_ID --query 'job.summary.status' --output text` returns `SUCCEED`.

## 3. Smoke test (CLI)

```bash
# Create session
SID=$(curl -s -X POST "$API_URL/sessions" -H "x-api-key: $API_KEY" | jq -r .session_id)
echo "session: $SID"

# Synchronous invocation (skips streaming)
curl -s -X POST "$API_URL/invoke" \
  -H "x-api-key: $API_KEY" -H "content-type: application/json" \
  -d "{\"session_id\":\"$SID\",\"prompt\":\"Run the headline demo at as_of_date=2020-03-15, lookback_days=1260, horizon=252, n_paths=2000, w_stress=0.5. Then plot a PFE overlay.\"}" \
  | jq .text

# Inspect transcript
curl -s "$API_URL/sessions/$SID/messages" -H "x-api-key: $API_KEY" | jq '.messages | length'
```

Expected: a non-empty `text` containing references to "parametric", "Chronos-2", and a markdown image URL.

## 4. End-to-end (browser)

Open `$APP_URL`. Type the same prompt as step 3. Watch the assistant stream
tokens and inline a PFE-overlay chart. Then exercise the **What-if** panel
with `w_stress=0.8` and confirm a second chart renders.

## 5. Run the Playwright happy-path

```bash
cd frontend
cat > tests/e2e/.env <<EOF
RUN_E2E=1
APP_URL=$APP_URL
API_URL=$API_URL
STREAM_URL=$STREAM_URL
API_KEY=$API_KEY
EOF
npm run e2e
```

Expected: 2 passed in ~3-5 minutes.

## 6. CloudWatch dashboard

Open the URL from the `Chronos2DemoObservability.DashboardUrl` output. The
dashboard live-updates while the demo runs; per-Lambda invocation /
duration / error widgets and the SageMaker endpoint widget should all
populate within a minute of activity.

## 7. Teardown

**Cost-bearing resources are tagged `chronos2-demo:teardown=on`.** Two-stage teardown is the canonical sequence:

```bash
# 1. Destroy CDK stacks (reverse dependency order). cdk handles ordering.
cd infra
npx cdk destroy --all --force

# 2. Stop / delete the Plan A SageMaker endpoint.
python -c "from chronos2_demo.infra.sagemaker_endpoint import delete_demo_endpoint; delete_demo_endpoint()"

# 3. (Optional) Wipe data buckets in case versioning kept retained objects.
for b in $(aws s3api list-buckets --query 'Buckets[?starts_with(Name, `chronos2demo`)].Name' --output text); do
  aws s3 rb s3://$b --force
done
```

Verify nothing is left:
```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=chronos2-demo:teardown,Values=on \
  --query 'ResourceTagMappingList[].ResourceARN'
```

Expected: empty list.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `cdk deploy` fails on Lambda layer asset | Docker not running locally | Start Docker Desktop; or set `--no-bundle` if using a pre-built layer asset |
| `bedrock:InvokeAgent` AccessDenied | Claude 3.5 Sonnet not enabled in the account/region | Bedrock console → Model access → Request access |
| Streaming endpoint returns 401 | Wrong API key in browser localStorage | Clear `localStorage["chronos2-demo-session"]`, reload, paste new key |
| Fargate baseline-MC task ENOSPC | Low ephemeral storage | Edit `tools-stack.ts` Fargate task `ephemeralStorageGiB` and redeploy |
| Empty transcript after `/invoke` | Agent action group not invoking Lambda | Check `cloudwatch logs tail /aws/lambda/<tool-fn>` and the agent's `bedrock:InvokeAgent` trace in CloudWatch |
| SSE stream cuts off mid-stream | Lambda timeout shorter than agent latency | Bump `sseFn` timeout in `api-stack.ts` (max 15 min for Function URL streaming) |
| Build fails on `npm run e2e` for first time | Playwright browsers not installed | `npx playwright install --with-deps chromium` |

## Demo script (for the live walkthrough)

1. **Open `$APP_URL`.** Show the Numerix-branded header and the empty chat.
2. **Type the headline prompt** (above). Talk through the streaming text as the agent calls `load_data → run_baseline_mc → run_chronos2 → blend_paths → price_book → plot`. Each tool call surfaces in the transcript.
3. **Inline chart appears.** Point at the PFE overlay: parametric in grey, blended in blue. Highlight the tail-region delta.
4. **Open the dashboard.** Show the Lambda invocation widgets light up — proves the agent is exercising real infrastructure.
5. **What-if.** Set `w_stress=0.8`. Apply. Discuss how the regime detector's signal is actionable: a single knob to dial up Chronos-2's contribution under stress.
6. **Lookup adjacent use cases.** Ask the agent: "What other Numerix workflows could Chronos-2 augment?" Watch it pull the curated briefs (FRTB-IMA-ES, IM/VM forecasting, market data gap-filling).
7. **Tear down** at the end of the day.
