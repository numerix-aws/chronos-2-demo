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

> **Frontend access-code gate (2026-07-24).** The SPA never receives a real API
> key at build time. Build only the API and stream URLs, deliberately supply a
> unique non-secret `VITE_API_KEY` sentinel for the bundle-leak test, and do not
> retrieve the real key until that exact deployment artifact has passed the gate.

### 0a. Local gates and rollback capture

Pin the commit, reject tracked deployment-input changes outside that commit,
and export a fresh build tree. Untracked files and unrelated working-tree
artifacts are never copied into this tree.

```bash
set -euo pipefail
export REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"
export GIT_SHA=$(git rev-parse HEAD)
DEPLOY_INPUTS=(src tools agent infra frontend pyproject.toml)
git diff --quiet "$GIT_SHA" -- "${DEPLOY_INPUTS[@]}"
git diff --cached --quiet "$GIT_SHA" -- "${DEPLOY_INPUTS[@]}"
git cat-file -e "$GIT_SHA^{commit}"
export BUILD_ROOT=$(mktemp -d /tmp/chronos2-task11-build.XXXXXX)
git archive "$GIT_SHA" | tar -x -C "$BUILD_ROOT"
export BUILD_ARCHIVE_SHA256=$(git archive "$GIT_SHA" | shasum -a 256 | awk '{print $1}')
test -n "$BUILD_ARCHIVE_SHA256"

export AWS_PROFILE=chronos2-demo
export AWS_REGION=us-east-1
export CDK_DOCKER=finch
export IMAGE_TAG=$GIT_SHA
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
test "$ACCOUNT" = "654654592675"
export ECR=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
```

Run the complete matrix against the exported commit. A failure stops the
deployment before any image is built or pushed.

```bash
(
  cd "$BUILD_ROOT"
  PYTHONPATH="$BUILD_ROOT/src" "$REPO_ROOT/.venv/bin/pytest" -q
  PYTHONPATH="$BUILD_ROOT/src" "$REPO_ROOT/.venv/bin/pytest" tools/tests agent/tests -q
  node --test tools/lambda/sse_relay/protocol.test.mjs
)
(
  cd "$BUILD_ROOT/infra"
  npm ci
  CDK_DOCKER=finch npm test -- --runInBand
  npm run build
)
(
  cd "$BUILD_ROOT/frontend"
  npm ci
  npm test -- --run
  export BUNDLE_SECRET_SENTINEL="chronos2-bundle-$GIT_SHA-${RANDOM}${RANDOM}"
  VITE_API_KEY="$BUNDLE_SECRET_SENTINEL" npm run build
  BUNDLE_SECRET_SENTINEL="$BUNDLE_SECRET_SENTINEL" \
    npm run e2e -- --grep 'built bundle excludes'
)
```

Resolve the existing resources. Do not enable shell tracing and do not print
`API_KEY`.

```bash
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
export AMPLIFY_APP_ID=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoFrontend \
  --query "Stacks[0].Outputs[?OutputKey=='AmplifyAppIdOut'].OutputValue | [0]" \
  --output text)
export ROLLBACK_ROOT=$(mktemp -d /tmp/chronos2-task11-rollback.XXXXXX)
export ROLLBACK_TEMPLATE_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue | [0]" \
  --output text)
test -n "$ROLLBACK_TEMPLATE_BUCKET"
```

Before any image push or AWS mutation, capture each prior CloudFormation
template and parameter value. These files are the exact stack rollback inputs,
not a reconstruction from the new checkout.

```bash
for STACK in \
  Chronos2DemoTools \
  Chronos2DemoAgent \
  Chronos2DemoFrontend \
  Chronos2DemoApi
do
  aws cloudformation get-template \
    --stack-name "$STACK" --template-stage Original \
    --query TemplateBody --output json \
    > "$ROLLBACK_ROOT/$STACK.template.json"
  aws cloudformation describe-stacks --stack-name "$STACK" --output json \
    > "$ROLLBACK_ROOT/$STACK.stack.json"
  jq '[.Stacks[0].Parameters[] | {ParameterKey,ParameterValue}]' \
    "$ROLLBACK_ROOT/$STACK.stack.json" \
    > "$ROLLBACK_ROOT/$STACK.rollback-parameters.json"
  jq -e 'type == "object" and length > 0' \
    "$ROLLBACK_ROOT/$STACK.template.json" >/dev/null
done
```

Capture both launcher configurations, complete task definitions, image
references and resolved digests. A tag is not accepted as rollback evidence
without the digest it resolves to now.

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
PREVIOUS_BASELINE_LAUNCHER=$(aws lambda get-function-configuration \
  --function-name "$BASELINE_LAUNCHER" --output json)
PREVIOUS_CHRONOS_LAUNCHER=$(aws lambda get-function-configuration \
  --function-name "$CHRONOS_LAUNCHER" --output json)
PREVIOUS_BASELINE_TASK_JSON=$(aws ecs describe-task-definition \
  --task-definition "$PREVIOUS_BASELINE_TASK" --output json)
PREVIOUS_CHRONOS_TASK_JSON=$(aws ecs describe-task-definition \
  --task-definition "$PREVIOUS_CHRONOS_TASK" --output json)
printf '%s\n' "$PREVIOUS_BASELINE_LAUNCHER" \
  > "$ROLLBACK_ROOT/baseline-launcher.json"
printf '%s\n' "$PREVIOUS_CHRONOS_LAUNCHER" \
  > "$ROLLBACK_ROOT/chronos-launcher.json"
printf '%s\n' "$PREVIOUS_BASELINE_TASK_JSON" \
  > "$ROLLBACK_ROOT/baseline-task.json"
printf '%s\n' "$PREVIOUS_CHRONOS_TASK_JSON" \
  > "$ROLLBACK_ROOT/chronos-task.json"

PREVIOUS_BASELINE_IMAGE=$(jq -r \
  '.taskDefinition.containerDefinitions[0].image' \
  "$ROLLBACK_ROOT/baseline-task.json")
PREVIOUS_CHRONOS_IMAGE=$(jq -r \
  '.taskDefinition.containerDefinitions[0].image' \
  "$ROLLBACK_ROOT/chronos-task.json")

resolve_image_digest() {
  local image=$1
  local repository_and_ref=${image#"$ECR/"}
  if [[ "$repository_and_ref" == *@sha256:* ]]; then
    printf 'sha256:%s\n' "${repository_and_ref##*:}"
    return
  fi
  local repository=${repository_and_ref%:*}
  local tag=${repository_and_ref##*:}
  aws ecr describe-images \
    --repository-name "$repository" --image-ids imageTag="$tag" \
    --query 'imageDetails[0].imageDigest' --output text
}

PREVIOUS_BASELINE_DIGEST=$(resolve_image_digest "$PREVIOUS_BASELINE_IMAGE")
PREVIOUS_CHRONOS_DIGEST=$(resolve_image_digest "$PREVIOUS_CHRONOS_IMAGE")

task_definition_semantics() {
  jq -S '.taskDefinition | {
    family,
    taskRoleArn,
    executionRoleArn,
    networkMode,
    containerDefinitions,
    volumes,
    placementConstraints,
    requiresCompatibilities,
    cpu,
    memory,
    pidMode,
    ipcMode,
    proxyConfiguration,
    inferenceAccelerators,
    ephemeralStorage,
    runtimePlatform
  }' "$1"
}

task_definition_image_digests() {
  aws ecs describe-task-definition --task-definition "$1" --output json \
    | jq -r '.taskDefinition.containerDefinitions[].image' \
    | while IFS= read -r image; do
        resolve_image_digest "$image"
      done \
    | sort
}

task_definition_semantics "$ROLLBACK_ROOT/baseline-task.json" \
  > "$ROLLBACK_ROOT/baseline-task.semantics.json"
task_definition_semantics "$ROLLBACK_ROOT/chronos-task.json" \
  > "$ROLLBACK_ROOT/chronos-task.semantics.json"
task_definition_image_digests "$PREVIOUS_BASELINE_TASK" \
  > "$ROLLBACK_ROOT/baseline-task.image-digests.txt"
task_definition_image_digests "$PREVIOUS_CHRONOS_TASK" \
  > "$ROLLBACK_ROOT/chronos-task.image-digests.txt"
test -s "$ROLLBACK_ROOT/baseline-task.image-digests.txt"
test -s "$ROLLBACK_ROOT/chronos-task.image-digests.txt"
```

Capture the exact AgentCore version serving `live`, including its container,
environment, network and role provenance, plus the endpoint routing state.

```bash
AGENT_RUNTIME_ID=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoAgent \
  --query "StackResources[?ResourceType=='AWS::BedrockAgentCore::Runtime'].PhysicalResourceId | [0]" \
  --output text)
PREVIOUS_AGENT_ENDPOINT=$(aws bedrock-agentcore-control \
  get-agent-runtime-endpoint \
  --agent-runtime-id "$AGENT_RUNTIME_ID" --endpoint-name live --output json)
PREVIOUS_AGENT_LIVE_VERSION=$(printf '%s' "$PREVIOUS_AGENT_ENDPOINT" \
  | jq -r .liveVersion)
PREVIOUS_AGENT=$(aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id "$AGENT_RUNTIME_ID" \
  --agent-runtime-version "$PREVIOUS_AGENT_LIVE_VERSION" --output json)
PREVIOUS_AGENT_IMAGE=$(printf '%s' "$PREVIOUS_AGENT" \
  | jq -r '.agentRuntimeArtifact.containerConfiguration.containerUri')
PREVIOUS_AGENT_DIGEST=$(resolve_image_digest "$PREVIOUS_AGENT_IMAGE")
printf '%s\n' "$PREVIOUS_AGENT" > "$ROLLBACK_ROOT/agent-runtime.json"
printf '%s\n' "$PREVIOUS_AGENT_ENDPOINT" > "$ROLLBACK_ROOT/agent-endpoint.json"
```

Capture the last successful Amplify artifact itself. A job record without a
downloadable, valid zip is not a restorable rollback, so stop before mutation.

```bash
PREVIOUS_AMPLIFY_JOB_ID=$(aws amplify list-jobs \
  --app-id "$AMPLIFY_APP_ID" --branch-name main \
  --query "jobSummaries[?status=='SUCCEED'] | [0].jobId" --output text)
PREVIOUS_AMPLIFY_JOB=$(aws amplify get-job \
  --app-id "$AMPLIFY_APP_ID" --branch-name main \
  --job-id "$PREVIOUS_AMPLIFY_JOB_ID" --output json)
printf '%s\n' "$PREVIOUS_AMPLIFY_JOB" \
  > "$ROLLBACK_ROOT/amplify-job.json"
PREVIOUS_AMPLIFY_ARTIFACT_URL=$(printf '%s' "$PREVIOUS_AMPLIFY_JOB" \
  | jq -r '[.job.steps[]?.artifactsUrl | select(length > 0)] | last // empty')
test -n "$PREVIOUS_AMPLIFY_ARTIFACT_URL"
PREVIOUS_FRONTEND_ARTIFACT="$ROLLBACK_ROOT/frontend.zip"
curl --fail --silent --show-error \
  "$PREVIOUS_AMPLIFY_ARTIFACT_URL" -o "$PREVIOUS_FRONTEND_ARTIFACT"
unzip -tq "$PREVIOUS_FRONTEND_ARTIFACT"
PREVIOUS_FRONTEND_SHA256=$(shasum -a 256 "$PREVIOUS_FRONTEND_ARTIFACT" \
  | awk '{print $1}')

jq -n \
  --arg captured_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg baseline_task "$PREVIOUS_BASELINE_TASK" \
  --arg baseline_image "$PREVIOUS_BASELINE_IMAGE" \
  --arg baseline_digest "$PREVIOUS_BASELINE_DIGEST" \
  --arg chronos_task "$PREVIOUS_CHRONOS_TASK" \
  --arg chronos_image "$PREVIOUS_CHRONOS_IMAGE" \
  --arg chronos_digest "$PREVIOUS_CHRONOS_DIGEST" \
  --arg agent_live_version "$PREVIOUS_AGENT_LIVE_VERSION" \
  --arg agent_image "$PREVIOUS_AGENT_IMAGE" \
  --arg agent_digest "$PREVIOUS_AGENT_DIGEST" \
  --arg amplify_job_id "$PREVIOUS_AMPLIFY_JOB_ID" \
  --arg frontend_sha256 "$PREVIOUS_FRONTEND_SHA256" \
  '{captured_at:$captured_at,baseline:{task_definition:$baseline_task,image:$baseline_image,digest:$baseline_digest},chronos:{task_definition:$chronos_task,image:$chronos_image,digest:$chronos_digest},agent:{live_version:$agent_live_version,image:$agent_image,digest:$agent_digest},amplify:{job_id:$amplify_job_id,sha256:$frontend_sha256}}' \
  > "$ROLLBACK_ROOT/rollback.json"
(cd "$ROLLBACK_ROOT" && shasum -a 256 \
  *.json *.txt *.zip > rollback-files.sha256)

export ROLLBACK_BUNDLE_PREFIX="task11-rollback/$GIT_SHA/$(date -u +%Y%m%dT%H%M%SZ)"
export ROLLBACK_BUNDLE_URI="s3://$ROLLBACK_TEMPLATE_BUCKET/$ROLLBACK_BUNDLE_PREFIX"
ROLLBACK_PUBLIC_ACCESS=$(aws s3api get-public-access-block \
  --bucket "$ROLLBACK_TEMPLATE_BUCKET" --output json)
test "$(jq -r '[.PublicAccessBlockConfiguration[]] | all' \
  <<<"$ROLLBACK_PUBLIC_ACCESS")" = "true"
aws s3 cp --recursive "$ROLLBACK_ROOT" "$ROLLBACK_BUNDLE_URI"
ROLLBACK_VERIFY_ROOT=$(mktemp -d /tmp/chronos2-task11-rollback-verify.XXXXXX)
aws s3 cp --recursive "$ROLLBACK_BUNDLE_URI" "$ROLLBACK_VERIFY_ROOT"
(cd "$ROLLBACK_VERIFY_ROOT" && shasum -a 256 -c rollback-files.sha256)
```

If a stack resource query returns `None`, resolve the physical ID from the full
`describe-stack-resources` output before continuing. If any digest, runtime
version, template, parameter set, or Amplify artifact is empty, stop. The
durable rollback bundle must remain private, hash-verified, and retrievable
before the first deployment mutation.

### 0b. Build, push, and resolve immutable images

Build the two Fargate images as `linux/amd64` and AgentCore as `linux/arm64`.
Every Dockerfile and context comes from `BUILD_ROOT`, the committed export.
The git SHA tag is the deployment identity; never use `latest` as the only
record. This subsection remains prohibited by the frontend-auth block above.

```bash
false # BLOCKED: approved frontend-auth implementation is required before AWS mutation.
aws ecr get-login-password --region "$AWS_REGION" \
  | finch login --username AWS --password-stdin "$ECR"

finch build --platform linux/amd64 \
  -f "$BUILD_ROOT/tools/fargate/baseline_mc/Dockerfile" \
  -t "$ECR/${BASELINE_REPO}:${GIT_SHA}" "$BUILD_ROOT"
finch push "$ECR/${BASELINE_REPO}:${GIT_SHA}"

finch build --platform linux/amd64 \
  -f "$BUILD_ROOT/tools/fargate/run_chronos2/Dockerfile" \
  -t "$ECR/${CHRONOS2_REPO}:${GIT_SHA}" "$BUILD_ROOT"
finch push "$ECR/${CHRONOS2_REPO}:${GIT_SHA}"

finch build --platform linux/arm64 \
  -f "$BUILD_ROOT/agent/runtime/Dockerfile" \
  -t "$ECR/${AGENT_REPO}:${GIT_SHA}" "$BUILD_ROOT"
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

for DIGEST in \
  "$BASELINE_IMAGE_DIGEST" \
  "$CHRONOS_IMAGE_DIGEST" \
  "$AGENT_IMAGE_DIGEST"
do
  printf '%s\n' "$DIGEST" | grep -Eq '^sha256:[0-9a-f]{64}$'
done
```

### 0c. Pin data and deployment provenance

The S3 source objects and local calibration files must be byte-identical.
Resolve `DATA_BUCKET` and compare hashes before deployment:

```bash
export DATA_BUCKET=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoStorage \
  --query "StackResources[?ResourceType=='AWS::S3::Bucket' && contains(LogicalResourceId,'DataBucket')].PhysicalResourceId | [0]" \
  --output text)
export MARKET_SHA256=$(shasum -a 256 \
  "$BUILD_ROOT/data/curated/panel.parquet" | awk '{print $1}')
export COVARIATE_SHA256=$(shasum -a 256 \
  "$BUILD_ROOT/data/curated/covariates.parquet" | awk '{print $1}')
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
pinned provenance environment. This is an intentional hard stop until the
frontend-auth decision is implemented and reviewed:

```bash
cd "$BUILD_ROOT/infra"
npx cdk deploy Chronos2DemoTools --exclusively \
  -c imageTag="$GIT_SHA" --require-approval never
TOOLS_STATUS=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoTools \
  --query 'Stacks[0].StackStatus' --output text)
case "$TOOLS_STATUS" in
  CREATE_COMPLETE|UPDATE_COMPLETE) ;;
  *)
    aws cloudformation describe-stack-events \
      --stack-name Chronos2DemoTools \
      --query "StackEvents[?contains(ResourceStatus,'FAILED') || contains(ResourceStatus,'ROLLBACK')].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]"
    exit 1
    ;;
esac

npx cdk deploy Chronos2DemoAgent --exclusively \
  -c imageTag="$GIT_SHA" --require-approval never
AGENT_STACK_STATUS=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoAgent \
  --query 'Stacks[0].StackStatus' --output text)
case "$AGENT_STACK_STATUS" in
  CREATE_COMPLETE|UPDATE_COMPLETE) ;;
  *)
    aws cloudformation describe-stack-events \
      --stack-name Chronos2DemoAgent \
      --query "StackEvents[?contains(ResourceStatus,'FAILED') || contains(ResourceStatus,'ROLLBACK')].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]"
    exit 1
    ;;
esac
```

Require both the runtime and `live` endpoint to become `READY`. Unknown or
failure states fail immediately; transient states get at most ten minutes.

```bash
AGENT_MAX_ATTEMPTS=60
AGENT_RUNTIME_READY=0
for ((ATTEMPT=1; ATTEMPT<=AGENT_MAX_ATTEMPTS; ATTEMPT++)); do
  AGENT_RUNTIME_STATUS=$(aws bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "$AGENT_RUNTIME_ID" --query status --output text)
  case "$AGENT_RUNTIME_STATUS" in
    READY) AGENT_RUNTIME_READY=1; break ;;
    CREATING|UPDATING) sleep 10 ;;
    *) printf 'Agent runtime failed closed in status %s\n' \
         "$AGENT_RUNTIME_STATUS" >&2; exit 1 ;;
  esac
done
test "$AGENT_RUNTIME_READY" = 1 \
  || { echo "agent runtime did not become READY" >&2; exit 1; }

AGENT_ENDPOINT_READY=0
for ((ATTEMPT=1; ATTEMPT<=AGENT_MAX_ATTEMPTS; ATTEMPT++)); do
  AGENT_ENDPOINT_STATUS=$(aws bedrock-agentcore-control \
    get-agent-runtime-endpoint \
    --agent-runtime-id "$AGENT_RUNTIME_ID" --endpoint-name live \
    --query status --output text)
  case "$AGENT_ENDPOINT_STATUS" in
    READY) AGENT_ENDPOINT_READY=1; break ;;
    CREATING|UPDATING) sleep 10 ;;
    *) printf 'Agent endpoint failed closed in status %s\n' \
         "$AGENT_ENDPOINT_STATUS" >&2; exit 1 ;;
  esac
done
test "$AGENT_ENDPOINT_READY" = 1 \
  || { echo "agent endpoint did not become READY" >&2; exit 1; }
```

Preserve the export-deadlock workaround exactly: deploy Frontend exclusively,
rebuild the SPA from the exported tree, publish the manual Amplify zip,
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
export APP_URL=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoFrontend \
  --query "Stacks[0].Outputs[?OutputKey=='AmplifyDomainOut'].OutputValue | [0]" --output text)

cd "$BUILD_ROOT/frontend"
export BUNDLE_SECRET_SENTINEL="chronos2-bundle-$GIT_SHA-${RANDOM}${RANDOM}"
VITE_API_URL="$API_URL" VITE_STREAM_URL="$STREAM_URL" \
  VITE_API_KEY="$BUNDLE_SECRET_SENTINEL" npm run build
BUNDLE_SECRET_SENTINEL="$BUNDLE_SECRET_SENTINEL" \
  npm run e2e -- --grep 'built bundle excludes'
unset BUNDLE_SECRET_SENTINEL
export FRONTEND_DEPLOY_DIR=$(mktemp -d /tmp/chronos2-frontend-deploy.XXXXXX)
export FRONTEND_ARTIFACT="$FRONTEND_DEPLOY_DIR/chronos2-frontend-$GIT_SHA.zip"
(cd dist && zip -X -r "$FRONTEND_ARTIFACT" .)
export FRONTEND_SHA256=$(shasum -a 256 "$FRONTEND_ARTIFACT" | awk '{print $1}')
printf '%s\n' "$FRONTEND_SHA256" | grep -Eq '^[0-9a-f]{64}$'

jq -n \
  --arg git_sha "$GIT_SHA" \
  --arg build_archive_sha256 "$BUILD_ARCHIVE_SHA256" \
  --arg frontend_sha256 "$FRONTEND_SHA256" \
  --slurpfile provenance /tmp/chronos2-task11-provenance.json \
  '{"git_sha":$git_sha,"build_archive_sha256":$build_archive_sha256,"frontend_artifact_sha256":$frontend_sha256,"provenance":$provenance[0]}' \
  > /tmp/chronos2-task11-deployment.json

DEPLOY=$(aws amplify create-deployment \
  --app-id "$AMPLIFY_APP_ID" --branch-name main --output json)
JOB_ID=$(printf '%s' "$DEPLOY" | jq -r .jobId)
UPLOAD_URL=$(printf '%s' "$DEPLOY" | jq -r .zipUploadUrl)
curl --fail --silent --show-error -T "$FRONTEND_ARTIFACT" "$UPLOAD_URL"
aws amplify start-deployment \
  --app-id "$AMPLIFY_APP_ID" --branch-name main --job-id "$JOB_ID"

AMPLIFY_MAX_ATTEMPTS=60
AMPLIFY_SUCCEEDED=0
for ((ATTEMPT=1; ATTEMPT<=AMPLIFY_MAX_ATTEMPTS; ATTEMPT++)); do
  AMPLIFY_STATUS=$(aws amplify get-job --app-id "$AMPLIFY_APP_ID" \
    --branch-name main --job-id "$JOB_ID" \
    --query 'job.summary.status' --output text)
  case "$AMPLIFY_STATUS" in
    SUCCEED) AMPLIFY_SUCCEEDED=1; break ;;
    PENDING|RUNNING) sleep 10 ;;
    FAILED|CANCELLED) echo "Amplify deployment failed: $AMPLIFY_STATUS" >&2; exit 1 ;;
    *) echo "Amplify deployment failed closed: $AMPLIFY_STATUS" >&2; exit 1 ;;
  esac
done
test "$AMPLIFY_SUCCEEDED" = 1 \
  || { echo "Amplify deployment timed out" >&2; exit 1; }

cd "$BUILD_ROOT/infra"
npx cdk deploy Chronos2DemoApi --exclusively \
  -c imageTag="$GIT_SHA" --require-approval never
API_STACK_STATUS=$(aws cloudformation describe-stacks \
  --stack-name Chronos2DemoApi \
  --query 'Stacks[0].StackStatus' --output text)
case "$API_STACK_STATUS" in
  CREATE_COMPLETE|UPDATE_COMPLETE) ;;
  *)
    aws cloudformation describe-stack-events \
      --stack-name Chronos2DemoApi \
      --query "StackEvents[?contains(ResourceStatus,'FAILED') || contains(ResourceStatus,'ROLLBACK')].[Timestamp,LogicalResourceId,ResourceStatus,ResourceStatusReason]"
    exit 1
    ;;
esac
cd "$REPO_ROOT"
```

### 0e. API key rotation acceptance

Run this only after the API deployment above has installed the no-cache
authorizer and relay changes. Do not rotate before that deployment is complete.
The old and new values remain shell variables for these runtime checks only;
never print them, add them to a Vite environment, or write them to a file.

```bash
export API_GATEWAY_ID=$(printf '%s' "$API_URL" | sed -E 's#https://([^.]+).*#\1#')
export AUTHORIZER_ID=$(aws apigateway get-authorizers \
  --rest-api-id "$API_GATEWAY_ID" \
  --query 'items[0].id' --output text)
test -n "$AUTHORIZER_ID"
test "$AUTHORIZER_ID" != "None"
aws apigateway update-authorizer \
  --rest-api-id "$API_GATEWAY_ID" --authorizer-id "$AUTHORIZER_ID" \
  --patch-operations op=replace,path=/authorizerResultTtlInSeconds,value=0
test "$(aws apigateway get-authorizer \
  --rest-api-id "$API_GATEWAY_ID" --authorizer-id "$AUTHORIZER_ID" \
  --query authorizerResultTtlInSeconds --output text)" = "0"

export OLD_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "$API_KEY_SECRET_ARN" --query SecretString --output text)
test -n "$OLD_API_KEY"
aws secretsmanager rotate-secret --secret-id "$API_KEY_SECRET_ARN" >/dev/null

NEW_API_KEY=
for ((ATTEMPT=1; ATTEMPT<=60; ATTEMPT++)); do
  NEW_API_KEY=$(aws secretsmanager get-secret-value \
    --secret-id "$API_KEY_SECRET_ARN" --version-stage AWSCURRENT \
    --query SecretString --output text)
  if test -n "$NEW_API_KEY" && test "$NEW_API_KEY" != "$OLD_API_KEY"; then
    break
  fi
  sleep 10
done
test -n "$NEW_API_KEY"
test "$NEW_API_KEY" != "$OLD_API_KEY"

expect_rejected() {
  case "$1" in
    401|403) ;;
    *) printf 'expected old key rejection, got HTTP %s\n' "$1" >&2; exit 1 ;;
  esac
}

expect_rejected "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --request POST "$API_URL/sessions" -H "x-api-key: $OLD_API_KEY")"
export NEW_SESSION_ID=$(curl --fail --silent --show-error \
  --request POST "$API_URL/sessions" -H "x-api-key: $NEW_API_KEY" \
  | jq -r .session_id)
test -n "$NEW_SESSION_ID"

expect_rejected "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H "x-api-key: $OLD_API_KEY" \
  "$STREAM_URL?session_id=$NEW_SESSION_ID&prompt=rotation-check")"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -H "x-api-key: $NEW_API_KEY" \
  "$STREAM_URL?session_id=$NEW_SESSION_ID&prompt=rotation-check")" = "200"

export API_KEY="$NEW_API_KEY"
unset OLD_API_KEY NEW_API_KEY
```

Open tabs holding the old key automatically clear their tab session when REST
or stream access is rejected and return to the masked access-code form. Enter
the new runtime access code to reconnect.

### 0f. Streaming-edge and live stop gates

Resolve the deployed edge and assert its structure, rather than relying on
descriptive output. The managed `AllViewerExceptHostHeader` policy forwards
viewer headers including `x-api-key`.

```bash
SSE_FUNCTION=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoApi \
  --query "StackResources[?ResourceType=='AWS::Lambda::Function' && contains(LogicalResourceId,'SseFn')].PhysicalResourceId | [0]" \
  --output text)
DISTRIBUTION_ID=$(aws cloudformation describe-stack-resources \
  --stack-name Chronos2DemoApi \
  --query "StackResources[?ResourceType=='AWS::CloudFront::Distribution'].PhysicalResourceId | [0]" \
  --output text)
FUNCTION_URL_CONFIG=$(aws lambda get-function-url-config \
  --function-name "$SSE_FUNCTION" --output json)
test "$(jq -r .AuthType <<<"$FUNCTION_URL_CONFIG")" = "AWS_IAM"
test "$(jq -r .InvokeMode <<<"$FUNCTION_URL_CONFIG")" = "RESPONSE_STREAM"

LAMBDA_POLICY=$(aws lambda get-policy \
  --function-name "$SSE_FUNCTION" --output json | jq -r .Policy)
printf '%s' "$LAMBDA_POLICY" | jq -e \
  '[.Statement[] | select(.Principal.Service? == "cloudfront.amazonaws.com") | .Action] | flatten | index("lambda:InvokeFunctionUrl") != null' \
  >/dev/null
printf '%s' "$LAMBDA_POLICY" | jq -e \
  '[.Statement[] | select(.Principal.Service? == "cloudfront.amazonaws.com") | .Action] | flatten | index("lambda:InvokeFunction") != null' \
  >/dev/null
printf '%s' "$LAMBDA_POLICY" | jq -e --arg source \
  "arn:aws:cloudfront::$ACCOUNT:distribution/$DISTRIBUTION_ID" \
  '[.Statement[] | select(.Principal.Service? == "cloudfront.amazonaws.com") | (.Condition.ArnLike["AWS:SourceArn"] // .Condition.StringEquals["AWS:SourceArn"] // empty)] | index($source) != null' \
  >/dev/null

CACHE_POLICY_ID=$(aws cloudfront list-cache-policies --type managed \
  --query "CachePolicyList.Items[?CachePolicy.CachePolicyConfig.Name=='Managed-CachingDisabled'].CachePolicy.Id | [0]" \
  --output text)
ORIGIN_REQUEST_POLICY_ID=$(aws cloudfront list-origin-request-policies \
  --type managed \
  --query "OriginRequestPolicyList.Items[?OriginRequestPolicy.OriginRequestPolicyConfig.Name=='Managed-AllViewerExceptHostHeader'].OriginRequestPolicy.Id | [0]" \
  --output text)
DISTRIBUTION_CONFIG=$(aws cloudfront get-distribution-config \
  --id "$DISTRIBUTION_ID" --output json)
test "$(jq -r .DistributionConfig.DefaultCacheBehavior.CachePolicyId \
  <<<"$DISTRIBUTION_CONFIG")" = "$CACHE_POLICY_ID"
test "$(jq -r .DistributionConfig.DefaultCacheBehavior.OriginRequestPolicyId \
  <<<"$DISTRIBUTION_CONFIG")" = "$ORIGIN_REQUEST_POLICY_ID"
test "$(jq -r '.DistributionConfig.WebACLId | length > 0' \
  <<<"$DISTRIBUTION_CONFIG")" = "true"
OAC_ID=$(jq -r \
  '.DistributionConfig.Origins.Items[0].OriginAccessControlId' \
  <<<"$DISTRIBUTION_CONFIG")
test -n "$OAC_ID"
OAC=$(aws cloudfront get-origin-access-control \
  --id "$OAC_ID" --output json)
test "$(jq -r .OriginAccessControl.OriginAccessControlConfig.SigningBehavior \
  <<<"$OAC")" = "always"
test "$(jq -r .OriginAccessControl.OriginAccessControlConfig.SigningProtocol \
  <<<"$OAC")" = "sigv4"
test "$(jq -r .OriginAccessControl.OriginAccessControlConfig.OriginAccessControlOriginType \
  <<<"$OAC")" = "lambda"

RAW_FUNCTION_URL=$(jq -r .FunctionUrl <<<"$FUNCTION_URL_CONFIG")
test "$(curl --silent --connect-timeout 10 --max-time 30 \
  --output /dev/null --write-out '%{http_code}' \
  "${RAW_FUNCTION_URL}?session_id=unsigned&prompt=hello")" = "403"
```

Run one stage-safe smoke prompt and inspect every tool lifecycle event before
the three-run gate. Any stopped ECS task with a non-zero container exit code
blocks acceptance.

Run calibration from the exported commit with the deployed provenance. The
verifier independently recomputes the spec hash, requires three terminal
streams, and compares every terminal cent against this calibration. Its
900-second default preserves the 10-second connect timeout while setting the
socket read timeout from the remaining live-stream deadline; a silent read that
hits that deadline is recorded as explicit failed evidence.

```bash
export ACCEPTANCE_ROOT=$(mktemp -d /tmp/chronos2-task11-acceptance.XXXXXX)
export CALIBRATION_MAX_SECONDS=1800
(
  cd "$BUILD_ROOT"
  export PYTHONPATH="$BUILD_ROOT/src"
  "$REPO_ROOT/.venv/bin/python" - <<'PY'
import os
import subprocess
import sys

subprocess.run(
    [
        sys.executable,
        "scripts/calibrate_headline.py",
        "--profile",
        "stage_safe_headline_v1",
        "--provenance-file",
        "/tmp/chronos2-task11-provenance.json",
    ],
    check=True,
    timeout=int(os.environ["CALIBRATION_MAX_SECONDS"]),
)
PY

  "$REPO_ROOT/.venv/bin/python" \
    scripts/verify_live_reproducibility.py \
    --stream-url "$STREAM_URL" \
    --api-key "$API_KEY" \
    --runs 3 \
    --prompt "Run the stage-safe headline demo for September 30, 2022. Use five years of trading history, project one trading year into the future, and generate 500 scenarios with each engine. Apply a 53.05% stress weight. Show the market regime and compare baseline exposure with Chronos-2-augmented exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change." \
    --calibration docs/results/headline_calibration.json \
    --collection-deadline-seconds 900 \
    --output "$ACCEPTANCE_ROOT/live_reproducibility.json"
)
test "$(jq -r .status "$ACCEPTANCE_ROOT/live_reproducibility.json")" = "passed"
```

Do not copy results into `docs/results` yet. Run both equivalent wording
variants once, one ambiguous prompt with no `tool_start`, and the desktop/mobile
Playwright acceptance. Inspect all task ARNs present in the raw events with
`aws ecs describe-tasks`; any non-zero container exit blocks acceptance. Only
after every CLI and browser gate passes, copy the calibration, summary, and raw
attempt logs from `BUILD_ROOT`/`ACCEPTANCE_ROOT` into `docs/results`.

### 0g. Rollback

Rollback begins by retrieving the durable, hash-verified bundle; do not move
`latest` or rebuild an approximation. Restore the exact prior templates and
parameter values in Tools, Agent, Frontend, Api order. CloudFormation restores
the previous ECS configuration by registering replacement task-definition
revisions: never attempt to launch an inactive captured revision or require the
old ARN. Instead, require each launcher to reference an active restored revision
whose captured semantic configuration and image digests match. After Agent is
restored, explicitly route `live` back to its captured version. After Frontend
is restored, re-upload the captured Amplify artifact before restoring Api.

```bash
ROLLBACK_RESTORE_ROOT=$(mktemp -d /tmp/chronos2-task11-rollback-restore.XXXXXX)
aws s3 cp --recursive "$ROLLBACK_BUNDLE_URI" "$ROLLBACK_RESTORE_ROOT"
(cd "$ROLLBACK_RESTORE_ROOT" && shasum -a 256 -c rollback-files.sha256)
ROLLBACK_ROOT=$ROLLBACK_RESTORE_ROOT

restore_stack() {
  local stack=$1
  local template_key="$ROLLBACK_BUNDLE_PREFIX/templates/$stack.template.json"
  aws s3 cp "$ROLLBACK_ROOT/$stack.template.json" \
    "s3://$ROLLBACK_TEMPLATE_BUCKET/$template_key"
  aws cloudformation update-stack \
    --stack-name "$stack" \
    --template-url \
      "https://$ROLLBACK_TEMPLATE_BUCKET.s3.$AWS_REGION.amazonaws.com/$template_key" \
    --parameters "file://$ROLLBACK_ROOT/$stack.rollback-parameters.json" \
    --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND
  aws cloudformation wait stack-update-complete --stack-name "$stack"
  test "$(aws cloudformation describe-stacks --stack-name "$stack" \
    --query 'Stacks[0].StackStatus' --output text)" = "UPDATE_COMPLETE"
}

verify_restored_task_definition() {
  local name=$1
  local restored_task=$2
  local previous_semantics=$3
  local previous_digests=$4
  local restored_json="$ROLLBACK_ROOT/restored-$name-task.json"
  local restored_semantics="$ROLLBACK_ROOT/restored-$name-task.semantics.json"
  local restored_digests="$ROLLBACK_ROOT/restored-$name-task.image-digests.txt"

  aws ecs describe-task-definition --task-definition "$restored_task" --output json \
    > "$restored_json"
  test "$(jq -r '.taskDefinition.status' "$restored_json")" = "ACTIVE"
  task_definition_semantics "$restored_json" > "$restored_semantics"
  task_definition_image_digests "$restored_task" > "$restored_digests"
  cmp --silent "$previous_semantics" "$restored_semantics"
  cmp --silent "$previous_digests" "$restored_digests"
}

restore_stack Chronos2DemoTools
RESTORED_BASELINE_TASK=$(aws lambda get-function-configuration \
  --function-name "$BASELINE_LAUNCHER" \
  --query 'Environment.Variables.TASK_DEFINITION_ARN' --output text)
RESTORED_CHRONOS_TASK=$(aws lambda get-function-configuration \
  --function-name "$CHRONOS_LAUNCHER" \
  --query 'Environment.Variables.TASK_DEFINITION_ARN' --output text)
verify_restored_task_definition baseline "$RESTORED_BASELINE_TASK" \
  "$ROLLBACK_ROOT/baseline-task.semantics.json" \
  "$ROLLBACK_ROOT/baseline-task.image-digests.txt"
verify_restored_task_definition chronos "$RESTORED_CHRONOS_TASK" \
  "$ROLLBACK_ROOT/chronos-task.semantics.json" \
  "$ROLLBACK_ROOT/chronos-task.image-digests.txt"

restore_stack Chronos2DemoAgent
aws bedrock-agentcore-control update-agent-runtime-endpoint \
  --agent-runtime-id "$AGENT_RUNTIME_ID" --endpoint-name live \
  --agent-runtime-version "$PREVIOUS_AGENT_LIVE_VERSION"
AGENT_MAX_ATTEMPTS=60
for ((ATTEMPT=1; ATTEMPT<=AGENT_MAX_ATTEMPTS; ATTEMPT++)); do
  RESTORED_ENDPOINT=$(aws bedrock-agentcore-control \
    get-agent-runtime-endpoint \
    --agent-runtime-id "$AGENT_RUNTIME_ID" --endpoint-name live --output json)
  if test "$(jq -r .status <<<"$RESTORED_ENDPOINT")" = "READY" \
    && test "$(jq -r .liveVersion <<<"$RESTORED_ENDPOINT")" \
      = "$PREVIOUS_AGENT_LIVE_VERSION"; then
    break
  fi
  test "$ATTEMPT" -lt "$AGENT_MAX_ATTEMPTS" \
    || { echo "agent endpoint did not restore prior version" >&2; exit 1; }
  sleep 10
done
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id "$AGENT_RUNTIME_ID" \
  --agent-runtime-version "$PREVIOUS_AGENT_LIVE_VERSION" --output json \
  | jq -S '{agentRuntimeArtifact,environmentVariables,networkConfiguration,roleArn}' \
  > "$ROLLBACK_ROOT/restored-agent-runtime.json"
jq -S '{agentRuntimeArtifact,environmentVariables,networkConfiguration,roleArn}' \
  "$ROLLBACK_ROOT/agent-runtime.json" \
  > "$ROLLBACK_ROOT/previous-agent-runtime-comparable.json"
cmp --silent \
  "$ROLLBACK_ROOT/restored-agent-runtime.json" \
  "$ROLLBACK_ROOT/previous-agent-runtime-comparable.json"

restore_stack Chronos2DemoFrontend
ROLLBACK_DEPLOY=$(aws amplify create-deployment \
  --app-id "$AMPLIFY_APP_ID" --branch-name main --output json)
ROLLBACK_JOB_ID=$(printf '%s' "$ROLLBACK_DEPLOY" | jq -r .jobId)
ROLLBACK_UPLOAD_URL=$(printf '%s' "$ROLLBACK_DEPLOY" | jq -r .zipUploadUrl)
test "$(shasum -a 256 "$PREVIOUS_FRONTEND_ARTIFACT" | awk '{print $1}')" \
  = "$PREVIOUS_FRONTEND_SHA256"
curl --fail --silent --show-error \
  -T "$PREVIOUS_FRONTEND_ARTIFACT" "$ROLLBACK_UPLOAD_URL"
aws amplify start-deployment \
  --app-id "$AMPLIFY_APP_ID" --branch-name main --job-id "$ROLLBACK_JOB_ID"
AMPLIFY_MAX_ATTEMPTS=60
for ((ATTEMPT=1; ATTEMPT<=AMPLIFY_MAX_ATTEMPTS; ATTEMPT++)); do
  ROLLBACK_AMPLIFY_STATUS=$(aws amplify get-job \
    --app-id "$AMPLIFY_APP_ID" --branch-name main \
    --job-id "$ROLLBACK_JOB_ID" \
    --query 'job.summary.status' --output text)
  case "$ROLLBACK_AMPLIFY_STATUS" in
    SUCCEED) break ;;
    PENDING|RUNNING) sleep 10 ;;
    FAILED|CANCELLED) exit 1 ;;
    *) exit 1 ;;
  esac
  test "$ATTEMPT" -lt "$AMPLIFY_MAX_ATTEMPTS" \
    || { echo "Amplify rollback timed out" >&2; exit 1; }
done

restore_stack Chronos2DemoApi
```

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
npm install
export BUNDLE_SECRET_SENTINEL="chronos2-bundle-$GIT_SHA-${RANDOM}${RANDOM}"
VITE_API_URL="$API_URL" VITE_STREAM_URL="$STREAM_URL" \
  VITE_API_KEY="$BUNDLE_SECRET_SENTINEL" npm run build
BUNDLE_SECRET_SENTINEL="$BUNDLE_SECRET_SENTINEL" \
  npm run e2e -- --grep 'built bundle excludes'
unset BUNDLE_SECRET_SENTINEL
export FRONTEND_DEPLOY_DIR=$(mktemp -d /tmp/chronos2-frontend-deploy.XXXXXX)
export FRONTEND_ARTIFACT="$FRONTEND_DEPLOY_DIR/chronos2-frontend-$GIT_SHA.zip"
(cd dist && zip -X -r "$FRONTEND_ARTIFACT" .)

DEPLOY=$(aws amplify create-deployment \
  --app-id $AMPLIFY_APP_ID --branch-name main --output json)
JOB_ID=$(echo $DEPLOY | jq -r .jobId)
URL=$(echo $DEPLOY | jq -r .zipUploadUrl)
curl -T "$FRONTEND_ARTIFACT" "$URL"
aws amplify start-deployment \
  --app-id $AMPLIFY_APP_ID --branch-name main --job-id $JOB_ID
```

Wait until `aws amplify get-job --app-id $AMPLIFY_APP_ID --branch-name main --job-id $JOB_ID --query 'job.summary.status' --output text` returns `SUCCEED`.

Only after the bundle gate and deployment command above, retrieve the runtime
access key without printing it:

```bash
export API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "$API_KEY_SECRET_ARN" --query SecretString --output text)
test -n "$API_KEY"
```

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

Open `$APP_URL`, enter the runtime access code, then type the same prompt as
step 3. Watch the assistant stream tokens and inline a PFE-overlay chart. Then
exercise the **What-if** panel with `w_stress=0.8` and confirm a second chart
renders.

## 5. Run the Playwright happy-path

```bash
cd frontend
cat > tests/e2e/.env <<EOF
RUN_E2E=1
APP_URL=$APP_URL
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
| `cdk deploy Chronos2DemoApi` rolls back: "Cannot delete export …SseRelayFnFunctionUrl… in use by Chronos2DemoFrontend" | Frontend imported the Api `streamUrl` export; repointing it to the CloudFront domain can't delete the in-use export | Frontend no longer imports it (env-vars are static placeholders; real URLs are supplied during the local URL-only build). If it recurs, `cdk deploy Chronos2DemoFrontend --exclusively` first (drops the import), then `Chronos2DemoApi --exclusively` |
| Stream CORS preflight fails | Custom `x-api-key` header not reaching origin | Verify the distribution uses `ALL_VIEWER_EXCEPT_HOST_HEADER`; fallback is a CloudFront `ResponseHeadersPolicy` with explicit CORS |
| Streaming endpoint returns 401 | Wrong API key in the tab session | Clear `sessionStorage["chronos2-demo-session"]`, reload, enter a new demo access code |
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
