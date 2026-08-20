# Scheduled Worker A V2 — Activation

## Current state

Scheduled Worker A V2 is integrated on public `main` and runs every ten minutes plus manual `workflow_dispatch`.

The workflow is intentionally fail-closed until its private bridge/provider configuration exists in **`market-predictions/control-engine` → Settings → Secrets and variables → Actions**.

Do not place secret values in issues, pull requests, chat, repository files or workflow YAML.

## Required Actions secrets

Create or expose these existing authorized credentials to `market-predictions/control-engine`:

```text
CONTROL_GITHUB_WRITE_TOKEN
CONTROL_CLOUDFLARE_API_TOKEN
CONTROL_CLOUDFLARE_ACCOUNT_ID
```

### CONTROL_GITHUB_WRITE_TOKEN

Use the existing Control cross-repository credential when it already has the intended least-privilege repository access. Otherwise create a dedicated fine-grained credential for the managed repositories Scheduled Worker A is allowed to mutate.

It must be able to:

- read/write the private `market-predictions/control-plane` repository, including `control-runtime-state`;
- read/write target work branches only in repositories that are already within Control's implementation authority.

Do not grant repository administration, Actions-secret administration, billing or organization administration merely for this worker.

If the credential is an organization Actions secret already used by private Control, prefer adding `market-predictions/control-engine` to that secret's allowed repository set rather than duplicating the value.

### Cloudflare provider credentials

Expose the already-authorized FREE_FAIL_CLOSED implementation credentials under:

```text
CONTROL_CLOUDFLARE_API_TOKEN
CONTROL_CLOUDFLARE_ACCOUNT_ID
```

No paid fallback or provider switch is implied by activation.

## Required Actions variable

Create:

```text
CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED=true
```

Only set this to `true` while the configured account/provider route is actually authorized to operate under the existing FREE_FAIL_CLOSED policy.

## Activation behavior

No queue edit is required.

After the configuration exists, either wait for the normal schedule or use **Actions → Scheduled Worker A V2 → Run workflow** once as acceleration.

The first successful private-state cycle must produce canonical evidence, not just a green public job:

1. expired `CONTROL-171-PR181-ADOPT` ownership is reconciled;
2. valid H2/R3 intake materializes to exact `ASSURANCE_QUEUED`;
3. no A ownership remains on #171;
4. the preferred eligible A implementation/repair task is selected;
5. a fresh canonical A1 claim is persisted/read back before inference;
6. result/finalization is persisted ghost-free when execution completes.

If provider credentials are absent but the GitHub bridge exists, the worker may still complete the deterministic reconcile/materialization phase, then stops before creating an A1 claim.

## Public-log expectations

The workflow may emit only bounded lifecycle classes, for example:

```text
SCHEDULED_WORKER_A_V2=IDLE_NO_ELIGIBLE_A1_TASK
SCHEDULED_WORKER_A_V2=COMPLETED_ONE_A1_TASK
SCHEDULED_WORKER_A_V2=EXECUTION_UNAVAILABLE_PRIVATE_GITHUB_CREDENTIAL
SCHEDULED_WORKER_A_V2=EXECUTION_UNAVAILABLE_IMPLEMENTATION_PROVIDER_CREDENTIAL
```

Private queue/task payloads, prompts, model responses, credential values and runtime metadata must not appear in public logs or artifacts.

## Verification

Activation is not considered complete until the private canonical readback proves the expected state transition. Public Actions success alone is never Control authority.
