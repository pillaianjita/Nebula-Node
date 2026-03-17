"""
Nebula Node - Game Client
=========================
Connects to the game server via TCP socket.
Also serves index.html so players just open http://127.0.0.1:8000

Usage:
    python client.py                   # server on same machine
    python client.py 192.168.1.5       # server on another laptop (LAN)

Each player runs this on THEIR OWN laptop, then opens:
    http://127.0.0.1:8000
"""

import socket
import threading
import json
import sys
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# ─── CONFIG ────────────────────────────────────────────────────────────────────
SERVER_HOST     = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
SERVER_PORT     = 9999
LOCAL_HTTP_PORT = 8000

# ─── SHARED STATE ──────────────────────────────────────────────────────────────
state = {
    "connected": False,
    "pid": None,
    "game": None,
    "message": "Connecting to server...",
}
sock = None
lock = threading.Lock()

# ─── SOCKET THREAD ─────────────────────────────────────────────────────────────

def socket_thread():
    global sock
    while True:
        try:
            print(f"[*] Connecting to server {SERVER_HOST}:{SERVER_PORT} ...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((SERVER_HOST, SERVER_PORT))
            with lock:
                state["connected"] = True
                state["message"] = "Connected! Waiting for opponent..."
            print("[+] Connected to server.")

            buffer = ""
            while True:
                sock.settimeout(0.1)
                try:
                    chunk = sock.recv(4096).decode()
                    if not chunk:
                        raise ConnectionResetError("Server closed connection")
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        mtype = msg.get("type")
                        with lock:
                            if mtype == "welcome":
                                state["pid"]     = msg["pid"]
                                state["message"] = msg.get("msg", "")
                            elif mtype == "state":
                                state["game"]    = msg["data"]
                                state["message"] = ""
                            elif mtype == "waiting":
                                state["message"] = msg.get("msg", "Waiting...")
                            elif mtype == "error":
                                state["message"] = "ERROR: " + msg.get("msg", "")
                except socket.timeout:
                    pass

        except Exception as e:
            with lock:
                state["connected"] = False
                state["game"]      = None
                state["message"]   = f"Disconnected. Retrying in 3s... ({e})"
            print(f"[!] Connection lost: {e}. Retrying...")
            time.sleep(3)


def send_to_server(data: dict):
    try:
        if sock:
            sock.sendall((json.dumps(data) + "\n").encode())
    except Exception as e:
        print(f"[!] Send error: {e}")


# ─── HTTP HANDLER ──────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress logs

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # Serve index.html for root requests
        if self.path in ("/", "/index.html"):
            html_path = os.path.join(BASE_DIR, "index.html")
            try:
                with open(html_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"index.html not found")

        elif self.path == "/state":
            with lock:
                self.send_json({
                    "connected": state["connected"],
                    "pid":       state["pid"],
                    "game":      state["game"],
                    "message":   state["message"],
                })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self.send_json({"ok": False, "error": "bad json"}, 400)
            return

        if self.path == "/move":
            direction = data.get("direction", "").upper()
            if direction in ("UP", "DOWN", "LEFT", "RIGHT"):
                send_to_server({"type": "move", "direction": direction})
                self.send_json({"ok": True})
            else:
                self.send_json({"ok": False, "error": "invalid direction"}, 400)

        elif self.path == "/restart":
            send_to_server({"type": "restart"})
            self.send_json({"ok": True})

        else:
            self.send_response(404)
            self.end_headers()


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    # Start TCP socket thread in background
    t = threading.Thread(target=socket_thread, daemon=True)
    t.start()

    # Start local HTTP server (serves game UI + API)
    httpd = HTTPServer(("0.0.0.0", LOCAL_HTTP_PORT), Handler)

    print(f"\n{'='*52}")
    print(f"  NEBULA NODE CLIENT")
    print(f"  Connecting to game server : {SERVER_HOST}:{SERVER_PORT}")
    print(f"")
    print(f"  >>> Open in browser: http://127.0.0.1:{LOCAL_HTTP_PORT}")
    print(f"{'='*52}\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Client shutting down.")


if __name__ == "__main__":
    main()