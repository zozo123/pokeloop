"""RAM-derived dense reward. Cheap, no learned RM."""
from dataclasses import dataclass

@dataclass
class Reward:
    total: float
    components: dict

W = {
    "badges":  3.0,
    "pokedex": 0.5,
    "money":   0.001,
    "new_map": 1.0,
    "party":   0.5,
    "step":   -0.001,
}

def reward(prev: dict, curr: dict, visited_maps: set) -> Reward:
    c = {
        "badges":  W["badges"]  * max(0, curr["badges"] - prev["badges"]),
        "pokedex": W["pokedex"] * max(0, curr["pokedex_seen"] - prev["pokedex_seen"]),
        "money":   W["money"]   * max(0, curr["money"] - prev["money"]),
        "new_map": W["new_map"] if curr["map_id"] not in visited_maps else 0.0,
        "party":   W["party"]   * max(0, curr["party_count"] - prev["party_count"]),
        "step":    W["step"],
    }
    visited_maps.add(curr["map_id"])
    return Reward(sum(c.values()), c)
