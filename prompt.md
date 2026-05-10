# The single-prompt build (Captain Claw shape)

Paste this into your islo.dev coding agent on a fresh sandbox:

---

Build a Pokémon RL post-training rig on this islo.dev sandbox, end-to-end.

ENV (port 8090):
- PyBoy headless running `roms/crystal.gbc` (I'll mount the ROM).
- HTTP env-worker exposing `/step {button}`, `/screen.png`, `/state`,
  `/save → snapshot_id`, `/load {id}`, `/tick {n}`.
- Save-states are the snapshot primitive — opaque ids, kept in process memory.

POLICY:
- Claude Sonnet 4.6 via the Anthropic SDK, tool-use action: `press_button(button, reason)`.
- Versioned system prompts at `policies/v{0,1,…}.txt`. Seed v0 with "you are
  playing Pokémon Crystal, advance dialogues with A, walk away from screen edges,
  fight with first move".

LOOP (orchestrator on port 8080):
- Roll out from a fixed root save state.
- At every wild encounter or map change, snapshot and fan into K=8 in-process
  forks, each starting with a different button, each rolling forward H=20 steps.
- Score with RAM-derived reward: badges (3.0), pokedex_seen (0.5), new_map (1.0),
  party_count (0.5), money (0.001), step (-0.001).
- Store (preferred, rejected) pairs from each tournament's best/worst.
- Every 10 decision points, run textual DPO: feed the last 10 pairs to a
  trainer Claude call asking it to rewrite the system prompt under fixed rules
  (output prompt only, ≤1500 chars, preserve uncontradicted rules, add ≤3 new
  imperatives). New prompt = v(N+1).

VIEWER (same port 8080):
- Center: live emulator framebuffer (PNG poll @ 4Hz from the env).
- Sidebar: agent thoughts stream (each press_button reason).
- Tree pane: fork tree drawn as SVG, winners green, losers red, spine yellow.
- Bottom: cumulative-reward curve with vertical dashed lines + labels at each
  policy-version bump.
- On `policy_bump`, fire a Pokémon-style evolution overlay (white flash +
  silhouette pulse + "Policy is evolving!" text).

SNAPSHOTTING (cross-VM, the platform-native flex):
- At each badge gained, call `islo snapshot save` to checkpoint the whole VM.
- Expose a `/branch` endpoint that spawns a sibling sandbox from a saved
  snapshot via the islo SDK and shares its viewer URL — let viewers click
  any chapter and jump into a parallel-universe rerun.

ACCEPTANCE:
- I open the public URL (`islo share viewer 8080`) and within 30 minutes I see:
  v0 → v1 → v2 → v3 → v4, four DPO-driven prompt rewrites, with the
  cumulative-reward curve strictly trending up across versions and at least
  one badge earned.
- The Pokémon evolution animation fires on every version bump.
- Each chapter snapshot is reachable as its own clickable sibling sandbox.
