# Numerix × Chronos-2 Demo — Runbook

Operational guide for deploying, demoing, and tearing down the PoC. Read once
end-to-end before running anything. Steps assume `us-east-1` and an AWS
profile named `chronos2-demo` with admin in the demo account.

> **First-deploy notes (2026-06-07).** The CDK app + agent were snapshot-tested
> but never actually deployed before, so the first real deploy surfaced (and
> fixed) a chain of latent issues. If deploying fresh, expect/verify these — all
> now fixed in code:
> - **Bootstrap qualifier** `chronos2` (was `chronos2demo`, >10 chars → bootstrap fails).
> - **CoreLayer was 608 MB** (>250 MB Lambda cap). Split into 3 tiered layers
>   (light/base/plot); ApiStack builds its **own** `ApiSharedLayer` (don't share a
>   layer's CFN export across stacks — version changes deadlock with "Cannot
>   update/delete in-use export"; deploy Api before Tools if it ever recurs).
>   pyarrow trim must keep substrait/dataset/acero libs (only `*flight*` is safe to drop).
> - **AgentCore Gateway target names** can't contain `_` (hyphenate opIds).
> - **Agent runtime image must be `linux/arm64`** (the 2 Fargate images stay `amd64`);
>   it lives in a 3rd ECR repo (in ToolsStack) and must be pushed before AgentStack.
> - **RuntimeRole** needs `bedrock-agentcore:GetWorkloadAccessToken*` + logs + xray +
>   cloudwatch, and a DependsOn so the Runtime waits for its pull policy.
> - **Agent MCP transport must SigV4-sign** (`mcp-proxy-for-aws` `aws_iam_streamablehttp_client`).
> - **InvokeFn** passes the runtime ARN + `qualifier='live'` (not the endpoint ARN).
> - **Authorizer** is TS → bundle to `handler.js` (host esbuild via `bundling.local`;
>   finch bind-mounts aren't writable under CDK's uid), reads the key from Secrets
>   Manager, and returns an **API-wide wildcard** Allow (cached authorizer reused across routes).
> - **finch** is the container engine here: export `CDK_DOCKER=finch`; build images
>   `--platform` explicitly. The full headline chain exceeds API GW's 29s sync cap —
>   it streams over SSE, now **re-enabled behind CloudFront + WAF** (the SSE Function URL is `AWS_IAM` + Origin Access Control, no longer public — see §6b streaming verification).
> - **Demo data must be seeded to S3** (`scripts/seed_demo_data.py`) — see §1b.

## Prerequisites

- Plan A merged: `pip install -e ".[dev]" && pytest` is green.
- Plan A Chronos-2 endpoint deployed via AutoGluon Cloud: `pip install -e ".[deploy]"` then `python scripts/deploy_chronos2_endpoint.py --action deploy --cache-uri s3://YOUR-BUCKET/fm-cache` (serverless default). Record the endpoint name (`chronos2-demo-ep`). It serves per-series quantiles; the client reconstructs joint paths. The Chronos-2 endpoint call runs in the `chronos2` Fargate task (AutoGluon SDK is too heavy for Lambda), so the task role holds `sagemaker:InvokeEndpoint`.
- Local toolchain: Node 20+, Python 3.11, a container engine for CDK bundling **and the three images** (here it's **finch** — `export CDK_DOCKER=finch`), AWS CLI v2.
- Bedrock model access: **Claude Sonnet 4.6** (`us.anthropic.claude-sonnet-4-6` inference profile) enabled in the target account/region. (The original `claude-3-5-sonnet-20241022-v2:0` is end-of-life.)
- Live demo data: a FRED API key in a gitignored `.env` (`FRED_API_KEY=...`) for `scripts/snapshot_data.py` (Plan A part-5 pulls live FRED keyed-JSON + ECB + Yahoo; credit uses the BAA10Y proxy). Then seed S3 — see §1b.
- CDK bootstrap: `cd infra && CDK_DOCKER=finch npx cdk bootstrap aws://ACCOUNT/us-east-1` (one-time).

## 0. Production reproducibility acceptance

This is the canonical update path for an existing live deployment. Keep one
deployment shell open so every command uses the same variables. Stop on a failed
local suite, image push, CloudFormation resource, unhealthy AgentCore endpoint,
failed ECS task, relay 4xx/5xx, or frontend smoke check.

### 0a. Local gates and rollback capture

Run every suite before creating deployment artifacts:

```bash
pytest -q
pytest tools/tests agent/tests -q
node --test tools/lambda/sse_relay/protocol.test.mjs

cd infra
npm test -- --runInBand
npm run build

cd ../frontend
npm test -- --run
npm run build
cd ..
```

Set the target and resolve the existing resources. Do not print `API_KEY`.

```bash
export AWS_PROFILE=chronos2-demo
export AWS_REGION=us-east-1
export CDK_DOCKER=finch
export GIT_SHA=$(git rev-parse HEAD)
export IMAGE_TAG=$GIT_SHA
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
test "$ACCOUNT" = "654654592675"
export ECR=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
export CHRONOS2_ENDPOINT_NAME=$(aws sagemaker list-endpoints \
  --query 'Endpoints[?starts_with(EndpointName,`chronos2`)].EndpointName | [0]' \
  --output text)

export BASELINE_REPO=$(aws ecr describe-repositories \
  --query "repositories[?contains(repositoryName,'baselinemcrepo')].repositoryName | [0]" \
  --output text)
export CHRONOS2_REPO=$(aws ecr describe-repositories \
  --query "repositories[?contains(repositoryName,'chronos2repo')].repositoryName | [0]" \
  --output text)
export AGENT_REPO=$(aws ecr describe-repositories \
  --query "repositories[?contains(repositoryName,'agentruntimerepo')].repositoryName | [0]" \
  --output text)
```

Before updating anything, record the deployed image identities, Lambda-owned
task-definition ARNs/revisions, AgentCore runtime identity, stack states, and
Amplify job. Store the JSON outside the repository:

```bash
BASELINE_LAUNCHER=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoTools \
  --query "StackResources[?starts_with(LogicalResourceId,'RunBaselineMc')].PhysicalResourceId | [0]" \
  --output text)
CHRONOS_LAUNCHER=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoTools \
  --query "StackResources[?starts_with(LogicalResourceId,'RunChronos2')].PhysicalResourceId | [0]" \
  --output text)
PREVIOUS_BASELINE_TASK=$(aws lambda get-function-configuration \
  --function-name "$BASELINE_LAUNCHER" \
  --query 'Environment.Variables.TASK_DEFINITION_ARN' --output text)
PREVIOUS_CHRONOS_TASK=$(aws lambda get-function-configuration \
  --function-name "$CHRONOS_LAUNCHER" \
  --query 'Environment.Variables.TASK_DEFINITION_ARN' --output text)
PREVIOUS_BASELINE_IMAGE=$(aws ecs describe-task-definition \
  --task-definition "$PREVIOUS_BASELINE_TASK" \
  --query 'taskDefinition.containerDefinitions[0].image' --output text)
PREVIOUS_CHRONOS_IMAGE=$(aws ecs describe-task-definition \
  --task-definition "$PREVIOUS_CHRONOS_TASK" \
  --query 'taskDefinition.containerDefinitions[0].image' --output text)
PREVIOUS_BASELINE_DIGEST=$(aws ecr describe-images \
  --repository-name "$BASELINE_REPO" --image-ids imageTag="${PREVIOUS_BASELINE_IMAGE##*:}" \
  --query 'imageDetails[0].imageDigest' --output text)
PREVIOUS_CHRONOS_DIGEST=$(aws ecr describe-images \
  --repository-name "$CHRONOS2_REPO" --image-ids imageTag="${PREVIOUS_CHRONOS_IMAGE##*:}" \
  --query 'imageDetails[0].imageDigest' --output text)
AGENT_RUNTIME_ID=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoAgent \
  --query "StackResources[?ResourceType=='AWS::BedrockAgentCore::Runtime'].PhysicalResourceId | [0]" \
  --output text)
PREVIOUS_AGENT=$(aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id "$AGENT_RUNTIME_ID" --output json)

jq -n \
  --arg captured_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg baseline_task "$PREVIOUS_BASELINE_TASK" \
  --arg baseline_image "$PREVIOUS_BASELINE_IMAGE" \
  --arg baseline_digest "$PREVIOUS_BASELINE_DIGEST" \
  --arg chronos_task "$PREVIOUS_CHRONOS_TASK" \
  --arg chronos_image "$PREVIOUS_CHRONOS_IMAGE" \
  --arg chronos_digest "$PREVIOUS_CHRONOS_DIGEST" \
  --argjson agent "$PREVIOUS_AGENT" \
  '{captured_at:$captured_at,baseline:{task_definition:$baseline_task,image:$baseline_image,digest:$baseline_digest},chronos:{task_definition:$chronos_task,image:$chronos_image,digest:$chronos_digest},agent:$agent}' \
  > /tmp/chronos2-task11-rollback.json
```

If a stack resource query returns `None`, resolve the physical ID from the full
`describe-stack-resources` output before continuing.

### 0b. Build, push, and resolve immutable images

Build the two Fargate images as `linux/amd64` and AgentCore as `linux/arm64`.
The git SHA tag is the deployment identity; never use `latest` as the only
record.

```bash
aws ecr get-login-password --region "$AWS_REGION" \
  | finch login --username AWS --password-stdin "$ECR"

finch build --platform linux/amd64 \
  -f tools/fargate/baseline_mc/Dockerfile \
  -t "$ECR/${BASELINE_REPO}:${GIT_SHA}" .
finch push "$ECR/${BASELINE_REPO}:${GIT_SHA}"

finch build --platform linux/amd64 \
  -f tools/fargate/run_chronos2/Dockerfile \
  -t "$ECR/${CHRONOS2_REPO}:${GIT_SHA}" .
finch push "$ECR/${CHRONOS2_REPO}:${GIT_SHA}"

finch build --platform linux/arm64 \
  -f agent/runtime/Dockerfile \
  -t "$ECR/${AGENT_REPO}:${GIT_SHA}" .
finch push "$ECR/${AGENT_REPO}:${GIT_SHA}"

export BASELINE_IMAGE_DIGEST=$(aws ecr describe-images \
  --repository-name "$BASELINE_REPO" --image-ids imageTag="$GIT_SHA" \
  --query 'imageDetails[0].imageDigest' --output text)
export CHRONOS_IMAGE_DIGEST=$(aws ecr describe-images \
  --repository-name "$CHRONOS2_REPO" --image-ids imageTag="$GIT_SHA" \
  --query 'imageDetails[0].imageDigest' --output text)
export AGENT_IMAGE_DIGEST=$(aws ecr describe-images \
  --repository-name "$AGENT_REPO" --image-ids imageTag="$GIT_SHA" \
  --query 'imageDetails[0].imageDigest' --output text)
```

Verify each digest matches `sha256:<64 lowercase hex characters>` before CDK.

### 0c. Pin data and deployment provenance

The S3 source objects and local calibration files must be byte-identical.
Resolve `DATA_BUCKET` and compare hashes before deployment:

```bash
export DATA_BUCKET=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoStorage \
  --query "StackResources[?ResourceType=='AWS::S3::Bucket' && contains(LogicalResourceId,'DataBucket')].PhysicalResourceId | [0]" \
  --output text)
export MARKET_SHA256=$(shasum -a 256 data/curated/panel.parquet | awk '{print $1}')
export COVARIATE_SHA256=$(shasum -a 256 data/curated/covariates.parquet | awk '{print $1}')
aws s3 cp "s3://$DATA_BUCKET/panel.parquet" /tmp/chronos2-panel.parquet
aws s3 cp "s3://$DATA_BUCKET/covariates.parquet" /tmp/chronos2-covariates.parquet
test "$(shasum -a 256 /tmp/chronos2-panel.parquet | awk '{print $1}')" = "$MARKET_SHA256"
test "$(shasum -a 256 /tmp/chronos2-covariates.parquet | awk '{print $1}')" = "$COVARIATE_SHA256"

export MARKET_SNAPSHOT_ID="panel.parquet@${GIT_SHA}"
export COVARIATE_SNAPSHOT_ID="covariates.parquet@${GIT_SHA}"
export CHRONOS_MODEL_VERSION=chronos-2
export BOOK_VERSION=cross_asset_demo_v1
export BLEND_VERSION=importance_weight_v1
export PRICING_VERSION=cross_asset_v1
export TOOL_BUNDLE_VERSION="git:${GIT_SHA}"

jq -n \
  --arg market_snapshot_id "$MARKET_SNAPSHOT_ID" \
  --arg market_sha256 "$MARKET_SHA256" \
  --arg covariate_snapshot_id "$COVARIATE_SNAPSHOT_ID" \
  --arg covariate_sha256 "$COVARIATE_SHA256" \
  --arg chronos_endpoint "$CHRONOS2_ENDPOINT_NAME" \
  --arg chronos_model_version "$CHRONOS_MODEL_VERSION" \
  --arg baseline_image_digest "$BASELINE_IMAGE_DIGEST" \
  --arg chronos_image_digest "$CHRONOS_IMAGE_DIGEST" \
  --arg agent_image_digest "$AGENT_IMAGE_DIGEST" \
  --arg book_version "$BOOK_VERSION" \
  --arg blend_version "$BLEND_VERSION" \
  --arg pricing_version "$PRICING_VERSION" \
  --arg tool_bundle_version "$TOOL_BUNDLE_VERSION" \
  '{market_snapshot_id:$market_snapshot_id,market_sha256:$market_sha256,covariate_snapshot_id:$covariate_snapshot_id,covariate_sha256:$covariate_sha256,chronos_endpoint:$chronos_endpoint,chronos_model_version:$chronos_model_version,baseline_image_digest:$baseline_image_digest,chronos_image_digest:$chronos_image_digest,agent_image_digest:$agent_image_digest,book_version:$book_version,blend_version:$blend_version,pricing_version:$pricing_version,tool_bundle_version:$tool_bundle_version,strands_version:"1.30.0"}' \
  > /tmp/chronos2-task11-provenance.json
```

### 0d. Deploy in dependency-safe order

The Tools stack owns the shared layers, tool Lambdas, and both Fargate task
definitions, so their CloudFormation update is one atomic deployment. The Agent
stack then updates the Gateway schema and AgentCore runtime together with the
pinned provenance environment.

```bash
cd infra
npx cdk deploy Chronos2DemoTools --exclusively \
  -c imageTag="$GIT_SHA" --require-approval never
test "$(aws cloudformation describe-stacks --stack-name Chronos2DemoTools \
  --query 'Stacks[0].StackStatus' --output text)" = "UPDATE_COMPLETE"

npx cdk deploy Chronos2DemoAgent --exclusively \
  -c imageTag="$GIT_SHA" --require-approval never
test "$(aws cloudformation describe-stacks --stack-name Chronos2DemoAgent \
  --query 'Stacks[0].StackStatus' --output text)" = "UPDATE_COMPLETE"
```

Require the `live` AgentCore endpoint to report a ready status before
continuing. Inspect any failed CloudFormation event and stop rather than
deploying downstream stacks:

```bash
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id "$AGENT_RUNTIME_ID"
aws bedrock-agentcore-control get-agent-runtime-endpoint \
  --agent-runtime-id "$AGENT_RUNTIME_ID" --endpoint-name live
aws cloudformation describe-stack-events --stack-name Chronos2DemoAgent \
  --query "StackEvents[?contains(ResourceStatus,'FAILED') || contains(ResourceStatus,'ROLLBACK')].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]"
```

Preserve the export-deadlock workaround exactly: deploy Frontend exclusively,
rebuild the SPA from local `.env.production`, publish the manual Amplify zip,
then deploy Api exclusively.

```bash
npx cdk deploy Chronos2DemoFrontend --exclusively \
  -c imageTag="$GIT_SHA" --require-approval never

export API_URL=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoApi \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrlOut'].OutputValue | [0]" --output text)
export STREAM_URL=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoApi \
  --query "Stacks[0].Outputs[?OutputKey=='StreamUrlOut'].OutputValue | [0]" --output text)
export API_KEY_SECRET_ARN=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoTools \
  --query "Stacks[0].Outputs[?OutputKey=='ApiKeySecretArnOut'].OutputValue | [0]" --output text)
export AMPLIFY_APP_ID=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoFrontend \
  --query "Stacks[0].Outputs[?OutputKey=='AmplifyAppIdOut'].OutputValue | [0]" --output text)
export APP_URL=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoFrontend \
  --query "Stacks[0].Outputs[?OutputKey=='AmplifyDomainOut'].OutputValue | [0]" --output text)
export API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "$API_KEY_SECRET_ARN" --query SecretString --output text)

cd ../frontend
printf 'VITE_API_URL=%s\nVITE_STREAM_URL=%s\nVITE_API_KEY=%s\n' \
  "$API_URL" "$STREAM_URL" "$API_KEY" > .env.production
npm run build
cd dist
zip -r ../app.zip .
cd ..
DEPLOY=$(aws amplify create-deployment \
  --app-id "$AMPLIFY_APP_ID" --branch-name main --output json)
JOB_ID=$(printf '%s' "$DEPLOY" | jq -r .jobId)
UPLOAD_URL=$(printf '%s' "$DEPLOY" | jq -r .zipUploadUrl)
curl --fail --silent --show-error -T app.zip "$UPLOAD_URL"
aws amplify start-deployment \
  --app-id "$AMPLIFY_APP_ID" --branch-name main --job-id "$JOB_ID"
until test "$(aws amplify get-job --app-id "$AMPLIFY_APP_ID" \
  --branch-name main --job-id "$JOB_ID" \
  --query 'job.summary.status' --output text)" = "SUCCEED"; do sleep 10; done

cd ../infra
npx cdk deploy Chronos2DemoApi --exclusively \
  -c imageTag="$GIT_SHA" --require-approval never
test "$(aws cloudformation describe-stacks --stack-name Chronos2DemoApi \
  --query 'Stacks[0].StackStatus' --output text)" = "UPDATE_COMPLETE"
cd ..
```

### 0e. Streaming-edge and live stop gates

Verify the raw Function URL remains `AWS_IAM`, the CloudFront OAC has both
Lambda permissions, WAF is associated, caching is disabled, and the viewer
`x-api-key` is forwarded. The raw URL must return 403 without SigV4; the
CloudFront relay must not return 4xx/5xx with the valid key.

Run one stage-safe smoke prompt and inspect every tool lifecycle event before
the three-run gate. Any stopped ECS task with a non-zero container exit code
blocks acceptance.

Run calibration with the same provenance, then the exact three-run verifier:

```bash
python scripts/calibrate_headline.py \
  --profile stage_safe_headline_v1 \
  --provenance-file /tmp/chronos2-task11-provenance.json

python scripts/verify_live_reproducibility.py \
  --stream-url "$STREAM_URL" \
  --api-key "$API_KEY" \
  --runs 3 \
  --prompt "Run the stage-safe headline demo for September 30, 2022. Use five years of trading history, project one trading year into the future, and generate 500 scenarios with each engine. Apply a 53.05% stress weight. Show the market regime and compare baseline exposure with Chronos-2-augmented exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change." \
  --output docs/results/live_reproducibility.json
```

Compare calibration and one live run at Decimal cent precision for baseline,
Chronos-only, and augmented EE, PFE 97.5%, and ES 97.5%. A mismatch is a defect,
not a number to bless. Run both equivalent wording variants once, one ambiguous
prompt with no `tool_start`, and the desktop/mobile Playwright acceptance.

### 0f. Rollback

Rollback uses the identities captured in
`/tmp/chronos2-task11-rollback.json`. Do not move `latest` to disguise the
deployed version. Restore the prior immutable image tags or digests in CDK,
redeploy Tools and Agent in the same order, then restore Frontend and Api using
the same exclusive-stack workaround. Confirm the launcher Lambda environment
variables again reference the prior task-definition revisions and AgentCore
reports the previous runtime image/version before reopening traffic.

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
- `Chronos2DemoApi.StreamUrlOut` → `STREAM_URL` (CloudFront domain fronting the SSE relay)
- `Chronos2DemoTools.ApiKeySecretArnOut` → `API_KEY_SECRET_ARN`
- `Chronos2DemoFrontend.AmplifyAppIdOut` → `AMPLIFY_APP_ID`
- `Chronos2DemoFrontend.AmplifyDomainOut` → `APP_URL`

### 1a. Build and push the three runtime images

The `cdk deploy` creates two **empty** ECR repos (`baseline_mc`, `chronos2`); the
Fargate tasks and AgentCore need images pushed before they can run. Use the
immutable full git SHA procedure in §0b. Do not deploy `:latest` as the only
identity. The chronos2 image bundles `autogluon-cloud`, so allow several
minutes.

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
GIT_SHA=$(git rev-parse HEAD)
aws ecr get-login-password --region $AWS_REGION | finch login --username AWS --password-stdin $ECR

# Resolve the repo names from the ToolsStack (CDK auto-names them).
BASELINE_REPO=$(aws ecr describe-repositories \
  --query "repositories[?contains(repositoryName,'baselinemcrepo')].repositoryName | [0]" --output text)
CHRONOS2_REPO=$(aws ecr describe-repositories \
  --query "repositories[?contains(repositoryName,'chronos2repo')].repositoryName | [0]" --output text)
AGENT_REPO=$(aws ecr describe-repositories \
  --query "repositories[?contains(repositoryName,'agentruntimerepo')].repositoryName | [0]" --output text)

# Fargate images are linux/amd64. (Use `finch` here; quote ${REPO}:${GIT_SHA} — zsh
# treats $VAR:l as a lowercase modifier and mangles the tag.)
finch build --platform linux/amd64 -f tools/fargate/baseline_mc/Dockerfile -t "$ECR/${BASELINE_REPO}:${GIT_SHA}" .
finch push "$ECR/${BASELINE_REPO}:${GIT_SHA}"

finch build --platform linux/amd64 -f tools/fargate/run_chronos2/Dockerfile -t "$ECR/${CHRONOS2_REPO}:${GIT_SHA}" .
finch push "$ECR/${CHRONOS2_REPO}:${GIT_SHA}"

# THIRD image: the AgentCore runtime — MUST be linux/arm64 (AgentCore rejects
# amd64), and its repo is in ToolsStack (agentruntimerepo). Push before AgentStack.
finch build --platform linux/arm64 -f agent/runtime/Dockerfile -t "$ECR/${AGENT_REPO}:${GIT_SHA}" .
finch push "$ECR/${AGENT_REPO}:${GIT_SHA}"
```

Fetch the API key from Secrets Manager:
```bash
export API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id $API_KEY_SECRET_ARN --query SecretString --output text)
```

### 1b. Seed the demo data to S3

The Lambda tools read `panel.parquet` / `regimes.parquet` from the data bucket;
nothing seeds it automatically. After `snapshot_data.py` has written
`data/curated/*` (live FRED/ECB/Yahoo pull), upload all three:
```bash
DATA_BUCKET=$(aws cloudformation describe-stack-resources --stack-name Chronos2DemoStorage \
  --query "StackResources[?ResourceType=='AWS::S3::Bucket' && contains(LogicalResourceId,'DataBucket')].PhysicalResourceId | [0]" --output text)
python scripts/seed_demo_data.py --data-bucket "$DATA_BUCKET"
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
| `bedrock-agentcore:InvokeAgentRuntime` AccessDenied | Claude Sonnet 4.6 not enabled in the account/region | Bedrock console → Model access → Request access |
| Agent `/invoke` returns 500, no runtime logs | RuntimeRole missing `GetWorkloadAccessToken*` / logs perms, or MCP calls unsigned | Confirm RuntimeRole has the AgentCore exec-role perms; agent uses `aws_iam_streamablehttp_client` (SigV4) |
| Agent runtime `Architecture incompatible … Supported: [arm64]` | Agent image built amd64 | Rebuild `--platform linux/arm64`, push, `update-agent-runtime` |
| `load_data` 500 `libarrow_substrait.so … not found` | Layer over-trimmed pyarrow | Keep substrait/dataset/acero; only strip `*flight*` |
| `cdk deploy` "Cannot update/delete export … in use" | Cross-stack layer export churn | Api uses its own `ApiSharedLayer`; deploy Api before Tools |
| Headline `/invoke` 504 at ~29s | API GW sync cap vs multi-minute Fargate | Use the streaming path (SSE via CloudFront) — `/invoke` is the non-streaming fallback only |
| Stream returns 403 via CloudFront (`{"Message":"Forbidden…Function URL authorization"}`) | OAC needs BOTH `lambda:InvokeFunctionUrl` AND `lambda:InvokeFunction` for the cloudfront principal — `withOriginAccessControl` only adds the former | `api-stack.ts` adds the `StreamCfInvokeFunction` `CfnPermission` (InvokeFunction, scoped to the distribution ARN). Confirm both statements are on the relay's resource policy and the Function URL is `AWS_IAM`; also check `chronos2StreamWebAcl` WAF metrics for blocks |
| `cdk deploy Chronos2DemoApi` rolls back: "Cannot delete export …SseRelayFnFunctionUrl… in use by Chronos2DemoFrontend" | Frontend imported the Api `streamUrl` export; repointing it to the CloudFront domain can't delete the in-use export | Frontend no longer imports it (env-vars are static placeholders; real URLs come from the local `.env.production`). If it recurs, `cdk deploy Chronos2DemoFrontend --exclusively` first (drops the import), then `Chronos2DemoApi --exclusively` |
| Stream CORS preflight fails | Custom `x-api-key` header not reaching origin | Verify the distribution uses `ALL_VIEWER_EXCEPT_HOST_HEADER`; fallback is a CloudFront `ResponseHeadersPolicy` with explicit CORS |
| Streaming endpoint returns 401 | Wrong API key in browser localStorage | Clear `localStorage["chronos2-demo-session"]`, reload, paste new key |
| Fargate task ENOSPC (baseline-MC or chronos2) | Low ephemeral storage; the chronos2 image is large (AutoGluon) | Edit the relevant `tools-stack.ts` Fargate task `ephemeralStorageGiB` and redeploy |
| chronos2 task fails immediately / `CannotPullContainerError` | ECR image not pushed after first `cdk deploy` | Run the §1a build-and-push step for the `chronos2` repo |
| chronos2 task `AccessDenied` on `sagemaker:InvokeEndpoint` | Endpoint name mismatch | Confirm `CHRONOS2_ENDPOINT` matches the deployed AutoGluon endpoint; the task role is scoped to that exact name |
| Empty transcript after `/invoke` | Gateway target not invoking tool Lambda | Check `cloudwatch logs tail /aws/lambda/<tool-fn>` and the agent's `bedrock-agentcore:InvokeAgentRuntime` trace in CloudWatch |
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
