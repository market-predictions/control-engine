# Private Runtime Assurance Actuator V1

## Purpose

`Scheduled Worker B V2` applies the existing Control Engine public/private actuator pattern to independent assurance.

The boundary is unchanged:

```text
public control-engine = trusted executable code + free GitHub-hosted runner
private control-plane = sole authoritative queue/state/result plane
GitHub App installation token = short-lived least-privilege transport
```

The public repository persists no private queue, prompt, candidate source, worker result, credential or runtime artifact.

## Solid-but-simple design

Worker B V2 deliberately reuses existing components instead of introducing another dispatcher or state machine:

1. the existing `control-runtime-state` queue and run ledger;
2. the existing stable role/instance `governance_release_assurance` / `B1`;
3. the existing private `control_connected_worker_runtime_v1.py` claim/result/terminal-completion lifecycle;
4. the existing provider policy and Cloudflare FREE_FAIL_CLOSED credential envelope;
5. the same Control GitHub App identity already used by Scheduled Worker A V2; and
6. the same exact-ref + exact-queue-blob CAS and non-force-push rules.

There is no second queue, daemon, watchdog, B slot, provider route, paid fallback or new authority domain.

## Trigger and authority

The workflow runs only from trusted `market-predictions/control-engine@main`, every ten minutes or by `workflow_dispatch`. Pull-request jobs never receive private-state credentials.

Before model execution the actuator must prove a current canonical claim with all of:

```text
state=ASSURANCE_EXECUTING
active_role=governance_release_assurance
active_worker_instance=B1
active_run_id=<nonempty>
claim_expires_at=<current>
principal_manual_relay_count=0
```

Only the private state plane can make that claim authoritative. Public workflow metadata is not START_PROVEN.

## Deterministic cycle

Each invocation executes at most one preferred B1 task:

1. authenticate the existing Control GitHub App and mint a short-lived installation token;
2. fetch an immutable private Control code ref and the current private runtime state;
3. reconcile expired leases and resume only inactive B-role `EXECUTION_UNAVAILABLE` records through the canonical state helper;
4. select the deterministic preferred B1 item and reselect immediately before claim;
5. create the B1 claim through the existing connected-worker runtime with a 900-second lease and read it back as START_PROVEN;
6. fetch the exact candidate SHA and blind evidence read-only;
7. remove Git/private-state workspaces before inference and run the existing provider-portable assurance adapter without the GitHub App token;
8. deterministically package PASS, FAIL, INDETERMINATE or EXECUTION_UNAVAILABLE;
9. re-fetch private code/state, prove the same claim remains current, and use the existing connected-worker completion lifecycle;
10. read back that all ownership fields are cleared and emit only a non-sensitive public liveness status.

## Credential and data boundary

The model subprocess receives only the configured inference credential envelope. It never receives `CONTROL_GITHUB_WRITE_TOKEN` or the public repository `GITHUB_TOKEN`.

Private candidate/state data exists only inside the ephemeral runner workspace. No artifacts or caches are uploaded. Private command output is redirected to private temporary files and deleted at job end.

## Bootstrap rationale

The private `control-plane` GitHub-hosted runner substrate is currently unavailable before job steps start. Because the public Control Engine actuator pattern already exists and is live-used by Worker A V2, adding B V2 is a recovery of a missing symmetric actuator, not a new execution architecture.

Bootstrap integration of this actuator may rely on public Control Engine exact-head CI plus deterministic contract review. It is not itself an independent B1 verdict. After integration, the required live proof is a real private canonical B1 claim, semantic result, immutable terminal completion and ghost-free release with `principal_manual_relay_count=0`.
