"""
Nebula Node - Game Server
=========================
Multiplayer TCP socket server. Supports 2-6 players.
Run this on ONE machine.

Usage: python server.py
"""

import socket, threading, json, random, time

HOST      = "0.0.0.0"
PORT      = 9999
GRID_ROWS = 12
GRID_COLS = 16
NUM_STARS = 40
NUM_BONUS = 6
MAX_PLAYERS = 6

BONUS_TYPES = [
    {"name": "Nebula Crystals", "emoji": "💎", "points": 3},
    {"name": "Cosmic Orbs",     "emoji": "🔮", "points": 3},
    {"name": "Nova Sparks",     "emoji": "🌟", "points": 3},
    {"name": "Sun Drops",       "emoji": "☀️",  "points": 3},
    {"name": "Galaxy Gems",     "emoji": "💠", "points": 3},
    {"name": "Aurora Shards",   "emoji": "🌈", "points": 3},
    {"name": "Comet Dust",      "emoji": "🪐", "points": 3},
    {"name": "Stardust",       "emoji": "✨", "points": 3},
    {"name": "Quantum Flux",   "emoji": "⚡", "points": 3},
    {"name": "Meteor Shard",   "emoji": "🪨", "points": 3},
]

# Colors and names for up to 6 players
PLAYER_COLORS = ["#FF6B6B", "#4ECDC4", "#FFE27A", "#a78bfa", "#f97316", "#34d399"]
PLAYER_NAMES  = ["Voyager 1", "Voyager 2", "Voyager 3", "Voyager 4", "Voyager 5", "Voyager 6"]

def get_start_positions(n):
    """Return n starting positions spread around the edges of the grid."""
    # Fixed corner + edge positions for up to 6 players
    all_positions = [
        (0,           0),             # top-left
        (GRID_ROWS-1, GRID_COLS-1),   # bottom-right
        (0,           GRID_COLS-1),   # top-right
        (GRID_ROWS-1, 0),             # bottom-left
        (0,           GRID_COLS//2),  # top-middle
        (GRID_ROWS-1, GRID_COLS//2),  # bottom-middle
    ]
    return all_positions[:n]

# ── game state ─────────────────────────────────────────────────────────────────

class GameState:
    def __init__(self): self.reset()

    def reset(self):
        self.players     = {}
        self.stars       = set()
        self.bonus_cells = {}
        self.explosions  = []
        self.turn        = 0
        self.game_over   = False
        self.winner      = None
        self.started     = False
        self.bonus_type  = random.choice(BONUS_TYPES)
        self.num_players = 0

    def generate_galaxy(self, num_players):
        self.num_players = num_players
        starts = set(get_start_positions(num_players))
        occupied  = set(starts)
        all_cells = [(r,c) for r in range(GRID_ROWS) for c in range(GRID_COLS)]
        random.shuffle(all_cells)
        self.stars = set()
        for cell in all_cells:
            if cell not in occupied and len(self.stars) < NUM_STARS:
                self.stars.add(cell); occupied.add(cell)
        self.bonus_cells = {}
        for cell in all_cells:
            if cell not in occupied and len(self.bonus_cells) < NUM_BONUS:
                self.bonus_cells[cell] = self.bonus_type; occupied.add(cell)

    def init_players(self, num_players, player_infos=None):
        self.players = {}
        starts = get_start_positions(num_players)
        for pid in range(num_players):
            r, c = starts[pid]
            name = PLAYER_NAMES[pid]
            color = PLAYER_COLORS[pid]
            if player_infos and pid < len(player_infos):
                info = player_infos[pid]
                if info.get("name"): name = info["name"]
                if info.get("color"): color = info["color"]
            self.players[pid] = {
                "row": r, "col": c, "score": 0,
                "name":  name,
                "color": color,
                "pid":   pid,
            }

    def to_dict(self):
        return {
            "grid_rows":   GRID_ROWS,
            "grid_cols":   GRID_COLS,
            "players":     self.players,
            "stars":       list(self.stars),
            "bonus_cells": {f"{r},{c}": v for (r,c),v in self.bonus_cells.items()},
            "explosions":  self.explosions,
            "turn":        self.turn,
            "game_over":   self.game_over,
            "winner":      self.winner,
            "started":     self.started,
            "bonus_type":  self.bonus_type,
            "num_players": self.num_players,
        }

game          = GameState()
clients       = {}
moves_pending = {}
lock          = threading.Lock()
turn_timer    = None   # timer to auto-resolve if a player is slow
TURN_TIMEOUT  = 10     # seconds to wait before auto-resolving

# ── helpers ────────────────────────────────────────────────────────────────────

def send_json(s, data):
    try: s.sendall((json.dumps(data) + "\n").encode())
    except: pass

def broadcast(data):
    for s in list(clients.values()):
        send_json(s, data)

# ── game logic ─────────────────────────────────────────────────────────────────

def apply_move(pid, direction):
    p = game.players[pid]
    r, c = p["row"], p["col"]
    dr, dc = {"UP":(-1,0),"DOWN":(1,0),"LEFT":(0,-1),"RIGHT":(0,1)}.get(direction,(0,0))
    return max(0,min(GRID_ROWS-1,r+dr)), max(0,min(GRID_COLS-1,c+dc))

def cancel_timer():
    global turn_timer
    if turn_timer:
        turn_timer.cancel()
        turn_timer = None

def start_timer():
    """Auto-resolve turn after TURN_TIMEOUT seconds if not all players moved."""
    global turn_timer
    cancel_timer()
    def auto_resolve():
        with lock:
            if game.started and not game.game_over and moves_pending:
                # Fill in missing players — they stay in place
                for pid in list(game.players.keys()):
                    if pid not in moves_pending:
                        r = game.players[pid]["row"]
                        c = game.players[pid]["col"]
                        moves_pending[pid] = (r, c)
                        print(f"  P{pid} timed out — staying in place")
                resolve_turn()
    turn_timer = threading.Timer(TURN_TIMEOUT, auto_resolve)
    turn_timer.daemon = True
    turn_timer.start()

def resolve_turn():
    cancel_timer()
    game.explosions = []

    # Find cells where multiple players land (collision)
    new_pos = {}
    for pid,(nr,nc) in moves_pending.items():
        game.players[pid]["row"] = nr
        game.players[pid]["col"] = nc
        new_pos[pid] = (nr,nc)

    # Count how many players landed on each cell
    cell_counts = {}
    for pid,(nr,nc) in new_pos.items():
        cell = (nr,nc)
        cell_counts[cell] = cell_counts.get(cell, []) + [pid]

    for cell, pids_on_cell in cell_counts.items():
        nr, nc = cell
        if len(pids_on_cell) > 1:
            # Collision — penalty for collision players and remove cell items
            for pid in pids_on_cell:
                game.players[pid]["score"] = max(0, game.players[pid]["score"] - 5)
            if cell in game.stars:
                game.stars.discard(cell)
                game.explosions.append([nr, nc])
            if cell in game.bonus_cells:
                del game.bonus_cells[cell]
                game.explosions.append([nr, nc])
        else:
            # Single player — normal capture
            pid = pids_on_cell[0]
            if cell in game.stars:
                game.stars.discard(cell)
                game.players[pid]["score"] += 1
            if cell in game.bonus_cells:
                game.players[pid]["score"] += game.bonus_cells[cell]["points"]
                del game.bonus_cells[cell]

    game.turn += 1

    if not game.stars and not game.bonus_cells:
        game.game_over = True
        scores  = {pid: game.players[pid]["score"] for pid in game.players}
        best    = max(scores.values())
        winners = [pid for pid,s in scores.items() if s == best]
        if len(winners) == 1:
            game.winner = game.players[winners[0]]["name"]
        else:
            game.winner = "TIE — " + " & ".join(game.players[p]["name"] for p in winners)

    moves_pending.clear()
    broadcast({"type": "state", "data": game.to_dict()})

# ── client handler ─────────────────────────────────────────────────────────────

def handle_client(conn, addr):
    conn_id = id(conn)
    buffer  = ""

    with lock:
        clients[conn_id] = conn
        print(f"[+] client.py connected from {addr}")
        broadcast({"type": "waiting", "msg": "Waiting for players to open the page..."})

    try:
        while True:
            chunk = conn.recv(1024).decode()
            if not chunk: break
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line: continue
                try: msg = json.loads(line)
                except: continue

                with lock:
                    mtype = msg.get("type")

                    if mtype == "start_game" and not game.started:
                        players = msg.get("players") or []
                        n = msg.get("count", len(players) or 2)
                        n = max(2, min(MAX_PLAYERS, n))
                        game.reset()
                        game.generate_galaxy(n)
                        game.init_players(n, players[:n])
                        game.started = True
                        moves_pending.clear()
                        print(f"[*] Game starting with {n} players! Names: {[p.get('name','') for p in players[:n]]}")
                        broadcast({"type": "state", "data": game.to_dict()})

                    elif mtype == "move" and game.started and not game.game_over:
                        pid       = msg.get("pid")
                        direction = msg.get("direction", "")
                        if pid not in game.players: continue

                        nr, nc = apply_move(pid, direction)
                        game.players[pid]["row"] = nr
                        game.players[pid]["col"] = nc

                        # Collision detection: if multiple players share cell
                        others = [other_pid for other_pid,p in game.players.items()
                                  if other_pid != pid and p["row"] == nr and p["col"] == nc]
                        game.explosions = []
                        cell = (nr, nc)
                        if others:
                            involved = [pid] + others
                            for cpid in involved:
                                game.players[cpid]["score"] = max(0, game.players[cpid]["score"] - 5)
                            if cell in game.stars:
                                game.stars.discard(cell)
                            if cell in game.bonus_cells:
                                del game.bonus_cells[cell]
                            game.explosions.append([nr, nc])
                            print(f"  Collision at ({nr},{nc}) by {involved} → -5 each")
                        elif cell in game.stars:
                            game.stars.discard(cell)
                            game.players[pid]["score"] += 1
                            print(f"  P{pid} captured star at ({nr},{nc}) → score {game.players[pid]['score']}")
                        elif cell in game.bonus_cells:
                            pts = game.bonus_cells[cell]["points"]
                            game.players[pid]["score"] += pts
                            del game.bonus_cells[cell]
                            print(f"  P{pid} got bonus at ({nr},{nc}) +{pts} → score {game.players[pid]['score']}")
                        else:
                            print(f"  P{pid} → {direction:5} → ({nr},{nc})")

                        game.turn += 1

                        if not game.stars and not game.bonus_cells:
                            game.game_over = True
                            scores  = {p: game.players[p]["score"] for p in game.players}
                            best    = max(scores.values())
                            winners = [p for p,s in scores.items() if s == best]
                            if len(winners) == 1:
                                game.winner = game.players[winners[0]]["name"]
                            else:
                                game.winner = "TIE — " + " & ".join(game.players[p]["name"] for p in winners)

                        broadcast({"type": "state", "data": game.to_dict()})

                    elif mtype == "restart":
                        game.reset()
                        game.started = False
                        game.game_over = False
                        game.winner = None
                        game.players = {}
                        game.stars = set()
                        game.bonus_cells = {}
                        game.explosions = []
                        moves_pending.clear()
                        print("[*] Game reset to lobby. Join names and start again.")
                        broadcast({"type": "state", "data": game.to_dict()})

    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        with lock:
            clients.pop(conn_id, None)
            game.started = False
            moves_pending.clear()
            print(f"[-] client.py disconnected")
            broadcast({"type": "waiting", "msg": "Client disconnected. Restart client.py."})
        conn.close()

# ── main ───────────────────────────────────────────────────────────────────────

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)

    import subprocess, platform
    try:
        if platform.system() == "Windows":
            out   = subprocess.check_output("ipconfig", shell=True).decode()
            lines = [l.strip() for l in out.splitlines() if "IPv4" in l]
            ip    = " | ".join(lines)
        else:
            ip = subprocess.check_output("hostname -I", shell=True).decode().strip()
    except: ip = "run ipconfig to find"

    print(f"\n{'='*54}")
    print(f"  NEBULA NODE SERVER — port {PORT}")
    print(f"  Supports 2 to {MAX_PLAYERS} players!")
    print(f"  Your IP : {ip}")
    print(f"{'='*54}\n")

    while True:
        try:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_client, args=(conn,addr), daemon=True)
            t.start()
        except KeyboardInterrupt:
            print("\n[*] Shutting down."); break
    srv.close()

if __name__ == "__main__":
    main()