#!/usr/bin/env bash
set -euo pipefail
umask 077

emit() {
  printf 'status_class=%s\n' "$1" >> "$GITHUB_OUTPUT"
}

APP_ID="${CONTROL_GITHUB_APP_ID:-}"
PRIVATE_KEY="${CONTROL_GITHUB_APP_PRIVATE_KEY:-}"
OWNER="${GITHUB_REPOSITORY_OWNER:-}"
TMP_ROOT="${RUNNER_TEMP:-/tmp}/control-app-preflight-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
mkdir -p "$TMP_ROOT"
chmod 700 "$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

if ! [[ "$APP_ID" =~ ^[0-9]+$ ]]; then
  emit APP_ID_MISSING_OR_INVALID
  exit 2
fi
if [ -z "$PRIVATE_KEY" ]; then
  emit APP_PRIVATE_KEY_MISSING
  exit 2
fi
if [ -z "$OWNER" ]; then
  emit APP_OWNER_MISSING
  exit 2
fi

KEY_FILE="$TMP_ROOT/app.pem"
printf '%s\n' "$PRIVATE_KEY" > "$KEY_FILE"
chmod 600 "$KEY_FILE"
if ! openssl pkey -in "$KEY_FILE" -noout >/dev/null 2>&1; then
  emit APP_PRIVATE_KEY_PARSE_FAILED
  exit 2
fi

b64url() {
  openssl base64 -A | tr '+/' '-_' | tr -d '='
}

now="$(date +%s)"
iat=$((now - 60))
exp=$((now + 540))
header="$(printf '%s' '{"alg":"RS256","typ":"JWT"}' | b64url)"
payload="$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$iat" "$exp" "$APP_ID" | b64url)"
unsigned="${header}.${payload}"
signature="$(printf '%s' "$unsigned" | openssl dgst -sha256 -sign "$KEY_FILE" | b64url)"
jwt="${unsigned}.${signature}"

APP_JSON="$TMP_ROOT/app.json"
app_code="$(curl -sS -o "$APP_JSON" -w '%{http_code}' \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -H "Authorization: Bearer $jwt" \
  https://api.github.com/app || true)"
if [ "$app_code" != "200" ]; then
  emit APP_AUTH_FAILED
  exit 2
fi

INSTALL_JSON="$TMP_ROOT/installations.json"
install_code="$(curl -sS -o "$INSTALL_JSON" -w '%{http_code}' \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -H "Authorization: Bearer $jwt" \
  'https://api.github.com/app/installations?per_page=100' || true)"
if [ "$install_code" != "200" ]; then
  emit APP_INSTALLATION_LOOKUP_FAILED
  exit 2
fi
if ! jq -e --arg owner "$OWNER" '.[] | select(.account.login == $owner)' "$INSTALL_JSON" >/dev/null 2>&1; then
  emit APP_INSTALLATION_NOT_FOUND
  exit 2
fi

emit APP_AUTH_PREFLIGHT_OK
