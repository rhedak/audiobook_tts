#!/usr/bin/env bash
# Stage the site and serve it locally at http://localhost:8001/.
#
#   shell_scripts/local-serve.sh          stage + (re)start in the background
#   shell_scripts/local-serve.sh --fg     stage + serve in the foreground
#   shell_scripts/local-serve.sh --stop   stop the local server
#
# A server already running on the port is restarted so it picks up the
# freshly staged site. Background mode logs to out/dev-server.log.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

port=8001
url="http://localhost:${port}"
log_file="out/dev-server.log"

server_pids() {
    lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true
}

is_running() {
    [[ -n "$(server_pids)" ]]
}

wait_port_up() {
    local deadline=$((SECONDS + 15))
    until is_running; do
        (( SECONDS < deadline )) || return 1
        sleep 0.25
    done
}

wait_port_down() {
    local deadline=$((SECONDS + 10))
    while is_running; do
        (( SECONDS < deadline )) || return 1
        sleep 0.25
    done
}

stop_server() {
    if ! is_running; then
        echo "No local server on port ${port}."
        return 0
    fi
    local pids
    pids="$(server_pids)"
    echo "Stopping local server (pid ${pids//$'\n'/ })..."
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    if ! wait_port_down; then
        echo "  still running, sending SIGKILL"
        # shellcheck disable=SC2086
        kill -9 $(server_pids) 2>/dev/null || true
        wait_port_down || true
    fi
    echo "Stopped."
}

start_background() {
    if is_running; then
        echo "Already running; restarting..."
        stop_server
    fi
    shell_scripts/web-stage.sh
    nohup node dev-server.mjs >"$log_file" 2>&1 &
    local pid=$!
    if wait_port_up; then
        echo "Serving at ${url} (pid ${pid})"
        echo "  logs: ${log_file}"
        echo "  stop: $(basename "$0") --stop"
    else
        echo "Server failed to start; log follows:" >&2
        cat "$log_file" >&2
        return 1
    fi
}

start_foreground() {
    shell_scripts/web-stage.sh --serve
}

case "${1:-}" in
    --stop) stop_server ;;
    --fg) start_foreground ;;
    "") start_background ;;
    *)
        echo "usage: $(basename "$0") [--fg | --stop]" >&2
        exit 2
        ;;
esac
