#!/usr/bin/env bash
# Run the browser E2E tests:
#   tests/e2e/web_e2e.py    full flow via the dev proxy (localhost)
#   tests/e2e/relay_e2e.py  deployed-style flow through relay/tts_relay.py
#
# Installs the Playwright dependency group on first use, opens a visible
# Chrome window, and drives the build flow end-to-end in both.
#
#   shell_scripts/e2e.sh              visible browser
#   shell_scripts/e2e.sh --headless   no window (CI)

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

uv sync --group e2e

# Use installed Chrome when present; otherwise fetch Playwright's Chromium.
if [[ "$(uname)" == "Darwin" ]]; then
    have_chrome=false
    [[ -d "/Applications/Google Chrome.app" ]] && have_chrome=true
else
    have_chrome=false
    command -v google-chrome >/dev/null 2>&1 && have_chrome=true
fi
if ! $have_chrome; then
    uv run playwright install chromium
fi

status=0
for suite in web_e2e relay_e2e; do
    echo "== $suite =="
    uv run --group e2e python "tests/e2e/$suite.py" "$@" || status=1
done
exit $status
