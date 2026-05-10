"""Real GA orchestrator — drives N actual islo.dev worker sandboxes through G generations.

Reads WORKER_URLS env var (comma-separated public share URLs of N worker sandboxes)
and N_GENERATIONS (default 20). Each generation:
  1. POST /setgen to all workers in parallel
  2. For ~10s: POST /tick on all workers concurrently, /state poll every 250ms
  3. Read final fitnesses, sort, pick top-2 elites
  4. Build 6 children via procedural crossover + mutation (no LLM call needed
     for the fan-out demo — heuristic strings combine over generations)
  5. POST /setpolicy to all non-elite workers with their new prompt
  6. Emit gen_complete + crossover events to the WS viewer

Run: WORKER_URLS=https://...,https://... uvicorn orchestrator_real:app --host 0.0.0.0 --port 8081
"""
from __future__ import annotations
import asyncio, json, os, random, time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ── config ──────────────────────────────────────────────────────────────
WORKER_URLS = [u.strip() for u in os.environ.get("WORKER_URLS", "").split(",") if u.strip()]
POP_SIZE = max(1, len(WORKER_URLS))
N_GENERATIONS = int(os.environ.get("N_GENERATIONS", "20"))
TICK_HZ = 8
GEN_DURATION_S = float(os.environ.get("GEN_DURATION_S", "10"))

# heuristic pool — these are the "good ideas" that propagate via crossover
HEURISTIC_POOL = [
    "press A to advance dialogue",
    "walk away from screen edges",
    "explore unexplored maps",
    "fight with first move",
    "throw a Pokéball",
    "enter gyms",
    "challenge gym leaders",
    "use type advantage",
]

clients: set[WebSocket] = set()
fitness_history: list[dict] = []
lineage_edges: list[dict] = []
pop_state: list[dict] = [{"id": f"G0-{i+1}", "slot": i, "fitness": 0.0,
                          "policy": "", "highlight": None, "milestone": None}
                         for i in range(POP_SIZE)]
gen_idx: int = 0

# ── viewer server ───────────────────────────────────────────────────────
async def emit(evt: dict):
    msg = json.dumps(evt)
    dead = []
    for c in clients:
        try: await c.send_text(msg)
        except Exception: dead.append(c)
    for d in dead: clients.discard(d)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not WORKER_URLS:
        print("[orchestrator_real] WORKER_URLS not set — refusing to run")
        yield
        return
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
    """Proxy each panel to its worker's /screen.png."""
    if idx < 0 or idx >= POP_SIZE:
        return Response(status_code=404)
    url = WORKER_URLS[idx]
    async with httpx.AsyncClient(timeout=5.0) as h:
        try:
            r = await h.get(f"{url.rstrip('/')}/screen.png")
            if r.status_code == 200:
                return Response(content=r.content, media_type="image/png")
        except Exception:
            pass
    return Response(status_code=502)

@app.get("/workers")
async def workers():
    """Public list of worker URLs so the viewer can render clickable per-individual links."""
    return {"urls": WORKER_URLS, "n_generations": N_GENERATIONS}

@app.websocket("/ws")
async def ws(c: WebSocket):
    await c.accept()
    clients.add(c)
    try:
        while True: await c.receive_text()
    except WebSocketDisconnect: pass
    finally: clients.discard(c)

# ── worker calls ────────────────────────────────────────────────────────
async def call(client: httpx.AsyncClient, url: str, path: str,
               method: str = "GET", json_body: dict | None = None):
    full = f"{url.rstrip('/')}{path}"
    try:
        if method == "GET":
            r = await client.get(full)
        else:
            r = await client.request(method, full, json=json_body or {})
        if r.status_code == 200: return r.json()
    except Exception as e:
        return {"error": str(e)}
    return {"error": f"http {r.status_code}"}

async def all_workers(client: httpx.AsyncClient, path: str,
                      method: str = "GET", json_body_for=None):
    """Call path on every worker concurrently. json_body_for(idx) for per-worker bodies."""
    tasks = []
    for i, url in enumerate(WORKER_URLS):
        body = json_body_for(i) if json_body_for else None
        tasks.append(call(client, url, path, method, body))
    return await asyncio.gather(*tasks)

# ── procedural crossover & mutation (no LLM call) ───────────────────────
def crossover(prompt_a: str, prompt_b: str) -> str:
    """Take heuristics from both parents."""
    a_set = set(s.strip() for s in prompt_a.split(".") if s.strip())
    b_set = set(s.strip() for s in prompt_b.split(".") if s.strip())
    combined = list(a_set | b_set)
    random.shuffle(combined)
    return ". ".join(combined) + "."

def mutate(prompt: str) -> str:
    """Add one heuristic from the pool that isn't already present."""
    available = [h for h in HEURISTIC_POOL if h not in prompt]
    if not available: return prompt
    new = random.choice(available)
    return (prompt + " " + new + ".").strip()

# ── GA loop ─────────────────────────────────────────────────────────────
def state_payload() -> list[dict]:
    return [{
        "id": p["id"], "slot": p["slot"], "gen": gen_idx,
        "fitness": round(p["fitness"], 2), "highlight": p["highlight"],
        "milestone": p["milestone"], "parents": p.get("parents", []),
        "mutated": p.get("mutated", False),
    } for p in pop_state]

async def emit_pop():
    await emit({"event": "pop_state", "pop": state_payload()})

async def run():
    global gen_idx
    print(f"[orchestrator_real] {POP_SIZE} workers, {N_GENERATIONS} generations")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Boot: emit boot event, set initial empty policies
        await asyncio.sleep(2.0)
        await emit({"event": "boot", "pop_size": POP_SIZE,
                    "n_generations": N_GENERATIONS, "pop": state_payload(),
                    "worker_urls": WORKER_URLS})

        # Seed: every worker starts with a tiny policy
        for i, p in enumerate(pop_state):
            p["policy"] = "press A to advance dialogue."
        await all_workers(client, "/setpolicy", "POST",
                          json_body_for=lambda i: {"policy": pop_state[i]["policy"], "version": 0})

        for g in range(1, N_GENERATIONS + 1):
            gen_idx = g
            # reset highlights
            for p in pop_state:
                p["highlight"] = None
                p["milestone"] = None
                p["mutated"] = False

            # advance generation on all workers
            await all_workers(client, "/setgen", "POST",
                              json_body_for=lambda i: {"gen": g})

            # mark ids
            for i, p in enumerate(pop_state):
                p["id"] = f"G{g}-{i+1}"
                p["fitness"] = 0.0

            await emit({"event": "gen_start", "gen": g,
                        "n_generations": N_GENERATIONS, "pop": state_payload()})

            # Drive workers for ~GEN_DURATION_S
            steps = int(GEN_DURATION_S * TICK_HZ)
            for t in range(steps):
                results = await all_workers(client, "/tick", "POST")
                for i, r in enumerate(results):
                    if isinstance(r, dict) and "fitness" in r:
                        pop_state[i]["fitness"] = r["fitness"]
                        pop_state[i]["milestone"] = r.get("milestone")
                if t % 2 == 0:
                    await emit_pop()
                await asyncio.sleep(1.0 / TICK_HZ)

            # collect final fitnesses
            fits = [p["fitness"] for p in pop_state]
            ranking = sorted(range(POP_SIZE), key=lambda i: fits[i], reverse=True)
            elite_count = max(1, POP_SIZE // 4)
            elites = ranking[:elite_count]
            for slot in elites: pop_state[slot]["highlight"] = "elite"

            mx, mn = max(fits), min(fits)
            mean = sum(fits) / len(fits)
            fitness_history.append({"gen": g, "max": round(mx, 2),
                                    "mean": round(mean, 2), "min": round(mn, 2),
                                    "vals": [round(f, 2) for f in fits]})
            await emit({"event": "gen_complete", "gen": g, "ranking": ranking,
                        "elites": elites, "fits": fits,
                        "max": mx, "mean": mean, "min": mn,
                        "history": fitness_history})

            await asyncio.sleep(1.5)

            if g < N_GENERATIONS:
                await emit({"event": "selection", "elites": elites,
                            "elite_ids": [pop_state[s]["id"] for s in elites]})
                await asyncio.sleep(0.6)

                # Build next-gen prompts: keep elites verbatim, build children via crossover+mutation
                next_prompts: list[str] = [None] * POP_SIZE
                next_lineage: list[dict] = []
                for k, e in enumerate(elites):
                    next_prompts[e] = pop_state[e]["policy"]  # elite carry-over
                child_slots = [i for i in range(POP_SIZE) if i not in elites]
                for k, slot in enumerate(child_slots):
                    a, b = random.sample(elites + [random.choice(ranking[:max(2, POP_SIZE//2)])], 2)
                    parent_a, parent_b = pop_state[a], pop_state[b]
                    child_prompt = crossover(parent_a["policy"], parent_b["policy"])
                    mutated = (random.random() < 0.5)
                    if mutated:
                        child_prompt = mutate(child_prompt)
                    next_prompts[slot] = child_prompt
                    edge = {"gen": g + 1,
                            "parents": [parent_a["id"], parent_b["id"]],
                            "child": f"G{g+1}-{slot+1}",
                            "mutated": mutated}
                    lineage_edges.append(edge)
                    next_lineage.append(edge)
                    await emit({"event": "crossover", **edge})
                    await asyncio.sleep(0.18)

                # push prompts to workers
                async def push(i):
                    pop_state[i]["policy"] = next_prompts[i]
                    pop_state[i]["mutated"] = any(
                        e["mutated"] and e["child"].endswith(f"-{i+1}") for e in next_lineage
                    )
                await asyncio.gather(*(push(i) for i in range(POP_SIZE)))
                await all_workers(client, "/setpolicy", "POST",
                                  json_body_for=lambda i: {"policy": pop_state[i]["policy"],
                                                            "version": g + 1})

                await emit({"event": "gen_advance", "next_gen": g + 1,
                            "pop": state_payload()})
                await asyncio.sleep(0.6)

        await asyncio.sleep(2.0)
        await emit({"event": "done",
                    "history": fitness_history,
                    "final_best": fitness_history[-1]["max"] if fitness_history else 0})
