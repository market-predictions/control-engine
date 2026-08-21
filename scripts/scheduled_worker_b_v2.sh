#!/usr/bin/env bash
set -euo pipefail
umask 077

PUBLIC_REPOSITORY="market-predictions/control-engine"
CONTROL_PLANE_REPOSITORY="market-predictions/control-plane"
CONTROL_RUNTIME_REF="control-runtime-state"
CONTROL_CODE_REF="runtime/public-b-v2-code-r1"
CONTROL_CODE_SHA="728117701e20ba3762e984ef779a74effb3bcc55"
MAX_CAS_ATTEMPTS=3
LEASE_SECONDS=900

status() {
  printf 'SCHEDULED_WORKER_B_V2=%s\n' "$1"
}

fail_closed() {
  status "$1"
  exit "${2:-2}"
}

if [ "${GITHUB_REPOSITORY:-}" != "$PUBLIC_REPOSITORY" ]; then
  fail_closed "FAIL_CLOSED_PUBLIC_REPOSITORY_IDENTITY"
fi
if [ "${GITHUB_REF:-}" != "refs/heads/main" ]; then
  fail_closed "FAIL_CLOSED_NON_MAIN_EXECUTION"
fi
if [ -z "${CONTROL_GITHUB_WRITE_TOKEN:-}" ]; then
  fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_GITHUB_CREDENTIAL" 78
fi
if [ -z "${CONTROL_CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CONTROL_CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  fail_closed "EXECUTION_UNAVAILABLE_ASSURANCE_PROVIDER_CREDENTIAL" 78
fi
if [ "${CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED:-}" != "true" ]; then
  fail_closed "EXECUTION_UNAVAILABLE_FREE_FAIL_CLOSED_ATTESTATION" 78
fi

WORK_ROOT="${RUNNER_TEMP:-/tmp}/control-scheduled-b-v2-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
CODE_DIR="$WORK_ROOT/code"
STATE_DIR="$WORK_ROOT/state"
REVIEW_DIR="$WORK_ROOT/review"
PRIVATE_TMP="$WORK_ROOT/private"
mkdir -p "$PRIVATE_TMP"
chmod 700 "$WORK_ROOT" "$PRIVATE_TMP"
trap 'rm -rf "$WORK_ROOT"' EXIT

AUTH_HEADER="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$CONTROL_GITHUB_WRITE_TOKEN" | base64 -w0)"
private_git() {
  git -c "http.https://github.com/.extraheader=$AUTH_HEADER" "$@"
}
private_api() {
  GH_TOKEN="$CONTROL_GITHUB_WRITE_TOKEN" gh api "$@"
}
connected_runtime() {
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=http.https://github.com/.extraheader \
  GIT_CONFIG_VALUE_0="$AUTH_HEADER" \
  GH_TOKEN="$CONTROL_GITHUB_WRITE_TOKEN" \
    python "$CODE_DIR/tools/control_connected_worker_runtime_v1.py" "$@"
}

fetch_code() {
  rm -rf "$CODE_DIR"
  mkdir -p "$CODE_DIR"
  git -C "$CODE_DIR" init -q
  git -C "$CODE_DIR" remote add origin "https://github.com/${CONTROL_PLANE_REPOSITORY}.git"
  if ! private_git -C "$CODE_DIR" fetch --quiet --depth=1 origin "refs/heads/${CONTROL_CODE_REF}" >/dev/null 2>&1; then
    return 1
  fi
  git -C "$CODE_DIR" checkout --detach --quiet FETCH_HEAD
  [ "$(git -C "$CODE_DIR" rev-parse HEAD)" = "$CONTROL_CODE_SHA" ]
}

fetch_state() {
  rm -rf "$STATE_DIR"
  mkdir -p "$STATE_DIR"
  git -C "$STATE_DIR" init -q
  git -C "$STATE_DIR" remote add origin "https://github.com/${CONTROL_PLANE_REPOSITORY}.git"
  git -C "$STATE_DIR" config user.name "control-scheduled-b-v2[bot]"
  git -C "$STATE_DIR" config user.email "control-scheduled-b-v2[bot]@users.noreply.github.com"
  private_git -C "$STATE_DIR" fetch --quiet origin "refs/heads/${CONTROL_RUNTIME_REF}" >/dev/null 2>&1 || return 1
  git -C "$STATE_DIR" checkout --detach --quiet FETCH_HEAD
}

reset_state() {
  private_git -C "$STATE_DIR" fetch --quiet origin "refs/heads/${CONTROL_RUNTIME_REF}" >/dev/null 2>&1 || return 1
  git -C "$STATE_DIR" reset --hard --quiet FETCH_HEAD
  git -C "$STATE_DIR" clean -fdq
}

runtime_identity() {
  local ref blob
  ref="$(git -C "$STATE_DIR" rev-parse HEAD)"
  blob="$(git -C "$STATE_DIR" rev-parse "${ref}:control/DISPATCH_QUEUE.json")"
  printf '%s %s\n' "$ref" "$blob"
}

remote_runtime_identity() {
  local ref blob
  private_git -C "$STATE_DIR" fetch --quiet origin "refs/heads/${CONTROL_RUNTIME_REF}" >/dev/null 2>&1 || return 1
  ref="$(git -C "$STATE_DIR" rev-parse FETCH_HEAD)"
  blob="$(git -C "$STATE_DIR" rev-parse "${ref}:control/DISPATCH_QUEUE.json")"
  printf '%s %s\n' "$ref" "$blob"
}

assert_reconcile_write_scope() {
  local path
  while IFS= read -r path; do
    [ -z "$path" ] && continue
    case "$path" in
      control/DISPATCH_QUEUE.json|control/DISPATCH_RUNS.json) ;;
      *) return 1 ;;
    esac
  done < <({ git -C "$STATE_DIR" diff --name-only; git -C "$STATE_DIR" ls-files --others --exclude-standard; } | sort -u)
}

persist_state_if_changed() {
  local message="$1"
  shift
  if [ -z "$(git -C "$STATE_DIR" status --porcelain -- "$@")" ]; then
    return 0
  fi
  git -C "$STATE_DIR" add -- "$@"
  git -C "$STATE_DIR" commit --quiet -m "$message"
  private_git -C "$STATE_DIR" push --quiet origin "HEAD:refs/heads/${CONTROL_RUNTIME_REF}" >/dev/null 2>&1
}

fetch_code || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_CODE_FETCH" 78
fetch_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78

reconciled=false
for cas_attempt in $(seq 1 "$MAX_CAS_ATTEMPTS"); do
  reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
  read -r observed_ref observed_blob < <(runtime_identity)

  if ! python "$CODE_DIR/dispatcher/cli.py" reconcile \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      --runs "$STATE_DIR/control/DISPATCH_RUNS.json" \
      >"$PRIVATE_TMP/reconcile.log" 2>&1; then
    fail_closed "FAIL_CLOSED_LEASE_RECONCILIATION"
  fi

  RESUMABLE_B="$PRIVATE_TMP/resumable-b.txt"
  if ! python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" list-resumable-b \
      --code-dir "$CODE_DIR" \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      --output "$RESUMABLE_B" \
      >"$PRIVATE_TMP/list-resumable-b.log" 2>&1; then
    fail_closed "FAIL_CLOSED_B_UNAVAILABLE_INSPECTION"
  fi
  while IFS= read -r resumable_task; do
    [ -z "$resumable_task" ] && continue
    if ! python "$CODE_DIR/dispatcher/cli.py" resume \
        --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
        --task-id "$resumable_task" \
        >>"$PRIVATE_TMP/resume-b.log" 2>&1; then
      fail_closed "FAIL_CLOSED_B_UNAVAILABLE_RECONCILIATION"
    fi
  done < "$RESUMABLE_B"

  if ! python "$CODE_DIR/dispatcher/cli.py" validate \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      >"$PRIVATE_TMP/validate.log" 2>&1; then
    fail_closed "FAIL_CLOSED_RECONCILED_QUEUE_INVALID"
  fi
  assert_reconcile_write_scope || fail_closed "FAIL_CLOSED_RECONCILE_WRITE_SCOPE"

  read -r current_ref current_blob < <(remote_runtime_identity)
  if [ "$current_ref" != "$observed_ref" ] || [ "$current_blob" != "$observed_blob" ]; then
    continue
  fi
  if persist_state_if_changed \
      "runtime: Scheduled Worker B V2 reconcile before B1 selection" \
      control/DISPATCH_QUEUE.json control/DISPATCH_RUNS.json; then
    reconciled=true
    break
  fi
done
if [ "$reconciled" != true ]; then
  fail_closed "RUNTIME_CAS_CONFLICT_RECONCILE" 75
fi

reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
SELECTION="$PRIVATE_TMP/selection.json"
if ! python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" select-b1 \
    --code-dir "$CODE_DIR" \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --output "$SELECTION" \
    >"$PRIVATE_TMP/select.log" 2>&1; then
  fail_closed "FAIL_CLOSED_B1_SELECTION"
fi
selected="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$SELECTION" --name selected)"
if [ "$selected" != "True" ]; then
  status "IDLE_NO_ELIGIBLE_B1_TASK"
  exit 0
fi

task_id="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$SELECTION" --name task_id)"
selected_repository="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$SELECTION" --name repository)"
selected_candidate="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$SELECTION" --name candidate_sha)"
if [ -z "$task_id" ] || [ -z "$selected_repository" ] || ! [[ "$selected_candidate" =~ ^[0-9a-f]{40}$ ]]; then
  fail_closed "FAIL_CLOSED_B1_EXECUTION_BINDING_INVALID"
fi

# Re-select immediately before claim so a stale scheduled invocation cannot bypass
# deterministic preferred-B ordering.
reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" select-b1 \
  --code-dir "$CODE_DIR" \
  --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
  --output "$SELECTION" \
  >"$PRIVATE_TMP/select-claim.log" 2>&1 || fail_closed "FAIL_CLOSED_B1_SELECTION"
selected_now="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$SELECTION" --name selected)"
[ "$selected_now" = "True" ] || { status "IDLE_B1_SELECTION_MOVED"; exit 0; }
task_now="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$SELECTION" --name task_id)"
[ "$task_now" = "$task_id" ] || { status "IDLE_B1_SELECTION_MOVED"; exit 0; }

if ! connected_runtime claim \
    --runtime-root "$STATE_DIR" \
    --runtime-ref "$CONTROL_RUNTIME_REF" \
    --task-id "$task_id" \
    --worker-instance B1 \
    --backend github-actions/public-control-engine-scheduled-b-v2 \
    --lease-seconds "$LEASE_SECONDS" \
    >"$PRIVATE_TMP/claim.log" 2>&1; then
  fail_closed "FAIL_CLOSED_B1_CLAIM"
fi

CLAIM_BINDING="$PRIVATE_TMP/claim-binding.json"
reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
if ! python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" assert-claim \
    --code-dir "$CODE_DIR" \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --task-id "$task_id" \
    --output "$CLAIM_BINDING" \
    >"$PRIVATE_TMP/claim-readback.log" 2>&1; then
  fail_closed "FAIL_CLOSED_START_PROVEN_READBACK"
fi
run_id="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$CLAIM_BINDING" --name run_id)"
target_repository="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$CLAIM_BINDING" --name repository)"
candidate_sha="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$CLAIM_BINDING" --name candidate_sha)"
candidate_pr="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" field --file "$CLAIM_BINDING" --name candidate_pr)"
if [ -z "$run_id" ] || [ "$target_repository" != "$selected_repository" ] || [ "$candidate_sha" != "$selected_candidate" ]; then
  fail_closed "FAIL_CLOSED_START_PROVEN_BINDING_MISMATCH"
fi

PROMPT="$PRIVATE_TMP/control-assurance-prompt.md"
MODEL_OUTPUT="$PRIVATE_TMP/control-assurance-model-output.json"
METADATA="$PRIVATE_TMP/control-assurance-metadata.json"
FINAL_RESULT="$PRIVATE_TMP/assurance-result.json"
python "$CODE_DIR/dispatcher/render_prompt.py" \
  --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
  --task-id "$task_id" \
  --run-id "$run_id" \
  --role assurance \
  --output "$PROMPT" \
  >"$PRIVATE_TMP/render.log" 2>&1 || fail_closed "FAIL_CLOSED_ASSURANCE_PROMPT_RENDER"
cp "$CODE_DIR/schemas/assurance_model_verdict_v1.schema.json" "$PRIVATE_TMP/assurance-model-verdict.schema.json"
cp "$CODE_DIR/dispatcher/package_assurance_result.py" "$PRIVATE_TMP/package_assurance_result.py"
cp "$CODE_DIR/dispatcher/inference_worker.py" "$PRIVATE_TMP/inference_worker.py"
cp "$CODE_DIR/dispatcher/provider_policy.py" "$PRIVATE_TMP/provider_policy.py"
cp "$CODE_DIR/dispatcher/make_result.py" "$PRIVATE_TMP/make_result.py"
cp "$CODE_DIR/control/INFERENCE_PROVIDER_POLICY_V1.md" "$PRIVATE_TMP/provider-policy.md"

rm -rf "$REVIEW_DIR"
mkdir -p "$REVIEW_DIR"
git -C "$REVIEW_DIR" init -q
git -C "$REVIEW_DIR" remote add origin "https://github.com/${target_repository}.git"
if ! private_git -C "$REVIEW_DIR" fetch --quiet --depth=1 origin "$candidate_sha" >/dev/null 2>&1; then
  fail_closed "EXECUTION_UNAVAILABLE_TARGET_FETCH" 78
fi
git -C "$REVIEW_DIR" checkout --detach --quiet FETCH_HEAD
if [ "$(git -C "$REVIEW_DIR" rev-parse HEAD)" != "$candidate_sha" ]; then
  fail_closed "FAIL_CLOSED_TARGET_HEAD_BINDING"
fi

mkdir -p "$REVIEW_DIR/.control-evidence/control-doctrine"
printf '%s\n' "$candidate_sha" > "$REVIEW_DIR/.control-evidence/frozen-candidate-sha.txt"
private_api "repos/${target_repository}/commits/${candidate_sha}" > "$REVIEW_DIR/.control-evidence/commit.json" 2>/dev/null || fail_closed "EXECUTION_UNAVAILABLE_TARGET_EVIDENCE" 78
private_api "repos/${target_repository}/commits/${candidate_sha}/status" > "$REVIEW_DIR/.control-evidence/combined-status.json" 2>/dev/null || true
private_api -H 'Accept: application/vnd.github+json' "repos/${target_repository}/commits/${candidate_sha}/check-runs" > "$REVIEW_DIR/.control-evidence/check-runs.json" 2>/dev/null || true
private_api "repos/${target_repository}/actions/runs?head_sha=${candidate_sha}&per_page=100" > "$REVIEW_DIR/.control-evidence/workflow-runs.json" 2>/dev/null || true
if [ -n "$candidate_pr" ]; then
  private_api -H 'Accept: application/vnd.github.v3.diff' "repos/${target_repository}/pulls/${candidate_pr}" > "$REVIEW_DIR/.control-evidence/pull-request.diff" 2>/dev/null || true
fi
cp "$CODE_DIR/control/CROSS_PROJECT_TWO_ROLE_GOVERNANCE_STANDARD_V1.md" "$REVIEW_DIR/.control-evidence/control-doctrine/" 2>/dev/null || true
cp "$CODE_DIR/control/ZERO_RELAY_ORCHESTRATION_STANDARD_V1.md" "$REVIEW_DIR/.control-evidence/control-doctrine/" 2>/dev/null || true
cp "$CODE_DIR/control/WORK_CONTRACT_RUNTIME_STANDARD_V1.md" "$REVIEW_DIR/.control-evidence/control-doctrine/" 2>/dev/null || true
cp "$CODE_DIR/control/INFERENCE_PROVIDER_POLICY_V1.md" "$REVIEW_DIR/.control-evidence/control-doctrine/" 2>/dev/null || true
rm -rf "$REVIEW_DIR/.git" "$CODE_DIR" "$STATE_DIR"

set +e
env -i \
  PATH="$PATH" \
  HOME="$HOME" \
  LANG="C.UTF-8" \
  PYTHONUNBUFFERED=1 \
  CLOUDFLARE_API_TOKEN="$CONTROL_CLOUDFLARE_API_TOKEN" \
  CLOUDFLARE_ACCOUNT_ID="$CONTROL_CLOUDFLARE_ACCOUNT_ID" \
  CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED="$CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED" \
  CONTROL_ATTEMPT_ID="$run_id" \
  python "$PRIVATE_TMP/inference_worker.py" \
    --provider-policy "$PRIVATE_TMP/provider-policy.md" \
    --prompt-file "$PROMPT" \
    --workspace "$REVIEW_DIR" \
    --role assurance \
    --attempt-id "$run_id" \
    --output-file "$MODEL_OUTPUT" \
    --metadata-file "$METADATA" \
    >"$PRIVATE_TMP/model.log" 2>&1
model_rc=$?
set -e

if [ "$model_rc" = "0" ] && [ -s "$MODEL_OUTPUT" ]; then
  if ! python "$PRIVATE_TMP/package_assurance_result.py" \
      --model-output "$MODEL_OUTPUT" \
      --task-id "$task_id" \
      --run-id "$run_id" \
      --candidate-sha "$candidate_sha" \
      --output "$FINAL_RESULT" \
      >"$PRIVATE_TMP/package.log" 2>&1; then
    python "$PRIVATE_TMP/make_result.py" \
      --task-id "$task_id" \
      --run-id "$run_id" \
      --role governance_release_assurance \
      --outcome INDETERMINATE \
      --candidate-sha "$candidate_sha" \
      --summary 'Assurance semantic verdict failed deterministic packaging.' \
      --finding 'Malformed, missing, extra or type-invalid semantic reviewer output was rejected.' \
      --evidence "public control-engine Actions run ${GITHUB_RUN_ID}; backend=scheduled-b-v2" \
      --output "$FINAL_RESULT" \
      >"$PRIVATE_TMP/make-result.log" 2>&1
  fi
elif [ "$model_rc" = "75" ]; then
  python "$PRIVATE_TMP/make_result.py" \
    --task-id "$task_id" \
    --run-id "$run_id" \
    --role governance_release_assurance \
    --outcome EXECUTION_UNAVAILABLE \
    --candidate-sha "$candidate_sha" \
    --summary 'Configured FREE_FAIL_CLOSED assurance provider is unavailable; no fallback or paid route was selected.' \
    --finding 'Provider-portable assurance adapter returned unavailable.' \
    --evidence "public control-engine Actions run ${GITHUB_RUN_ID}; backend=scheduled-b-v2" \
    --output "$FINAL_RESULT" \
    >"$PRIVATE_TMP/make-result.log" 2>&1
else
  python "$PRIVATE_TMP/make_result.py" \
    --task-id "$task_id" \
    --run-id "$run_id" \
    --role governance_release_assurance \
    --outcome INDETERMINATE \
    --candidate-sha "$candidate_sha" \
    --summary 'Assurance worker failed before producing a valid structured verdict.' \
    --finding 'Provider-portable assurance worker failed; PASS is forbidden.' \
    --evidence "public control-engine Actions run ${GITHUB_RUN_ID}; backend=scheduled-b-v2" \
    --output "$FINAL_RESULT" \
    >"$PRIVATE_TMP/make-result.log" 2>&1
fi

outcome="$(python - "$FINAL_RESULT" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['outcome'])
PY
)"

fetch_code || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_CODE_REFETCH" 78
fetch_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_REFETCH" 78
if ! python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" assert-claim \
    --code-dir "$CODE_DIR" \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --task-id "$task_id" \
    >"$PRIVATE_TMP/precomplete-claim.log" 2>&1; then
  fail_closed "FAIL_CLOSED_B1_CLAIM_NOT_CURRENT_BEFORE_COMPLETE"
fi

if ! connected_runtime complete \
    --runtime-root "$STATE_DIR" \
    --runtime-ref "$CONTROL_RUNTIME_REF" \
    --github-repository "$CONTROL_PLANE_REPOSITORY" \
    --task-id "$task_id" \
    --worker-instance B1 \
    --active-run-id "$run_id" \
    --result "$FINAL_RESULT" \
    >"$PRIVATE_TMP/complete.log" 2>&1; then
  fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION"
fi

reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
if ! python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_b.py" assert-finalized \
    --code-dir "$CODE_DIR" \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --task-id "$task_id" \
    --run-id "$run_id" \
    >"$PRIVATE_TMP/final-readback.log" 2>&1; then
  fail_closed "FAIL_CLOSED_B1_GHOST_FINALIZATION"
fi

case "$outcome" in
  PASS|FAIL|INDETERMINATE|EXECUTION_UNAVAILABLE)
    status "COMPLETED_ONE_B1_${outcome}"
    ;;
  *)
    fail_closed "FAIL_CLOSED_UNKNOWN_ASSURANCE_OUTCOME"
    ;;
esac
