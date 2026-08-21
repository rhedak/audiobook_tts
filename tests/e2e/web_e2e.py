#!/usr/bin/env python3
"""End-to-end browser test for the web audiobook builder.

Stages the static site, starts the dev server, opens a (visible) Chromium,
and drives the three-button build flow from the landing page:

  1. "Add chapter"        -- adds the pre-filled sample chapter
  2. "Configure & Build"  -- moves to the configuration screen
  3. "Build audiobook"    -- synthesizes via Microsoft's TTS endpoint

The run passes only if the chapter finishes building, the produced MP3 is
a plausible size, and the page logged no console errors, uncaught
exceptions, or failed requests along the way.

Setup (once):
    uv sync --group e2e
    uv run playwright install chromium     # not needed if Chrome is installed

Run:
    uv run --group e2e python tests/e2e/web_e2e.py
    uv run --group e2e python tests/e2e/web_e2e.py --headless
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
PORT = 8001
BASE_URL = f"http://localhost:{PORT}"

PYODIDE_TIMEOUT_MS = 180_000
VOICES_TIMEOUT_MS = 60_000
BUILD_TIMEOUT_MS = 300_000

# A spoken sample chapter is tens of KB; anything smaller means the audio
# pipeline silently produced nothing.
MIN_MP3_BYTES = 10_000


def log(msg: str) -> None:
    print(msg, flush=True)


def stage_site() -> None:
    """Assemble out/web-stage/ so the server serves the current sources."""
    subprocess.run(["bash", "shell_scripts/web-stage.sh"], cwd=ROOT, check=True)


def server_running() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("localhost", PORT)) == 0


def wait_for_server(deadline_s: float = 15.0) -> None:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(BASE_URL, timeout=1)
            return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"dev server did not come up on port {PORT}")


async def launch_browser(pw, headless: bool):
    """Prefer installed Chrome; fall back to Playwright's bundled Chromium."""
    try:
        return await pw.chromium.launch(headless=headless, channel="chrome")
    except Exception:
        return await pw.chromium.launch(headless=headless)


async def run_flow(headless: bool) -> list[str]:
    """Drive the UI and return a list of problems (empty list = pass)."""
    issues: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []

    server: subprocess.Popen | None = None
    browser = None

    async with async_playwright() as pw:
        try:
            if server_running():
                log(f"  reusing dev server already on port {PORT}")
            else:
                server = subprocess.Popen(["node", "dev-server.mjs"], cwd=ROOT)
                wait_for_server()

            browser = await launch_browser(pw, headless)
            page = await browser.new_page()
            page.on(
                "console",
                lambda msg: console_errors.append(
                    f"{msg.text} ({msg.location.get('url') or 'no-url'})"
                )
                if msg.type == "error"
                else None,
            )
            page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
            page.on(
                "requestfailed",
                lambda req: failed_requests.append(f"{req.url} ({req.failure})"),
            )

            log("  loading page...")
            await page.goto(BASE_URL)
            await page.wait_for_selector("#add-paste-btn")

            log("  waiting for Pyodide + Python bridge...")
            try:
                await page.wait_for_function(
                    "() => typeof bridge === 'undefined' ? false : bridge !== null",
                    timeout=PYODIDE_TIMEOUT_MS,
                )
            except Exception:
                status = await page.locator("#status").text_content()
                issues.append(f"Python bridge never became ready (status: {status!r})")
                return issues

            try:
                await page.wait_for_function(
                    "() => document.getElementById('voice-select').value !== ''",
                    timeout=VOICES_TIMEOUT_MS,
                )
            except Exception:
                issues.append("voice list never loaded")

            # Button 1: add the pre-filled sample chapter.
            log("  click 1/3: add chapter")
            await page.click("#add-paste-btn")
            await page.wait_for_selector("#chapter-items li")

            # Button 2: move to the configure/build screen.
            log("  click 2/3: configure & build")
            await page.click("#to-config-btn")
            await page.wait_for_selector("#editor-section", state="visible")

            # Button 3: synthesize for real.
            log("  click 3/3: build audiobook (synthesizes via Microsoft TTS)...")
            started = time.monotonic()
            await page.click("#build-btn")
            try:
                handle = await page.wait_for_function(
                    """() => {
                        if (document.querySelector('#chapter-status .download-link'))
                            return 'done';
                        if (document.querySelector('#chapter-status .status-icon.error'))
                            return 'error';
                        return false;
                    }""",
                    timeout=BUILD_TIMEOUT_MS,
                )
                outcome = await handle.json_value()
            except Exception:
                progress = await page.locator("#progress-text").text_content()
                status = await page.locator("#status").text_content()
                issues.append(
                    f"build never finished after {BUILD_TIMEOUT_MS // 1000}s "
                    f"(progress: {progress!r}, status: {status!r})"
                )
                return issues
            log(f"  build finished in {time.monotonic() - started:.0f}s")

            if outcome == "error":
                msg = await page.locator("#chapter-status .status-msg").text_content()
                status = await page.locator("#status").text_content()
                issues.append(f"build reported an error: {msg!r} (status: {status!r})")
                return issues

            size = await page.evaluate(
                """async () => {
                    const link = document.querySelector('#chapter-status .download-link');
                    const blob = await fetch(link.href).then((r) => r.blob());
                    return blob.size;
                }"""
            )
            if size < MIN_MP3_BYTES:
                issues.append(f"built MP3 is suspiciously small ({size} bytes)")
            else:
                log(f"  built MP3: {size:,} bytes")

            # The progress line must show full completion once the build is
            # done (regression guard: it used to stick at "4 / 7 paragraphs"
            # because the denominator counted paragraphs, not segments).
            progress = await page.locator("#progress-text").text_content()
            match = re.fullmatch(r"(\d+) / (\d+) segments", progress or "")
            if not match or match.group(1) != match.group(2):
                issues.append(f"progress line not complete at end: {progress!r}")

            # Config export/import round trip.
            async with page.expect_download() as download_info:
                await page.click("#export-config-btn")
            download = await download_info.value
            config_path = await download.path()
            saved = json.loads(Path(config_path).read_text())
            if saved.get("pronunciations", {}).get("Kapitaen") != "kah-pee-tehn":
                issues.append(
                    f"exported config has unexpected pronunciations: "
                    f"{saved.get('pronunciations')!r}"
                )
            else:
                log(f"  config exported: {download.suggested_filename}")
            # Change a pronunciation, then load the file back and confirm
            # the saved value is restored.
            await page.fill(".pronunciation-row .pron-phonetic", "temp")
            await page.set_input_files("#config-file-input", config_path)
            await page.wait_for_function(
                "() => document.getElementById('status').textContent.includes('Config loaded')"
            )
            restored = await page.input_value(".pronunciation-row .pron-phonetic")
            if restored != "kah-pee-tehn":
                issues.append(f"config import did not restore pronunciation: {restored!r}")

        finally:
            if browser is not None:
                await browser.close()
            if server is not None:
                server.terminate()

    for err in console_errors:
        if "favicon" not in err.lower():
            issues.append(f"console error: {err}")
    for req in failed_requests:
        if "favicon" not in req.lower():
            issues.append(f"request failed: {req}")

    return issues


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Browser E2E test for the audiobook builder web UI"
    )
    parser.add_argument(
        "--headless", action="store_true", help="run without a visible browser window"
    )
    args = parser.parse_args()

    log("[1/2] staging site + starting dev server")
    stage_site()

    log("[2/2] driving browser through the build flow")
    issues = await run_flow(args.headless)

    if issues:
        log("\nFAILED:")
        for issue in issues:
            log(f"  - {issue}")
        return 1
    log("\nPASSED: chapter built end-to-end with no errors.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
