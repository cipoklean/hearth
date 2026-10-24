#!/usr/bin/env python
"""Take screenshots of the Hearth web app with Playwright (for review; output is gitignored).

    python scripts/screenshots.py http://127.0.0.1:8000 screenshots/ [--prefix live-] [--chromium /usr/bin/chromium]

Starts from a fresh browser (new care home), loads the sample home and walks every screen.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

LONG = 90_000


async def main(base: str, out: Path, prefix: str, chromium: str | None, only: set[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def path(name: str) -> str:
        return str(out / f"{prefix}{name}.png")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=chromium) if chromium else await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1366, "height": 900}, device_scale_factor=1)
        http = httpx.AsyncClient(timeout=20, follow_redirects=True)  # honours the shell's proxy settings

        async def via_python(route):
            """Some sandboxes need an authenticated proxy Chromium can't use: fetch images here instead."""
            try:
                r = await http.get(route.request.url)
                await route.fulfill(status=r.status_code, body=r.content,
                                    headers={"content-type": r.headers.get("content-type", "image/jpeg")})
            except Exception:
                await route.abort()
        await ctx.route("https://images.qloo.com/**", via_python)
        page = await ctx.new_page()
        page.set_default_timeout(LONG)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        await page.goto(base + "/")
        await page.wait_for_selector(".landing")
        await page.wait_for_timeout(600)
        await page.screenshot(path=path("01-landing"), full_page=True)

        await page.get_by_role("button", name="Explore a sample care home").click()
        await page.wait_for_selector(".shelf .taste-card")
        await page.wait_for_selector(".tour__card")
        await page.wait_for_timeout(900)
        await page.screenshot(path=path("02-demo-home-tour"))
        await page.get_by_role("button", name="Skip tour").click()
        await page.wait_for_timeout(300)
        await page.screenshot(path=path("03-demo-home"), full_page=True)

        await page.locator(".shelf .taste-card").first.click()
        await page.wait_for_selector(".profile-head")
        await page.wait_for_selector(".mini-week")
        await page.wait_for_timeout(500)
        await page.screenshot(path=path("04-resident-profile"), full_page=True)
        rid = page.url.rstrip("/").split("/")[-1]

        await page.goto(f"{base}/r/{rid}/week")
        await page.wait_for_selector(".days .slip")
        whys = page.get_by_role("button", name="Why this?")
        if await whys.count() > 1:
            await whys.nth(1).click()
        await page.wait_for_timeout(500)
        await page.screenshot(path=path("05-weekly-plan"), full_page=True)

        await page.emulate_media(media="print")
        await page.wait_for_timeout(300)
        await page.screenshot(path=path("06-print-view"), full_page=True)
        await page.pdf(path=str(out / f"{prefix}06-print-view.pdf"), format="A4", print_background=True)
        await page.emulate_media(media="screen")

        await page.goto(base + "/group")
        await page.get_by_role("button", name="Find the best").click()
        await page.wait_for_selector(".group-result", timeout=LONG)
        if await page.locator(".excluded summary").count():
            await page.locator(".excluded summary").click()
        await page.wait_for_timeout(500)
        await page.screenshot(path=path("07-group-activity"), full_page=True)

        await page.goto(base + "/check")
        await page.get_by_role("button", name="Fill with an example list").click()
        await page.locator(".check-form .btn--accent").click()
        await page.wait_for_selector(".ledger-results", timeout=LONG)
        ev = page.get_by_role("button", name="Show evidence")
        if await ev.count():
            await ev.first.click()
        await page.wait_for_timeout(500)
        await page.screenshot(path=path("08-taste-check"), full_page=True)

        await page.goto(base + "/privacy")
        await page.wait_for_selector(".remove-list")
        await page.screenshot(path=path("09-privacy"), full_page=True)

        await page.goto(base + "/setup")
        await page.get_by_label("Their name").fill("Iris")
        await page.get_by_role("button", name="Next: favourites").click()
        q = "Ella Fitzgerald" if "mock" not in prefix else "Harbour Lights"
        if "mock" in prefix:
            await page.get_by_role("tab", name="Films").click()
        await page.get_by_placeholder("Search for a").fill(q)
        await page.wait_for_selector(".result", timeout=LONG)
        await page.locator(".result").first.click()
        await page.wait_for_timeout(500)
        await page.screenshot(path=path("10-setup-favourites"), full_page=True)
        await page.get_by_role("button", name="Next: care needs").click()
        await page.get_by_role("button", name="Soft food").click()
        await page.get_by_role("button", name="Hard of hearing").click()
        await page.screenshot(path=path("11-setup-needs"), full_page=True)

        # feedback loop: mark the film night as not enjoyed -> toast + new pick
        await page.goto(f"{base}/r/{rid}/week")
        await page.wait_for_selector(".days .slip")
        await page.get_by_role("button", name="Didn't enjoy").last.click()
        await page.wait_for_selector(".toast", timeout=LONG)
        await page.wait_for_timeout(400)
        await page.screenshot(path=path("15-feedback"))

        storage = await ctx.storage_state()
        m = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                      storage_state=storage, is_mobile=True, has_touch=True)
        await m.route("https://images.qloo.com/**", via_python)
        mp = await m.new_page()
        mp.set_default_timeout(LONG)
        await mp.goto(base + "/")
        await mp.wait_for_selector(".shelf .taste-card")
        await mp.screenshot(path=path("12-mobile-home"), full_page=True)
        await mp.goto(f"{base}/r/{rid}/week")
        await mp.wait_for_selector(".days .slip")
        await mp.wait_for_timeout(400)
        await mp.screenshot(path=path("13-mobile-week"), full_page=True)
        await mp.goto(base + "/welcome")
        await mp.wait_for_selector(".landing")
        await mp.screenshot(path=path("14-mobile-landing"), full_page=True)

        await browser.close()
        await http.aclose()
        if errors:
            print("BROWSER ERRORS:")
            for e in errors:
                print("  ", e[:300])
    print("done", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("out")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--chromium", default=None)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    asyncio.run(main(a.base.rstrip("/"), Path(a.out), a.prefix, a.chromium, set(filter(None, a.only.split(",")))))
