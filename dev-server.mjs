#!/usr/bin/env node
/**
 * Dev server with WebSocket proxy for the audiobook TTS builder.
 *
 * Serves static files from out/web-stage/ and proxies WebSocket
 * connections to Microsoft's TTS endpoint using raw TCP relay
 * (no ws library for the proxy path — just pipe bytes after upgrade).
 *
 * Usage:
 *   shell_scripts/web-stage.sh --serve    stage + start dev server
 *   npm run dev               same thing
 *   Then open http://localhost:8001
 */

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import tls from "node:tls";
import crypto from "node:crypto";

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = join(__dirname, "out", "web-stage");
const PORT = 8001;

const TTS_HOST = "api.msedgeservices.com";
const TTS_PORT = 443;
const TTS_PATH = "/tts/cognitiveservices/websocket/v1";

const MIME_TYPES = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "application/javascript",
  ".mjs": "application/javascript",
  ".json": "application/json",
  ".py": "text/plain",
  ".mp3": "audio/mpeg",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

// --- Static file server ---

async function serveStatic(req, res) {
  let filePath = join(STATIC_DIR, req.url === "/" ? "/index.html" : req.url);
  try {
    const s = await stat(filePath);
    if (s.isDirectory()) filePath = join(filePath, "index.html");
  } catch {
    res.writeHead(404);
    res.end("Not found");
    return;
  }
  try {
    const data = await readFile(filePath);
    const ext = extname(filePath);
    res.writeHead(200, { "Content-Type": MIME_TYPES[ext] || "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(500);
    res.end("Internal error");
  }
}

// --- Raw TCP WebSocket proxy ---

function proxyWebSocket(clientSocket, requestUrl, clientWsKey, head) {
  const clientUrl = new URL(requestUrl, "http://localhost");
  const ttsQuery = clientUrl.search;
  const wsKey = crypto.randomBytes(16).toString("base64");

  // RFC 6455: the client validates Sec-WebSocket-Accept against the key IT
  // sent, so the 101 we forward must be derived from the client's key (not
  // the one we send upstream to Microsoft).
  const clientAccept = crypto
    .createHash("sha1")
    .update(clientWsKey + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
    .digest("base64");

  let serverHeadersDone = false;
  let clientBuf = head && head.length > 0 ? Buffer.from(head) : Buffer.alloc(0);

  const tlsSocket = tls.connect({
    host: TTS_HOST,
    port: TTS_PORT,
    servername: TTS_HOST,
  });

  tlsSocket.on("secureConnect", () => {
    const upgradeReq = [
      `GET ${TTS_PATH}${ttsQuery} HTTP/1.1`,
      `Host: ${TTS_HOST}`,
      "Upgrade: websocket",
      "Connection: Upgrade",
      "Sec-WebSocket-Version: 13",
      `Sec-WebSocket-Key: ${wsKey}`,
      "Pragma: no-cache",
      "Cache-Control: no-cache",
      "Origin: chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
      "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
      "",
      "",
    ].join("\r\n");
    tlsSocket.write(upgradeReq);
  });

  // Buffer from Microsoft until HTTP 101 headers are complete
  let serverHeaderBuf = Buffer.alloc(0);

  tlsSocket.on("data", (data) => {
    if (!serverHeadersDone) {
      serverHeaderBuf = Buffer.concat([serverHeaderBuf, data]);
      const headerEnd = serverHeaderBuf.indexOf("\r\n\r\n");
      if (headerEnd !== -1) {
        serverHeadersDone = true;
        const headerStr = serverHeaderBuf.slice(0, headerEnd + 4).toString();
        const statusLine = headerStr.split("\r\n")[0];
        console.log(`  Proxy: Microsoft responded: ${statusLine}`);

        // Forward the 101 to the client
        if (!clientSocket.destroyed) {
          clientSocket.write(
            "HTTP/1.1 101 Switching Protocols\r\n" +
            "Upgrade: websocket\r\n" +
            "Connection: Upgrade\r\n" +
            `Sec-WebSocket-Accept: ${clientAccept}\r\n` +
            "\r\n"
          );
        }

        // Flush any buffered client data now that Microsoft is ready
        if (clientBuf.length > 0 && !tlsSocket.destroyed) {
          tlsSocket.write(clientBuf);
          clientBuf = null;
        }

        // Forward any data after the headers
        const remaining = serverHeaderBuf.slice(headerEnd + 4);
        if (remaining.length > 0 && !clientSocket.destroyed) {
          clientSocket.write(remaining);
        }
      }
    } else {
      // Upgraded — relay to client
      if (!clientSocket.destroyed) {
        clientSocket.write(data);
      }
    }
  });

  // Relay client -> Microsoft (buffer until upgrade completes)
  clientSocket.on("data", (data) => {
    if (serverHeadersDone) {
      if (!tlsSocket.destroyed) tlsSocket.write(data);
    } else {
      clientBuf = Buffer.concat([clientBuf, data]);
    }
  });

  clientSocket.on("close", () => {
    if (!tlsSocket.destroyed) tlsSocket.end();
  });

  tlsSocket.on("close", () => {
    if (!clientSocket.destroyed) clientSocket.end();
  });

  clientSocket.on("error", () => {
    if (!tlsSocket.destroyed) tlsSocket.destroy();
  });

  tlsSocket.on("error", (err) => {
    console.error(`  Proxy: TLS error: ${err.message}`);
    if (!clientSocket.destroyed) clientSocket.destroy();
  });
}

// --- HTTP server ---

const server = createServer(serveStatic);

server.on("upgrade", (req, socket, head) => {
  if (req.url.startsWith("/tts-ws")) {
    console.log(`  Proxy: client upgrade for ${req.url.slice(0, 80)}...`);
    proxyWebSocket(socket, req.url, req.headers["sec-websocket-key"], head);
  } else {
    socket.destroy();
  }
});

server.listen(PORT, () => {
  console.log(`Audiobook TTS dev server running at http://localhost:${PORT}`);
  console.log(`  Static files: ${STATIC_DIR}`);
  console.log(`  TTS proxy:    wss://${TTS_HOST}${TTS_PATH} (via /tts-ws)`);
  console.log(`  Press Ctrl+C to stop.\n`);
});
