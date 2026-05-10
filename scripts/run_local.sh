#!/usr/bin/env bash
# Local test (macOS / Linux). Mount a Pokémon Crystal ROM you legally own at roms/crystal.gbc.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ANTHROPIC_API_KEY not set. export it after rotating your key." >&2
  exit 1
fi
if [[ ! -f roms/crystal.gbc ]]; then
  echo "Place pokemon_crystal.gbc at roms/crystal.gbc (you must own the cartridge)." >&2
  exit 1
fi

uv pip install -e . 2>/dev/null || pip install -e .

# env-worker on :8090
POKE_ROM=roms/crystal.gbc \
  uvicorn env_worker:app --host 127.0.0.1 --port 8090 &
ENVPID=$!
trap "kill $ENVPID 2>/dev/null || true" EXIT

# wait for env
for i in {1..30}; do
  curl -sf http://127.0.0.1:8090/state >/dev/null && break || sleep 0.5
done

# orchestrator + viewer on :8080
ENV_URL=http://127.0.0.1:8090 \
  uvicorn orchestrator:app --host 0.0.0.0 --port 8080
