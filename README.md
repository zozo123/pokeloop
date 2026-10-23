# Pokeloop: evolving LLM prompts across parallel sandboxes

A demo by Yossi Eliaz of a genetic-algorithm loop over LLM system prompts on parallel
[islo.dev](https://islo.dev) sandboxes, with a Pokémon Crystal-style viewer. The published
results are a scripted playback (`mock_ga.py`); no agent was trained.

[Read the page](https://zozo123.github.io/pokeloop/) · [Watch the scripted movie](docs/assets/movie.mp4) · [Run it](#run-it)

![Scripted playback of the GA viewer: population grid, lineage tree, fitness ranking, gain curve](docs/assets/screenshot.png)

## TL;DR

Pokémon GO can't run honestly from a Linux sandbox in 2026 — Play Integrity hardware
attestation, arm64-only APKs, and a $5M Niantic injunction make the literal version
a ban-on-first-frame botnet.

So this is a demo of the next thing: **a population of 8 LLM agents whose system prompts
evolve via a genetic algorithm across parallel forkable VMs.** The designed fitness signal
is RAM-derived rewards in *Pokémon Crystal* on PyBoy (`reward.py`). The "GO feel" is a
HUD overlay (Pokédex pops, catch animations). The substrate — `islo snapshot save` → `islo use --snapshot` →
`islo logs --type agent` — is borrowed directly from
[meta-harness on islo](https://zozo123.github.io/meta-harness-on-islo-page/).

The snapshot tree **is** the search tree.

## Results (scripted playback)

Scripted playback (`mock_ga.py`): fitness values and milestones are predefined to
demonstrate the viewer; no agent was trained.

| metric (scripted) | G1 | G8 |
|---|---|---|
| best fitness | +1.5 | **+17.0** |
| mean fitness | 0.0 | **+12.0** |
| worst fitness | −1.5 | +6.0 |
| badges earned (best) | 0 | **1 (Falkner)** |
| Pokédex seen (best) | 0 | 8 |

## How it works

```
for gen in 1..8:
    pop = [sandbox_from(snapshot_base, prompt_i) for i in 1..8]   # parallel fork
    fits = parallel_rollout(pop, horizon=H)
    elites = top_k(pop, fits, k=2)                                # tournament
    children = [LLM.crossover(*sample_pair(elites)) for _ in 6]   # textual crossover
    children = [LLM.mutate(c) if random() < .5 else c for c in children]
    pop = elites + children
    snapshot_base = best_individual.snapshot                      # advance the gym
```

In the target design, each individual is a Claude system prompt; each generation runs
in 8 islo sandboxes in parallel; fitness is a RAM-derived dense signal (badges, pokedex,
map progress). Separately, the fan-out was run once on real islo.dev VMs (8 workers forked
from one snapshot, 7 came up) with procedural frames, fitness, and crossover
(`worker.py`, `orchestrator_real.py`), not PyBoy or Claude.

The "evolution" is *textual* — natural-language gradients on prompts, not weight
updates. It's the
[Promptbreeder](https://arxiv.org/abs/2309.16797) /
[TextGrad](https://arxiv.org/abs/2406.07496) /
[Reflexion](https://arxiv.org/abs/2303.11366) family, with parallel forkable
sandboxes underneath instead of a single trajectory.

It's a **multi-agent** system in the population sense: 8 agents per generation,
each with its own policy, never communicating during a rollout — only via the
genetic information channel between generations.

## Repo layout

```
pokeloop/
├── docs/                 ← GitHub Pages site
│   ├── index.html
│   ├── style.css
│   └── assets/
│       ├── movie.mp4
│       ├── movie.gif
│       ├── screenshot.png
│       └── og.svg / og.png  ← share card
├── env_worker.py         ← PyBoy HTTP gym (save/load/screen/state)
├── policy.py             ← Claude tool-use action policy
├── trainer.py            ← textual DPO over preference pairs (DPO version)
├── reward.py             ← RAM-derived dense reward
├── orchestrator.py       ← real-run loop (DPO version)
├── mock_orchestrator.py  ← deterministic mock for the DPO movie
├── mock_ga.py            ← scripted playback for the GA movie
├── worker.py             ← fan-out worker, procedural frames + fitness
├── orchestrator_real.py  ← GA over N worker sandboxes, procedural crossover
├── frames.py             ← procedural Crystal-ish PIL frame generator
├── viewer/               ← single-policy DPO viewer
├── viewer_ga/            ← population/generation GA viewer
├── record.py             ← Playwright recorder
├── policies/v0.txt       ← seed system prompt
├── prompt.md             ← the one-shot islo build prompt
└── scripts/
    ├── make_movie.sh     ← build the DPO movie
    ├── make_ga_movie.sh  ← build the GA movie
    ├── run_local.sh      ← real run on a local Mac
    └── run_islo.sh       ← real run inside an islo sandbox
```

## Run it

### Scripted GA playback (no ROM, no API key)

```bash
git clone https://github.com/zozo123/pokeloop
cd pokeloop
pip install fastapi 'uvicorn[standard]' pillow pydantic websockets
uvicorn mock_ga:app --host 127.0.0.1 --port 8081
open http://127.0.0.1:8081/
```

### DPO-style loop on islo.dev (Claude + PyBoy; bring your own Crystal ROM)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cp /your/legal/copy/crystal.gbc roms/crystal.gbc

islo use pokeloop --image python:3.12-slim --source github://zozo123/pokeloop
islo use pokeloop -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -- bash scripts/run_islo.sh
islo share pokeloop 8080
# → https://<id>.share.islo.dev — your live demo URL
```

### DPO-style loop locally (macOS / Linux)

```bash
bash scripts/run_local.sh
open http://localhost:8080
```

## The build prompt

[`prompt.md`](prompt.md) is a single prompt for an islo.dev coding agent that describes
the whole rig (DPO-shaped variant).

## Inspiration

- **[Meta-harness on islo](https://zozo123.github.io/meta-harness-on-islo-page/)** (Yossi Eliaz, 2026) —
  the `snapshot → use → logs` pattern this work copies. Pokeloop is meta-harness
  applied to RL post-training.
- **Karpathy's agentic autoresearch** — LLMs that propose, run, read, update,
  in sandboxes. The GA loop is one realization.
- **[Claude Plays Pokémon](https://www.twitch.tv/claudeplayspokemon)** &
  **[Gemini Plays Pokémon](https://blog.jcz.dev/the-making-of-gemini-plays-pokemon)** —
  single-agent, no learning. Pokeloop sketches a multi-agent, population-based variant.

## Caveats

- Bring your own ROM. We never ship one.
- Anthropic API calls dominate latency (~1–2 actions/sec).
- The movie is a scripted playback (`mock_ga.py`). `orchestrator.py` is a separate
  DPO-style loop with Claude and PyBoy; `orchestrator_real.py` fans the GA out to real
  sandboxes with procedural fitness. Neither produced the published results.
- "Pokémon GO" in the title is a frame, not a game. We don't connect to Niantic
  servers and we don't want to.

## License

MIT — see [LICENSE](LICENSE).

No Niantic accounts were created or harmed in the making of this demo.
