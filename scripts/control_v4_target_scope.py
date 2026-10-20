from __future__ import annotations

"""Choose only current V4 Mission-bound GitHub App read scopes.

Called from the EXISTING native Control workflow after the private Control Plane
capability exists. Emits repository names only; never any queue/task/authority
contents or secrets. This is a scope selector, NOT a grant or task admission.
"""

import os
from pathlib import Path

from control_engine.v4_runtime_protocol import parse_public_command, select_task_id_v4
from scripts import control_v4_owner_admin as admin
from scripts import control_v4_review_resume as review
from scripts import control_v4_runtime_carrier as carrier


def choose(mode: str, state: dict) -> list[str]:
    queue = state["queue"]
    authorized = {m["repository"].lower() for m in carrier._load_authority_bundle(state["main_sha"]).missions}
    if mode == "native":
        requested = os.environ.get("CONTROL_V4_START_REPOSITORY", "").strip().lower()
        repositories = [requested] if requested else []
    elif mode == "event":
        command = parse_public_command(os.environ["CONTROL_V4_PUBLIC_COMMAND"])
        if command["kind"] == "EVENT":
            repositories = [command["repository"]]
            # Do not mint a capability for an event with no current matching task.
            if not any(
                t["repository"] == command["repository"]
                and t["status"] == "ACTIVE"
                and queue["execution_lock"] is not None
                and queue["execution_lock"]["task_id"] == t["task_id"]
                and queue["execution_lock"]["run_id"] == command["run_id"]
                for t in queue["tasks"]
            ):
                repositories = []
        else:
            holder = queue["execution_lock"]
            if holder is not None and holder["run_id"] == command["run_id"]:
                repositories = [next(t["repository"] for t in queue["tasks"] if t["task_id"] == holder["task_id"])]
            elif holder is None:
                selected = select_task_id_v4(
                    queue, run_id=command["run_id"], integration_enabled=False,
                    yielded_task_tokens=command.get("yielded_task_tokens", []),
                )
                repositories = [
                    next(t["repository"] for t in queue["tasks"] if t["task_id"] == selected)
                ] if selected else []
            else:
                repositories = []
    elif mode == "review":
        # One repository per invocation, never all pending private projects.
        # The existing review job still proves exact candidate/CI/review facts.
        from datetime import datetime, timezone
        targets = sorted({t["repository"] for t in queue["tasks"] if review.eligible(t)})
        repositories = [targets[int(datetime.now(timezone.utc).timestamp()) // 3600 % len(targets)]] if targets else []
    elif mode == "owner-admin":
        command = admin.parse_owner_admin_command(os.environ["CONTROL_V4_OWNER_COMMAND"])
        repositories = [command["repository"]]
    elif mode == "replenish":
        # Automatic NO_WORK discovery remains public-only. Never grant
        # access to every private Mission merely to search for candidates.
        repositories = []
    else:
        raise ValueError("unknown target scope source")

    result = sorted(set(repositories))
    if any(repository.lower() not in authorized for repository in result):
        raise ValueError("target scope is outside current governed Mission")
    # The existing GitHub App installation owner is 'market-predictions'. Another
    # owner's private repo needs its own explicitly authorized installation.
    return [repository for repository in result if repository.startswith("market-predictions/")]


def main() -> None:
    state = carrier._load_current()
    mode = os.environ["CONTROL_TARGET_SCOPE_MODE"]
    selected = choose(mode, state)
    private = []
    for repository in selected:
        # Keep every existing public target on the original unauthenticated path.
        # GitHub intentionally returns 404 for inaccessible private repositories;
        # only a current-Mission-approved owner/name may then receive a token.
        observed = carrier._public_get(f"repos/{repository}", allow_404=True)
        if observed is not None:
            if not isinstance(observed, dict) or observed.get("full_name") != repository:
                raise ValueError("target repository public identity mismatch")
            if observed.get("private") is False:
                continue
            if observed.get("private") is not True:
                raise ValueError("target repository privacy response invalid")
        if not repository.startswith("market-predictions/"):
            raise ValueError("private target requires an installed owner-scoped App")
        private.append(repository)

    # Empty scope must skip token creation entirely. Never mint an unrestricted
    # installation token when a target was public or no private work exists.
    names = "\n".join(repo.split("/", 1)[1] for repo in private)
    full_names = "\n".join(private)
    output = Path(os.environ["GITHUB_OUTPUT"])
    with output.open("a", encoding="utf-8") as f:
        f.write("repository_names<<CONTROL_SCOPE_END\n" + names + "\nCONTROL_SCOPE_END\n")
        f.write("full_names<<CONTROL_SCOPE_END\n" + full_names + "\nCONTROL_SCOPE_END\n")
        f.write("has_targets=" + ("true" if private else "false") + "\n")
    print("CONTROL_V4_TARGET_READ_SCOPE=" + ("PRIVATE_SELECTED" if private else "PUBLIC_ONLY"))


if __name__ == "__main__":
    main()
