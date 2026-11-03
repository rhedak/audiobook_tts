#!/usr/bin/env bash
# Assemble the deployable static site into out/web-stage/.
#
# web/index.html loads app.js, style.css, and edge-tts.js (split out from
# one inline file), then app.js bootstraps Pyodide and fetches "bridge.py"
# and the package files as plain relative paths.  Those files are not
# siblings of index.html in the repository: web/ sits at the top level and
# src/audiobook_tts/ is shared with the Python package.
# This script does the one thing that reconciles the two: copy the pieces
# into one flat directory, which is what both a local test server and the
# GitHub Actions deploy (.github/workflows/pages.yml) serve from.
#
#   shell_scripts/web-stage.sh            stage into out/web-stage/
#   shell_scripts/web-stage.sh --serve    stage, then serve it on http://localhost:8001
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stage="$root/out/web-stage"

rm -rf "$stage"
mkdir -p "$stage"
cp "$root"/web/*.html "$stage/"
cp "$root/web/app.js" "$stage/"
cp "$root/web/style.css" "$stage/"
cp "$root"/web/*.jpg "$stage/"
cp "$root/web/edge-tts.js" "$stage/"
cp "$root/web/bridge.py" "$stage/"
mkdir -p "$stage/src/audiobook_tts"
rsync -a --exclude '__pycache__' --exclude '*.pyc' \
    "$root/src/audiobook_tts/." "$stage/src/audiobook_tts/"

echo "staged at $stage"

if [ "${1-}" = "--serve" ]; then
    cd "$root"
    node dev-server.mjs
fi
