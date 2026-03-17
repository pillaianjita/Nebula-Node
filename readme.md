# 🌌 Nebula Node — Constellation Land-Grab
### A Multiplayer Socket Programming Game

---

## 📁 FILES IN THIS PROJECT

```
nebula_node/
├── server.py     ← Game server (run on ONE machine)
├── client.py     ← Game client (run on EACH player's machine)
├── index.html    ← Browser UI (just open in browser — no install needed)
└── README.md     ← This file
```

---

## ⚙️ WHAT TO INSTALL

Python 3.x is already available on most systems. This project uses **only Python standard library modules** — no pip install needed!

Modules used (all built-in):
- `socket`       — TCP networking
- `threading`    — Handle multiple clients simultaneously
- `json`         — Message format between server ↔ client
- `http.server`  — Local HTTP bridge for the browser
- `random`       — Galaxy generation
- `time`, `sys`  — Utilities

**To verify Python:**
```bash
python --version    # Should be 3.6+
```

---

## 🚀 HOW TO RUN (Two Laptops)

### Step 1 — On Player 1's laptop (Server machine)
```bash
python server.py
```
Note the IP address it prints (e.g., `192.168.1.10`).

Also run the client on the same machine:
```bash
python client.py        # connects to localhost by default
```

Then open `index.html` in the browser.

---

### Step 2 — On Player 2's laptop
```bash
python client.py 192.168.1.10    # use the IP from Step 1
```
Then open `index.html` in the browser.

---

### Step 3 — Play!
- Both players should be on the **same Wi-Fi network** (or LAN)
- Player 1 starts at top-left, Player 2 at bottom-right
- Use **WASD** or **Arrow Keys** or the **on-screen D-Pad**

---

## 🎮 HOW THE GAME WORKS

| Symbol | Name | Points |
|--------|------|--------|
| ★ | Star | +1 pt |
| 💎/🔮/⚡/etc. | Bonus Item (random per game) | +3 pts |
| 💥 | Explosion (collision) | 0 pts |

- Move one step per turn (Up/Down/Left/Right)
- Land on a star → you capture it
- Both land on the **same star same turn** → it **explodes**, nobody gets it
- 4 random bonus items (type chosen randomly each game) worth 3 pts each
- Game ends when all stars and bonus items are gone

---

## 🧠 SOCKET PROGRAMMING CONCEPTS USED

### Architecture Diagram:
```
[Player 1 Browser]              [Player 2 Browser]
       |                                |
  HTTP polling                    HTTP polling
  (port 8000)                    (port 8000)
       |                                |
[client.py P1]                  [client.py P2]
       |                                |
       └─────── TCP Socket ────────────┘
                    |
              [server.py]
          (Port 9999, LAN IP)
```

### Key Concepts:
1. **TCP Socket** — Reliable, ordered, connection-based (AF_INET + SOCK_STREAM)
2. **Bind & Listen** — Server binds to a port and waits for connections
3. **Accept** — Server accepts each client in a new thread
4. **Threading** — One thread per player, shared state protected by a Lock
5. **JSON over TCP** — Newline-delimited JSON messages as the protocol
6. **HTTP Bridge** — client.py runs a tiny HTTP server so the browser can talk to it
7. **Polling** — Browser polls /state every 200ms (simple alternative to WebSockets)

---

## ❓ TEACHER QUESTIONS & ANSWERS

### Q1: What type of socket did you use, and why?
**A:** We used `socket.AF_INET` (IPv4) and `socket.SOCK_STREAM` (TCP).  
TCP was chosen because the game needs **reliable, ordered delivery** — if a move message is lost or arrives out of order, the game state breaks. UDP would be faster but unreliable.

---

### Q2: What is the role of `bind()` and `listen()`?
**A:**  
- `bind(HOST, PORT)` attaches the socket to a specific IP address and port number, so the OS knows to send incoming connections to this program.  
- `listen(5)` puts the socket in passive mode — it can now accept up to 5 queued incoming connections.

---

### Q3: How does the server handle two clients simultaneously?
**A:** Each client connection spawns a **new thread** via `threading.Thread`. This allows both players to send/receive independently without blocking each other. A `threading.Lock()` protects shared game state from race conditions.

---

### Q4: What is a race condition and how did you handle it?
**A:** A race condition occurs when two threads access/modify shared data at the same time, causing unpredictable results. We use `with lock:` (a mutex lock) around all reads/writes to `game`, `clients`, and `moves_this_turn` to ensure only one thread modifies state at a time.

---

### Q5: How do the client and server communicate? What is your protocol?
**A:** We use **newline-delimited JSON over TCP**. Each message is a JSON object followed by `\n`. The receiver buffers incoming bytes and splits on `\n` to get complete messages. Example messages:
```json
{"type": "move", "direction": "UP"}
{"type": "state", "data": {...}}
{"type": "welcome", "pid": 0}
```

---

### Q6: Why does each player run client.py? What does it do?
**A:** The browser (HTML/JS) cannot directly open TCP sockets. So `client.py` acts as a **bridge** — it holds the TCP socket connection to the server, and exposes a simple HTTP API (`/state`, `/move`, `/restart`) that the browser can call using `fetch()`.

---

### Q7: What is `SO_REUSEADDR` and why is it used?
**A:** `setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)` allows the server to reuse a port that was recently closed. Without it, restarting the server quickly would fail with "Address already in use" because the OS keeps the port in TIME_WAIT state for a few minutes.

---

### Q8: What happens if both players move to the same star simultaneously?
**A:** The server collects both players' moves before resolving them. After both moves arrive, it checks if both players ended up on the same cell. If so, any star or bonus item there is **removed** (exploded) and neither player scores. This is the "simultaneous turn resolution" mechanic.

---

### Q9: What is the difference between `send()` and `sendall()`?
**A:** `send()` may only send part of the data if the buffer is full. `sendall()` loops internally until all bytes are sent. We use `sendall()` to guarantee complete message delivery.

---

### Q10: How does the client handle server disconnection?
**A:** The socket thread in `client.py` runs inside a `while True` loop with a `try/except`. If the connection drops, it catches the exception and retries after 3 seconds — implementing automatic reconnection.

---

### Q11: What is `hostname -I` / `ipconfig` used for in the server?
**A:** It's a convenience feature — the server auto-detects and prints its LAN IP address when it starts, so the second player knows which IP to connect to.

---

### Q12: Why poll every 200ms instead of using WebSockets?
**A:** For simplicity. WebSockets require more complex setup. Polling (repeated GET requests) is easier to implement with Python's built-in `http.server`, and 200ms is fast enough that the game feels responsive. In production, WebSockets would be more efficient.

---

## 🖼️ IMAGES TO DOWNLOAD (Optional)

No images are required — the game uses Unicode characters and CSS for all visuals:
- `★` for stars
- `💎 🔮 ⚡ 🫧 ✨ 🌙 💠` for bonus items
- `●` tokens for players (colored via CSS)
- Animated CSS starfield for background

If you want to add a custom favicon:
- Download any free space/star icon from **favicon.io** or **flaticon.com**
- Save as `favicon.ico` in the same folder
- Add `<link rel="icon" href="favicon.ico">` to index.html's `<head>`

---

## 🌟 FEATURES IMPLEMENTED

- [x] 2D grid (Galaxy) — 12×16 by default
- [x] 30 stars placed randomly
- [x] 2 players starting at opposite corners
- [x] Move one step per turn (Up/Down/Left/Right)
- [x] Star capture on landing
- [x] Explosion mechanic (same cell, same turn)
- [x] Bonus items (4 per game, type chosen randomly each game, +3 pts)
- [x] Score tracking
- [x] Game over detection + winner display
- [x] Restart without restarting the server
- [x] Works across two laptops on same network
- [x] Backend (server.py + client.py) completely separate from frontend (index.html)
- [x] Beautiful space-themed UI with animations

---

*Built with Python standard library only. No external dependencies.*