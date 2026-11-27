import hmac
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SOULSLIGHTS_DB", os.path.join(SERVER_DIR, "soulslights_admin.db"))
INITIAL_TOKENS_PATH = os.path.join(SERVER_DIR, "initial_tokens.json")

ADMIN_USER = "admin"
ADMIN_PASS = "ishaantuff"
SESSION_SECRET = os.environ.get("SOULSLIGHTS_SECRET", "SL_ADMIN_SECRET_7282_KEY")

_DB_LOCK = threading.Lock()


def _db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _DB_LOCK:
        conn = _db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tokens (
                token TEXT PRIMARY KEY,
                is_master INTEGER DEFAULT 0,
                used INTEGER DEFAULT 0,
                revoked INTEGER DEFAULT 0,
                uses INTEGER DEFAULT 0,
                used_by_machine TEXT DEFAULT '',
                used_os TEXT DEFAULT '',
                used_at TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                user_agent TEXT,
                page TEXT,
                referrer TEXT,
                ts TEXT
            );
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                os TEXT,
                ip TEXT,
                user_agent TEXT,
                ts TEXT
            );
        """)
        cnt = conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
        if cnt == 0 and os.path.exists(INITIAL_TOKENS_PATH):
            with open(INITIAL_TOKENS_PATH, "r", encoding="utf-8") as f:
                seed = json.load(f)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            master = seed.get("master_token", "7282")
            conn.execute(
                "INSERT OR IGNORE INTO tokens (token, is_master, created_at) VALUES (?, 1, ?)",
                (master, now),
            )
            for t in seed.get("tokens", []):
                conn.execute(
                    "INSERT OR IGNORE INTO tokens (token, is_master, created_at) VALUES (?, 0, ?)",
                    (t, now),
                )
        conn.commit()
        conn.close()


def _sign_session(user: str) -> str:
    exp = int(time.time()) + 86400 * 7
    payload = f"{user}:{exp}"
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_session(token: str) -> bool:
    try:
        user, exp_s, sig = (token or "").split(":", 2)
        if user != ADMIN_USER or int(exp_s) < int(time.time()):
            return False
        expected = hmac.new(SESSION_SECRET.encode("utf-8"), f"{user}:{exp_s}".encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def _gen_random_token() -> str:
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    digits = "23456789"
    both = alpha + digits
    chars = [secrets.choice(digits) for _ in range(3)] + [secrets.choice(alpha) for _ in range(3)] + [secrets.choice(both) for _ in range(4)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


_MIME = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


class AdminHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _client_ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return fwd or (self.client_address[0] if self.client_address else "")

    def _send_json(self, code: int, obj: dict):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict:
        ln = int(self.headers.get("Content-Length", "0") or 0)
        if ln <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(min(ln, 65536)).decode("utf-8"))
        except Exception:
            return {}

    def _is_admin(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return _verify_session(auth[7:].strip())
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/admin/stats":
            if not self._is_admin():
                return self._send_json(401, {"ok": False, "error": "Unauthorized"})
            with _DB_LOCK:
                conn = _db()
                tokens = [dict(r) for r in conn.execute("SELECT * FROM tokens ORDER BY is_master DESC, used DESC, created_at DESC").fetchall()]
                visits = [dict(r) for r in conn.execute("SELECT * FROM visits ORDER BY id DESC LIMIT 100").fetchall()]
                downloads = [dict(r) for r in conn.execute("SELECT * FROM downloads ORDER BY id DESC LIMIT 100").fetchall()]
                tot_v = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
                uniq_v = conn.execute("SELECT COUNT(DISTINCT ip) FROM visits").fetchone()[0]
                win_d = conn.execute("SELECT COUNT(*) FROM downloads WHERE os='windows'").fetchone()[0]
                mac_d = conn.execute("SELECT COUNT(*) FROM downloads WHERE os='macos'").fetchone()[0]
                conn.close()
            return self._send_json(200, {
                "ok": True,
                "summary": {
                    "total_visits": tot_v,
                    "unique_visitors": uniq_v,
                    "win_downloads": win_d,
                    "mac_downloads": mac_d,
                    "total_downloads": win_d + mac_d,
                    "tokens_total": len(tokens),
                    "tokens_used": sum(1 for t in tokens if t["used"] and not t["is_master"]),
                    "tokens_unused": sum(1 for t in tokens if not t["used"] and not t["revoked"] and not t["is_master"]),
                    "tokens_revoked": sum(1 for t in tokens if t["revoked"]),
                },
                "tokens": tokens,
                "visits": visits,
                "downloads": downloads,
            })

        # Static website files (index.html, admin.html, mobile/*, logo.png)
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        if rel.endswith("/"):
            rel += "index.html"
        target = os.path.abspath(os.path.join(BASE_DIR, rel))
        if not target.startswith(BASE_DIR) or not os.path.isfile(target):
            return self._send_json(404, {"ok": False, "error": "Not found"})
        ext = os.path.splitext(target)[1].lower()
        with open(target, "rb") as f:
            raw = f.read()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        ip = self._client_ip()
        ua = self.headers.get("User-Agent", "")[:240]

        if path == "/api/track/visit":
            with _DB_LOCK:
                conn = _db()
                conn.execute(
                    "INSERT INTO visits (ip, user_agent, page, referrer, ts) VALUES (?, ?, ?, ?, ?)",
                    (ip, ua, str(body.get("page", "/"))[:80], str(body.get("referrer", ""))[:160], now),
                )
                conn.commit()
                conn.close()
            return self._send_json(200, {"ok": True})

        if path == "/api/track/download":
            os_name = "macos" if "mac" in str(body.get("os", "")).lower() else "windows"
            with _DB_LOCK:
                conn = _db()
                conn.execute("INSERT INTO downloads (os, ip, user_agent, ts) VALUES (?, ?, ?, ?)", (os_name, ip, ua, now))
                conn.commit()
                conn.close()
            return self._send_json(200, {"ok": True})

        if path == "/api/activate":
            tok = str(body.get("token", "")).strip().upper()
            mid = str(body.get("machine_id", "")).strip()[:32]
            os_n = str(body.get("os", "")).strip()[:24]
            if not tok:
                return self._send_json(400, {"ok": False, "error": "Token required"})
            with _DB_LOCK:
                conn = _db()
                row = conn.execute("SELECT * FROM tokens WHERE token=?", (tok,)).fetchone()
                if not row:
                    conn.close()
                    return self._send_json(403, {"ok": False, "error": "Invalid activation token."})
                if row["revoked"]:
                    conn.close()
                    return self._send_json(403, {"ok": False, "error": "This token has been revoked."})
                if row["is_master"]:
                    conn.execute("UPDATE tokens SET uses=uses+1, used=1, used_at=?, used_by_machine=? WHERE token=?", (now, mid, tok))
                    conn.commit()
                    conn.close()
                    return self._send_json(200, {"ok": True, "is_master": True, "message": "Master token verified!"})
                if row["used"] and row["used_by_machine"] and mid and row["used_by_machine"] != mid:
                    conn.close()
                    return self._send_json(403, {"ok": False, "error": "Token already used on another device."})
                conn.execute(
                    "UPDATE tokens SET used=1, uses=uses+1, used_by_machine=?, used_os=?, used_at=? WHERE token=?",
                    (mid, os_n, now, tok),
                )
                conn.commit()
                conn.close()
            return self._send_json(200, {"ok": True, "is_master": False, "message": "Token verified!"})

        if path == "/api/admin/login":
            u = str(body.get("username", "")).strip()
            p = str(body.get("password", "")).strip()
            if hmac.compare_digest(u, ADMIN_USER) and hmac.compare_digest(p, ADMIN_PASS):
                return self._send_json(200, {"ok": True, "token": _sign_session(u)})
            return self._send_json(401, {"ok": False, "error": "Invalid admin credentials"})

        if path == "/api/admin/tokens":
            if not self._is_admin():
                return self._send_json(401, {"ok": False, "error": "Unauthorized"})
            act = str(body.get("action", ""))
            tok = str(body.get("token", "")).strip().upper()
            with _DB_LOCK:
                conn = _db()
                if act == "generate":
                    count = max(1, min(100, int(body.get("count", 10))))
                    created = []
                    for _ in range(count * 3):
                        if len(created) >= count:
                            break
                        nt = _gen_random_token()
                        try:
                            conn.execute("INSERT INTO tokens (token, is_master, created_at) VALUES (?, 0, ?)", (nt, now))
                            created.append(nt)
                        except sqlite3.IntegrityError:
                            continue
                    conn.commit()
                    conn.close()
                    return self._send_json(200, {"ok": True, "created": created})
                elif act == "revoke" and tok:
                    conn.execute("UPDATE tokens SET revoked=1 WHERE token=? AND is_master=0", (tok,))
                elif act == "unrevoke" and tok:
                    conn.execute("UPDATE tokens SET revoked=0 WHERE token=?", (tok,))
                elif act == "reset" and tok:
                    conn.execute("UPDATE tokens SET used=0, used_by_machine='', used_os='', used_at='' WHERE token=?", (tok,))
                elif act == "clear_logs":
                    conn.execute("DELETE FROM visits")
                    conn.execute("DELETE FROM downloads")
                conn.commit()
                conn.close()
            return self._send_json(200, {"ok": True})

        return self._send_json(404, {"ok": False, "error": "Not found"})


def main():
    init_db()
    port = int(os.environ.get("PORT", "8090"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), AdminHandler)
    print(f"SoulsLights Admin & Token Server running on http://0.0.0.0:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
