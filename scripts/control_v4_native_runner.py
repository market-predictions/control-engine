from __future__ import annotations

"""Native GitHub Actions Control V4 runner.

This replaces the pause-capable ChatGPT Scheduled actuator. GitHub Actions owns
only wake/liveness and deterministic state/effect orchestration. Semantic work is
bounded and invoked only for an acquired WORK item.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from control_engine.v4_runtime_protocol import (
    RuntimeProtocolError,
    parse_public_command,
    task_token,
)
from scripts import control_v4_auto_replenish as auto_replenish
from scripts import control_v4_runtime_carrier as carrier


GENERATION = "9c7e1a4b2d6f8053"
RUN_ID_PREFIX = f"v4:gha:{GENERATION}:"
TARGET_BOT = "chatgpt-codex-connector[bot]"
INTERNAL_FINDING_MARKER = "CONTROL_V4_INTERNAL_REVIEW_FINDING"
MAX_PUBLIC_DIFF_CHARS = 120_000
MAX_LLM_OUTPUT_CHARS = 80_000
FAIL_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required"}
PASS_REVIEW_PHRASES = (
    "no major issues",
    "didn't find any major issues",
    "did not find any major issues",
    "no material issues",
    "no findings",
)


class NativeRunnerError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _json_output(name: str, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    _output(name, encoded)


def _native_run_id() -> str:
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if not run.isdigit() or not attempt.isdigit():
        raise NativeRunnerError("GitHub workflow run identity unavailable")
    nonce = hashlib.sha256(f"{run}:{attempt}".encode("ascii")).hexdigest()[:32]
    return f"{RUN_ID_PREFIX}{nonce}"


def _set_tick_env(run_id: str) -> dict[str, Any]:
    created = _now()
    command_body = (
        "CONTROL_V4_RUNTIME_TICK\n"
        + json.dumps({"run_id": run_id, "yielded_task_tokens": []}, separators=(",", ":"))
    )
    os.environ["CONTROL_V4_PUBLIC_COMMAND"] = command_body
    os.environ["CONTROL_V4_PUBLIC_COMMAND_ID"] = os.environ.get("GITHUB_RUN_ID", "1")
    os.environ["CONTROL_V4_PUBLIC_COMMAND_CREATED_AT"] = _ts(created)
    return parse_public_command(command_body)


def _set_event_env(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = "CONTROL_V4_RUNTIME_EVENT\n" + json.dumps(payload, separators=(",", ":"))
    os.environ["CONTROL_V4_PUBLIC_COMMAND"] = body
    return parse_public_command(body)


def _target_headers() -> dict[str, str]:
    token = os.environ.get("CONTROL_TARGET_TOKEN", "")
    if not token:
        raise NativeRunnerError("exact target capability unavailable")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "control-v4-native-runner",
    }


def _request_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    allow_404: bool = False,
) -> Any:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={**(headers or {}), **({"Content-Type": "application/json"} if data is not None else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        raise NativeRunnerError(f"GitHub target transport failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise NativeRunnerError("GitHub target transport/read failed") from exc


def _target_api(repository: str, path: str, *, method: str = "GET", payload: Mapping[str, Any] | None = None) -> Any:
    return _request_json(
        f"https://api.github.com/repos/{repository}/{path}",
        headers=_target_headers(),
        method=method,
        payload=payload,
    )


def _candidate_from_pr(pr: Mapping[str, Any]) -> dict[str, Any]:
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    values = (head.get("sha"), head.get("ref"), base.get("ref"), base.get("sha"))
    if not all(isinstance(value, str) and value for value in values):
        raise NativeRunnerError("target candidate identity incomplete")
    number = pr.get("number")
    if not isinstance(number, int):
        raise NativeRunnerError("target PR identity invalid")
    return {
        "candidate_sha": values[0],
        "candidate_pr_number": number,
        "candidate_head_branch": values[1],
        "expected_base_branch": values[2],
        "expected_base_sha": values[3],
    }


def _work() -> dict[str, Any]:
    raw = os.environ.get("CONTROL_NATIVE_WORK", "")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise NativeRunnerError("WORK envelope invalid") from exc
    if not isinstance(value, dict) or value.get("result") != "WORK":
        raise NativeRunnerError("WORK envelope invalid")
    for key in ("run_id", "task_token", "repository", "action"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise NativeRunnerError("WORK identity incomplete")
    return value


def _task_for_work(state: Mapping[str, Any], work: Mapping[str, Any]) -> Mapping[str, Any]:
    queue = state["queue"]
    lock = queue.get("execution_lock")
    if not isinstance(lock, Mapping):
        raise NativeRunnerError("WORK holder missing")
    if lock.get("run_id") != work["run_id"]:
        raise NativeRunnerError("WORK holder run drifted")
    matches = [
        task
        for task in queue["tasks"]
        if task_token(task, work["run_id"]) == work["task_token"]
    ]
    if len(matches) != 1:
        raise NativeRunnerError("WORK task token drifted")
    task = matches[0]
    if task.get("repository") != work["repository"]:
        raise NativeRunnerError("WORK repository drifted")
    return task


def _assert_effect_ready(work: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any], dict[str, Any] | None]:
    state = carrier._load_current()
    task = _task_for_work(state, work)
    lock = state["queue"].get("execution_lock")
    expiry = datetime.fromisoformat(str(lock["expires_at"]).replace("Z", "+00:00"))
    if expiry <= _now():
        raise NativeRunnerError("WORK holder expired before target effect")

    candidate = work.get("candidate")
    if candidate is None:
        return state, task, None
    if not isinstance(candidate, Mapping):
        raise NativeRunnerError("WORK candidate invalid")
    live = carrier._target_pr_candidate(work["repository"], candidate["candidate_pr_number"])
    if live != dict(candidate):
        raise NativeRunnerError("target candidate drifted before effect")
    return state, task, live


def _event_payload(work: Mapping[str, Any], event: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": work["run_id"],
        "task_token": work["task_token"],
        "event": event,
        "repository": work["repository"],
        "action": work["action"],
    }
    if isinstance(work.get("candidate"), Mapping):
        payload["candidate"] = dict(work["candidate"])
    payload.update(extra)
    return payload


def _commit_event(work: Mapping[str, Any], event: str, **extra: Any) -> dict[str, Any]:
    payload = _event_payload(work, event, **extra)
    command = _set_event_env(payload)
    state = carrier._load_current()
    _state, result = carrier._event(command, state, now=_now())
    return result


def _yield(work: Mapping[str, Any]) -> dict[str, Any]:
    return _commit_event(work, "YIELD")


def acquire() -> int:
    run_id = _native_run_id()
    command = _set_tick_env(run_id)
    try:
        state = carrier._load_current()
        carrier._assert_tick_not_superseded(command)
        carrier._assert_tick_fresh(now=_now())
        state, result = carrier._tick(command, state, now=_now())

        if result.get("result") == "NO_WORK":
            bundle = carrier._load_authority_bundle(state["main_sha"])
            if auto_replenish._auto_materialization_policy_enabled(state):
                planned = auto_replenish._plan_materialize_and_acquire_one(state, bundle, command)
                if planned is not None:
                    acquired_queue, candidate_command, work_result = planned
                    carrier._assert_tick_not_superseded(command)
                    carrier._assert_tick_fresh(now=_now())
                    state = carrier._write_queue_exact(
                        state,
                        acquired_queue,
                        reason="native-auto-replenish-acquire",
                        pre_ref_cas=lambda: auto_replenish._revalidate_candidate_command(
                            state, bundle, candidate_command
                        ),
                    )
                    result = work_result
                else:
                    result = auto_replenish._proposal_fallback(result, state, bundle)

        carrier.compact_public_result(result)
    except carrier.StaleWriteError:
        result = {"protocol": carrier.RESULT_PROTOCOL_ID, "result": "RETRY", "code": "STALE_PRIVATE_STATE", "run_id": run_id}
    except carrier.StaleEventError:
        result = {"protocol": carrier.RESULT_PROTOCOL_ID, "result": "REJECTED", "code": "STALE_EVENT", "run_id": run_id}
    except (RuntimeProtocolError, carrier.V4ValidationError, carrier.CarrierError, auto_replenish.AutoReplenishError):
        result = {"protocol": carrier.RESULT_PROTOCOL_ID, "result": "ERROR", "code": "FAIL_CLOSED", "run_id": run_id}

    _json_output("result_json", result)
    _output("result", str(result.get("result", "ERROR")))
    _output("run_id", run_id)
    if result.get("result") == "WORK":
        repository = result["repository"]
        _output("repository", repository)
        _output("repository_name", repository.split("/", 1)[1])
        _output("action", result["action"])
        _output("semantic", "true" if result["action"] in {"REVIEW_INTERNAL", "REPAIR"} else "false")
    print(json.dumps(result, sort_keys=True))
    return 0


def _post_pr_comment(work: Mapping[str, Any], body: str) -> str:
    candidate = work.get("candidate")
    if not isinstance(candidate, Mapping):
        raise NativeRunnerError("target PR comment requires candidate")
    response = _target_api(
        work["repository"],
        f"issues/{candidate['candidate_pr_number']}/comments",
        method="POST",
        payload={"body": body},
    )
    url = response.get("html_url") if isinstance(response, Mapping) else None
    if not isinstance(url, str) or not url.startswith(f"https://github.com/{work['repository']}/pull/{candidate['candidate_pr_number']}#"):
        raise NativeRunnerError("target PR comment readback invalid")
    return url


def _pr_and_diff(work: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    candidate = work.get("candidate")
    if not isinstance(candidate, Mapping):
        raise NativeRunnerError("semantic work requires candidate")
    pr = _target_api(work["repository"], f"pulls/{candidate['candidate_pr_number']}")
    if not isinstance(pr, Mapping):
        raise NativeRunnerError("target PR unavailable")
    if _candidate_from_pr(pr) != dict(candidate):
        raise NativeRunnerError("target candidate drifted")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{work['repository']}/pulls/{candidate['candidate_pr_number']}",
        headers={**_target_headers(), "Accept": "application/vnd.github.v3.diff"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            diff = response.read(MAX_PUBLIC_DIFF_CHARS + 1).decode("utf-8", "strict")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise NativeRunnerError("target diff unavailable") from exc
    if len(diff) > MAX_PUBLIC_DIFF_CHARS:
        raise NativeRunnerError("target diff exceeds bounded semantic context")
    return dict(pr), diff


def _checks_gate(work: Mapping[str, Any]) -> str:
    candidate = work.get("candidate")
    if not isinstance(candidate, Mapping):
        return "READY"
    data = _target_api(
        work["repository"],
        f"commits/{candidate['candidate_sha']}/check-runs?per_page=100",
    )
    runs = data.get("check_runs") if isinstance(data, Mapping) else None
    if not isinstance(runs, list):
        return "READY"
    for item in runs:
        if not isinstance(item, Mapping):
            continue
        if item.get("status") != "completed":
            return "PENDING"
        if item.get("conclusion") in FAIL_CONCLUSIONS:
            return "FAILED"
    return "READY"


def _strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3:
            value = "\n".join(lines[1:-1]).strip()
            if value.startswith("json\n"):
                value = value[5:].strip()
    return value


def _llm_json(system: str, user: str) -> dict[str, Any]:
    base = os.environ.get("FREELLMAPI_BASE_URL", "").rstrip("/")
    key = os.environ.get("FREELLMAPI_API_KEY", "")
    if not base.startswith("http://127.0.0.1:") or not key.startswith("freellmapi-"):
        raise NativeRunnerError("bounded FreeLLMAPI worker unavailable")
    payload = {
        "model": "auto",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 5000,
        "temperature": 0,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "control-v4-bounded-free-worker",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise NativeRunnerError("bounded FreeLLMAPI inference failed") from exc
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise NativeRunnerError("bounded FreeLLMAPI response invalid") from exc
    if not isinstance(text, str) or len(text) > MAX_LLM_OUTPUT_CHARS:
        raise NativeRunnerError("bounded FreeLLMAPI output invalid")
    try:
        value = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise NativeRunnerError("bounded FreeLLMAPI output is not strict JSON") from exc
    if not isinstance(value, dict):
        raise NativeRunnerError("bounded FreeLLMAPI JSON root invalid")
    return value


def _internal_review(work: Mapping[str, Any]) -> dict[str, Any]:
    gate = _checks_gate(work)
    if gate == "PENDING":
        return _yield(work)
    if gate == "FAILED":
        finding_url = _post_pr_comment(
            work,
            f"{INTERNAL_FINDING_MARKER}\n\nExact-head CI/check evidence is failing for `{work['candidate']['candidate_sha']}`. "
            "Repair only the concrete failed checks before requesting another review.",
        )
        print(f"internal check finding: {finding_url}")
        return _commit_event(work, "INTERNAL_REPAIR")

    pr, diff = _pr_and_diff(work)
    system = (
        "You are a bounded independent code reviewer. Use only the supplied public PR facts and diff. "
        "A blocker is admissible only if it is a concrete regression or creates a concrete security, privacy, "
        "data-integrity, reliability, production-correctness, or explicit claimed-scope failure. "
        "Style, speculative hardening and future extensibility are non-blocking. "
        "Return ONLY JSON: {\"decision\":\"PASS\"|\"REPAIR\",\"finding\":\"...\"}. "
        "For PASS, finding must be empty. For REPAIR, name one material root-cause finding."
    )
    user = (
        f"PR title: {pr.get('title','')}\nPR body:\n{pr.get('body') or ''}\n\n"
        f"Exact candidate: {work['candidate']['candidate_sha']}\n"
        f"Exact base: {work['candidate']['expected_base_sha']}\n\nDIFF:\n{diff}"
    )
    result = _llm_json(system, user)
    decision = result.get("decision")
    finding = result.get("finding")
    if decision == "PASS" and finding == "":
        return _commit_event(work, "INTERNAL_PASS")
    if decision == "REPAIR" and isinstance(finding, str) and finding.strip():
        url = _post_pr_comment(
            work,
            f"{INTERNAL_FINDING_MARKER}\n\nExact-head bounded internal review found one admitted material issue:\n\n{finding.strip()}",
        )
        print(f"internal review finding: {url}")
        return _commit_event(work, "INTERNAL_REPAIR")
    raise NativeRunnerError("bounded internal review decision invalid")


def _request_external_review(work: Mapping[str, Any]) -> dict[str, Any]:
    _state, _task, _live = _assert_effect_ready(work)
    candidate = work["candidate"]
    body = (
        "@codex review\n\n"
        f"Fresh independent exact-candidate review for head `{candidate['candidate_sha']}` "
        f"against base `{candidate['expected_base_sha']}`.\n\n"
        "Admit a blocker only for an explicit current claimed-scope failure, a concrete regression, "
        "or a concrete security/privacy/data-integrity/reliability/production-correctness failure. "
        "Pre-existing debt, style, speculative hardening and future extensibility are non-blocking. "
        "Prefer the smallest complete root-cause fix. Explicitly PASS if no admitted blocker remains."
    )
    ref = _post_pr_comment(work, body)
    return _commit_event(work, "EXTERNAL_REQUESTED", request_ref=ref)


def _parse_comment_id(url: str) -> int | None:
    match = re.search(r"#issuecomment-(\d+)$", url)
    return int(match.group(1)) if match else None


def _reconcile_external_review(work: Mapping[str, Any]) -> dict[str, Any]:
    candidate = work["candidate"]
    comments = _target_api(work["repository"], f"issues/{candidate['candidate_pr_number']}/comments?per_page=100")
    review_comments = _target_api(work["repository"], f"pulls/{candidate['candidate_pr_number']}/comments?per_page=100")
    reviews = _target_api(work["repository"], f"pulls/{candidate['candidate_pr_number']}/reviews?per_page=100")
    if not all(isinstance(value, list) for value in (comments, review_comments, reviews)):
        raise NativeRunnerError("external review evidence listing invalid")
    if any(len(value) >= 100 for value in (comments, review_comments, reviews)):
        raise NativeRunnerError("external review evidence exceeds bounded read")

    owner_requests = [
        item for item in comments
        if isinstance(item, Mapping)
        and (item.get("user") or {}).get("login") == "market-predictions"
        and isinstance(item.get("body"), str)
        and "@codex review" in item["body"]
        and candidate["candidate_sha"] in item["body"]
        and candidate["expected_base_sha"] in item["body"]
    ]
    if not owner_requests:
        return _yield(work)
    request = max(owner_requests, key=lambda item: str(item.get("created_at") or ""))
    requested_at = str(request.get("created_at") or "")

    exact_findings = [
        item for item in review_comments
        if isinstance(item, Mapping)
        and (item.get("user") or {}).get("login") == TARGET_BOT
        and item.get("commit_id") == candidate["candidate_sha"]
        and str(item.get("created_at") or "") >= requested_at
        and isinstance(item.get("html_url"), str)
    ]
    if exact_findings:
        finding = min(exact_findings, key=lambda item: str(item.get("created_at") or ""))
        return _commit_event(work, "EXTERNAL_FINDING", evidence_ref=finding["html_url"])

    evidence: list[Mapping[str, Any]] = []
    evidence.extend(
        item for item in reviews
        if isinstance(item, Mapping)
        and (item.get("user") or {}).get("login") == TARGET_BOT
        and item.get("commit_id") == candidate["candidate_sha"]
        and str(item.get("submitted_at") or "") >= requested_at
        and isinstance(item.get("html_url"), str)
    )
    evidence.extend(
        item for item in comments
        if isinstance(item, Mapping)
        and (item.get("user") or {}).get("login") == TARGET_BOT
        and str(item.get("created_at") or "") >= requested_at
        and isinstance(item.get("html_url"), str)
    )
    for item in sorted(evidence, key=lambda value: str(value.get("submitted_at") or value.get("created_at") or "")):
        body = str(item.get("body") or "").lower()
        if any(phrase in body for phrase in PASS_REVIEW_PHRASES):
            return _commit_event(work, "EXTERNAL_PASS", evidence_ref=item["html_url"])
    return _yield(work)


def _latest_repair_finding(work: Mapping[str, Any], task: Mapping[str, Any]) -> str:
    external = task.get("external_review")
    if isinstance(external, Mapping) and external.get("status") == "FAIL":
        ref = external.get("evidence_ref")
        if isinstance(ref, str):
            discussion = re.search(r"#discussion_r(\d+)$", ref)
            issue = re.search(r"#issuecomment-(\d+)$", ref)
            if discussion:
                item = _request_json(
                    f"https://api.github.com/repos/{work['repository']}/pulls/comments/{discussion.group(1)}",
                    headers=_target_headers(),
                )
                if isinstance(item, Mapping) and isinstance(item.get("body"), str):
                    return item["body"]
            if issue:
                item = _request_json(
                    f"https://api.github.com/repos/{work['repository']}/issues/comments/{issue.group(1)}",
                    headers=_target_headers(),
                )
                if isinstance(item, Mapping) and isinstance(item.get("body"), str):
                    return item["body"]

    candidate = work.get("candidate")
    if isinstance(candidate, Mapping):
        comments = _target_api(work["repository"], f"issues/{candidate['candidate_pr_number']}/comments?per_page=100")
        if isinstance(comments, list):
            matching = [
                item for item in comments
                if isinstance(item, Mapping)
                and isinstance(item.get("body"), str)
                and item["body"].startswith(INTERNAL_FINDING_MARKER)
            ]
            if matching:
                latest = max(matching, key=lambda item: str(item.get("created_at") or ""))
                return latest["body"]
    raise NativeRunnerError("REPAIR has no public material finding evidence")


def _clone_exact_candidate(work: Mapping[str, Any], root: Path) -> Path:
    candidate = work["candidate"]
    repo_dir = root / "target"
    auth = f"AUTHORIZATION: bearer {os.environ['CONTROL_TARGET_TOKEN']}"
    subprocess.run(
        ["git", "-c", f"http.extraHeader={auth}", "clone", "--filter=blob:none", "--no-checkout",
         f"https://github.com/{work['repository']}.git", str(repo_dir)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "-c", f"http.extraHeader={auth}", "fetch", "origin",
         candidate["candidate_head_branch"]],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "checkout", "--detach", candidate["candidate_sha"]],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    head = subprocess.check_output(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()
    if head != candidate["candidate_sha"]:
        raise NativeRunnerError("candidate checkout identity mismatch")
    return repo_dir


def _repair(work: Mapping[str, Any]) -> dict[str, Any]:
    live_candidate = work.get("live_candidate")
    candidate = work.get("candidate")
    if isinstance(candidate, Mapping) and isinstance(live_candidate, Mapping) and dict(live_candidate) != dict(candidate):
        # Existing Runner semantics: a safe same-PR/branch/base live drift is not
        # rewritten. Bind current public truth and return to REVIEW.
        if (
            live_candidate.get("candidate_pr_number") == candidate.get("candidate_pr_number")
            and live_candidate.get("candidate_head_branch") == candidate.get("candidate_head_branch")
            and live_candidate.get("expected_base_branch") == candidate.get("expected_base_branch")
        ):
            return _commit_event(
                work,
                "CANDIDATE_READY",
                new_candidate_sha=live_candidate["candidate_sha"],
                candidate_pr_number=live_candidate["candidate_pr_number"],
                candidate_head_branch=live_candidate["candidate_head_branch"],
                new_expected_base_branch=live_candidate["expected_base_branch"],
                new_expected_base_sha=live_candidate["expected_base_sha"],
            )
        return _yield(work)

    state, task, _live = _assert_effect_ready(work)
    finding = _latest_repair_finding(work, task)
    pr, diff = _pr_and_diff(work)
    system = (
        "You are a bounded repair worker for a public GitHub candidate. Use only the supplied exact diff and "
        "one admitted review finding. Produce the smallest complete root-cause repair. Do not broaden scope. "
        "Return ONLY JSON: {\"decision\":\"PATCH\"|\"NO_PATCH\",\"patch\":\"...\",\"summary\":\"...\"}. "
        "PATCH must be a standard unified git diff that applies to the exact candidate. NO_PATCH must use an empty patch."
    )
    user = (
        f"PR title: {pr.get('title','')}\nExact candidate: {candidate['candidate_sha']}\n"
        f"Exact base: {candidate['expected_base_sha']}\n\nADMITTED FINDING:\n{finding}\n\nCURRENT DIFF:\n{diff}"
    )
    result = _llm_json(system, user)
    if result.get("decision") != "PATCH" or not isinstance(result.get("patch"), str) or not result["patch"].strip():
        return _yield(work)
    patch = result["patch"].strip()
    if len(patch) > MAX_LLM_OUTPUT_CHARS or "\x00" in patch:
        return _yield(work)

    # Revalidate immediately before the write-producing operation.
    _assert_effect_ready(work)
    with tempfile.TemporaryDirectory(prefix="control-v4-repair-") as tmp:
        repo = _clone_exact_candidate(work, Path(tmp))
        patch_path = Path(tmp) / "repair.diff"
        patch_path.write_text(patch + "\n", encoding="utf-8")
        try:
            subprocess.run(["git", "-C", str(repo), "apply", "--check", str(patch_path)], check=True, timeout=30)
            subprocess.run(["git", "-C", str(repo), "apply", str(patch_path)], check=True, timeout=30)
        except subprocess.CalledProcessError:
            return _yield(work)

        changed = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip()
        if not changed:
            return _yield(work)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "control-runtime-actuator[bot]"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "control-runtime-actuator[bot]@users.noreply.github.com"], check=True)
        summary = str(result.get("summary") or "Repair admitted Control finding").strip()[:120]
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", summary], check=True, timeout=30)
        new_sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        auth = f"AUTHORIZATION: bearer {os.environ['CONTROL_TARGET_TOKEN']}"
        subprocess.run(
            ["git", "-C", str(repo), "-c", f"http.extraHeader={auth}", "push", "origin",
             f"HEAD:refs/heads/{candidate['candidate_head_branch']}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )

    live = carrier._target_pr_candidate(work["repository"], candidate["candidate_pr_number"])
    if (
        live["candidate_sha"] != new_sha
        or live["candidate_head_branch"] != candidate["candidate_head_branch"]
        or live["expected_base_branch"] != candidate["expected_base_branch"]
    ):
        raise NativeRunnerError("target repair readback mismatch")
    return _commit_event(
        work,
        "CANDIDATE_READY",
        new_candidate_sha=live["candidate_sha"],
        candidate_pr_number=live["candidate_pr_number"],
        candidate_head_branch=live["candidate_head_branch"],
        new_expected_base_branch=live["expected_base_branch"],
        new_expected_base_sha=live["expected_base_sha"],
    )


def process() -> int:
    work = _work()
    action = work["action"]
    try:
        if action == "BUILD":
            result = _yield(work)
        elif action == "REPAIR":
            result = _repair(work)
        elif action == "REVIEW_INTERNAL":
            result = _internal_review(work)
        elif action == "REQUEST_EXTERNAL_REVIEW":
            result = _request_external_review(work)
        elif action == "RECONCILE_EXTERNAL_REVIEW":
            result = _reconcile_external_review(work)
        else:
            result = _yield(work)
    except Exception as exc:
        print(f"native WORK processing failed closed: {type(exc).__name__}: {exc}")
        try:
            result = _yield(work)
        except Exception:
            raise
    _json_output("result_json", result)
    print(json.dumps(result, sort_keys=True))
    return 0


def yield_only() -> int:
    work = _work()
    result = _yield(work)
    _json_output("result_json", result)
    print(json.dumps(result, sort_keys=True))
    return 0


def main() -> int:
    mode = os.environ.get("CONTROL_NATIVE_MODE", "acquire")
    if mode == "acquire":
        return acquire()
    if mode == "process":
        return process()
    if mode == "yield":
        return yield_only()
    raise SystemExit("unsupported native runner mode")


if __name__ == "__main__":
    raise SystemExit(main())
