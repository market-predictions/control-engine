#!/usr/bin/env bash
set -euo pipefail
umask 077

PUBLIC_REPOSITORY="market-predictions/control-engine"
CONTROL_PLANE_REPOSITORY="market-predictions/control-plane"
CONTROL_RUNTIME_REF="control-runtime-state"
CONTROL_CODE_REF="recovery/187-policy-metadata-r1"
CONTROL_CODE_SHA="62cf2a88edd8700c073e51274d331210c7a36900"
MAX_CAS_ATTEMPTS=3
LEASE_MINUTES=75

status() {
  printf 'SCHEDULED_WORKER_A_V2=%s\n' "$1"
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

WORK_ROOT="${RUNNER_TEMP:-/tmp}/control-scheduled-a-v2-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
CODE_DIR="$WORK_ROOT/code"
STATE_DIR="$WORK_ROOT/state"
TARGET_TRUSTED="$WORK_ROOT/target-trusted"
TARGET_WORK="$WORK_ROOT/target-work"
PUBLISH_DIR="$WORK_ROOT/publish"
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

mkdir -p "$CODE_DIR"
git -C "$CODE_DIR" init -q
git -C "$CODE_DIR" remote add origin "https://github.com/${CONTROL_PLANE_REPOSITORY}.git"
if ! private_git -C "$CODE_DIR" fetch --quiet --depth=1 origin "refs/heads/${CONTROL_CODE_REF}" >/dev/null 2>&1; then
  fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_CODE_FETCH" 78
fi
git -C "$CODE_DIR" checkout --detach --quiet FETCH_HEAD
if [ "$(git -C "$CODE_DIR" rev-parse HEAD)" != "$CONTROL_CODE_SHA" ]; then
  fail_closed "FAIL_CLOSED_PRIVATE_CODE_SHA_MISMATCH"
fi

mkdir -p "$STATE_DIR"
git -C "$STATE_DIR" init -q
git -C "$STATE_DIR" remote add origin "https://github.com/${CONTROL_PLANE_REPOSITORY}.git"
git -C "$STATE_DIR" config user.name "control-scheduled-a-v2[bot]"
git -C "$STATE_DIR" config user.email "control-scheduled-a-v2[bot]@users.noreply.github.com"

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
      control/DISPATCH_QUEUE.json|control/DISPATCH_RUNS.json|control/project-intake/*.json) ;;
      *) return 1 ;;
    esac
  done < <({ git -C "$STATE_DIR" diff --name-only; git -C "$STATE_DIR" ls-files --others --exclude-standard; } | sort -u)
}

assert_claim_write_scope() {
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
  if ! python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" resume-a-unavailable \
      --code-dir "$CODE_DIR" \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      --output "$PRIVATE_TMP/resume-a.json" \
      >"$PRIVATE_TMP/resume-a.log" 2>&1; then
    fail_closed "FAIL_CLOSED_A_UNAVAILABLE_RECONCILIATION"
  fi
  if ! python "$CODE_DIR/tools/control_project_intake_reconcile_v1.py" \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      --intake-dir "$STATE_DIR/control/project-intake" \
      --handover-dir "$STATE_DIR/control/handovers" \
      --worker-result-dir "$STATE_DIR/control/worker-results" \
      --write \
      --report "$PRIVATE_TMP/intake-report.json" \
      >"$PRIVATE_TMP/intake.log" 2>&1; then
    fail_closed "FAIL_CLOSED_PROJECT_INTAKE_RECONCILIATION"
  fi
  if ! python "$CODE_DIR/dispatcher/cli.py" validate \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      >"$PRIVATE_TMP/validate.log" 2>&1; then
    fail_closed "FAIL_CLOSED_RECONCILED_QUEUE_INVALID"
  fi
  if ! assert_reconcile_write_scope; then
    fail_closed "FAIL_CLOSED_RECONCILE_WRITE_SCOPE"
  fi

  read -r current_ref current_blob < <(remote_runtime_identity)
  if [ "$current_ref" != "$observed_ref" ] || [ "$current_blob" != "$observed_blob" ]; then
    continue
  fi

  if persist_state_if_changed \
      "runtime: Scheduled Worker A V2 reconcile before A1 selection" \
      control/DISPATCH_QUEUE.json control/DISPATCH_RUNS.json control/project-intake; then
    reconciled=true
    break
  fi
done
if [ "$reconciled" != true ]; then
  fail_closed "RUNTIME_CAS_CONFLICT_RECONCILE" 75
fi

reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
SELECTION="$PRIVATE_TMP/selection.json"
if ! python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" select-a1 \
    --code-dir "$CODE_DIR" \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --output "$SELECTION" \
    >"$PRIVATE_TMP/select.log" 2>&1; then
  fail_closed "FAIL_CLOSED_A1_SELECTION"
fi
selected="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name selected)"
if [ "$selected" != "True" ]; then
  status "IDLE_NO_ELIGIBLE_A1_TASK"
  exit 0
fi

if [ -z "${CONTROL_CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CONTROL_CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  fail_closed "EXECUTION_UNAVAILABLE_IMPLEMENTATION_PROVIDER_CREDENTIAL" 78
fi
if [ "${CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED:-}" != "true" ]; then
  fail_closed "EXECUTION_UNAVAILABLE_FREE_FAIL_CLOSED_ATTESTATION" 78
fi

task_id="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name task_id)"
target_repository="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name repository)"
operation="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name operation)"
work_branch="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name work_branch)"
target_branch="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name target_branch)"
if [ -z "$task_id" ] || [ -z "$target_repository" ] || [ -z "$work_branch" ] || [ -z "$target_branch" ]; then
  fail_closed "FAIL_CLOSED_A1_EXECUTION_BINDING_INVALID"
fi
if [ "$operation" = "PROJECT_INTEGRATION" ]; then
  fail_closed "EXECUTION_UNAVAILABLE_PROJECT_INTEGRATION_EXECUTOR" 78
fi
if [ "$operation" != "IMPLEMENTATION" ] && [ "$operation" != "REPAIR" ]; then
  fail_closed "FAIL_CLOSED_UNSUPPORTED_A1_OPERATION"
fi

claimed=false
CLAIM_BINDING="$PRIVATE_TMP/claim-binding.json"
for cas_attempt in $(seq 1 "$MAX_CAS_ATTEMPTS"); do
  reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
  python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" select-a1 \
    --code-dir "$CODE_DIR" \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --output "$SELECTION" \
    >"$PRIVATE_TMP/select-claim.log" 2>&1 || fail_closed "FAIL_CLOSED_A1_SELECTION"
  selected_now="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name selected)"
  [ "$selected_now" = "True" ] || { status "IDLE_A1_SELECTION_MOVED"; exit 0; }
  task_now="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$SELECTION" --name task_id)"
  [ "$task_now" = "$task_id" ] || { status "IDLE_A1_SELECTION_MOVED"; exit 0; }

  read -r observed_ref observed_blob < <(runtime_identity)
  if ! python "$CODE_DIR/dispatcher/cli.py" claim \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      --runs "$STATE_DIR/control/DISPATCH_RUNS.json" \
      --task-id "$task_id" \
      --backend github-actions/public-control-engine-scheduled-a-v2 \
      --lease-minutes "$LEASE_MINUTES" \
      >"$PRIVATE_TMP/claim.log" 2>&1; then
    fail_closed "FAIL_CLOSED_A1_CLAIM"
  fi
  python "$CODE_DIR/dispatcher/cli.py" validate \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    >"$PRIVATE_TMP/claim-validate.log" 2>&1 || fail_closed "FAIL_CLOSED_CLAIMED_QUEUE_INVALID"
  assert_claim_write_scope || fail_closed "FAIL_CLOSED_CLAIM_WRITE_SCOPE"

  read -r current_ref current_blob < <(remote_runtime_identity)
  if [ "$current_ref" != "$observed_ref" ] || [ "$current_blob" != "$observed_blob" ]; then
    continue
  fi
  if persist_state_if_changed \
      "runtime: Scheduled Worker A V2 claim A1" \
      control/DISPATCH_QUEUE.json control/DISPATCH_RUNS.json; then
    reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
    python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" assert-claim \
      --code-dir "$CODE_DIR" \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      --task-id "$task_id" \
      --output "$CLAIM_BINDING" \
      >"$PRIVATE_TMP/claim-readback.log" 2>&1 || fail_closed "FAIL_CLOSED_START_PROVEN_READBACK"
    claimed=true
    break
  fi
done
if [ "$claimed" != true ]; then
  fail_closed "RUNTIME_CAS_CONFLICT_CLAIM" 75
fi
run_id="$(python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" field --file "$CLAIM_BINDING" --name run_id)"

branch_head=""
if branch_head="$(private_api "repos/${target_repository}/git/ref/heads/${work_branch}" --jq .object.sha 2>/dev/null)"; then
  :
else
  base_sha="$(private_api "repos/${target_repository}/git/ref/heads/${target_branch}" --jq .object.sha 2>/dev/null)" || fail_closed "EXECUTION_UNAVAILABLE_TARGET_REPOSITORY_ACCESS" 78
  private_api -X POST "repos/${target_repository}/git/refs" \
    -f ref="refs/heads/${work_branch}" \
    -f sha="$base_sha" >/dev/null 2>&1 || fail_closed "EXECUTION_UNAVAILABLE_TARGET_BRANCH_CREATE" 78
  branch_head="$base_sha"
fi

mkdir -p "$TARGET_TRUSTED"
git -C "$TARGET_TRUSTED" init -q
git -C "$TARGET_TRUSTED" remote add origin "https://github.com/${target_repository}.git"
private_git -C "$TARGET_TRUSTED" fetch --quiet --depth=1 origin "refs/heads/${work_branch}" >/dev/null 2>&1 || fail_closed "EXECUTION_UNAVAILABLE_TARGET_FETCH" 78
git -C "$TARGET_TRUSTED" checkout --detach --quiet FETCH_HEAD
[ "$(git -C "$TARGET_TRUSTED" rev-parse HEAD)" = "$branch_head" ] || fail_closed "FAIL_CLOSED_TARGET_HEAD_BINDING"
mkdir -p "$TARGET_WORK"
rsync -a --delete --exclude='.git/' "$TARGET_TRUSTED/" "$TARGET_WORK/"

PROMPT="$PRIVATE_TMP/control-worker-prompt.md"
SUMMARY="$PRIVATE_TMP/control-worker-summary.txt"
METADATA="$PRIVATE_TMP/control-worker-metadata.json"
python "$CODE_DIR/dispatcher/render_prompt.py" \
  --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
  --task-id "$task_id" \
  --run-id "$run_id" \
  --role "$([ "$operation" = "REPAIR" ] && printf repair || printf implementation)" \
  --output "$PROMPT" \
  >"$PRIVATE_TMP/render.log" 2>&1 || fail_closed "FAIL_CLOSED_WORKER_PROMPT_RENDER"
cp "$CODE_DIR/dispatcher/inference_worker.py" "$PRIVATE_TMP/inference_worker.py"
cp "$CODE_DIR/dispatcher/provider_policy.py" "$PRIVATE_TMP/provider_policy.py"
cp "$CODE_DIR/control/INFERENCE_PROVIDER_POLICY_V1.md" "$PRIVATE_TMP/provider-policy.md"

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
    --workspace "$TARGET_WORK" \
    --role "$([ "$operation" = "REPAIR" ] && printf repair || printf implementation)" \
    --attempt-id "$run_id" \
    --max-turns 48 \
    --request-timeout 600 \
    --output-file "$SUMMARY" \
    --metadata-file "$METADATA" \
    >"$PRIVATE_TMP/model.log" 2>&1
model_rc=$?
set -e

candidate_sha=""
publish_outcome="skipped"
if [ "$model_rc" -eq 0 ]; then
  remote_head="$(private_api "repos/${target_repository}/git/ref/heads/${work_branch}" --jq .object.sha 2>/dev/null)" || remote_head=""
  if [ "$remote_head" != "$branch_head" ]; then
    publish_outcome="conflict"
  else
    mkdir -p "$PUBLISH_DIR"
    git -C "$PUBLISH_DIR" init -q
    git -C "$PUBLISH_DIR" remote add origin "https://github.com/${target_repository}.git"
    if private_git -C "$PUBLISH_DIR" fetch --quiet --depth=1 origin "refs/heads/${work_branch}" >/dev/null 2>&1; then
      git -C "$PUBLISH_DIR" checkout --detach --quiet FETCH_HEAD
      if [ "$(git -C "$PUBLISH_DIR" rev-parse HEAD)" = "$branch_head" ]; then
        rsync -a --delete --exclude='.git/' "$TARGET_WORK/" "$PUBLISH_DIR/"
        git -C "$PUBLISH_DIR" config user.name "control-implementation[bot]"
        git -C "$PUBLISH_DIR" config user.email "control-implementation[bot]@users.noreply.github.com"
        git -C "$PUBLISH_DIR" config core.hooksPath /dev/null
        if [ -n "$(git -C "$PUBLISH_DIR" status --porcelain)" ]; then
          git -C "$PUBLISH_DIR" add -A
          git -C "$PUBLISH_DIR" -c core.hooksPath=/dev/null commit --quiet -m "control: execute Scheduled Worker A V2 task"
        fi
        candidate_sha="$(git -C "$PUBLISH_DIR" rev-parse HEAD)"
        if private_git -C "$PUBLISH_DIR" push --quiet origin "HEAD:refs/heads/${work_branch}" >/dev/null 2>&1; then
          publish_outcome="success"
        else
          candidate_sha=""
          publish_outcome="failed"
        fi
      fi
    fi
  fi
fi

if [ "$model_rc" -eq 0 ] && [ "$publish_outcome" = "success" ] && [ -n "$candidate_sha" ]; then
  outcome="COMPLETED"
  finding=""
elif [ "$model_rc" -eq 75 ]; then
  outcome="EXECUTION_UNAVAILABLE"
  finding="Configured FREE_FAIL_CLOSED implementation provider unavailable; no fallback or paid route was selected."
else
  outcome="BLOCKED"
  finding="Scheduled Worker A V2 execution or exact-head publication failed closed."
fi
if [ ! -s "$SUMMARY" ]; then
  printf '%s\n' "${finding:-Scheduled Worker A V2 completed.}" >"$SUMMARY"
fi

recorded=false
for cas_attempt in $(seq 1 "$MAX_CAS_ATTEMPTS"); do
  reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
  python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" assert-claim \
    --code-dir "$CODE_DIR" \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --task-id "$task_id" \
    >"$PRIVATE_TMP/pre-record-claim.log" 2>&1 || fail_closed "FAIL_CLOSED_STALE_A1_COMPLETION"
  read -r observed_ref observed_blob < <(runtime_identity)

  result_args=(
    --task-id "$task_id"
    --run-id "$run_id"
    --role implementation_operations
    --outcome "$outcome"
    --summary-file "$SUMMARY"
    --evidence "Public Control Engine Scheduled Worker A V2 run ${GITHUB_RUN_ID}; exact private state remained authoritative"
    --output "$PRIVATE_TMP/worker-result.json"
  )
  if [ -n "$candidate_sha" ]; then result_args+=(--candidate-sha "$candidate_sha"); fi
  if [ -n "$finding" ]; then result_args+=(--finding "$finding"); fi
  python "$CODE_DIR/dispatcher/make_result.py" "${result_args[@]}" \
    >"$PRIVATE_TMP/make-result.log" 2>&1 || fail_closed "FAIL_CLOSED_RESULT_CONSTRUCTION"
  if [ -s "$METADATA" ]; then
    python "$CODE_DIR/dispatcher/attach_runtime_metadata.py" \
      --runs "$STATE_DIR/control/DISPATCH_RUNS.json" \
      --run-id "$run_id" \
      --metadata "$METADATA" \
      >"$PRIVATE_TMP/metadata.log" 2>&1 || fail_closed "FAIL_CLOSED_RUNTIME_METADATA"
  fi
  python "$CODE_DIR/dispatcher/cli.py" record \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    --runs "$STATE_DIR/control/DISPATCH_RUNS.json" \
    --task-id "$task_id" \
    --result "$PRIVATE_TMP/worker-result.json" \
    >"$PRIVATE_TMP/record.log" 2>&1 || fail_closed "FAIL_CLOSED_RESULT_RECORD"
  python "$CODE_DIR/dispatcher/cli.py" validate \
    --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
    >"$PRIVATE_TMP/record-validate.log" 2>&1 || fail_closed "FAIL_CLOSED_RECORDED_QUEUE_INVALID"
  assert_claim_write_scope || fail_closed "FAIL_CLOSED_RECORD_WRITE_SCOPE"

  read -r current_ref current_blob < <(remote_runtime_identity)
  if [ "$current_ref" != "$observed_ref" ] || [ "$current_blob" != "$observed_blob" ]; then
    continue
  fi
  if persist_state_if_changed \
      "runtime: Scheduled Worker A V2 finalize A1" \
      control/DISPATCH_QUEUE.json control/DISPATCH_RUNS.json; then
    reset_state || fail_closed "EXECUTION_UNAVAILABLE_PRIVATE_RUNTIME_FETCH" 78
    python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" assert-finalized \
      --code-dir "$CODE_DIR" \
      --queue "$STATE_DIR/control/DISPATCH_QUEUE.json" \
      --task-id "$task_id" \
      --run-id "$run_id" \
      >"$PRIVATE_TMP/final-readback.log" 2>&1 || fail_closed "FAIL_CLOSED_FINALIZATION_READBACK"
    recorded=true
    break
  fi
done
if [ "$recorded" != true ]; then
  fail_closed "RUNTIME_CAS_CONFLICT_FINALIZE" 75
fi

if [ "$outcome" = "COMPLETED" ]; then
  status "COMPLETED_ONE_A1_TASK"
elif [ "$outcome" = "EXECUTION_UNAVAILABLE" ]; then
  status "EXECUTION_UNAVAILABLE_PROVIDER"
  exit 78
else
  status "BLOCKED_TASK_EXECUTION"
  exit 2
fi
