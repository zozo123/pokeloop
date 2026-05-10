"""Main loop. Roll out → fork at decision points → tournament → preference pair
→ every N pairs, textual DPO bumps the policy version. Streams events to the
viewer over WebSocket.

Run: uvicorn orchestrator:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations
import asyncio, json, os, time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from policy import act
from reward import reward
from trainer import textual_dpo

ENV = os.environ.get("ENV_URL", "http://localhost:8090")
POLICIES = Path("policies"); POLICIES.mkdir(exist_ok=True)
RUNS = Path("runs"); RUNS.mkdir(exist_ok=True)

K_FORKS     = int(os.environ.get("K_FORKS", "8"))
HORIZON     = int(os.environ.get("HORIZON", "20"))
DPO_EVERY   = int(os.environ.get("DPO_EVERY", "10"))
MAX_STEPS   = int(os.environ.get("MAX_STEPS", "5000"))
DIVERSITY   = ["a", "b", "up", "down", "left", "right", "start", "a"]

clients: set[WebSocket] = set()

async def emit(evt: dict):
    msg = json.dumps(evt)
    dead = []
    for c in clients:
        try: await c.send_text(msg)
        except Exception: dead.append(c)
    for d in dead: clients.discard(d)

# ── env client ───────────────────────────────────────────────────────────
class Env:
    def __init__(self, base: str):
        self.h = httpx.AsyncClient(base_url=base, timeout=30.0)
    async def step(self, button: str) -> dict:
        r = await self.h.post("/step", json={"button": button}); r.raise_for_status()
        return r.json()["state"]
    async def screen(self) -> bytes:
        r = await self.h.get("/screen.png"); r.raise_for_status(); return r.content
    async def state(self) -> dict:
        r = await self.h.get("/state"); r.raise_for_status(); return r.json()
    async def save(self) -> str:
        r = await self.h.post("/save"); r.raise_for_status(); return r.json()["id"]
    async def load(self, sid: str) -> None:
        r = await self.h.post("/load", json={"id": sid}); r.raise_for_status()

# ── loop ─────────────────────────────────────────────────────────────────
def is_decision_point(prev: dict, curr: dict) -> bool:
    return (curr["party_count"] != prev["party_count"]
            or curr["map_id"] != prev["map_id"])

async def fork_score(env: Env, snap: str, prompt: str, visited: set,
                     first_button: str | None, horizon: int) -> tuple[float, list]:
    await env.load(snap)
    actions, prev = [], await env.state()
    total = 0.0
    for i in range(horizon):
        if i == 0 and first_button:
            btn, why = first_button, "fork-diversify"
        else:
            png = await env.screen()
            btn, why = await act(png, prev, prompt)
        curr = await env.step(btn)
        total += reward(prev, curr, set(visited)).total
        actions.append({"button": btn, "why": why})
        prev = curr
    return total, actions

async def run():
    env = Env(ENV)
    version = 0
    prompt = (POLICIES / "v0.txt").read_text()
    pairs: list[dict] = []
    visited: set = set()
    decision_count = 0
    log = open(RUNS / f"run-{int(time.time())}.jsonl", "w")

    def L(evt):
        log.write(json.dumps(evt) + "\n"); log.flush()

    prev = await env.state()
    visited.add(prev["map_id"])
    await emit({"event": "boot", "version": version, "state": prev})
    L({"event": "boot", "version": version, "state": prev})

    cum_reward = 0.0
    for step_i in range(MAX_STEPS):
        png = await env.screen()
        btn, why = await act(png, prev, prompt)
        curr = await env.step(btn)
        rwd = reward(prev, curr, visited)
        cum_reward += rwd.total

        await emit({"event": "step", "t": step_i, "v": version,
                    "button": btn, "why": why, "r": rwd.total,
                    "cum_r": cum_reward, "state": curr})
        L({"event": "step", "t": step_i, "v": version,
           "button": btn, "why": why, "r": rwd.total, "state": curr})

        if is_decision_point(prev, curr):
            decision_count += 1
            snap = await env.save()
            await emit({"event": "fork_start", "decision": decision_count,
                        "snapshot": snap, "k": K_FORKS})

            results = await asyncio.gather(*[
                fork_score(env, snap, prompt, visited,
                           DIVERSITY[k % len(DIVERSITY)], HORIZON)
                for k in range(K_FORKS)
            ])
            scored = [(s, a, DIVERSITY[k % len(DIVERSITY)])
                      for k, (s, a) in enumerate(results)]
            scored.sort(key=lambda x: x[0], reverse=True)
            best, worst = scored[0], scored[-1]

            pairs.append({
                "context": f"v{version} step={step_i} state={curr}",
                "preferred": [a["button"] for a in best[1]],
                "rejected":  [a["button"] for a in worst[1]],
                "pref_score": best[0], "rej_score": worst[0],
            })
            await emit({"event": "fork_done", "decision": decision_count,
                        "scores": [s for s, _, _ in scored],
                        "pref_first": best[2], "rej_first": worst[2]})

            # main timeline takes the winning first action
            await env.load(snap)
            curr = await env.step(best[1][0]["button"])

            if decision_count % DPO_EVERY == 0 and len(pairs) >= DPO_EVERY:
                await emit({"event": "training_start", "from_v": version,
                            "pairs": len(pairs[-DPO_EVERY:])})
                new_prompt = await textual_dpo(prompt, pairs[-DPO_EVERY:])
                version += 1
                (POLICIES / f"v{version}.txt").write_text(new_prompt)
                prompt = new_prompt
                await emit({"event": "policy_bump", "version": version,
                            "prompt_preview": new_prompt[:240]})
                L({"event": "policy_bump", "version": version})

        prev = curr

    await emit({"event": "done", "steps": MAX_STEPS, "version": version})

# ── viewer server ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run())
    try:
        yield
    finally:
        task.cancel()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="viewer"), name="static")

@app.get("/")
async def root(): return FileResponse("viewer/index.html")

@app.get("/screen.png")
async def proxy_screen():
    async with httpx.AsyncClient() as h:
        r = await h.get(f"{ENV}/screen.png")
        from fastapi.responses import Response
        return Response(content=r.content, media_type="image/png")

@app.websocket("/ws")
async def ws(c: WebSocket):
    await c.accept()
    clients.add(c)
    try:
        while True: await c.receive_text()
    except WebSocketDisconnect: pass
    finally: clients.discard(c)
