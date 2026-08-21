# Scheduled Worker A V2 — Activation

## Current state

Scheduled Worker A V2 is integrated on public `main` and runs every ten minutes plus manual `workflow_dispatch`.

The private GitHub bridge uses a dedicated GitHub App rather than a personal access token. The workflow creates a short-lived installation token on every trusted `main` run and GitHub revokes that token automatically at job completion.

Do not place secret values in issues, pull requests, chat, repository files or workflow YAML.

## Required GitHub App configuration

The GitHub App must be installed on every `market-predictions` repository Scheduled Worker A is authorized to access. For the initial #171 recovery this requires at minimum:

```text
control-engine
control-plane
```

The App installation must grant only the repository permissions needed by the actuator. The initial bridge requests:

```text
Contents: read/write
Workflows: write
```

The public repository's built-in `GITHUB_TOKEN` remains `contents: read` and is not private Control authority.

## Required Actions variable and secret

In **`market-predictions/control-engine` → Settings → Secrets and variables → Actions** configure:

```text
Repository variable:
CONTROL_GITHUB_APP_ID=<numeric GitHub App ID>

Repository secret:
CONTROL_GITHUB_APP_PRIVATE_KEY=<complete PEM private key>
```

The pinned `actions/create-github-app-token` action accepts `app-id` for compatibility. Current upstream also supports and prefers Client ID; migration from App ID to Client ID is non-blocking and may be done separately after live recovery is proven.

No personal access token is required. The legacy environment variable name `CONTROL_GITHUB_WRITE_TOKEN` remains only as an internal compatibility input to the existing shell actuator; at runtime its value is the one-hour GitHub App installation token.

## Cloudflare provider configuration

To proceed beyond deterministic queue reconciliation into actual IMPLEMENTATION/REPAIR execution, expose the already-authorized FREE_FAIL_CLOSED provider configuration:

```text
Repository secrets:
CONTROL_CLOUDFLARE_API_TOKEN
CONTROL_CLOUDFLARE_ACCOUNT_ID

Repository variable:
CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED=true
```

No paid fallback, new paid capacity or provider switch is implied by activation.

The GitHub App bridge alone is sufficient for the initial deterministic #171 liveness repair because reconciliation/materialization occurs before the provider credential gate.

## Activation behavior

No queue edit is required.

After the GitHub App configuration exists, either wait for the normal schedule or use **Actions → Scheduled Worker A V2 → Run workflow** once as acceleration.

The first successful private-state cycle must produce canonical evidence, not just a green public job:

1. expired `CONTROL-171-PR181-ADOPT` ownership is reconciled;
2. valid H2/R3 intake materializes to exact `ASSURANCE_QUEUED`;
3. no A ownership remains on #171;
4. if provider credentials are present, the preferred eligible A implementation/repair task is selected;
5. a fresh canonical A1 claim is persisted/read back before inference;
6. result/finalization is persisted ghost-free when execution completes.

If provider credentials are absent but the GitHub App bridge works, the worker must still complete deterministic reconcile/materialization, then stop before creating an A1 claim.

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

Activation is not considered complete until private canonical readback proves the expected state transition. Public Actions success alone is never Control authority.
