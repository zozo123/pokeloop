"""Textual DPO: rewrite the policy's system prompt from preference pairs.

Mechanism: feed (preferred trajectory, rejected trajectory) pairs to a
'trainer' Claude call and ask it to rewrite the action policy's system
prompt to bias toward winning behavior. The new prompt becomes v(N+1).

This is in-context policy improvement (Reflexion / TextGrad / Promptbreeder
family) using DPO-style preference data. It's not weight-update RL; it
*is* a real post-training loop driven by RL-shaped signals.
"""
from __future__ import annotations
import asyncio, os
from anthropic import Anthropic

CLIENT = Anthropic()
MODEL = os.environ.get("TRAINER_MODEL", "claude-sonnet-4-6")

TRAINER_SYS = """You improve a Pokémon-playing agent's system prompt using
preference data from forked rollouts.

For each case you'll see:
- the game context at a decision point,
- a PREFERRED action sequence (won the rollout tournament, score shown),
- a REJECTED action sequence (lost the rollout tournament, score shown).

Rewrite the agent's system prompt to bias toward preferred-style behavior.

HARD RULES:
- Output ONLY the new system prompt. No preamble, no markdown fences.
- Keep total length under 1500 characters.
- Preserve any existing rule that wasn't contradicted by the evidence.
- Add at most 2-3 new concrete heuristics per revision.
- Never invent game knowledge that isn't supported by the evidence.
- Phrase rules as imperatives ("If X, then Y.")."""

def _dpo_sync(current_prompt: str, pairs: list[dict]) -> str:
    body = "\n\n".join(
        f"CASE {i+1}\n"
        f"context: {p['context']}\n"
        f"PREFERRED (score {p['pref_score']:+.2f}): {p['preferred']}\n"
        f"REJECTED  (score {p['rej_score']:+.2f}): {p['rejected']}"
        for i, p in enumerate(pairs)
    )
    user = (
        f"CURRENT PROMPT:\n---\n{current_prompt}\n---\n\n"
        f"EVIDENCE ({len(pairs)} cases):\n{body}\n\n"
        "Rewrite the prompt now."
    )
    msg = CLIENT.messages.create(
        model=MODEL, max_tokens=2000, system=TRAINER_SYS,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()

async def textual_dpo(current_prompt: str, pairs: list[dict]) -> str:
    return await asyncio.to_thread(_dpo_sync, current_prompt, pairs)
