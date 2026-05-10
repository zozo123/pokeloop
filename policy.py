"""Action policy: Claude with tool-use. Reads ANTHROPIC_API_KEY from env."""
from __future__ import annotations
import asyncio, base64, os
from anthropic import Anthropic

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError("ANTHROPIC_API_KEY not set. Rotate and export your key.")

CLIENT = Anthropic()
MODEL = os.environ.get("POLICY_MODEL", "claude-sonnet-4-6")

TOOL = {
    "name": "press_button",
    "description": "Press one Game Boy button to advance the agent's policy.",
    "input_schema": {
        "type": "object",
        "properties": {
            "button": {
                "type": "string",
                "enum": ["a", "b", "start", "select", "up", "down", "left", "right"],
            },
            "reason": {"type": "string", "description": "one short sentence"},
        },
        "required": ["button", "reason"],
    },
}

def _act_sync(png: bytes, state: dict, system_prompt: str) -> tuple[str, str]:
    img_b64 = base64.b64encode(png).decode()
    user_text = (
        f"State: badges={state['badges']} party={state['party_count']} "
        f"map={state['map_id']} pokedex={state['pokedex_seen']} "
        f"money={state['money']} pos=({state['x']},{state['y']})."
    )
    msg = CLIENT.messages.create(
        model=MODEL,
        max_tokens=400,
        system=system_prompt,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "press_button"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": user_text},
            ],
        }],
    )
    for block in msg.content:
        if block.type == "tool_use" and block.name == "press_button":
            return block.input["button"], block.input.get("reason", "")
    return "a", "fallback"

async def act(png: bytes, state: dict, system_prompt: str) -> tuple[str, str]:
    return await asyncio.to_thread(_act_sync, png, state, system_prompt)
