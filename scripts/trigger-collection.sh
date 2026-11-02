#!/usr/bin/env bash
# Fire the collector through GitHub's repository_dispatch API.
#
#   GITHUB_PAT=github_pat_... ./scripts/trigger-collection.sh
#
# This is what an external scheduler calls on a timer. GitHub's own scheduler
# is best-effort and drops most triggers on public repos: it fires 4-5 times a
# day whatever the cron says, and once went quiet for 16 hours. Since Spotify
# retains only ~50 recent plays and this account's busiest 3-hour window holds
# 64, a dependable interval is the only thing preventing permanent loss.
#
# The token needs one permission: Contents -> Read and write, scoped to this
# repository alone. Treat it as a password — it can push to the repo. Give it
# an expiry and store it only in the scheduler's secret field.
set -euo pipefail

REPO="${REPO:-iochoa808/SpotifyData}"
EVENT="${EVENT:-collect}"

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "GITHUB_PAT is not set." >&2
  echo "Create one at https://github.com/settings/personal-access-tokens/new" >&2
  echo "  Repository access : only ${REPO}" >&2
  echo "  Permissions       : Contents -> Read and write" >&2
  exit 1
fi

body=$(mktemp)
trap 'rm -f "$body"' EXIT

status=$(curl -sS -o "$body" -w '%{http_code}' -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GITHUB_PAT}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${REPO}/dispatches" \
  -d "{\"event_type\":\"${EVENT}\"}")

case "$status" in
  204)
    echo "Dispatched '${EVENT}' to ${REPO}."
    echo "Watch it at https://github.com/${REPO}/actions"
    ;;
  401|403)
    echo "Rejected (HTTP ${status}): the token is wrong, expired, or lacks" >&2
    echo "Contents: Read and write on ${REPO}." >&2
    cat "$body" >&2
    exit 1
    ;;
  422)
    echo "HTTP 422: no 'repository_dispatch' trigger for event_type" >&2
    echo "'${EVENT}' on the default branch." >&2
    cat "$body" >&2
    exit 1
    ;;
  404)
    echo "HTTP 404: ${REPO} not found, or the token cannot see it." >&2
    cat "$body" >&2
    exit 1
    ;;
  *)
    echo "Unexpected HTTP ${status}:" >&2
    cat "$body" >&2
    exit 1
    ;;
esac
