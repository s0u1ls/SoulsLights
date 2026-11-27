import io
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from core.platform_utils import get_resource_path


def get_lan_ip() -> str:
    """Returns the host's primary LAN IPv4 address for local Wi-Fi iPad/mobile access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


class MobileCompanionServer:
    """Built-in local Wi-Fi web server so iPad, iPhone & Android can run SoulsLights in Safari/Chrome."""

    def __init__(self, config_manager, engine_ctrl, media_monitor, on_remote_change=None, port: int = 8765):
        self.cfg_mgr = config_manager
        self.engine = engine_ctrl
        self.media_mon = media_monitor
        self.on_remote_change = on_remote_change
        self.preferred_port = int(port)
        self.port = int(port)
        self.httpd = None
        self.thread = None
        self.running = False
        self._art_cache = {"sig": None, "bytes": b""}
        self._art_lock = threading.Lock()

    def get_url(self) -> str:
        return f"http://{get_lan_ip()}:{self.port}"

    def _get_art_jpeg(self) -> bytes:
        info = self.media_mon.current_info if self.media_mon else {}
        sig = (info.get("title", ""), info.get("artist", ""), info.get("album", ""))
        thumb = info.get("thumbnail_img")
        with self._art_lock:
            if self._art_cache["sig"] == sig and self._art_cache["bytes"]:
                return self._art_cache["bytes"]
        if thumb is None:
            return b""
        try:
            buf = io.BytesIO()
            thumb.convert("RGB").save(buf, format="JPEG", quality=86)
            raw = buf.getvalue()
            with self._art_lock:
                self._art_cache = {"sig": sig, "bytes": raw}
            return raw
        except Exception:
            return b""

    def _build_state_payload(self) -> dict:
        cfg = self.cfg_mgr.config
        amb = cfg.get("ambient", {})
        lyr = cfg.get("lyrics", {})
        info = dict(self.media_mon.current_info) if self.media_mon else {}
        live_pos = self.media_mon.get_live_position_sec() if self.media_mon else 0.0

        eng = self.engine.lyrics_engine if self.engine else None
        if eng is not None:
            with eng._lock:
                lines = list(eng.current_lyrics)
                l_status = eng.lyrics_status
                accent_rgb = eng.accent_color
                sec_rgb = eng.secondary_color
                style = eng.style
                script_mode = eng.script_mode
                font_scale = eng.font_scale
                offset_sec = eng.offset_sec
        else:
            lines = []
            l_status = "Idle"
            accent_rgb = (236, 72, 153)
            sec_rgb = (99, 102, 241)
            style = lyr.get("style", "Fisheye Visual")
            script_mode = lyr.get("script_mode", "Auto")
            font_scale = float(lyr.get("font_scale", 1.0))
            offset_sec = float(lyr.get("sync_offset_ms", 0)) / 1000.0

        colors = list(info.get("colors") or ["#6366F1", "#EC4899", "#8B5CF6"])
        if amb.get("override_album_color", False):
            custom = list(amb.get("custom_colors") or [amb.get("color_1", "#6366F1"), amb.get("color_2", "#EC4899")])
            if custom:
                colors = custom

        return {
            "title": info.get("title", "No Active Music"),
            "artist": info.get("artist", ""),
            "album": info.get("album", ""),
            "source": info.get("source", "Idle"),
            "status": info.get("status", "Idle"),
            "is_playing": bool(info.get("is_playing", False)),
            "position_sec": round(float(live_pos), 3),
            "duration_sec": round(float(info.get("duration_sec", 0.0)), 3),
            "has_art": info.get("thumbnail_img") is not None,
            "colors": colors,
            "accent": f"#{accent_rgb[0]:02X}{accent_rgb[1]:02X}{accent_rgb[2]:02X}",
            "secondary": f"#{sec_rgb[0]:02X}{sec_rgb[1]:02X}{sec_rgb[2]:02X}",
            "lyrics_style": style,
            "script_mode": script_mode,
            "font_scale": font_scale,
            "offset_sec": offset_sec,
            "lyrics_status": l_status,
            "glow_enabled": bool(cfg.get("ambient_enabled", True)),
            "backdrop_mode": amb.get("album_backdrop", "Desktop Layer"),
            "lyrics": lines,
            "styles": [
                "Fisheye Visual", "Native Design", "Web", "Constellation",
                "Visual", "Branches", "Codestyle Visual", "Flashbang Visual",
                "Ship", "Apple Design", "Minimal",
            ],
            "server_ts": time.time(),
        }

    def _handle_control(self, body: dict) -> dict:
        act = (body.get("action") or "").strip()
        val = body.get("value")
        if act == "play_pause" and self.media_mon:
            self.media_mon.send_play_pause()
        elif act == "next" and self.media_mon:
            self.media_mon.send_next()
        elif act == "previous" and self.media_mon:
            self.media_mon.send_previous()
        elif act == "set_style" and isinstance(val, str) and val:
            self.cfg_mgr.config["lyrics"]["style"] = val
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.lyrics_engine.set_style(val)
        elif act == "set_script_mode" and val in ("Auto", "Native", "Romanized"):
            self.cfg_mgr.config["lyrics"]["script_mode"] = val
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.lyrics_engine.set_script_mode(val)
        elif act == "set_font_scale" and val is not None:
            sc = max(0.6, min(2.8, round(float(val), 2)))
            self.cfg_mgr.config["lyrics"]["font_scale"] = sc
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.lyrics_engine.set_font_scale(sc)
        elif act == "refresh_lyrics" and self.engine:
            self.engine.lyrics_engine.force_refresh_lyrics()
        elif act == "toggle_glow":
            cur = bool(self.cfg_mgr.config.get("ambient_enabled", True))
            self.cfg_mgr.config["ambient_enabled"] = not cur
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.sync_state(
                    self.cfg_mgr.config.get("master_enabled", True),
                    self.cfg_mgr.config["ambient_enabled"],
                    self.cfg_mgr.config.get("lyrics_enabled", True),
                )
        elif act == "cycle_backdrop" and self.engine:
            self.engine.cycle_backdrop_mode()
        else:
            return {"ok": False, "error": f"Unknown action: {act}"}

        if self.on_remote_change and act not in ("play_pause", "next", "previous"):
            try:
                self.on_remote_change()
            except Exception:
                pass
        return {"ok": True}

    def _make_handler(self):
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _send(self, code: int, content_type: str, data: bytes, cache: str = "no-store"):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", cache)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                path = urlparse(self.path).path
                if path in ("/", "/index.html"):
                    html_p = get_resource_path(os.path.join("mobile", "index.html"))
                    if os.path.exists(html_p):
                        with open(html_p, "rb") as f:
                            self._send(200, "text/html; charset=utf-8", f.read())
                    else:
                        self._send(404, "text/plain", b"mobile/index.html not found")
                elif path == "/manifest.json":
                    manifest = {
                        "name": "SoulsLights",
                        "short_name": "SoulsLights",
                        "start_url": "/",
                        "display": "fullscreen",
                        "orientation": "any",
                        "background_color": "#090812",
                        "theme_color": "#090812",
                        "icons": [
                            {"src": "/icon.png", "sizes": "512x512", "type": "image/png"},
                        ],
                    }
                    self._send(200, "application/manifest+json; charset=utf-8", json.dumps(manifest).encode("utf-8"))
                elif path == "/icon.png":
                    icon_p = get_resource_path(os.path.join("assets", "app_icon.png"))
                    if os.path.exists(icon_p):
                        with open(icon_p, "rb") as f:
                            self._send(200, "image/png", f.read(), cache="public, max-age=86400")
                    else:
                        self._send(404, "text/plain", b"")
                elif path == "/api/state":
                    payload = json.dumps(srv._build_state_payload(), ensure_ascii=False).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", payload)
                elif path == "/api/art":
                    raw = srv._get_art_jpeg()
                    if raw:
                        self._send(200, "image/jpeg", raw)
                    else:
                        self._send(404, "text/plain", b"")
                else:
                    self._send(404, "text/plain", b"Not Found")

            def do_POST(self):
                path = urlparse(self.path).path
                if path == "/api/control":
                    ln = int(self.headers.get("Content-Length", "0") or 0)
                    raw = self.rfile.read(min(ln, 16384)) if ln > 0 else b"{}"
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except Exception:
                        body = {}
                    res = srv._handle_control(body if isinstance(body, dict) else {})
                    self._send(200, "application/json; charset=utf-8", json.dumps(res).encode("utf-8"))
                else:
                    self._send(404, "text/plain", b"Not Found")

        return Handler

    def start(self):
        if self.running:
            return
        handler_cls = self._make_handler()
        for p in range(self.preferred_port, self.preferred_port + 6):
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", p), handler_cls)
                self.port = p
                self.running = True
                self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
                self.thread.start()
                return
            except OSError:
                continue

    def stop(self):
        self.running = False
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
