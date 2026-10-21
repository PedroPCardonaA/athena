#!/usr/bin/env bash
# One-shot local install: start the container, then optionally wire up the agent skill.
set -euo pipefail
cd "$(dirname "$0")"
URL="http://127.0.0.1:8787"

command -v podman >/dev/null || { echo "podman is required: https://podman.io/docs/installation" >&2; exit 1; }
command -v podman-compose >/dev/null || { echo "podman-compose is required (e.g. pip install --user podman-compose)" >&2; exit 1; }

mkdir -p data
podman-compose up -d

printf 'Waiting for the app'
for _ in $(seq 1 30); do
  curl -fs "$URL/healthz" >/dev/null 2>&1 && break
  printf '.'; sleep 1
done
curl -fs "$URL/healthz" >/dev/null || { echo; echo "App did not become healthy; check: podman-compose logs" >&2; exit 1; }
echo " up."
echo "1) Open $URL and choose your password."

read -r -p "Install the Claude Code research skill? [y/N] " yn || yn=n
if [[ "$yn" =~ ^[Yy]$ ]]; then
  mkdir -p ~/.claude/skills ~/.config/ideas-saver
  cp -r skill/research-idea ~/.claude/skills/
  echo "2) In the UI go to 'API tokens' and create a write token, then paste it here."
  read -r -s -p "Token (hidden): " tok; echo
  if [[ -n "$tok" ]]; then
    umask 077
    printf '{"url": "%s", "token": "%s"}\n' "$URL" "$tok" > ~/.config/ideas-saver/config
    echo "Saved ~/.config/ideas-saver/config (mode 600). Try: research idea 1"
  fi
fi
