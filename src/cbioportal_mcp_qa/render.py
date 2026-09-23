"""Open cBioPortal links in headless Chromium and record what the page shows, for the judge and the report."""

import asyncio
import hashlib
import time
from dataclasses import asdict, dataclass
from pathlib import Path

NAV_END = "Login\n"
TEXT_CHARS = 1500


@dataclass
class Render:
    url: str
    ok: bool
    text: str
    error: str | None
    screenshot: str | None
    seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


def screenshot_name(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12] + ".jpg"


def visible_text(body: str) -> str:
    """Page text after the site's top navigation bar, truncated."""
    return body.split(NAV_END, 1)[-1].strip()[:TEXT_CHARS]


async def _render_one(browser, url: str, shots_dir: Path, rel_dir: str) -> Render:
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    page = await browser.new_page(viewport={"width": 1400, "height": 900})
    started = time.monotonic()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=30_000)
        except PlaywrightTimeout:
            pass
        text = visible_text(await page.inner_text("body"))
        name = screenshot_name(url)
        await page.screenshot(path=shots_dir / name, type="jpeg", quality=60)
        return Render(url, True, text, None, f"{rel_dir}/{name}", time.monotonic() - started)
    except Exception as exc:  # noqa: BLE001 - a page that fails to load is a result, not a crash
        return Render(url, False, "", f"{type(exc).__name__}: {exc}"[:300], None, time.monotonic() - started)
    finally:
        await page.close()


async def render_links(
    urls: list[str], shots_dir: Path, rel_dir: str, executable: str | None = None, concurrency: int = 3
) -> dict[str, Render]:
    from playwright.async_api import async_playwright

    shots_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=executable, args=["--no-sandbox"])

        async def one(url: str) -> Render:
            async with sem:
                return await _render_one(browser, url, shots_dir, rel_dir)

        try:
            results = await asyncio.gather(*(one(u) for u in urls))
        finally:
            await browser.close()
    return {r.url: r for r in results}
