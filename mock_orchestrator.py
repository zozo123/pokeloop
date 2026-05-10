"""Mock orchestrator: drives the viewer through a deterministic v0→v4
evolution arc with no PyBoy, no ROM, no API calls. Used for the recorded
movie and for end-to-end viewer verification.

Run: uvicorn mock_orchestrator:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations
import asyncio, json, random
from contextlib import asynccontextmanager
from typing import Callable, Awaitable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import frames

clients: set[WebSocket] = set()

# Scripted scene sequence — deterministic so the recording is reproducible
# State carried frame-to-frame
S = {
    "phase": "title",   # title|overworld|dialogue|battle|menu|evolve|caught
    "tick": 0,
    "version": 0,
    "step": 0,
    "x": 0, "y": 0,
    "map_id": 24,
    "badges": 0,
    "pokedex_seen": 0,
    "party_count": 0,
    "money": 3000,
    "cum_r": 0.0,
    "dialogue": "Hello!",
    "enemy": "RATTATA",
    "hp": 1.0,
    "evolving": 0,           # frames remaining of evo overlay
    "caught_species": None,
    "caught_t": 0,
}

# Action narration libraries per policy version — what the agent's "thoughts"
# look like as it evolves. v0 is naive, v4 is competent. Used for the
# thoughts-stream sidebar and to give each version a visibly different vibe.
THOUGHTS = {
    0: [
        "Pressing buttons to see what happens.",
        "I think I should press START.",
        "Trying B in case it skips.",
        "Random direction.",
        "Maybe SELECT does something.",
        "Pressing A on this menu I opened by mistake.",
    ],
    1: [
        "Dialogue visible — pressing A to advance.",
        "Closing the menu I opened.",
        "Walking away from screen edge.",
        "A to confirm.",
        "Continuing dialogue.",
    ],
    2: [
        "Heading toward unexplored area.",
        "New map detected — keep walking.",
        "Pressing A on NPC.",
        "Walking up to find route exit.",
        "Path leads north — UP.",
    ],
    3: [
        "Wild encounter — selecting FIGHT.",
        "First move usually highest priority — A.",
        "HP low — switching to BAG for Pokéball.",
        "Throwing Pokéball.",
        "Walking back to heal.",
    ],
    4: [
        "Gym in sight — entering.",
        "Trainer blocking path — engaging.",
        "Lead Pokémon has type advantage — FIGHT.",
        "Use SuperEffective move — A.",
        "Badge earned — heading to next route.",
    ],
}

PROMPT_PREVIEWS = {
    1: "If a dialogue arrow is visible, ALWAYS press A. Never press START unless you intend to open the menu.",
    2: "If position is at a screen edge, walk away from that edge in the perpendicular direction. New maps yield reward.",
    3: "In wild battles default to DOWN+A (first move). If party HP is below 30%, switch to BAG and throw a Pokéball.",
    4: "When approaching a gym, fight blocking trainers first. Lead with the highest-level party member. Type-advantage matters.",
}

# ── viewer server ────────────────────────────────────────────────────────

async def emit(evt: dict):
    msg = json.dumps(evt)
    dead = []
    for c in clients:
        try: await c.send_text(msg)
        except Exception: dead.append(c)
    for d in dead: clients.discard(d)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run())
    try: yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="viewer"), name="static")

@app.get("/")
async def root(): return FileResponse("viewer/index.html")

@app.get("/screen.png")
async def screen():
    if S["evolving"] > 0:
        png = frames.evolve(40 - S["evolving"])
    elif S["caught_species"] and S["caught_t"] > 0:
        png = frames.caught(S["caught_species"], 30 - S["caught_t"])
    elif S["phase"] == "title":
        png = frames.title_screen(S["tick"])
    elif S["phase"] == "battle":
        png = frames.battle(S["enemy"], S["hp"], S["tick"])
    elif S["phase"] == "menu":
        png = frames.menu(S["tick"])
    elif S["phase"] == "dialogue":
        png = frames.dialogue(S["dialogue"], S["tick"])
    else:
        hint = "" if S["version"] >= 2 else "(stuck)"
        png = frames.overworld(S["x"], S["y"], S["map_id"], S["tick"], hint)
    return Response(content=png, media_type="image/png")

@app.websocket("/ws")
async def ws(c: WebSocket):
    await c.accept()
    clients.add(c)
    try:
        while True: await c.receive_text()
    except WebSocketDisconnect: pass
    finally: clients.discard(c)

# ── the scripted run ─────────────────────────────────────────────────────

def state_payload() -> dict:
    return {
        "badges": S["badges"], "pokedex_seen": S["pokedex_seen"],
        "map_id": S["map_id"], "party_count": S["party_count"],
        "money": S["money"], "x": S["x"], "y": S["y"],
    }

async def play_step(button: str, why: str, reward: float = 0.0, dt: float = 0.18):
    S["step"] += 1
    S["tick"] += 1
    S["cum_r"] += reward
    await emit({
        "event": "step", "t": S["step"], "v": S["version"],
        "button": button, "why": why, "r": reward,
        "cum_r": S["cum_r"], "state": state_payload(),
    })
    await asyncio.sleep(dt)

async def play_scene(scene: Callable[[int], Awaitable[None]], n_steps: int,
                     version_thoughts: list[str], reward_per_step: float = -0.001):
    for i in range(n_steps):
        await scene(i)
        why = random.choice(version_thoughts)
        btn = random.choice(["a", "b", "up", "down", "left", "right"])
        await play_step(btn, why, reward_per_step)

async def fan_out(decision_label: str, k: int = 8):
    """Visualize a fork tournament on the tree pane."""
    await emit({"event": "fork_start", "decision": decision_label,
                "snapshot": f"snap-{S['step']}", "k": k})
    await asyncio.sleep(0.4)
    # fake scores — winner has high score, losers cluster low
    scores = sorted([random.uniform(-2, -0.5) for _ in range(k - 2)] +
                    [random.uniform(0.5, 1.2)] + [random.uniform(-3, -1.5)],
                    reverse=True)
    await emit({"event": "fork_done", "decision": decision_label,
                "scores": scores, "pref_first": "a", "rej_first": "start"})
    await asyncio.sleep(0.3)

async def policy_bump(new_v: int):
    await emit({"event": "training_start", "from_v": new_v - 1, "pairs": 10})
    await asyncio.sleep(0.6)
    S["evolving"] = 40
    for _ in range(40):
        S["evolving"] -= 1; S["tick"] += 1
        await asyncio.sleep(0.05)
    S["version"] = new_v
    await emit({"event": "policy_bump", "version": new_v,
                "prompt_preview": PROMPT_PREVIEWS.get(new_v, "Refined policy.")})
    await asyncio.sleep(0.4)

async def caught_animation(species: str):
    S["caught_species"] = species
    S["caught_t"] = 30
    for _ in range(30):
        S["caught_t"] -= 1; S["tick"] += 1
        await asyncio.sleep(0.05)
    S["caught_species"] = None
    S["pokedex_seen"] += 1
    S["party_count"] += 1
    S["cum_r"] += 0.5

async def run():
    """Deterministic v0→v4 movie. ~85 seconds end-to-end at default cadence."""
    await asyncio.sleep(1.0)  # let the viewer connect
    await emit({"event": "boot", "version": 0, "state": state_payload()})

    # ─── Act I: title screen ─────────────────────────────────────────────
    S["phase"] = "title"
    for _ in range(8):
        S["tick"] += 1; await asyncio.sleep(0.15)
    await play_step("start", "Pressing buttons to see what happens.", 0.0, 0.2)

    # ─── Act II: v0 bumbles ──────────────────────────────────────────────
    S["phase"] = "menu"   # v0 mistakenly opened the menu
    async def t(_): pass
    await play_scene(t, 6, THOUGHTS[0], -0.001)
    await fan_out("decision-1 (menu open)")
    await play_scene(t, 5, THOUGHTS[0], -0.001)
    await fan_out("decision-2 (still in menu)")
    await play_scene(t, 4, THOUGHTS[0], -0.001)

    # bump → v1 (don't press START)
    await policy_bump(1)

    # ─── Act III: v1 dialogue + walk ─────────────────────────────────────
    S["phase"] = "dialogue"
    S["dialogue"] = "PROF.ELM: Hi! I have a Pokémon for you!"
    for i in range(12):
        S["tick"] += 1
        await play_step("a", random.choice(THOUGHTS[1]), 0.0, 0.15)
    S["phase"] = "overworld"
    S["party_count"] = 1; S["pokedex_seen"] = 1
    await play_step("down", "Walking away from house.", 0.5, 0.18)
    await fan_out("decision-3 (route choice)")
    for i in range(8):
        S["x"] += 1
        await play_step(random.choice(["down","left"]), random.choice(THOUGHTS[1]), 0.05, 0.15)

    # bump → v2 (explore unexplored)
    await policy_bump(2)

    # ─── Act IV: v2 explores, finds new map ──────────────────────────────
    S["phase"] = "overworld"
    for i in range(10):
        S["x"] += 1; S["y"] += i % 2
        await play_step("up", random.choice(THOUGHTS[2]), 0.02, 0.13)
    S["map_id"] = 25  # Route 29
    await play_step("up", "Crossed into Route 29 — new map!", 1.0, 0.2)
    await fan_out("decision-4 (encounter trigger)")
    for i in range(6):
        await play_step(random.choice(["up","right"]), random.choice(THOUGHTS[2]), 0.0, 0.13)

    # ─── Act V: v3 wild encounter, catches ───────────────────────────────
    S["phase"] = "battle"; S["enemy"] = "PIDGEY"; S["hp"] = 1.0
    await play_step("a", "Wild PIDGEY appeared.", 0.0, 0.2)

    # bump → v3 (combat)
    await policy_bump(3)

    for i in range(6):
        S["hp"] = max(0.2, 1.0 - i * 0.13)
        await play_step("a", random.choice(THOUGHTS[3]), 0.05, 0.15)
    # throw ball
    S["phase"] = "menu"
    await play_step("b", "Opening BAG for Pokéball.", 0.0, 0.2)
    await caught_animation("PIDGEY")
    S["phase"] = "overworld"

    await fan_out("decision-5 (post-catch route)")
    for i in range(4):
        S["x"] += 1
        await play_step("up", random.choice(THOUGHTS[3]), 0.0, 0.13)

    # ─── Act VI: v4 routes to gym, earns badge ───────────────────────────
    await policy_bump(4)

    S["map_id"] = 26  # Cherrygrove
    await play_step("up", "Entering Cherrygrove.", 0.5, 0.2)
    S["map_id"] = 27  # Violet Gym (compressed for the demo)
    await play_step("up", "Found gym entrance.", 1.0, 0.2)
    await fan_out("decision-6 (gym leader)")

    # battle leader
    S["phase"] = "battle"; S["enemy"] = "FALKNER"; S["hp"] = 1.0
    for i in range(8):
        S["hp"] = max(0.0, 1.0 - i * 0.14)
        await play_step("a", random.choice(THOUGHTS[4]), 0.1, 0.13)
    S["badges"] = 1
    S["pokedex_seen"] = 8
    S["cum_r"] += 3.0
    await emit({"event": "step", "t": S["step"]+1, "v": S["version"],
                "button": "a", "why": "Badge earned!", "r": 3.0,
                "cum_r": S["cum_r"], "state": state_payload()})
    await asyncio.sleep(1.5)

    # closing fan-out across "futures"
    await fan_out("decision-7 (next-gym route)", k=8)
    await asyncio.sleep(2.0)
    await emit({"event": "done", "steps": S["step"], "version": S["version"]})
