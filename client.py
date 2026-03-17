"""
Nebula Node - Game Client
=========================
Connects to game server via TCP socket.
Serves index.html + API. Each browser session = one player.

Usage:
    python client.py                   # server on same machine
    python client.py 192.168.1.5       # server on another laptop

Open in browser:  http://<this-machine-ip>:8000
"""

import socket, threading, json, sys, time, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

SERVER_HOST     = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
SERVER_PORT     = 9999
LOCAL_HTTP_PORT = 8000

# ── shared state ───────────────────────────────────────────────────────────────
state = {
    "connected": False,
    "game":      None,
    "message":   "Connecting to server...",
}
sock = None
lock = threading.Lock()

# Start delay window to let more players join before starting.
pending_start_time = None
START_DELAY = 1.0

# ── per-browser session state ──────────────────────────────────────────────────
# sid -> { "pid": 0 or 1 or None, "last_seen": timestamp }
sessions     = {}
SESSION_TTL  = 10   # seconds before a browser is considered gone

MAX_PLAYERS = 6

PLAYER_NAMES = ["Voyager 1", "Voyager 2", "Voyager 3", "Voyager 4", "Voyager 5", "Voyager 6"]


def clean_sessions():
    now = time.time()
    dead = [s for s, v in sessions.items() if now - v["last_seen"] > SESSION_TTL]
    for s in dead:
        del sessions[s]


def active_sessions():
    now = time.time()
    return {sid: v for sid, v in sessions.items() if now - v["last_seen"] < SESSION_TTL}


def lobby_list():
    active = active_sessions()
    joined = [v for v in active.values() if v.get("joined")]
    return sorted(joined, key=lambda v: v["joined"])


def assign_pid_for_session(sid):
    if sid in sessions and sessions[sid].get("pid") is not None:
        sessions[sid]["last_seen"] = time.time()
        return sessions[sid]["pid"]

    # if game has started and is active, do not assign new pids.
    if state.get("game") and state["game"].get("started") and not state["game"].get("game_over"):
        sessions.setdefault(sid, {"name": None, "pid": None, "last_seen": time.time()})
        sessions[sid]["last_seen"] = time.time()
        return None

    # assign next available pid for lobby players before start
    taken = {v["pid"] for v in sessions.values() if v.get("pid") is not None}
    for pid in range(MAX_PLAYERS):
        if pid not in taken:
            name = sessions.get(sid, {}).get("name") or PLAYER_NAMES[pid]
            sessions[sid] = {"name": name, "pid": pid, "last_seen": time.time(), "joined": time.time()}
            print(f"[+] Browser {sid[:6]} joined lobby as Player {pid} ({name})")
            return pid

    sessions[sid] = {"name": sessions.get(sid, {}).get("name"), "pid": None, "last_seen": time.time(), "joined": time.time()}
    print(f"[~] Browser {sid[:6]} joined as spectator (lobby full)")
    return None

# ── socket thread ──────────────────────────────────────────────────────────────
def socket_thread():
    global sock
    while True:
        try:
            print(f"[*] Connecting to {SERVER_HOST}:{SERVER_PORT} ...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((SERVER_HOST, SERVER_PORT))
            with lock:
                state["connected"] = True
                state["message"]   = "Waiting for players..."
            print("[+] Connected to server.")
            buf = ""
            while True:
                sock.settimeout(0.1)
                try:
                    chunk = sock.recv(4096).decode()
                    if not chunk: raise ConnectionResetError("server closed")
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line: continue
                        try: msg = json.loads(line)
                        except: continue
                        with lock:
                            t = msg.get("type")
                            if t == "state":
                                state["game"]    = msg["data"]
                                state["message"] = ""
                            elif t == "waiting":
                                state["message"] = msg.get("msg", "Waiting...")
                            elif t == "error":
                                state["message"] = "ERROR: " + msg.get("msg", "")
                except socket.timeout:
                    pass
        except Exception as e:
            with lock:
                state["connected"] = False
                state["game"]      = None
                state["message"]   = f"Disconnected. Retrying... ({e})"
            print(f"[!] Lost: {e}. Retrying in 3s...")
            time.sleep(3)

def send_to_server(data):
    try:
        if sock: sock.sendall((json.dumps(data) + "\n").encode())
    except Exception as e:
        print(f"[!] Send error: {e}")

# ── HTTP handler ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors(); self.end_headers(); self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        global pending_start_time
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path   = parsed.path
        sid    = params.get("sid", [None])[0]

        if path in ("/", "/index.html"):
            html_path = os.path.join(BASE_DIR, "index.html")
            try:
                body = open(html_path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
            except FileNotFoundError:
                self.send_response(404); self.end_headers()

        elif path == "/state":
            clean_sessions()

            with lock:
                game = state["game"]
                started = game["started"] if game else False
                game_num_players = game.get("num_players") if game else None

            if sid and sid in sessions:
                sessions[sid]["last_seen"] = time.time()
            elif sid:
                sessions[sid] = {"name": None, "pid": None, "last_seen": time.time()}

            pid = sessions.get(sid, {}).get("pid") if sid else None
            lobby = []
            for s, v in active_sessions().items():
                if v.get("name"):
                    lobby.append({"sid": s, "name": v["name"], "pid": v.get("pid")})

            with lock:
                self._json({
                    "connected": state["connected"],
                    "pid":       pid,
                    "game":      state["game"],
                    "message":   state["message"],
                    "lobby":     lobby,
                })
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        sid    = params.get("sid", [None])[0]
        length = int(self.headers.get("Content-Length", 0))
        try: data = json.loads(self.rfile.read(length))
        except: self._json({"ok": False}, 400); return

        if self.path.startswith("/move"):
            d = data.get("direction", "").upper()
            pid = sessions.get(sid, {}).get("pid") if sid else None
            if d in ("UP","DOWN","LEFT","RIGHT") and pid is not None:
                send_to_server({"type": "move", "direction": d, "pid": pid})
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "invalid or no pid"}, 400)

        elif self.path.startswith("/join"):
            if not sid:
                self._json({"ok": False, "error": "Missing sid"}, 400); return
            name = data.get("name", "").strip()[:24] or None
            if not name:
                self._json({"ok": False, "error": "Please enter a name."}, 400); return
            pid = assign_pid_for_session(sid)
            sess = sessions.setdefault(sid, {})
            sess["name"] = name
            sess["pid"] = pid
            sess["last_seen"] = time.time()
            sess["joined"] = sess.get("joined", time.time())
            print(f"[JOIN] {name} assigned pid {pid}")
            self._json({"ok": True, "name": name, "pid": pid})

        elif self.path.startswith("/start"):
            lobby = [(sid, v) for sid, v in active_sessions().items() if v.get("name")]
            if len(lobby) < 2:
                self._json({"ok": False, "error": "Need at least 2 players to start."}, 400)
                return
            lobby.sort(key=lambda x: x[1].get("joined", 0))
            players = []
            for pid, (sid, sess) in enumerate(lobby[:MAX_PLAYERS]):
                sess["pid"] = pid
                players.append({"pid": pid, "name": sess["name"]})
            send_to_server({"type": "start_game", "count": len(players), "players": players})
            self._json({"ok": True, "count": len(players), "players": players})

        elif self.path.startswith("/restart"):
            sessions.clear()
            send_to_server({"type": "restart"})
            self._json({"ok": True})

        else:
            self.send_response(404); self.end_headers()

def main():
    threading.Thread(target=socket_thread, daemon=True).start()
    httpd = HTTPServer(("0.0.0.0", LOCAL_HTTP_PORT), Handler)
    print(f"\n{'='*54}")
    print(f"  NEBULA NODE CLIENT")
    print(f"  Server     : {SERVER_HOST}:{SERVER_PORT}")
    print(f"  Laptop URL : http://127.0.0.1:{LOCAL_HTTP_PORT}")
    print(f"  Phone URL  : http://<your-wifi-ip>:{LOCAL_HTTP_PORT}")
    print(f"  Game starts when 2 browsers open the page!")
    print(f"{'='*54}\n")
    try:    httpd.serve_forever()
    except KeyboardInterrupt: print("\n[*] Shutting down.")

if __name__ == "__main__":
    main()