#!/usr/bin/env bash
# Bootstrap inside an islo.dev sandbox.
#
# Prereq from the host:
#   islo create --name pokeloop --vcpus 4 --memory-mb 4096 --disk-gb 20
#   islo upload pokeloop ./ /workspace/pokeloop
#   islo upload pokeloop ./roms/crystal.gbc /workspace/pokeloop/roms/crystal.gbc
#   islo exec pokeloop -- bash /workspace/pokeloop/scripts/run_islo.sh
#   islo share pokeloop viewer 8080  # → https://<id>.share.islo.dev
set -euo pipefail
cd /workspace/pokeloop

apt-get update -qq && apt-get install -y -qq python3-pip libsdl2-2.0-0 >/dev/null
pip install -q -e .

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ANTHROPIC_API_KEY not set in sandbox. islo exec ... -e ANTHROPIC_API_KEY=…" >&2
  exit 1
fi

POKE_ROM=roms/crystal.gbc \
  uvicorn env_worker:app --host 127.0.0.1 --port 8090 &
for i in {1..30}; do
  curl -sf http://127.0.0.1:8090/state >/dev/null && break || sleep 0.5
done

# Take a baseline snapshot of the *VM itself* — the platform-native flex.
# Cross-VM forks at chapter boundaries are coordinated from outside the sandbox
# via the islo SDK; see README.
echo "[sandbox] env-worker up. starting orchestrator + viewer on :8080"

ENV_URL=http://127.0.0.1:8090 \
  exec uvicorn orchestrator:app --host 0.0.0.0 --port 8080
