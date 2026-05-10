"""Individual worker — runs in one islo.dev sandbox per individual.

Exposes:
  GET /screen.png   — current GB-style frame for this individual
  GET /state        — full state json (slot, gen, fitness, phase, milestone)
  GET /score        — just the fitness number
  POST /setgen      — orchestrator advances this worker to a new generation
  POST /setpolicy   — orchestrator hands this worker a new system prompt
  POST /tick        — orchestrator advances simulation by one tick

Fitness is a deterministic function of (slot, gen, current_policy_text).
The policy_text accumulates "heuristics" via crossover/mutation; each known
heuristic substring adds to the bonus, so prompts that pick up more rules
score higher — same shape as real RL prompt-evolution.
"""
from __future__ import annotations
import io, os, random, time
from fastapi import FastAPI, Request
from fastapi.responses import Response
from pydantic import BaseModel

import frames

SLOT = int(os.environ.get("WORKER_SLOT", "1"))
random.seed(SLOT * 17 + 7)

state = {
    "slot": SLOT,
    "id": f"G0-{SLOT}",
    "gen": 0,
    "fitness": 0.0,
    "phase": "title",
    "tick": SLOT * 5,
    "x": random.randint(0, 6),
    "y": random.randint(0, 6),
    "map_id": 24,
    "policy_text": "",
    "policy_version": 0,
    "milestone": None,
    "milestone_t": 0,
}

# heuristics that fitness rewards if present in policy_text
HEURISTICS = {
    "press A to advance dialogue":  ("dialogue",    1.2),
    "walk away from screen edges":  ("walked",      0.7),
    "explore unexplored maps":      ("route",       1.5),
    "fight with first move":        ("battle",      0.6),
    "throw a Pokéball":             ("caught",      1.4),
    "enter gyms":                   ("cherrygrove", 1.0),
    "challenge gym leaders":        ("gym",         1.8),
    "use type advantage":           ("badge",       2.0),
}

def baseline(gen: int, slot: int) -> float:
    return -0.5 + gen * 0.65 + (slot % 4 - 1.5) * 0.4

def policy_bonus(text: str) -> tuple[float, str | None]:
    if not text: return 0.0, None
    total = 0.0
    last_milestone = None
    for k, (ms, w) in HEURISTICS.items():
        if k in text:
            total += w
            last_milestone = ms
    return total, last_milestone

def update_phase():
    s = state
    if s["milestone_t"] > 0:
        s["milestone_t"] -= 1
        if s["milestone_t"] == 0:
            s["milestone"] = None
            s["phase"] = "overworld"
        return
    r = random.random()
    if s["phase"] == "title" and s["tick"] > 8:
        s["phase"] = "overworld"
    if s["phase"] == "overworld":
        if r < 0.55:
            s["x"] = (s["x"] + random.choice([-1, 1])) % 16
            s["y"] = (s["y"] + random.choice([-1, 0, 1])) % 16
        if "press A" in s["policy_text"] and r > 0.93:
            s["phase"] = "dialogue"
        elif "fight" in s["policy_text"] and r > 0.95:
            s["phase"] = "battle"
        elif "throw a Pokéball" in s["policy_text"] and r > 0.97:
            s["phase"] = "battle"
            s["milestone"] = "caught"
            s["milestone_t"] = 25
    elif s["phase"] == "menu" and r > 0.55:
        s["phase"] = "overworld"
    elif s["phase"] == "dialogue" and r > 0.7:
        s["phase"] = "overworld"
    elif s["phase"] == "battle" and s["milestone"] is None and r > 0.6:
        s["phase"] = "overworld"

class GenReq(BaseModel):
    gen: int

class PolicyReq(BaseModel):
    policy: str
    version: int | None = None

app = FastAPI()

@app.get("/screen.png")
def screen():
    s = state
    if s["milestone_t"] > 0 and s["milestone"] == "caught":
        png = frames.caught("PIDGEY", 25 - s["milestone_t"])
    elif s["phase"] == "battle":
        enemy = "FALKNER" if s["map_id"] == 27 else "WILD"
        hp = max(0.05, 1.0 - (s["tick"] % 40) / 50)
        png = frames.battle(enemy, hp, s["tick"])
    elif s["phase"] == "menu":
        png = frames.menu(s["tick"])
    elif s["phase"] == "dialogue":
        png = frames.dialogue("PROF.ELM: Take this Pokémon!", s["tick"])
    elif s["phase"] == "title":
        png = frames.title_screen(s["tick"])
    else:
        png = frames.overworld(s["x"], s["y"], s["map_id"], s["tick"])
    return Response(content=png, media_type="image/png")

@app.get("/state")
def get_state():
    return state

@app.get("/score")
def score():
    return {"fitness": state["fitness"], "milestone": state["milestone"]}

@app.post("/setgen")
def setgen(req: GenReq):
    state["gen"] = req.gen
    state["id"] = f"G{req.gen}-{SLOT}"
    state["fitness"] = max(-1.0, baseline(req.gen, SLOT) - 1.0)
    state["tick"] = SLOT * 5
    state["phase"] = "title" if random.random() > 0.5 else "overworld"
    state["x"] = random.randint(0, 6); state["y"] = random.randint(0, 6)
    state["milestone"] = None; state["milestone_t"] = 0
    state["map_id"] = 24
    return {"ok": True, "id": state["id"]}

@app.post("/setpolicy")
def setpolicy(req: PolicyReq):
    state["policy_text"] = req.policy
    state["policy_version"] = req.version or state["policy_version"] + 1
    return {"ok": True, "version": state["policy_version"]}

@app.post("/tick")
def tick():
    s = state
    s["tick"] += 1
    target = baseline(s["gen"], SLOT)
    bonus, ms = policy_bonus(s["policy_text"])
    target += bonus
    s["fitness"] += (target - s["fitness"]) * 0.06 + random.uniform(-0.02, 0.02)
    update_phase()
    return {"slot": SLOT, "fitness": round(s["fitness"], 2),
            "phase": s["phase"], "milestone": s["milestone"]}

@app.get("/")
def root():
    return {"worker": SLOT, "id": state["id"], "fitness": state["fitness"],
            "policy_version": state["policy_version"]}
