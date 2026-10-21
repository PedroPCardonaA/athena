#!/usr/bin/env bash
# One-shot local install: start the container, then optionally connect your AI agent over MCP.
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

CMD=(podman exec -i athena python -m app.athena_mcp)
echo
echo "2) Connect an AI agent (no tokens needed):"
echo "     claude mcp add athena -- ${CMD[*]}"
echo "     codex mcp add athena -- ${CMD[*]}"
echo "   Other clients: see docs/mcp.md. Add --read-only for view-only access."
for tool in claude codex; do
  if command -v "$tool" >/dev/null; then
    read -r -p "Add Athena to $tool now? [y/N] " yn || yn=n
    [[ "$yn" =~ ^[Yy]$ ]] && "$tool" mcp add athena -- "${CMD[@]}"
  fi
done
