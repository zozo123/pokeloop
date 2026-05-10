"""Procedural 'Pokémon-Crystal-ish' frame generator for the mock movie.

Produces 160x144 PNGs at game-boy resolution. Pure PIL, no ROM. The output
is *plausibly* GB-shaped (4-color palette, pixel grid) but is its own art.
"""
from __future__ import annotations
import io, math
from PIL import Image, ImageDraw, ImageFont
from functools import lru_cache

W, H = 160, 144

# Game Boy Crystal-ish 4-color palette (slightly tinted)
PAL = {
    0: (15, 56, 15),       # darkest
    1: (48, 98, 48),
    2: (139, 172, 15),
    3: (200, 232, 200),    # lightest
}
GO_BLUE = (59, 76, 202)
GO_RED  = (238, 21, 21)
GO_GOLD = (255, 203, 5)

@lru_cache(maxsize=4)
def _font(size: int):
    # Try system mono, fall back to default bitmap
    for path in [
        "/System/Library/Fonts/Monaco.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ]:
        try: return ImageFont.truetype(path, size)
        except Exception: pass
    return ImageFont.load_default()

def _new(bg=PAL[3]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), bg)
    return im, ImageDraw.Draw(im)

def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO(); im.save(buf, "PNG"); return buf.getvalue()

# ── frames ──────────────────────────────────────────────────────────────

def title_screen(tick: int) -> bytes:
    im, d = _new(PAL[0])
    # gold "POKEMON"
    f1 = _font(18)
    d.text((20, 28), "POKéMON", fill=GO_GOLD, font=f1)
    # blue "CRYSTAL"
    f2 = _font(14)
    d.text((38, 52), "CRYSTAL", fill=(120, 200, 255), font=f2)
    # sparkle dots
    for i in range(5):
        x = 16 + i * 28 + (tick // 4) % 8
        y = 70 + (i % 2) * 4
        d.rectangle([x, y, x+1, y+1], fill=GO_GOLD)
    # "PRESS START" flicker
    if (tick // 8) % 2 == 0:
        f3 = _font(10)
        d.text((38, 110), "PRESS START", fill=PAL[3], font=f3)
    return _png(im)

def overworld(x: int, y: int, map_id: int, tick: int, hint: str = "") -> bytes:
    im, d = _new(PAL[2])  # grass
    # tile grid (suggesting GB tiling)
    for gx in range(0, W, 8):
        for gy in range(0, H, 8):
            shade = PAL[2] if (gx // 8 + gy // 8) % 2 == 0 else PAL[1]
            d.rectangle([gx, gy, gx+7, gy+7], fill=shade)
    # path
    d.rectangle([60, 0, 80, H], fill=PAL[3])
    # tree clusters
    for tx, ty in [(20, 30), (110, 50), (130, 100), (10, 90)]:
        d.ellipse([tx, ty, tx+18, ty+22], fill=PAL[0])
        d.ellipse([tx+3, ty+3, tx+15, ty+18], fill=PAL[1])
    # pond
    d.ellipse([95, 16, 130, 36], fill=GO_BLUE)
    # player sprite (4 colors, 12x16)
    px = 60 + (x % 20) - 6
    py = 60 + (y % 20) - 8
    # head
    d.rectangle([px+2, py, px+10, py+6], fill=GO_RED)
    # body
    d.rectangle([px+1, py+6, px+11, py+13], fill=PAL[0])
    d.rectangle([px+3, py+8, px+9, py+11], fill=PAL[3])
    # legs (animate)
    leg_off = (tick // 4) % 2
    d.rectangle([px+2, py+13, px+4, py+15], fill=PAL[0])
    d.rectangle([px+8, py+13, px+10, py+15], fill=PAL[0])
    if leg_off:
        d.rectangle([px+2, py+15, px+4, py+15], fill=PAL[2])
    else:
        d.rectangle([px+8, py+15, px+10, py+15], fill=PAL[2])
    # tiny map label
    d.rectangle([0, 0, 50, 10], fill=PAL[0])
    d.text((2, 0), f"MAP {map_id}", fill=PAL[3], font=_font(8))
    if hint:
        d.rectangle([0, H-12, W, H], fill=PAL[0])
        d.text((2, H-11), hint[:24], fill=PAL[3], font=_font(8))
    return _png(im)

def dialogue(text: str, tick: int) -> bytes:
    bg = overworld(0, 0, 24, tick)
    im = Image.open(io.BytesIO(bg)).convert("RGB")
    d = ImageDraw.Draw(im)
    # text box
    d.rectangle([4, 88, W-4, H-4], fill=PAL[3], outline=PAL[0], width=2)
    f = _font(10)
    visible = text[: max(1, (tick // 2) % (len(text) + 1))]
    # wrap
    words = visible.split(" ")
    line, lines = "", []
    for w in words:
        cand = (line + " " + w).strip()
        if len(cand) > 22:
            lines.append(line); line = w
        else: line = cand
    lines.append(line)
    for i, ln in enumerate(lines[:3]):
        d.text((10, 92 + i * 12), ln, fill=PAL[0], font=f)
    # blinking arrow
    if (tick // 8) % 2 == 0:
        d.polygon([(W-12, H-14), (W-6, H-14), (W-9, H-9)], fill=PAL[0])
    return _png(im)

def battle(enemy: str, hp_pct: float, tick: int) -> bytes:
    im, d = _new(PAL[3])
    # enemy platform (top right)
    d.ellipse([90, 24, 150, 38], fill=PAL[1])
    # enemy sprite (abstract)
    d.ellipse([102, 6, 138, 32], fill=GO_RED)
    d.rectangle([108, 12, 114, 18], fill=PAL[3])
    d.rectangle([126, 12, 132, 18], fill=PAL[3])
    # enemy HP box (top left)
    d.rectangle([4, 6, 76, 28], fill=PAL[3], outline=PAL[0], width=1)
    d.text((6, 7), enemy[:8].upper(), fill=PAL[0], font=_font(8))
    d.text((6, 16), "HP", fill=PAL[0], font=_font(8))
    d.rectangle([18, 18, 70, 22], fill=PAL[3], outline=PAL[0])
    bar_color = (60, 200, 60) if hp_pct > 0.5 else (220, 200, 40) if hp_pct > 0.2 else (220, 60, 60)
    d.rectangle([19, 19, 19 + int(50 * hp_pct), 21], fill=bar_color)
    # player platform (bottom left)
    d.ellipse([10, 80, 70, 96], fill=PAL[1])
    # player back-sprite
    d.rectangle([28, 50, 52, 86], fill=PAL[0])
    d.rectangle([30, 56, 50, 80], fill=GO_BLUE)
    # menu (bottom)
    d.rectangle([0, 100, W, H], fill=PAL[3], outline=PAL[0], width=2)
    d.text((6, 104), "FIGHT", fill=PAL[0], font=_font(10))
    d.text((6, 120), "BAG",   fill=PAL[0], font=_font(10))
    d.text((80, 104), "PKMN", fill=PAL[0], font=_font(10))
    d.text((80, 120), "RUN",  fill=PAL[0], font=_font(10))
    # cursor blink
    if (tick // 6) % 2 == 0:
        d.polygon([(2, 108), (5, 110), (2, 112)], fill=PAL[0])
    return _png(im)

def menu(tick: int) -> bytes:
    bg = overworld(0, 0, 24, tick)
    im = Image.open(io.BytesIO(bg)).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([100, 4, W-4, H-4], fill=PAL[3], outline=PAL[0], width=2)
    items = ["POKéDEX", "POKéMON", "PACK", "MAP", "PLAYER", "SAVE", "EXIT"]
    f = _font(8)
    for i, it in enumerate(items):
        d.text((104, 8 + i * 16), it, fill=PAL[0], font=f)
    if (tick // 6) % 2 == 0:
        d.polygon([(102, 12), (105, 14), (102, 16)], fill=PAL[0])
    return _png(im)

def evolve(tick: int) -> bytes:
    """Pokémon-style evolution flash. tick 0..40."""
    im, d = _new((255, 255, 255))
    pulse = abs(math.sin(tick * 0.4))
    radius = int(20 + 30 * pulse)
    cx, cy = W // 2, H // 2 - 10
    # silhouette
    color = (255, 203, 5) if (tick // 4) % 2 == 0 else (59, 76, 202)
    d.ellipse([cx-radius, cy-radius, cx+radius, cy+radius], fill=color)
    # text
    d.text((30, H-30), "EVOLVING!", fill=PAL[0], font=_font(14))
    return _png(im)

def caught(species: str, tick: int) -> bytes:
    """Pokéball capture animation."""
    im, d = _new(PAL[3])
    cx, cy = W // 2, H // 2
    # ball
    d.ellipse([cx-12, cy-12, cx+12, cy+12], fill=GO_RED)
    d.rectangle([cx-12, cy-2, cx+12, cy+2], fill=PAL[0])
    d.ellipse([cx-12, cy, cx+12, cy+12], fill=PAL[3])
    d.ellipse([cx-12, cy-12, cx+12, cy], fill=GO_RED)
    d.rectangle([cx-12, cy-2, cx+12, cy+2], fill=PAL[0])
    d.ellipse([cx-3, cy-3, cx+3, cy+3], fill=PAL[3])
    d.ellipse([cx-2, cy-2, cx+2, cy+2], fill=PAL[0])
    # wobble dots
    for i in range(3):
        if (tick // 6 + i) % 4 == 0:
            d.ellipse([cx - 22 + i*16, cy-26, cx-18 + i*16, cy-22], fill=GO_GOLD)
    d.text((10, H-20), f"{species} CAUGHT!", fill=PAL[0], font=_font(10))
    return _png(im)
