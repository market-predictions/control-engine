# GitHub App Bridge V1

Scheduled Worker A authenticates cross-repository access through a dedicated GitHub App installation token, never through a personal access token.

## Runtime invariants

- trusted execution only from `market-predictions/control-engine@main`;
- public repository `GITHUB_TOKEN` remains read-only;
- App installation token is created at runtime and expires after at most one hour;
- normal action post-processing revokes the installation token at job completion;
- token scope is limited to repositories on which the App is installed;
- token permissions are explicitly down-scoped by the workflow;
- no token enters the model subprocess environment;
- no token is stored in artifacts, caches, repository content or public logs;
- private Control state remains authoritative only in `market-predictions/control-plane`;
- `principal_manual_relay_count=0` remains invariant.

## Bootstrap compatibility

The existing shell actuator still names its transport environment variable `CONTROL_GITHUB_WRITE_TOKEN`. Under this bridge the variable contains only the fresh GitHub App installation token generated for the current job. It is not a PAT and must never be populated from `secrets.CONTROL_GITHUB_WRITE_TOKEN`.

## Initial installation scope

For Control #171 recovery the App must be installed on at least:

- `market-predictions/control-engine`;
- `market-predictions/control-plane`.

Additional repositories are added only when they become legitimate Scheduled Worker A targets. Cross-owner repositories require a compatible installation of the same GitHub App on that owner; access is never inferred from the installation on `market-predictions`.
