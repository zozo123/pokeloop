#!/usr/bin/env bash
# Produce movie/pokeloop.mp4 + movie/pokeloop.gif from the mock orchestrator.
# No ROM, no API key — pure deterministic playback of the v0→v4 evolution arc.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".venv-mock"
SECONDS_RUN="${SECONDS_RUN:-90}"

if [[ ! -d "$VENV" ]]; then
  echo "[movie] creating venv $VENV"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "[movie] installing deps"
pip install --quiet --upgrade pip
pip install --quiet \
  fastapi 'uvicorn[standard]' pillow httpx websockets pydantic playwright

if [[ ! -d "$HOME/Library/Caches/ms-playwright/chromium-"* ]] && \
   [[ ! -d "$HOME/.cache/ms-playwright/chromium-"* ]]; then
  echo "[movie] installing chromium for playwright (one-time, ~150MB)"
  python -m playwright install chromium
fi

# start mock server
echo "[movie] starting mock orchestrator on :8080"
uvicorn mock_orchestrator:app --host 127.0.0.1 --port 8080 --log-level warning &
SVR=$!
trap "kill $SVR 2>/dev/null || true" EXIT

# wait until /ws is up
for i in {1..40}; do
  if curl -sf http://127.0.0.1:8080/ >/dev/null 2>&1; then break; fi
  sleep 0.25
done
sleep 1

# record
mkdir -p movie
echo "[movie] recording for ${SECONDS_RUN}s..."
python record.py --seconds "$SECONDS_RUN" --out-dir movie --url http://127.0.0.1:8080/

# convert webm → mp4 + gif
WEBM=$(ls -t movie/*.webm | head -1)
echo "[movie] webm: $WEBM"
ffmpeg -y -i "$WEBM" \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart \
  -vf "scale=1280:800" movie/pokeloop.mp4 2>/dev/null
ffmpeg -y -i "$WEBM" \
  -vf "fps=15,scale=720:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  movie/pokeloop.gif 2>/dev/null

ls -lh movie/pokeloop.mp4 movie/pokeloop.gif
echo "[movie] done. share movie/pokeloop.mp4 on HN."
