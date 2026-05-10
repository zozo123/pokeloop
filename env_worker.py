"""PyBoy HTTP env-worker. Save-states are the snapshot primitive.

Run: uvicorn env_worker:app --host 0.0.0.0 --port 8090
Env: POKE_ROM=/path/to/pokemon_crystal.gbc
"""
from __future__ import annotations
import io, os, uuid
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
from pyboy import PyBoy

ROM = os.environ.get("POKE_ROM", "roms/crystal.gbc")
SAVES: dict[str, bytes] = {}

pyboy = PyBoy(ROM, window="null", sound_emulated=False)
pyboy.set_emulation_speed(0)

BUTTONS = {"a", "b", "start", "select", "up", "down", "left", "right"}

# Pokémon Crystal RAM map (USA v1.0). Public, well-documented.
RAM = {
    "map_id":      0xDCB5,
    "party_count": 0xDCD7,
    "money_bcd":   (0xD84E, 3),
    "badges_jht":  0xD857,
    "badges_knt":  0xD858,
    "pokedex":     (0xDEB9, 32),
    "player_x":    0xDCB8,
    "player_y":    0xDCB7,
}

def _bcd3(addr: int) -> int:
    bs = [pyboy.memory[addr + i] for i in range(3)]
    return sum(((b >> 4) * 10 + (b & 0xF)) * 10 ** (2 * (2 - i)) for i, b in enumerate(bs))

def _popcount(addr: int, n: int) -> int:
    return sum(bin(pyboy.memory[addr + i]).count("1") for i in range(n))

def read_state() -> dict:
    return {
        "map_id":       pyboy.memory[RAM["map_id"]],
        "party_count":  pyboy.memory[RAM["party_count"]],
        "money":        _bcd3(RAM["money_bcd"][0]),
        "badges":       _popcount(RAM["badges_jht"], 1) + _popcount(RAM["badges_knt"], 1),
        "pokedex_seen": _popcount(*RAM["pokedex"]),
        "x":            pyboy.memory[RAM["player_x"]],
        "y":            pyboy.memory[RAM["player_y"]],
    }

class StepReq(BaseModel):
    button: str
    hold_ticks: int = 8
    wait_ticks: int = 16

class LoadReq(BaseModel):
    id: str

app = FastAPI(title="pokeloop env-worker")

@app.post("/step")
def step(req: StepReq):
    b = req.button.lower()
    if b not in BUTTONS:
        return {"error": f"unknown button {b}"}
    pyboy.button(b, req.hold_ticks)
    for _ in range(req.hold_ticks + req.wait_ticks):
        pyboy.tick()
    return {"state": read_state()}

@app.post("/tick")
def tick(n: int = 60):
    for _ in range(n):
        pyboy.tick()
    return {"state": read_state()}

@app.get("/screen.png")
def screen():
    buf = io.BytesIO()
    pyboy.screen.image.save(buf, "PNG")
    return Response(content=buf.getvalue(), media_type="image/png")

@app.get("/state")
def state():
    return read_state()

@app.post("/save")
def save():
    sid = uuid.uuid4().hex
    buf = io.BytesIO()
    pyboy.save_state(buf)
    SAVES[sid] = buf.getvalue()
    return {"id": sid, "size": len(SAVES[sid])}

@app.post("/load")
def load(req: LoadReq):
    if req.id not in SAVES:
        return {"error": "unknown id"}
    pyboy.load_state(io.BytesIO(SAVES[req.id]))
    return {"ok": True, "state": read_state()}
