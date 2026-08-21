#!/usr/bin/env python3
"""End-to-end test of the BYO-relay path, simulating the deployed page.

The production page lives on github.io with no dev proxy, so its only way
to reach Microsoft is a relay. This suite reproduces that situation
locally:

  * the staged site is served by a plain static file server (no /tts-ws
    proxy) under a fake foreign origin, pages.example.test;
  * Chrome maps that name to 127.0.0.1 and treats the origin as secure so
    crypto.subtle works (on real HTTPS this is automatic);
  * relay/tts_relay.py runs on ws://localhost:8765/tts-ws;
  * the page is pointed at the relay through the Speech relay UI.

The run passes only if the relay health check succeeds from the page and a
chapter builds end-to-end through the relay, with no console errors or
failed requests.

Setup (once):
    uv sync --group e2e
    uv run playwright install chromium     # not needed if Chrome is installed

Run:
    uv run --group e2e python tests/e2e/relay_e2e.py
    uv run --group e2e python tests/e2e/relay_e2e.py --headless
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
SITE_PORT = 8001
FAKE_HOST = "pages.example.test"
BASE_URL = f"http://{FAKE_HOST}:{SITE_PORT}"
RELAY_PORT = 8765
RELAY_URL = f"ws://localhost:{RELAY_PORT}/tts-ws"

PYODIDE_TIMEOUT_MS = 180_000
VOICES_TIMEOUT_MS = 60_000
BUILD_TIMEOUT_MS = 300_000

MIN_MP3_BYTES = 10_000


def log(msg: str) -> None:
    print(msg, flush=True)


def stage_site() -> None:
    subprocess.run(["bash", "shell_scripts/web-stage.sh"], cwd=ROOT, check=True)


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("localhost", port)) == 0


def wait_for(url: str, deadline_s: float = 15.0) -> None:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"{url} never came up")


async def launch_browser(pw, headless: bool):
    args = [
        f"--host-resolver-rules=MAP {FAKE_HOST} 127.0.0.1",
        f"--unsafely-treat-insecure-origin-as-secure={BASE_URL}",
    ]
    try:
        return await pw.chromium.launch(headless=headless, channel="chrome", args=args)
    except Exception:
        return await pw.chromium.launch(headless=headless, args=args)


async def run_flow(headless: bool) -> list[str]:
    issues: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []

    site_server: subprocess.Popen | None = None
    relay_proc: subprocess.Popen | None = None
    browser = None

    async with async_playwright() as pw:
        try:
            if not port_open(RELAY_PORT):
                relay_proc = subprocess.Popen(
                    [sys.executable, "relay/tts_relay.py"], cwd=ROOT
                )
                wait_for(f"http://localhost:{RELAY_PORT}/health")
                log("  started tts_relay.py on :8765")
            else:
                log("  reusing relay already on :8765")

            if port_open(SITE_PORT):
                log(f"  reusing server already on port {SITE_PORT}")
            else:
                site_server = subprocess.Popen(
                    [sys.executable, "-m", "http.server", str(SITE_PORT)],
                    cwd=ROOT / "out" / "web-stage",
                    stdout=subprocess.DEVNULL,
                )
                # The fake hostname only resolves inside Chrome; probe the
                # loopback address directly.
                wait_for(f"http://127.0.0.1:{SITE_PORT}")

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

            log(f"  loading page from {BASE_URL} (foreign origin)...")
            await page.goto(BASE_URL)
            await page.wait_for_selector("#add-paste-btn")

            # Confirm we really are off localhost, i.e. edge-tts.js will not
            # take the dev-proxy branch.
            hostname = await page.evaluate("location.hostname")
            if hostname != FAKE_HOST:
                issues.append(f"expected to run under {FAKE_HOST}, got {hostname!r}")
                return issues

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

            # Add a chapter and move to the config screen where the relay
            # fieldset lives.
            await page.click("#add-paste-btn")
            await page.wait_for_selector("#chapter-items li")
            await page.click("#to-config-btn")
            await page.wait_for_selector("#editor-section", state="visible")

            # Point the page at the local relay via the UI.
            log("  configuring speech relay via UI")
            await page.fill("#relay-url-input", RELAY_URL)
            await page.click("#relay-save-btn")
            try:
                await page.wait_for_function(
                    """() =>
                        document.getElementById('relay-status').textContent
                            .includes('Relay reachable')""",
                    timeout=10_000,
                )
            except Exception:
                status = await page.locator("#relay-status").text_content()
                issues.append(f"relay health check did not pass (status: {status!r})")
                return issues
            saved = await page.evaluate("localStorage.getItem('tts-relay-url')")
            if saved != RELAY_URL:
                issues.append(f"relay URL not persisted: {saved!r}")

            log("  building audiobook through the relay...")
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
                issues.append(f"build reported an error: {msg!r}")
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

        finally:
            if browser is not None:
                await browser.close()
            if site_server is not None:
                site_server.terminate()
            if relay_proc is not None:
                relay_proc.terminate()

    for err in console_errors:
        if "favicon" not in err.lower():
            issues.append(f"console error: {err}")
    for req in failed_requests:
        if "favicon" not in req.lower():
            issues.append(f"request failed: {req}")

    return issues


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E test of the BYO local relay path (simulated foreign origin)"
    )
    parser.add_argument(
        "--headless", action="store_true", help="run without a visible browser window"
    )
    args = parser.parse_args()

    log("[1/2] staging site")
    stage_site()

    log("[2/2] driving browser through the relay build flow")
    issues = await run_flow(args.headless)

    if issues:
        log("\nFAILED:")
        for issue in issues:
            log(f"  - {issue}")
        return 1
    log("\nPASSED: chapter built through the local relay with no errors.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
