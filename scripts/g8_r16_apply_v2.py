from pathlib import Path
import sys

root = Path(sys.argv[1])
script = root / "scripts/canonical_b1_dual_executor_v1.py"
workflow = root / ".github/workflows/canonical-b1-dual-executor-v1.yml"
tests = root / "tests/test_canonical_b1_dual_executor_v1.py"

s = script.read_text(encoding="utf-8")
old = '''    for item in reviews:\n        if _record_login(item) not in TRUSTED_CODEX_LOGINS:\n            continue\n        event_time = _record_event_time(item)\n        if event_time < request_start:\n            continue\n        if not _positive_int(item.get("id")) or not isinstance(item.get("state"), str) or not item.get("state"):\n            raise CanonicalB1Error("trusted DEEP review malformed")\n        _validate_commit_binding(item, "DEEP review")\n\n    for item in review_comments:\n        if _record_login(item) not in TRUSTED_CODEX_LOGINS:\n            continue\n        event_time = _record_event_time(item)\n        if event_time < request_start:\n            continue\n        if (\n            not _positive_int(item.get("id"))\n            or not _positive_int(item.get("pull_request_review_id"))\n            or not isinstance(item.get("body"), str)\n        ):\n            raise CanonicalB1Error("trusted DEEP review comment malformed")\n        _validate_commit_binding(item, "DEEP review comment")\n'''
new = '''    trusted_review_ids: set[int] = set()\n    for item in reviews:\n        if _record_login(item) not in TRUSTED_CODEX_LOGINS:\n            continue\n        event_time = _record_event_time(item)\n        if event_time < request_start:\n            continue\n        if not _positive_int(item.get("id")) or not isinstance(item.get("state"), str) or not item.get("state"):\n            raise CanonicalB1Error("trusted DEEP review malformed")\n        _validate_commit_binding(item, "DEEP review")\n        trusted_review_ids.add(item["id"])\n\n    for item in review_comments:\n        if _record_login(item) not in TRUSTED_CODEX_LOGINS:\n            continue\n        event_time = _record_event_time(item)\n        if event_time < request_start:\n            continue\n        if (\n            not _positive_int(item.get("id"))\n            or not _positive_int(item.get("pull_request_review_id"))\n            or not isinstance(item.get("body"), str)\n            or not item.get("body", "").strip()\n        ):\n            raise CanonicalB1Error("trusted DEEP review comment malformed")\n        if item["pull_request_review_id"] not in trusted_review_ids:\n            raise CanonicalB1Error("trusted DEEP review comment linkage invalid")\n        _validate_commit_binding(item, "DEEP review comment")\n'''
if s.count(old) != 1:
    raise SystemExit("script validator anchor mismatch")
script.write_text(s.replace(old, new), encoding="utf-8")

w = workflow.read_text(encoding="utf-8")
for old_text, new_text in {
    "CONTROL_PRIVATE_B_CODE_REF: runtime/public-b-v2-code-r2": "CONTROL_PRIVATE_B_CODE_REF: runtime/public-b-v2-code-r3",
    "CONTROL_PRIVATE_B_CODE_SHA: 97ef7de0007b4886e336182c7a9a0ee20ae77455": "CONTROL_PRIVATE_B_CODE_SHA: 01b3fb7e5905e61a8a96c2665d2d8afd74b4dd60",
}.items():
    if w.count(old_text) != 1:
        raise SystemExit(f"workflow anchor mismatch: {old_text}")
    w = w.replace(old_text, new_text)

old_claim = '''          assert_active_profile "$state"\n          GH_TOKEN="$CONTROL_TOKEN" PYTHONPATH="$b_code" python "$b_code/tools/control_connected_worker_runtime_v1.py" claim \\\n            --runtime-root "$state" --runtime-ref "$CONTROL_RUNTIME_REF" --task-id "$task_id" \\\n            --worker-instance B1 --backend github-actions/canonical-b1-dual-executor-v1 --lease-seconds 900 > "$RUNNER_TEMP/claim.json"\n'''
new_claim = '''          assurance_class="$(jq -r --arg task "$task_id" '.tasks[] | select(.task_id==$task) | if ((.instruction // "") | contains("CONTROL_ASSURANCE_CLASS=DEEP")) then "DEEP" else "STANDARD" end' "$state/control/DISPATCH_QUEUE.json")"\n          lease_seconds=900\n          if [ "$assurance_class" = DEEP ]; then lease_seconds=5400; fi\n          designated_ci_run_id="$(python - "$state/control/DISPATCH_QUEUE.json" "$task_id" <<'PYCI'\n          import json, re, sys\n          q=json.load(open(sys.argv[1], encoding='utf-8')); task_id=sys.argv[2]\n          rows=[x for x in q['tasks'] if x.get('task_id')==task_id]\n          if len(rows)!=1: raise SystemExit('designated CI task identity mismatch')\n          t=rows[0]; texts=[t.get('instruction',''), *t.get('acceptance_criteria',[])]\n          ids=set()\n          for text in texts:\n              if isinstance(text,str): ids.update(re.findall(r'\\bCI run[ _-]*(\\d+)\\b', text, flags=re.I))\n          if len(ids)!=1: raise SystemExit('exactly one designated CI run identity is required')\n          print(next(iter(ids)))\n          PYCI\n          )"\n          [[ "$designated_ci_run_id" =~ ^[0-9]+$ ]]\n\n          assert_active_profile "$state"\n          GH_TOKEN="$CONTROL_TOKEN" PYTHONPATH="$b_code" python "$b_code/tools/control_connected_worker_runtime_v1.py" claim \\\n            --runtime-root "$state" --runtime-ref "$CONTROL_RUNTIME_REF" --task-id "$task_id" \\\n            --worker-instance B1 --backend github-actions/canonical-b1-dual-executor-v1 --lease-seconds "$lease_seconds" > "$RUNNER_TEMP/claim.json"\n'''
if w.count(old_claim) != 1:
    raise SystemExit("claim anchor mismatch")
w = w.replace(old_claim, new_claim)

out_anchor = '''          printf 'run_id=%s\\n' "$run_id" >> "$GITHUB_OUTPUT"\n'''
if w.count(out_anchor) != 1:
    raise SystemExit("claim output anchor mismatch")
w = w.replace(out_anchor, out_anchor + '''          printf 'designated_ci_run_id=%s\\n' "$designated_ci_run_id" >> "$GITHUB_OUTPUT"\n          printf 'assurance_class=%s\\n' "$assurance_class" >> "$GITHUB_OUTPUT"\n''')

dollar = "$"
env_anchor = f'''          ACTIVE_RUN_ID: {dollar}{{{{ steps.claim.outputs.run_id }}}}\n          PYTHONPATH: .\n'''
env_new = f'''          ACTIVE_RUN_ID: {dollar}{{{{ steps.claim.outputs.run_id }}}}\n          DESIGNATED_CI_RUN_ID: {dollar}{{{{ steps.claim.outputs.designated_ci_run_id }}}}\n          PYTHONPATH: .\n'''
if w.count(env_anchor) != 1:
    raise SystemExit("evidence env anchor mismatch")
w = w.replace(env_anchor, env_new)

old_ci = '''          ci_run_id="$(\n            jq -r --arg sha "$TARGET_CANDIDATE_SHA" --argjson workflow_id "$CONTROL_CI_WORKFLOW_ID" '\n              [.workflow_runs[] |\n                select(\n                  .workflow_id == $workflow_id and\n                  .head_sha == $sha and\n                  .status == "completed" and\n                  .conclusion == "success"\n                )\n              ] | sort_by(.id) | last | .id // empty\n            ' "$RUNNER_TEMP/workflow-runs.json"\n          )"\n          [[ "$ci_run_id" =~ ^[0-9]+$ ]]\n'''
new_ci = '''          ci_run_id="$DESIGNATED_CI_RUN_ID"\n          [[ "$ci_run_id" =~ ^[0-9]+$ ]]\n'''
if w.count(old_ci) != 1:
    raise SystemExit("dynamic CI selection anchor mismatch")
w = w.replace(old_ci, new_ci)
workflow.write_text(w, encoding="utf-8")

t = tests.read_text(encoding="utf-8")
old_sha = "CONTROL_PRIVATE_B_CODE_SHA: 97ef7de0007b4886e336182c7a9a0ee20ae77455"
if t.count(old_sha) != 1:
    raise SystemExit("test SHA anchor mismatch")
t = t.replace(old_sha, "CONTROL_PRIVATE_B_CODE_SHA: 01b3fb7e5905e61a8a96c2665d2d8afd74b4dd60")
addition = r'''


def _valid_deep_records(*, comment_body="P1 BLOCKER", review_id=777, linked_review_id=777):
    request_start = "2026-08-24T22:00:00Z"
    return dict(
        reviews=[{
            "id": review_id,
            "user": {"login": "chatgpt-codex-connector"},
            "state": "COMMENTED",
            "submitted_at": "2026-08-24T22:00:10Z",
            "commit_id": CANDIDATE,
        }],
        review_comments=[{
            "id": 888,
            "user": {"login": "chatgpt-codex-connector"},
            "pull_request_review_id": linked_review_id,
            "commit_id": CANDIDATE,
            "body": comment_body,
            "created_at": "2026-08-24T22:00:11Z",
        }],
        reactions=[],
        issue_comments=[{
            "id": 321,
            "user": {"login": "market-predictions"},
            "body": "request",
            "created_at": request_start,
            "updated_at": request_start,
        }],
        request_comment_id=321,
        trusted_actuator_login="market-predictions",
    )


def test_trusted_review_comment_empty_body_fails_closed():
    with pytest.raises(mod.CanonicalB1Error, match="review comment malformed"):
        mod._validate_deep_snapshot_records(**_valid_deep_records(comment_body="   "))


def test_trusted_review_comment_requires_fetched_trusted_review_linkage():
    with pytest.raises(mod.CanonicalB1Error, match="review comment linkage"):
        mod._validate_deep_snapshot_records(**_valid_deep_records(linked_review_id=999))


def test_trusted_review_comment_valid_linkage_remains_accepted():
    mod._validate_deep_snapshot_records(**_valid_deep_records())


def test_workflow_uses_bounded_deep_lease_and_exact_designated_ci_run():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CONTROL_PRIVATE_B_CODE_REF: runtime/public-b-v2-code-r3" in text
    assert "CONTROL_PRIVATE_B_CODE_SHA: 01b3fb7e5905e61a8a96c2665d2d8afd74b4dd60" in text
    assert "lease_seconds=900" in text
    assert 'if [ "$assurance_class" = DEEP ]; then lease_seconds=5400; fi' in text
    assert '--lease-seconds "$lease_seconds"' in text
    assert "steps.claim.outputs.designated_ci_run_id" in text
    assert 'ci_run_id="$DESIGNATED_CI_RUN_ID"' in text
    assert "sort_by(.id) | last" not in text
    assert "exactly one designated CI run identity is required" in text
'''
if "test_workflow_uses_bounded_deep_lease_and_exact_designated_ci_run" in t:
    raise SystemExit("R16 tests already present")
tests.write_text(t + addition, encoding="utf-8")
