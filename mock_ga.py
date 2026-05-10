"""Mock GA orchestrator: drives the GA viewer through 8 generations of an 8-individual
population evolving via tournament selection + crossover + mutation. No PyBoy, no ROM,
no API. Used for the recorded 'evolutionary gain' movie.

Each individual is one islo.dev sandbox running its own policy. Each generation is a
parallel fan-out of 8 sandboxes from the previous generation's elites + offspring.

Run: uvicorn mock_ga:app --host 0.0.0.0 --port 8081
"""
from __future__ import annotations
import asyncio, json, random
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import frames

random.seed(7)

POP_SIZE = 8
N_GENERATIONS = 8

# ── per-individual state ─────────────────────────────────────────────────
def make_individual(slot: int, gen: int, parents: list[str] | None = None,
                    mutated: bool = False) -> dict:
    return {
        "id": f"G{gen}-{slot+1}",
        "slot": slot,
        "gen": gen,
        "parents": parents or [],
        "mutated": mutated,
        "phase": "title",
        "x": random.randint(0, 6),
        "y": random.randint(0, 6),
        "map_id": 24,
        "fitness": 0.0,
        "tick": slot * 5,
        "milestone": None,            # transient: 'caught','badge','starter'
        "milestone_t": 0,
        "highlight": None,            # 'elite','parent','child','mutated', None
    }

pop: list[dict] = [make_individual(i, 0) for i in range(POP_SIZE)]
fitness_history: list[dict] = []      # [{gen, max, mean, min, vals: [...]}, ...]
lineage_edges: list[dict] = []        # [{parents: [a,b], child: c, gen: n}]
clients: set[WebSocket] = set()

# ── narrative arc — designed to show clear gain ─────────────────────────
# (gen, scripted_max, scripted_mean, milestones_per_slot)
# milestones: { slot_idx: ('walked'|'dialogue'|'starter'|'route'|'caught'|'cherrygrove'|'gym'|'badge', fitness) }
GEN_SCRIPT = [
    {"max": 1.5,  "mean": 0.0,  "milestones": {0: ("walked", 1.5)}},
    {"max": 3.0,  "mean": 0.6,  "milestones": {3: ("dialogue", 3.0), 0: ("walked", 1.2)}},
    {"max": 5.0,  "mean": 2.0,  "milestones": {3: ("starter", 5.0), 5: ("dialogue", 3.0), 0: ("walked", 1.5)}},
    {"max": 7.0,  "mean": 3.5,  "milestones": {1: ("route", 7.0), 3: ("starter", 5.0), 5: ("starter", 4.5)}},
    {"max": 9.5,  "mean": 5.5,  "milestones": {4: ("caught", 9.5), 1: ("route", 7.0), 3: ("starter", 5.5)}},
    {"max": 12.0, "mean": 7.5,  "milestones": {2: ("cherrygrove", 12.0), 4: ("caught", 9.5), 1: ("route", 7.5)}},
    {"max": 14.5, "mean": 9.5,  "milestones": {6: ("gym", 14.5), 2: ("cherrygrove", 12.0), 4: ("caught", 10.0)}},
    {"max": 17.0, "mean": 12.0, "milestones": {7: ("badge", 17.0), 6: ("gym", 14.0), 2: ("cherrygrove", 12.5)}},
]

# Mapping milestone → (phase, map_id, x_drift, y_drift, badge_delta, dex_delta)
MILESTONE_PHASE = {
    "walked":      ("overworld", 24, 8, 0),
    "dialogue":    ("dialogue",  24, 0, 0),
    "starter":     ("dialogue",  24, 0, 0),
    "route":       ("overworld", 25, 4, 4),
    "caught":      ("battle",    25, 0, 0),
    "cherrygrove": ("overworld", 26, 6, 0),
    "gym":         ("overworld", 27, 0, 0),
    "badge":       ("battle",    27, 0, 0),
}

PROMPT_FRAGMENTS = {
    "walked":      "Walk away from screen edges.",
    "dialogue":    "If a dialogue arrow appears, press A.",
    "starter":     "Receive the starter Pokémon by advancing all dialogue with A.",
    "route":       "After a new map appears, continue in the same direction to explore further.",
    "caught":      "In wild battles, throw a Pokéball after damaging the wild to <50% HP.",
    "cherrygrove": "In towns, talk to NPCs and stock the bag at the mart.",
    "gym":         "When entering a gym, defeat blocking trainers before challenging the leader.",
    "badge":       "Lead with type advantage; spam the most-effective move until KO.",
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
app.mount("/static", StaticFiles(directory="viewer_ga"), name="static")

@app.get("/")
async def root(): return FileResponse("viewer_ga/index.html")

@app.get("/panel/{idx}.png")
async def panel(idx: int):
    if idx < 0 or idx >= POP_SIZE:
        return Response(status_code=404)
    p = pop[idx]
    if p["milestone_t"] > 0 and p["milestone"] == "caught":
        png = frames.caught("PIDGEY", 30 - p["milestone_t"])
    elif p["milestone_t"] > 0 and p["milestone"] == "evolve":
        png = frames.evolve(40 - p["milestone_t"])
    elif p["phase"] == "title":
        png = frames.title_screen(p["tick"])
    elif p["phase"] == "battle":
        enemy = "FALKNER" if p["map_id"] == 27 else "PIDGEY"
        hp = max(0.05, 1.0 - (p["tick"] % 40) / 50)
        png = frames.battle(enemy, hp, p["tick"])
    elif p["phase"] == "menu":
        png = frames.menu(p["tick"])
    elif p["phase"] == "dialogue":
        png = frames.dialogue("PROF.ELM: Take this Pokémon!", p["tick"])
    else:
        png = frames.overworld(p["x"], p["y"], p["map_id"], p["tick"],
                               hint=p.get("hint", ""))
    return Response(content=png, media_type="image/png")

@app.websocket("/ws")
async def ws(c: WebSocket):
    await c.accept()
    clients.add(c)
    try:
        while True: await c.receive_text()
    except WebSocketDisconnect: pass
    finally: clients.discard(c)

# ── GA loop ──────────────────────────────────────────────────────────────
def state_payload() -> list[dict]:
    return [{
        "id": p["id"], "slot": p["slot"], "gen": p["gen"],
        "fitness": round(p["fitness"], 2), "highlight": p["highlight"],
        "milestone": p["milestone"], "parents": p["parents"],
        "mutated": p["mutated"],
    } for p in pop]

async def emit_pop():
    await emit({"event": "pop_state", "pop": state_payload()})

def fitness_for_gen(gen_idx: int) -> list[float]:
    """Generate fitness values for each slot for this generation, biased so the
    'milestone' slots score high (matching GEN_SCRIPT) and others vary around mean."""
    spec = GEN_SCRIPT[gen_idx]
    vals = [0.0] * POP_SIZE
    milestones = spec["milestones"]
    base_mean = spec["mean"]
    for i in range(POP_SIZE):
        if i in milestones:
            _, fit = milestones[i]
            vals[i] = fit + random.uniform(-0.3, 0.3)
        else:
            # population mean drifts up over generations
            vals[i] = max(-1.0, random.gauss(base_mean, 1.5))
    return vals

async def animate_rollouts(gen_idx: int, duration_s: float = 12.0):
    """For ~12s, animate parallel rollouts in all panels: tick increments,
    positions wander, milestones trigger toward the end with phase changes."""
    spec = GEN_SCRIPT[gen_idx]
    target_fits = fitness_for_gen(gen_idx)

    # mid-rollout: trigger milestone phases for the slots that are scripted to hit them
    milestone_trigger_at = duration_s * 0.55

    steps = int(duration_s * 8)         # 8Hz updates
    for t in range(steps):
        elapsed = t / 8.0
        progress = t / steps
        for i, p in enumerate(pop):
            p["tick"] += 1
            # drift fitness toward target
            p["fitness"] = target_fits[i] * progress + random.uniform(-0.05, 0.05)
            # vary phase for visual richness
            r = random.random()
            if p["phase"] == "title" and elapsed > 0.6:
                p["phase"] = random.choice(["overworld", "menu"])
            if p["phase"] == "overworld":
                if r < 0.55:
                    p["x"] = (p["x"] + random.choice([-1, 1])) % 16
                if r > 0.94 and gen_idx < 3:
                    p["phase"] = "menu"
                if r > 0.92 and gen_idx >= 1 and i in spec["milestones"]:
                    p["phase"] = "dialogue"
            elif p["phase"] == "menu" and gen_idx >= 1 and r > 0.5:
                p["phase"] = "overworld"
            if p["milestone_t"] > 0:
                p["milestone_t"] -= 1
                if p["milestone_t"] == 0:
                    p["milestone"] = None
                    p["phase"] = "overworld"

            # milestone trigger
            if (elapsed >= milestone_trigger_at and i in spec["milestones"]
                    and p["milestone"] is None
                    and not getattr(p, "_triggered", False)):
                kind, _ = spec["milestones"][i]
                phase, map_id, dx, dy = MILESTONE_PHASE[kind]
                p["phase"] = phase
                p["map_id"] = map_id
                p["x"] += dx; p["y"] += dy
                p["milestone"] = kind
                if kind in ("caught", "evolve"):
                    p["milestone_t"] = 30
                p["_triggered"] = True
                await emit({"event": "milestone", "slot": i, "id": p["id"],
                            "kind": kind})

        if t % 4 == 0:
            await emit_pop()
        await asyncio.sleep(1.0 / 8)

    # snap fitness to exact targets
    for i, f in enumerate(target_fits):
        pop[i]["fitness"] = round(f, 2)
        pop[i].pop("_triggered", None)
    await emit_pop()

def select_elites(fits: list[float]) -> list[int]:
    """Top-2 by fitness."""
    ranked = sorted(range(POP_SIZE), key=lambda i: fits[i], reverse=True)
    return ranked[:2]

async def crossover_and_mutate(gen_idx: int, elite_slots: list[int]) -> list[dict]:
    """Build the next-generation population:
       2 elites carry over, 6 children produced via crossover from elite ∪ random,
       4 of the children get mutated."""
    next_pop: list[dict] = []

    # 2 elites carry over (keep their id but advance gen counter)
    for k, e in enumerate(elite_slots):
        new = make_individual(k, gen_idx + 1, parents=[pop[e]["id"]])
        new["highlight"] = "elite-carry"
        new["fitness"] = pop[e]["fitness"]
        next_pop.append(new)

    # 6 children
    for k in range(2, POP_SIZE):
        a, b = random.sample(elite_slots + [random.randint(0, POP_SIZE-1)], 2)
        parents = [pop[a]["id"], pop[b]["id"]]
        mutated = (k % 2 == 0)  # half the children mutate
        child = make_individual(k, gen_idx + 1, parents=parents, mutated=mutated)
        child["highlight"] = "mutated" if mutated else "child"
        next_pop.append(child)
        lineage_edges.append({"gen": gen_idx + 1, "parents": parents,
                              "child": child["id"], "mutated": mutated})
        await emit({"event": "crossover", "gen": gen_idx + 1,
                    "parents": parents, "child": child["id"],
                    "mutated": mutated})
        await asyncio.sleep(0.3)

    return next_pop

async def run():
    """Main GA loop. Drives 8 generations, emits events, ~3 minutes total."""
    await asyncio.sleep(1.0)
    await emit({"event": "boot", "pop_size": POP_SIZE,
                "n_generations": N_GENERATIONS, "pop": state_payload()})

    for g in range(N_GENERATIONS):
        # reset highlights at start of generation
        for p in pop:
            p["highlight"] = None
            p["milestone"] = None
            p["milestone_t"] = 0
            if g > 0:
                p["phase"] = random.choice(["title", "overworld"])
                p["x"], p["y"] = random.randint(0, 6), random.randint(0, 6)
                p["map_id"] = 24
        await emit({"event": "gen_start", "gen": g + 1,
                    "n_generations": N_GENERATIONS, "pop": state_payload()})
        await asyncio.sleep(0.6)

        # Run parallel rollouts for ~12s
        await animate_rollouts(g, duration_s=12.0)

        # Compute fitness & ranking
        fits = [p["fitness"] for p in pop]
        ranking = sorted(range(POP_SIZE), key=lambda i: fits[i], reverse=True)
        elites = ranking[:2]
        for slot in elites: pop[slot]["highlight"] = "elite"
        max_f, mean_f, min_f = max(fits), sum(fits)/len(fits), min(fits)
        fitness_history.append({"gen": g + 1, "max": round(max_f, 2),
                                "mean": round(mean_f, 2), "min": round(min_f, 2),
                                "vals": [round(f, 2) for f in fits]})
        await emit({"event": "gen_complete", "gen": g + 1, "ranking": ranking,
                    "elites": elites, "fits": fits,
                    "max": max_f, "mean": mean_f, "min": min_f,
                    "history": fitness_history})

        # Sort animation pause
        await asyncio.sleep(2.5)

        if g < N_GENERATIONS - 1:
            # crossover + mutation
            await emit({"event": "selection", "elites": elites,
                        "elite_ids": [pop[s]["id"] for s in elites]})
            await asyncio.sleep(1.0)

            next_pop = await crossover_and_mutate(g, elites)

            # reveal next generation
            await asyncio.sleep(0.8)
            for i in range(POP_SIZE):
                pop[i] = next_pop[i]
            await emit({"event": "gen_advance", "next_gen": g + 2,
                        "pop": state_payload()})
            await asyncio.sleep(0.8)

    await asyncio.sleep(2.0)
    await emit({"event": "done", "history": fitness_history,
                "final_best": fitness_history[-1]["max"]})
