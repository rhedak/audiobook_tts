# Audiobook TTS Builder

Turn Markdown chapter files into multi-chapter audiobooks using Microsoft's
Neural TTS voices, entirely in your browser. No account, no install.

**Live page:** https://rhedak.github.io/audiobook_tts/ (after first deploy)

## How it works

The page is a static site (GitHub Pages) that runs Python via Pyodide for
chapter parsing and a JavaScript reimplementation of the Edge TTS protocol
for audio. Microsoft rejects speech WebSocket handshakes from arbitrary web
origins (they expect the Edge read-aloud extension), so requests are
forwarded through a small relay that presents the expected origin:

```
browser ──ws──> relay ──wss (spoofed Origin)──> api.msedgeservices.com
```

Two relay options exist; pick per your comfort:

| | Hosted relay (default) | Your own relay |
|---|---|---|
| Setup | none | run one Python command |
| Where chapter text flows | your browser -> author's Worker -> Microsoft | your browser -> localhost -> Microsoft |
| Trust required | author's server sees text in transit | nothing leaves your machine |

The hosted relay is a ~100-line Cloudflare Worker (`worker/worker.js`). It
forwards bytes verbatim and keeps no logs or storage, but it *is* another
machine on the path. If you would rather your chapters never leave your
computer, run the local relay instead — it is standard-library-only Python,
no dependencies:

```sh
python3 relay/tts_relay.py        # listens on ws://localhost:8765/tts-ws
```

Then open the page, scroll to **Speech relay**, enter
`ws://localhost:8765/tts-ws`, click **Use my relay**, and build as usual.
The setting is remembered in `localStorage`; **Use hosted** switches back.
The page health-checks the relay URL so you can see whether it is running.

Note: the local relay only helps when the page itself is reachable from the
same machine (the live GitHub Pages site, or a locally served copy). The
relay never sees your text unless you point the page at it.

## Building an audiobook

1. Add text chapter files (`.md`, `.txt`, anything readable; one file per
   chapter, `# Heading` = title).
2. Pick a voice, or enable multi-voice and assign voices per speaker
   (dialogue lines like `"Hello," said X` are attributed automatically).
3. Add pronunciations for names the engine mangles (e.g. `Kapitaen` ->
   `kah-pee-tehn`).
4. Build. Each chapter becomes one MP3; download individually or all as zip.

Config (voice choices + pronunciations) can be saved to / loaded from JSON.

## Development

Requires `ffmpeg` on your PATH (MP3 export shells out to it; on macOS
`brew install ffmpeg`).

```sh
uv sync                          # library deps
shell_scripts/local-serve.sh     # stage web UI + start dev proxy (:8001)
                                 #   --fg foreground, --stop to stop
uv run pytest -q                 # unit tests (library)
shell_scripts/e2e.sh             # browser E2E (playwright, visible)
```

The dev proxy (`dev-server.mjs`) does the same origin-spoofing as the
relays above, on `/tts-ws`, so the page works identically in development.

### E2E suites

- `tests/e2e/web_e2e.py` — full flow against the dev server (localhost).
- `tests/e2e/relay_e2e.py` — simulates the deployed case: serves the staged
  site under a fake foreign origin (`pages.example.test`) with no dev
  proxy, points the page at the real local relay, and builds audio through
  it. This is the path production users take.

## Deploying your own hosted relay

The default page uses the author's Worker. To run your own:

```sh
npm install -g wrangler
wrangler login
cd worker && wrangler deploy
```

Optionally restrict who may use it by setting `ALLOWED_ORIGINS` in
`wrangler.toml` (comma-separated origins, e.g. your Pages URL). Then set
`HOSTED_RELAY_URL` at the top of `web/edge-tts.js` to your worker's
`wss://...workers.dev/tts-ws` address and redeploy the site.

Honest caveat: `ALLOWED_ORIGINS` stops other *web pages* from embedding
your relay; it cannot stop someone deliberately forging headers outside a
browser. Treat any public relay as untrusted capacity, not a private API.

## Repository layout

```
src/audiobook_tts/    Python library (parsing, speaker attribution, synthesis)
web/                  Browser app (Pyodide bridge, edge-tts.js, UI)
relay/tts_relay.py    BYO local relay (stdlib only)
worker/               Hosted relay (Cloudflare Worker)
dev-server.mjs        Dev proxy used by shell_scripts/local-serve.sh
shell_scripts/        staging / serving / e2e helpers
tests/                unit tests + e2e/
```
