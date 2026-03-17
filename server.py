"""
Nebula Node - Game Server
=========================
Pure TCP socket server. Handles all game logic.
Run this on ONE machine. Both players connect to this IP.

Usage: python server.py
"""

import socket
import threading
import json
import random
import time

# ─── CONFIG ────────────────────────────────────────────────────────────────────
HOST = "0.0.0.0"   # Listen on all interfaces (so other laptops can connect)
PORT = 9999
GRID_ROWS = 12
GRID_COLS = 16
NUM_STARS = 30
NUM_BONUS_ITEMS = 4  # Random bonus collectibles

# Bonus item types chosen randomly each game
BONUS_TYPES = [
    {"name": "Nebula Crystals", "emoji": "💎", "points": 3},
    {"name": "Cosmic Orbs",     "emoji": "🔮", "points": 3},
    {"name": "Star Shards",     "emoji": "⚡", "points": 3},
    {"name": "Void Pearls",     "emoji": "🫧", "points": 3},
    {"name": "Nova Sparks",     "emoji": "✨", "points": 3},
    {"name": "Moon Dust",       "emoji": "🌙", "points": 3},
    {"name": "Pulsar Gems",     "emoji": "💠", "points": 3},
]

PLAYER_COLORS = ["#FF6B6B", "#4ECDC4"]   # Red-ish, Teal
PLAYER_NAMES  = ["Voyager 1", "Voyager 2"]
PLAYER_STARTS = [(0, 0), (GRID_ROWS - 1, GRID_COLS - 1)]  # Top-left, Bottom-right

# ─── GAME STATE ────────────────────────────────────────────────────────────────

class GameState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.players = {}          # pid -> {row, col, score, name, color}
        self.stars = set()         # set of (row, col)
        self.bonus_cells = {}      # (row, col) -> bonus_type dict
        self.explosions = []       # [(row,col), ...] cells that just exploded
        self.turn = 0
        self.game_over = False
        self.winner = None
        self.started = False
        self.bonus_type = random.choice(BONUS_TYPES)  # One random bonus type per game

    def generate_galaxy(self):
        """Place stars and bonus items randomly, avoiding player start positions."""
        occupied = set(PLAYER_STARTS)
        all_cells = [(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS)]
        random.shuffle(all_cells)

        self.stars = set()
        placed = 0
        for cell in all_cells:
            if cell not in occupied and placed < NUM_STARS:
                self.stars.add(cell)
                occupied.add(cell)
                placed += 1

        # Place bonus items (not on stars or player starts)
        self.bonus_cells = {}
        bonus_placed = 0
        for cell in all_cells:
            if cell not in occupied and bonus_placed < NUM_BONUS_ITEMS:
                self.bonus_cells[cell] = self.bonus_type
                occupied.add(cell)
                bonus_placed += 1

    def to_dict(self):
        return {
            "grid_rows": GRID_ROWS,
            "grid_cols": GRID_COLS,
            "players": self.players,
            "stars": list(self.stars),
            "bonus_cells": {f"{r},{c}": v for (r, c), v in self.bonus_cells.items()},
            "explosions": self.explosions,
            "turn": self.turn,
            "game_over": self.game_over,
            "winner": self.winner,
            "started": self.started,
            "bonus_type": self.bonus_type,
        }


game = GameState()
clients = {}        # pid -> socket
moves_this_turn = {}   # pid -> (row, col)  pending moves
lock = threading.Lock()


# ─── UTILITIES ─────────────────────────────────────────────────────────────────

def send_json(sock, data):
    """Send a JSON message terminated with newline."""
    try:
        msg = json.dumps(data) + "\n"
        sock.sendall(msg.encode())
    except Exception:
        pass


def broadcast(data):
    """Send game state to all connected players."""
    for pid, sock in clients.items():
        send_json(sock, data)


def assign_player_id():
    """Return next available player id (0 or 1)."""
    for pid in [0, 1]:
        if pid not in clients:
            return pid
    return None


# ─── GAME LOGIC ────────────────────────────────────────────────────────────────

def apply_move(pid, direction):
    """Compute new position for player given direction."""
    p = game.players[pid]
    r, c = p["row"], p["col"]
    dr, dc = {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}.get(direction, (0, 0))
    nr = max(0, min(GRID_ROWS - 1, r + dr))
    nc = max(0, min(GRID_COLS - 1, c + dc))
    return nr, nc


def resolve_turn():
    """
    Called when both players have submitted moves.
    1. Move players.
    2. Check for star captures / explosions.
    3. Check for bonus captures.
    4. Check game over.
    5. Broadcast new state.
    """
    global moves_this_turn

    game.explosions = []

    # Apply positions
    new_positions = {}
    for pid, (nr, nc) in moves_this_turn.items():
        game.players[pid]["row"] = nr
        game.players[pid]["col"] = nc
        new_positions[pid] = (nr, nc)

    # Check collision on same cell
    positions_list = list(new_positions.values())
    same_cell = len(positions_list) == 2 and positions_list[0] == positions_list[1]

    for pid, (nr, nc) in new_positions.items():
        cell = (nr, nc)

        if same_cell:
            # Both on same star → explode
            if cell in game.stars:
                game.stars.discard(cell)
                game.explosions.append([nr, nc])
            # Bonus also explodes if both land on it
            if cell in game.bonus_cells:
                del game.bonus_cells[cell]
                game.explosions.append([nr, nc])
        else:
            # Normal capture
            if cell in game.stars:
                game.stars.discard(cell)
                game.players[pid]["score"] += 1

            if cell in game.bonus_cells:
                pts = game.bonus_cells[cell]["points"]
                game.players[pid]["score"] += pts
                del game.bonus_cells[cell]

    game.turn += 1

    # Game over when all stars + bonus items collected/exploded
    if not game.stars and not game.bonus_cells:
        game.game_over = True
        scores = {pid: game.players[pid]["score"] for pid in game.players}
        max_score = max(scores.values())
        winners = [pid for pid, s in scores.items() if s == max_score]
        if len(winners) == 1:
            game.winner = game.players[winners[0]]["name"]
        else:
            game.winner = "TIE"

    moves_this_turn = {}
    broadcast({"type": "state", "data": game.to_dict()})


# ─── CLIENT HANDLER ────────────────────────────────────────────────────────────

def handle_client(sock, addr):
    pid = None
    buffer = ""

    with lock:
        pid = assign_player_id()
        if pid is None:
            send_json(sock, {"type": "error", "msg": "Game is full (2 players max)"})
            sock.close()
            return

        clients[pid] = sock
        r, c = PLAYER_STARTS[pid]
        game.players[pid] = {
            "row": r, "col": c,
            "score": 0,
            "name": PLAYER_NAMES[pid],
            "color": PLAYER_COLORS[pid],
            "pid": pid,
        }
        print(f"[+] Player {pid} connected from {addr}")
        send_json(sock, {"type": "welcome", "pid": pid, "msg": f"You are {PLAYER_NAMES[pid]}"})

        # Start game when 2 players connected
        if len(clients) == 2:
            game.generate_galaxy()
            game.started = True
            print("[*] Both players connected. Game starting!")
            broadcast({"type": "state", "data": game.to_dict()})
        else:
            broadcast({"type": "waiting", "msg": "Waiting for second player..."})

    try:
        while True:
            chunk = sock.recv(1024).decode()
            if not chunk:
                break
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

                with lock:
                    if msg.get("type") == "move" and game.started and not game.game_over:
                        direction = msg.get("direction", "")
                        nr, nc = apply_move(pid, direction)
                        moves_this_turn[pid] = (nr, nc)
                        print(f"  Player {pid} → {direction} → ({nr},{nc})")

                        # When both players have moved, resolve the turn
                        if len(moves_this_turn) == len(clients):
                            resolve_turn()

                    elif msg.get("type") == "restart":
                        game.reset()
                        game.generate_galaxy()
                        game.started = True
                        moves_this_turn.clear()
                        broadcast({"type": "state", "data": game.to_dict()})

    except Exception as e:
        print(f"[!] Player {pid} error: {e}")
    finally:
        with lock:
            clients.pop(pid, None)
            game.players.pop(pid, None)
            game.started = False
            moves_this_turn.pop(pid, None)
            print(f"[-] Player {pid} disconnected")
            broadcast({"type": "waiting", "msg": f"{PLAYER_NAMES[pid]} disconnected. Waiting..."})
        sock.close()


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, PORT))
    server_sock.listen(5)

    # Print local IPs so players know what to connect to
    import subprocess, platform
    try:
        if platform.system() == "Windows":
            result = subprocess.check_output("ipconfig", shell=True).decode()
        else:
            result = subprocess.check_output("hostname -I", shell=True).decode()
        print(f"\n{'='*50}")
        print(f"  NEBULA NODE SERVER RUNNING on port {PORT}")
        print(f"  Your IP(s): {result.strip()}")
        print(f"  Tell Player 2 to connect to: <YOUR_IP>:{PORT}")
        print(f"{'='*50}\n")
    except Exception:
        print(f"\n[*] Server running on port {PORT}\n")

    while True:
        try:
            sock, addr = server_sock.accept()
            t = threading.Thread(target=handle_client, args=(sock, addr), daemon=True)
            t.start()
        except KeyboardInterrupt:
            print("\n[*] Server shutting down.")
            break

    server_sock.close()


if __name__ == "__main__":
    main()