#!/usr/bin/env node
/**
 * Manual E2E test for the edge-tts WebSocket synthesis.
 *
 * Tests the same flow used in the browser GUI: token generation,
 * WebSocket connection, SSML synthesis, and MP3 audio reception.
 *
 * Run with:  node tests/manual/test_edge_tts_e2e.mjs
 *
 * This test calls Microsoft's live TTS endpoint and is excluded
 * from the regular CI pipeline.
 */

import { createHash } from "node:crypto";
import { writeFile, mkdir } from "node:fs/promises";

// --- Constants (mirrored from web/edge-tts.js) ---

const WSS_URL = "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1";
const TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
const CHROMIUM_FULL_VERSION = "143.0.3650.75";
const SEC_MS_GEC_VERSION = `1-${CHROMIUM_FULL_VERSION}`;
const WIN_EPOCH = 11644473600;

// --- DRM token generation ---

function generateSecMsGec() {
  const nowSec = Math.floor(Date.now() / 1000);
  let ticks = nowSec + WIN_EPOCH;
  ticks -= ticks % 300;
  const windowsTicks = ticks * 10_000_000;

  const strToHash = `${windowsTicks}${TRUSTED_CLIENT_TOKEN}`;
  return createHash("sha256").update(strToHash, "ascii").digest("hex").toUpperCase();
}

function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// --- SSML ---

function longVoiceName(shortName) {
  const match = shortName.match(/^([a-zA-Z]{2,})-([A-Za-z]{2,})-(.+Neural)$/);
  if (!match) return shortName;
  const [, lang, region, name] = match;
  return `Microsoft Server Speech Text to Speech Voice (${lang}-${region}, ${name})`;
}

function buildSSML(text, voice) {
  const voiceTag = longVoiceName(voice);
  const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'><voice name='${voiceTag}'><prosody pitch='+0Hz' rate='+0%' volume='+0%'>${escaped}</prosody></voice></speak>`;
}

// --- Binary message parsing ---

function indexOf(arr, subarr) {
  for (let i = 0; i <= arr.length - subarr.length; i++) {
    let match = true;
    for (let j = 0; j < subarr.length; j++) {
      if (arr[i + j] !== subarr[j]) {
        match = false;
        break;
      }
    }
    if (match) return i;
  }
  return -1;
}

// --- Synthesis ---

function synthesize(text, voice) {
  return new Promise((resolve, reject) => {
    const secMsGec = generateSecMsGec();
    const connectionId = generateUUID();
    const url = `${WSS_URL}?Ocp-Apim-Subscription-Key=${TRUSTED_CLIENT_TOKEN}&Sec-MS-GEC=${secMsGec}&Sec-MS-GEC-Version=${SEC_MS_GEC_VERSION}&ConnectionId=${connectionId}`;

    // Dynamic import so the script fails gracefully if ws is not installed
    import("ws").then(({ default: WebSocket }) => {
      const ws = new WebSocket(url);
      const audioChunks = [];
      let receivedTurnEnd = false;

      ws.on("open", () => {
        console.log("  WebSocket connected");

        // Send config
        const timestamp = new Date().toUTCString().replace("GMT", "GMT+0000 (Coordinated Universal Time)");
        const configMsg = [
          `X-Timestamp:${timestamp}`,
          "Content-Type:application/json; charset=utf-8",
          "Path:speech.config",
          "",
          "",
        ].join("\r\n") + '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}';

        ws.send(configMsg);

        // Send SSML
        const reqId = generateUUID();
        const ssml = buildSSML(text, voice);
        const ssmlMsg = [
          `X-RequestId:${reqId}`,
          "Content-Type:application/ssml+xml",
          `X-Timestamp:${timestamp}Z`,
          "Path:ssml",
          "",
          "",
        ].join("\r\n") + ssml;

        ws.send(ssmlMsg);
        console.log("  SSML sent");
      });

      ws.on("message", (data, isBinary) => {
        if (isBinary) {
          const needle = Buffer.from("Path:audio\r\n");
          const buf = Buffer.isBuffer(data) ? data : Buffer.from(data);
          const idx = buf.indexOf(needle);
          if (idx !== -1) {
            const audioChunk = buf.slice(idx + needle.length);
            audioChunks.push(audioChunk);
          }
        } else {
          const msg = data.toString();
          if (msg.includes("Path:turn.end")) {
            receivedTurnEnd = true;
            ws.close();
          }
        }
      });

      ws.on("error", (err) => {
        reject(new Error(`WebSocket error: ${err.message}`));
      });

      ws.on("close", () => {
        if (audioChunks.length === 0 && !receivedTurnEnd) {
          reject(new Error("Connection closed before receiving audio"));
          return;
        }
        const totalLength = audioChunks.reduce((sum, chunk) => sum + chunk.length, 0);
        const result = Buffer.concat(audioChunks, totalLength);
        resolve(result);
      });

      // Timeout
      setTimeout(() => {
        ws.close();
        reject(new Error("Synthesis timed out after 30s"));
      }, 30000);
    });
  });
}

// --- Main ---

const TEST_TEXT = `The old lighthouse stood at the edge of the world, its beam cutting through the fog like a golden sword.

We set sail at dawn. The charts say there's nothing beyond the reef, but I've never trusted charts.

And I've never trusted captains who ignore them. What exactly are you expecting to find out there?

Something no map has drawn yet. That's the only thing worth sailing for.`;

const VOICES = [
  "en-US-GuyNeural",       // Kapitaen
  "en-US-JennyNeural",     // Mira
  "en-US-EmmaMultilingualNeural", // narrator default
];

async function main() {
  console.log("Edge TTS E2E test");
  console.log("=================\n");

  let passed = 0;
  let failed = 0;

  for (const voice of VOICES) {
    process.stdout.write(`Testing ${voice}... `);
    try {
      const audio = await synthesize(TEST_TEXT, voice);
      const sizeKB = (audio.length / 1024).toFixed(1);

      if (audio.length < 1000) {
        console.log(`FAIL (too small: ${audio.length} bytes)`);
        failed++;
        continue;
      }

      // Verify it's valid MP3 (starts with ID3 or frame sync)
      const header = audio.slice(0, 3);
      const isID3 = header[0] === 0x49 && header[1] === 0x44 && header[2] === 0x33; // "ID3"
      const isFrameSync = (header[0] === 0xff && (header[1] & 0xe0) === 0xe0);
      if (!isID3 && !isFrameSync) {
        console.log(`FAIL (not valid MP3, header: ${header.toString("hex")})`);
        failed++;
        continue;
      }

      // Save to out/ for manual inspection
      const safeName = voice.replace(/[^a-zA-Z0-9]/g, "_");
      const outPath = `out/manual_test_${safeName}.mp3`;
      await mkdir("out", { recursive: true });
      await writeFile(outPath, audio);

      console.log(`OK (${sizeKB} KB, saved to ${outPath})`);
      passed++;
    } catch (err) {
      console.log(`FAIL (${err.message})`);
      failed++;
    }
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
