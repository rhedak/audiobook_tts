/**
 * edge-tts.js — Reimplementation of the Microsoft Edge TTS WebSocket protocol.
 *
 * Connects directly to Microsoft's speech synthesis service, same as the
 * Python edge-tts library. Produces raw MP3 audio chunks that can be
 * concatenated into a complete file.
 *
 * No dependencies. Uses the browser's native WebSocket and Web Crypto API.
 */

const EdgeTTS = (() => {
  // In dev, the Node.js proxy relays /tts-ws to Microsoft's endpoint.
  // In production (GitHub Pages), direct connection to Microsoft works
  // because the page is served over HTTPS from a real domain.
  const isLocal = location.hostname === "localhost" || location.hostname === "127.0.0.1";
  const wsProto = isLocal ? "ws" : "wss";
  const WSS_BASE = isLocal
    ? `${wsProto}://${location.host}/tts-ws`
    : "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1";
  const TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
  const CHROMIUM_FULL_VERSION = "143.0.3650.75";
  const SEC_MS_GEC_VERSION = `1-${CHROMIUM_FULL_VERSION}`;
  const WIN_EPOCH = 11644473600;
  const MAX_CHUNK_BYTES = 4096;

  // --- DRM: Sec-MS-GEC token generation ---

  async function generateSecMsGec(skewSeconds = 0) {
    const nowSec = Math.floor(Date.now() / 1000) + skewSeconds;
    let ticks = nowSec + WIN_EPOCH;
    ticks -= ticks % 300;
    const windowsTicks = ticks * 10_000_000;

    const strToHash = `${windowsTicks}${TRUSTED_CLIENT_TOKEN}`;
    const encoder = new TextEncoder();
    const data = encoder.encode(strToHash);
    const hashBuffer = await crypto.subtle.digest("SHA-256", data);
    const hashArray = new Uint8Array(hashBuffer);
    return Array.from(hashArray).map(b => b.toString(16).padStart(2, "0")).join("").toUpperCase();
  }

  // --- MUID generation ---

  function generateMuid() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("").toUpperCase();
  }

  // --- Connection ID ---

  function generateConnectionId() {
    return crypto.randomUUID().replace(/-/g, "");
  }

  // --- Request ID ---

  function generateRequestId() {
    return crypto.randomUUID().replace(/-/g, "");
  }

  // --- Date string for headers ---

  function dateToString() {
    return new Date().toUTCString().replace("GMT", "GMT+0000 (Coordinated Universal Time)");
  }

  // --- Voice name conversion ---

  function longVoiceName(shortName) {
    // en-US-JennyNeural -> Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)
    const match = shortName.match(/^([a-zA-Z]{2,})-([A-Za-z]{2,})-(.+Neural)$/);
    if (!match) return shortName;
    const [, lang, region, name] = match;
    return `Microsoft Server Speech Text to Speech Voice (${lang}-${region}, ${name})`;
  }

  // --- Text splitting ---

  function splitText(text, maxBytes) {
    const encoder = new TextEncoder();
    if (encoder.encode(text).length <= maxBytes) return [text];

    const chunks = [];
    let remaining = text;

    while (remaining.length > 0) {
      const encoded = encoder.encode(remaining);
      if (encoded.length <= maxBytes) {
        chunks.push(remaining);
        break;
      }

      // Find a good split point: newline > space > UTF-8 boundary
      let splitIdx = -1;
      const textEncoder = new TextEncoder();

      // Try newlines first
      for (let i = Math.min(remaining.length, maxBytes); i > 0; i--) {
        if (remaining[i - 1] === "\n") {
          splitIdx = i;
          break;
        }
      }

      // Then spaces
      if (splitIdx === -1) {
        for (let i = Math.min(remaining.length, maxBytes); i > 0; i--) {
          if (remaining[i - 1] === " ") {
            splitIdx = i;
            break;
          }
        }
      }

      // Binary search for valid UTF-8 boundary
      if (splitIdx === -1) {
        let lo = 0, hi = Math.min(remaining.length, maxBytes);
        while (lo < hi) {
          const mid = Math.ceil((lo + hi) / 2);
          if (textEncoder.encode(remaining.slice(0, mid)).length <= maxBytes) {
            lo = mid;
          } else {
            hi = mid - 1;
          }
        }
        splitIdx = lo;
      }

      // Back off to avoid splitting XML entities
      const entityMatch = remaining.slice(0, splitIdx).match(/&[^;]*$/);
      if (entityMatch) {
        splitIdx -= entityMatch[0].length;
      }

      chunks.push(remaining.slice(0, splitIdx));
      remaining = remaining.slice(splitIdx);
    }

    return chunks.filter(c => c.length > 0);
  }

  // --- XML escaping ---

  function xmlEscape(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // --- SSML generation ---

  function buildSSML(text, voice, rate, pitch, volume) {
    const voiceTag = longVoiceName(voice);
    return `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'><voice name='${voiceTag}'><prosody pitch='${pitch}' rate='${rate}' volume='${volume}'>${xmlEscape(text)}</prosody></voice></speak>`;
  }

  // --- Binary message parsing ---

  function parseBinaryMessage(buffer) {
    const uint8Array = new Uint8Array(buffer);
    const needle = new TextEncoder().encode("Path:audio\r\n");
    const audioStartIndex = indexOf(uint8Array, needle);

    if (audioStartIndex !== -1) {
      const audioChunk = uint8Array.slice(audioStartIndex + needle.length);
      return { audio: audioChunk };
    }
    return null;
  }

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

  /**
   * Synthesize text to MP3 audio.
   *
   * @param {string} text - The text to synthesize
   * @param {object} opts
   * @param {string} opts.voice - Voice short name (e.g. "en-US-JennyNeural")
   * @param {string} [opts.rate="+0%"] - Prosody rate
   * @param {string} [opts.pitch="+0Hz"] - Prosody pitch
   * @param {string} [opts.volume="+0%"] - Prosody volume
   * @param {function} [opts.onProgress] - Callback with (bytesReceived)
   * @returns {Promise<Blob>} - The synthesized MP3 audio
   */
  async function synthesize(text, opts = {}) {
    const {
      voice = "en-US-EmmaMultilingualNeural",
      rate = "+0%",
      pitch = "+0Hz",
      volume = "+0%",
      onProgress = null,
    } = opts;

    const muid = generateMuid();
    const connectionId = generateConnectionId();
    const secMsGec = await generateSecMsGec();

    const url = `${WSS_BASE}?Ocp-Apim-Subscription-Key=${TRUSTED_CLIENT_TOKEN}&Sec-MS-GEC=${secMsGec}&Sec-MS-GEC-Version=${SEC_MS_GEC_VERSION}&ConnectionId=${connectionId}`;

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      let audioChunks = [];
      let totalBytes = 0;
      let receivedTurnEnd = false;

      ws.binaryType = "arraybuffer";

      ws.onopen = async () => {
        // Set headers that mimic the Edge extension
        // (WebSocket API doesn't let us set custom headers, but the token in the URL is sufficient)

        // Send speech.config
        const configMsg = [
          `X-Timestamp:${dateToString()}`,
          "Content-Type:application/json; charset=utf-8",
          "Path:speech.config",
          "",
          "",
        ].join("\r\n") + '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}';

        ws.send(configMsg);

        // Split text and send each chunk
        const chunks = splitText(text, MAX_CHUNK_BYTES);

        for (const chunk of chunks) {
          const requestId = generateRequestId();
          const ssml = buildSSML(chunk, voice, rate, pitch, volume);

          const ssmlMsg = [
            `X-RequestId:${requestId}`,
            "Content-Type:application/ssml+xml",
            `X-Timestamp:${dateToString()}Z`,
            "Path:ssml",
            "",
            "",
          ].join("\r\n") + ssml;

          ws.send(ssmlMsg);
        }
      };

      ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          // Text message
          const msg = event.data;

          if (msg.includes("Path:turn.end")) {
            receivedTurnEnd = true;
            ws.close();
          }
        } else {
          // Binary message - use FileReader to convert Blob to ArrayBuffer
          const reader = new FileReader();
          reader.onload = () => {
            const arrayBuffer = reader.result;
            const parsed = parseBinaryMessage(arrayBuffer);
            if (parsed && parsed.audio.byteLength > 0) {
              audioChunks.push(parsed.audio);
              totalBytes += parsed.audio.byteLength;
              if (onProgress) onProgress(totalBytes);
            }
          };
          reader.readAsArrayBuffer(event.data);
        }
      };

      ws.onerror = (err) => {
        reject(new Error(`WebSocket error: ${err.message || "unknown"}`));
      };

      ws.onclose = () => {
        if (audioChunks.length === 0 && !receivedTurnEnd) {
          reject(new Error("Connection closed before receiving audio"));
          return;
        }
        // Concatenate all MP3 chunks
        const totalLength = audioChunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
        const result = new Uint8Array(totalLength);
        let offset = 0;
        for (const chunk of audioChunks) {
          result.set(new Uint8Array(chunk), offset);
          offset += chunk.byteLength;
        }
        resolve(new Blob([result], { type: "audio/mpeg" }));
      };
    });
  }

  // --- Voice list ---

  /**
   * Fetch the list of available voices.
   *
   * @returns {Promise<Array>} - Array of voice objects
   */
  async function fetchVoices() {
    // Hardcoded voice list — the live endpoint blocks CORS from localhost.
    // This subset covers the most common English voices.
    return [
      { ShortName: "en-US-EmmaMultilingualNeural", FriendlyName: "Emma Multilingual", Locale: "en-US" },
      { ShortName: "en-US-GuyNeural", FriendlyName: "Guy", Locale: "en-US" },
      { ShortName: "en-US-JennyNeural", FriendlyName: "Jenny", Locale: "en-US" },
      { ShortName: "en-US-AriaNeural", FriendlyName: "Aria", Locale: "en-US" },
      { ShortName: "en-US-DavisNeural", FriendlyName: "Davis", Locale: "en-US" },
      { ShortName: "en-US-JaneNeural", FriendlyName: "Jane", Locale: "en-US" },
      { ShortName: "en-US-JasonNeural", FriendlyName: "Jason", Locale: "en-US" },
      { ShortName: "en-US-SaraNeural", FriendlyName: "Sara", Locale: "en-US" },
      { ShortName: "en-US-TonyNeural", FriendlyName: "Tony", Locale: "en-US" },
      { ShortName: "en-US-AvaNeural", FriendlyName: "Ava", Locale: "en-US" },
      { ShortName: "en-US-AndrewNeural", FriendlyName: "Andrew", Locale: "en-US" },
      { ShortName: "en-US-BrianNeural", FriendlyName: "Brian", Locale: "en-US" },
      { ShortName: "en-US-ChristopherNeural", FriendlyName: "Christopher", Locale: "en-US" },
      { ShortName: "en-US-EricNeural", FriendlyName: "Eric", Locale: "en-US" },
      { ShortName: "en-US-MichelleNeural", FriendlyName: "Michelle", Locale: "en-US" },
      { ShortName: "en-US-MonicaNeural", FriendlyName: "Monica", Locale: "en-US" },
      { ShortName: "en-GB-SoniaNeural", FriendlyName: "Sonia", Locale: "en-GB" },
      { ShortName: "en-GB-RyanNeural", FriendlyName: "Ryan", Locale: "en-GB" },
      { ShortName: "en-AU-NatashaNeural", FriendlyName: "Natasha", Locale: "en-AU" },
      { ShortName: "en-AU-WilliamNeural", FriendlyName: "William", Locale: "en-AU" },
    ];
  }

  // --- Public API ---

  return {
    synthesize,
    fetchVoices,
    longVoiceName,
  };
})();

// Export for ES module or global
if (typeof module !== "undefined" && module.exports) {
  module.exports = EdgeTTS;
}
