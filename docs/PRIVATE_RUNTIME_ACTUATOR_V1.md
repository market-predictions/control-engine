# Private Runtime Actuator V1

## Purpose

`Scheduled Worker A V2` restores Control liveness on public GitHub-hosted compute without moving canonical governance state out of the private `market-predictions/control-plane` repository.

The boundary is:

```text
public control-engine = trusted executable code + free runner
private control-plane = authoritative state + authority
GitHub App installation token = short-lived least-privilege transport only
```

The public repository never becomes a mirror of the private runtime. Private state may exist only transiently inside one ephemeral trusted default-branch Actions job and is deleted at job completion.

## Execution authority

A public runner is an execution host, not a second Control authority. Every consequential transition remains authoritative only when it is durably persisted to the private `control-runtime-state` branch under the existing queue, handover, claim, result and CAS contracts.

A successful public job without private canonical persistence has no Control effect.

## Trigger model

Scheduled Worker A V2 runs:

- every ten minutes as the liveness backstop; and
- by explicit `workflow_dispatch` as an acceleration path.

Private-state execution is permitted only from `refs/heads/main` in exactly `market-predictions/control-engine`. Pull-request and fork workflows never receive the private-state execution path.

The scheduler does not create a second queue. It polls and advances the one private canonical `DISPATCH_QUEUE`.

## Deterministic cycle

Each invocation performs at most one A1 worker execution and follows this order:

1. Create a short-lived GitHub App installation token from the dedicated App identity/private key on trusted public `main`.
2. Fetch the bounded private Control implementation from an immutable 40-character SHA.
3. Read the exact private `control-runtime-state` commit and exact `control/DISPATCH_QUEUE.json` blob.
4. Reconcile expired leases.
5. Resume inactive A-role `EXECUTION_UNAVAILABLE` records through the canonical state helper; exhausted attempt budgets become `BLOCKED` rather than looping forever.
6. Reconcile managed `PROJECT_INTAKE_V1` records through the canonical intake materializer.
7. Validate the queue and enforce the bounded runtime write scope.
8. Re-read the remote runtime ref + queue blob; any movement discards and recomputes.
9. Persist reconciliation only by ordinary non-force push.
10. Select the preferred eligible A1 task through `CONTROL_PARALLEL_EXECUTION_V1` priority, dependency, capacity and repository-exclusion rules.
11. Verify implementation provider credentials and the `FREE_FAIL_CLOSED` attestation before creating an executing claim.
12. Re-read/reselect, create the exact A1 claim and persist it under a second exact ref+blob CAS cycle.
13. Re-fetch canonical state and prove `START_PROVEN` from exact role, stable worker `A1`, run id and live lease.
14. Prepare a credential-free target workspace.
15. Run the existing provider-portable implementation/repair adapter with provider credentials but without the GitHub publication credential.
16. Before publishing, prove the target work branch has not moved from the observed head.
17. Publish by ordinary push only.
18. Re-read the private runtime, prove the same claim is still current, construct the worker result, record/finalize under exact CAS, and read back ghost-free finalization.

`PROJECT_INTEGRATION` is deliberately fail-closed in V1. Model-driven implementation execution must not silently acquire exact-head merge authority. A separately bounded deterministic integration executor may be added later under its own contract.

## Credential boundary

The live workflow expects the GitHub bridge configuration:

```text
CONTROL_GITHUB_APP_ID
CONTROL_GITHUB_APP_PRIVATE_KEY
```

and, for model execution beyond deterministic state reconciliation:

```text
CONTROL_CLOUDFLARE_API_TOKEN
CONTROL_CLOUDFLARE_ACCOUNT_ID
CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED=true
```

The workflow uses the exact-pinned `actions/create-github-app-token` action to exchange the App identity/private key for a one-hour installation token. The token is restricted to repositories where the App is installed and to the explicitly requested permission subset. The action's normal post-step revokes the token when the job completes.

The existing shell actuator receives that short-lived token under the compatibility environment name `CONTROL_GITHUB_WRITE_TOKEN`; this name no longer denotes a personal access token or durable credential.

The public repository's built-in `GITHUB_TOKEN` remains `contents: read` and is never private Control authority.

Provider credentials are passed only to the isolated inference process. The inference process is launched from a clean environment and does not receive the GitHub App installation token.

No credential value may be printed, written to an artifact/cache, committed, or embedded in a repository URL.

## Private-data handling

Private state includes, at minimum:

- `DISPATCH_QUEUE` and `DISPATCH_RUNS`;
- project intakes;
- handovers and worker results;
- rendered worker prompts;
- provider runtime metadata;
- private repository source/workspaces.

For Scheduled Worker A V2 these values may be read into `$RUNNER_TEMP` only. The job uses `umask 077`, private temp files, redirects private program output away from the public log, uploads no artifacts, creates no cache and deletes the workspace on exit.

Only bounded non-sensitive lifecycle statuses such as `IDLE_NO_ELIGIBLE_A1_TASK`, `COMPLETED_ONE_A1_TASK` or an `EXECUTION_UNAVAILABLE_*` class may appear in the public job log.

## CAS and stale-writer rule

The private runtime transition is computed from:

```text
observed_runtime_ref
observed_queue_blob
```

Immediately before persistence both values are re-read from origin. If either moved, the entire proposed mutation is discarded and recomputed from the new state. Push is ordinary non-force push only.

Forbidden:

- `git pull --rebase` to replay a stale mutation;
- force push;
- hand reconstruction of the queue;
- merging an old state snapshot over a newer one;
- retrying a stale worker completion after its claim is no longer current.

## Write scopes

Reconciliation may modify only:

```text
control/DISPATCH_QUEUE.json
control/DISPATCH_RUNS.json
control/project-intake/*.json
```

Claim/finalization may modify only:

```text
control/DISPATCH_QUEUE.json
control/DISPATCH_RUNS.json
```

Any other private-state filesystem delta fails closed before persistence.

Target project changes remain constrained by the canonical task instruction and existing Worker A tooling.

## Security boundary for public contributions

The actuator workflow is not a pull-request execution surface. PR CI may compile/test the public actuator code against synthetic fixtures only. Repository secrets are not a mechanism for reviewing untrusted contributions.

Live private-state access begins only after code is integrated into trusted `main`, where the scheduled/default-branch workflow is the source of the executable job.

## Liveness success criteria

V1 is operationally proven only when canonical private readback demonstrates:

1. an expired A1 claim is automatically reconciled;
2. a valid successor intake is automatically materialized without hand-editing the queue;
3. A1 capacity is released;
4. the preferred eligible implementation/repair task is automatically claimed as stable A1;
5. `START_PROVEN` exists before model execution;
6. the task result is finalized with no ghost ownership; and
7. a later scheduled invocation can continue to the next eligible item without principal relay.

For the initial recovery, the first required proof is Control #171 moving from the expired A1 projection to exact H2/R3 `ASSURANCE_QUEUED`. The same invocation or a subsequent schedule must then be able to select a real eligible A task.

`principal_manual_relay_count=0` remains invariant.
