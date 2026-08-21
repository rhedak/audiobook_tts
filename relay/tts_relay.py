#!/usr/bin/env python3
"""Local speech relay for the Audiobook TTS Builder web page.

Microsoft's speech endpoint rejects WebSocket handshakes from arbitrary
web origins, so the page cannot connect to it directly. This relay stands
in the middle: the page connects here, and this process connects upstream
claiming to be the Edge read-aloud extension -- exactly what dev-server.mjs
does during development, packaged as a standalone tool.

Python standard library only; nothing to pip install.

    python tts_relay.py            # listen on ws://localhost:8765/tts-ws
    python tts_relay.py 9000       # custom port

Leave it running while you use the page, and point the page's relay
setting at ws://localhost:8765/tts-ws.
"""

import base64
import hashlib
import os
import socket
import ssl
import sys
import threading

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
UPSTREAM_HOST = "api.msedgeservices.com"
UPSTREAM_PORT = 443
UPSTREAM_PATH = "/tts/cognitiveservices/websocket/v1"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# The Edge extension origin Microsoft expects to see.
SPOOFED_HEADERS = [
    ("Pragma", "no-cache"),
    ("Cache-Control", "no-cache"),
    ("Origin", "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold"),
    (
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
    ),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def read_headers(sock: socket.socket) -> tuple[bytes, bytes]:
    """Read HTTP headers off *sock*.

    Returns (headers_including_terminator, leftover_bytes). The leftover is
    whatever arrived in the same segments after the blank line -- for a
    WebSocket peer that is already frame data and must not be dropped.
    """
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed mid-headers")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head + b"\r\n\r\n", rest


def handle_health(client: socket.socket) -> None:
    body = b"ok"
    client.sendall(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/plain\r\n"
        # The page on github.io is a different origin; let it check health.
        b"Access-Control-Allow-Origin: *\r\n"
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"\r\n" + body
    )
    client.close()


def pipe(source: socket.socket, target: socket.socket) -> None:
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def header_value(headers: bytes, name: str) -> bytes | None:
    want = name.lower().encode()
    for line in headers.split(b"\r\n"):
        key, _, value = line.partition(b":")
        if key.strip().lower() == want:
            return value.strip()
    return None


def handle_websocket(
    client: socket.socket, query: str, client_key: bytes, client_backlog: bytes
) -> None:
    accept = base64.b64encode(hashlib.sha1(client_key + WS_GUID.encode()).digest())
    client.sendall(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
    )

    # Connect upstream as the Edge extension.
    upstream = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=15)
    tls = ssl.create_default_context().wrap_socket(upstream, server_hostname=UPSTREAM_HOST)
    request_lines = [f"GET {UPSTREAM_PATH}{query} HTTP/1.1", f"Host: {UPSTREAM_HOST}",
                     "Upgrade: websocket", "Connection: Upgrade",
                     "Sec-WebSocket-Version: 13",
                     # Any 16 random bytes, base64-encoded.
                     "Sec-WebSocket-Key: " + base64.b64encode(os.urandom(16)).decode()]
    for name, value in SPOOFED_HEADERS:
        request_lines.append(f"{name}: {value}")
    tls.sendall(("\r\n".join(request_lines) + "\r\n\r\n").encode())

    server_headers, server_backlog = read_headers(tls)
    status = server_headers.split(b"\r\n", 1)[0]
    log(f"  relay: upstream responded: {status.decode(errors='replace')}")
    if b" 101 " not in status:
        tls.close()
        client.close()
        return

    # The browser may have sent speech.config / ssml frames while the
    # upstream handshake was still in flight; they arrived in the same
    # reads as its handshake headers (client_backlog) and must be
    # forwarded now or the stream is corrupted.
    if client_backlog:
        tls.sendall(client_backlog)

    # Same for any audio frames Microsoft sent ahead of its header split.
    if server_backlog:
        client.sendall(server_backlog)

    up_to_client = threading.Thread(target=pipe, args=(tls, client), daemon=True)
    up_to_client.start()
    pipe(client, tls)
    up_to_client.join(timeout=5)
    tls.close()
    client.close()


def handle_client(client: socket.socket) -> None:
    try:
        request_head, backlog = read_headers(client)
        request_line = request_head.split(b"\r\n", 1)[0].decode(errors="replace")
        method, path, _version = request_line.split(" ", 2)
        if method == "GET" and path.startswith("/health"):
            handle_health(client)
            return
        upgrade = header_value(request_head, "Upgrade") or b""
        # Any WebSocket upgrade path is tunneled -- the page is configured
        # with a full URL and typos in the path should not break it; this
        # relay does exactly one thing.
        if method == "GET" and upgrade.lower() == b"websocket":
            key = header_value(request_head, "Sec-WebSocket-Key")
            if key is None:
                client.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                client.close()
                return
            _path, _, query = path.partition("?")
            handle_websocket(client, ("?" + query) if query else "", key, backlog)
            return
        client.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        client.close()
    except (OSError, ValueError) as exc:
        log(f"  relay: {type(exc).__name__}: {exc}")
        try:
            client.close()
        except OSError:
            pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, port))
    server.listen(8)
    log(f"TTS relay listening on ws://{HOST}:{port}/tts-ws")
    log("Point the page's relay setting at this address, and leave")
    log("this window open while building.\n")
    while True:
        client, addr = server.accept()
        threading.Thread(target=handle_client, args=(client,), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
