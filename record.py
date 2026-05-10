"""Record the viewer to MP4 using Playwright. The mock_orchestrator must
already be running on localhost:8080.

Run: python record.py [--seconds 90] [--out movie.webm]
"""
from __future__ import annotations
import argparse, asyncio, os, sys
from pathlib import Path
from playwright.async_api import async_playwright

async def main(seconds: int, out_dir: str, url: str):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=out_dir,
            record_video_size={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        # Wait for WS to connect; either viewer renders body quickly
        await page.wait_for_selector("body")
        await asyncio.sleep(1.5)  # let WS boot event arrive
        # Let the run play
        for i in range(seconds):
            await asyncio.sleep(1)
            if i % 10 == 0:
                print(f"[record] {i}/{seconds}s", file=sys.stderr)
        await ctx.close()
        await browser.close()
    # Find the produced webm
    vids = sorted(Path(out_dir).glob("*.webm"))
    if vids:
        print(vids[-1])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=90)
    ap.add_argument("--out-dir", default="movie")
    ap.add_argument("--url", default="http://localhost:8080/")
    a = ap.parse_args()
    asyncio.run(main(a.seconds, a.out_dir, a.url))
