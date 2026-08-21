#!/usr/bin/env bash
set -euo pipefail
umask 077

repository="${1:-}"
output_file="${2:-}"
app_id="${CONTROL_GITHUB_APP_ID:-}"
private_key="${CONTROL_GITHUB_APP_PRIVATE_KEY:-}"

if ! [[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  exit 2
fi
if [ -z "$output_file" ] || ! [[ "$app_id" =~ ^[0-9]+$ ]] || [ -z "$private_key" ]; then
  exit 2
fi

owner="${repository%%/*}"
repo_name="${repository#*/}"
tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT
chmod 700 "$tmp_root"
key_file="$tmp_root/app.pem"
printf '%s\n' "$private_key" > "$key_file"
chmod 600 "$key_file"
openssl pkey -in "$key_file" -noout >/dev/null 2>&1

b64url() {
  openssl base64 -A | tr '+/' '-_' | tr -d '='
}

now="$(date +%s)"
iat=$((now - 60))
exp=$((now + 540))
header="$(printf '%s' '{"alg":"RS256","typ":"JWT"}' | b64url)"
payload="$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$iat" "$exp" "$app_id" | b64url)"
unsigned="${header}.${payload}"
signature="$(printf '%s' "$unsigned" | openssl dgst -sha256 -sign "$key_file" | b64url)"
jwt="${unsigned}.${signature}"

installation_json="$tmp_root/installation.json"
code="$(curl -sS -o "$installation_json" -w '%{http_code}' \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -H "Authorization: Bearer $jwt" \
  "https://api.github.com/repos/${repository}/installation" || true)"
[ "$code" = "200" ] || exit 3
jq -e --arg owner "$owner" '.account.login == $owner' "$installation_json" >/dev/null 2>&1 || exit 3
installation_id="$(jq -r '.id // empty' "$installation_json")"
[[ "$installation_id" =~ ^[0-9]+$ ]] || exit 3

request_json="$tmp_root/request.json"
jq -nc --arg repo "$repo_name" '{repositories:[$repo],permissions:{contents:"write"}}' > "$request_json"
token_json="$tmp_root/token.json"
code="$(curl -sS -o "$token_json" -w '%{http_code}' \
  -X POST \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -H "Authorization: Bearer $jwt" \
  -H 'Content-Type: application/json' \
  --data-binary "@$request_json" \
  "https://api.github.com/app/installations/${installation_id}/access_tokens" || true)"
[ "$code" = "201" ] || exit 4
token="$(jq -r '.token // empty' "$token_json")"
[ -n "$token" ] || exit 4

mkdir -p "$(dirname "$output_file")"
printf '%s' "$token" > "$output_file"
chmod 600 "$output_file"
printf 'TARGET_APP_TOKEN=OK\n'
