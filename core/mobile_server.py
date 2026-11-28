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
        self._sp_verifier = ""
        self._yt_cache = {}

    def get_url(self) -> str:
        return f"http://{get_lan_ip()}:{self.port}"

    def get_spotify_redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/spotify_callback"

    def build_spotify_auth_url(self) -> str:
        import base64, hashlib, secrets
        from urllib.parse import urlencode
        sp = self.cfg_mgr.config.get("spotify", {}) if self.cfg_mgr else {}
        cid = (sp.get("client_id") or "").strip()
        if not cid:
            return ""
        verifier = secrets.token_hex(48)
        self._sp_verifier = verifier
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        qs = urlencode({
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": self.get_spotify_redirect_uri(),
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": "user-read-playback-state user-modify-playback-state user-read-currently-playing",
        })
        return f"https://accounts.spotify.com/authorize?{qs}"

    def complete_spotify_auth(self, code: str, err: str = "") -> tuple[bool, str]:
        if err:
            return False, f"Authorization error: {err}"
        if not code:
            return False, "Missing authorization code from Spotify."
        sp = self.cfg_mgr.config.setdefault("spotify", {}) if self.cfg_mgr else {}
        cid = (sp.get("client_id") or "").strip()
        ver = self._sp_verifier
        if not (cid and ver):
            return False, "Spotify PKCE session expired. Start Connect Spotify again from SoulsLights."
        try:
            from urllib.parse import urlencode
            import urllib.request
            from core.media_monitor import _urlopen
            body = urlencode({
                "client_id": cid,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.get_spotify_redirect_uri(),
                "code_verifier": ver,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://accounts.spotify.com/api/token",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "SoulsLights/2.3"},
                method="POST",
            )
            with _urlopen(req, timeout=8.0) as resp:
                tok = json.loads(resp.read().decode("utf-8"))
            if not tok.get("access_token"):
                return False, tok.get("error_description") or "Spotify did not return an access token."
            sp["access_token"] = tok["access_token"]
            if tok.get("refresh_token"):
                sp["refresh_token"] = tok["refresh_token"]
            sp["expires_at"] = int(time.time() * 1000 + float(tok.get("expires_in", 3600)) * 1000)
            try:
                me_req = urllib.request.Request(
                    "https://api.spotify.com/v1/me",
                    headers={"Authorization": f"Bearer {sp['access_token']}", "User-Agent": "SoulsLights/2.3"},
                )
                with _urlopen(me_req, timeout=5.0) as mr:
                    me = json.loads(mr.read().decode("utf-8"))
                    sp["user_name"] = me.get("display_name") or me.get("id") or "Spotify Connected"
            except Exception:
                sp["user_name"] = sp.get("user_name") or "Spotify Connected"
            if self.cfg_mgr:
                self.cfg_mgr.save_config()
            if self.on_remote_change:
                try:
                    self.on_remote_change()
                except Exception:
                    pass
            return True, f"Signed in as {sp['user_name']}. Music Video backdrop & Spotify sync are ready."
        except Exception as e:
            return False, str(e)

    def _lookup_music_video(self, title: str, artist: str = "") -> dict:
        import re
        from urllib.parse import urlencode
        import urllib.request
        from core.media_monitor import _urlopen
        clean_t = (title or "").strip()
        clean_a = (artist or "").split(",")[0].strip()
        if not clean_t:
            return {"ok": False, "mp4_url": "", "youtube_id": ""}
        mp4_url = self.media_mon.fetch_music_video_url(clean_t, clean_a) if self.media_mon else ""
        ck = (clean_a.lower(), clean_t.lower())
        yt_id = self._yt_cache.get(ck)
        if yt_id is None:
            yt_id = ""
            try:
                q = urlencode({"search_query": f"{clean_a} {clean_t} official music video".strip()})
                req = urllib.request.Request(
                    f"https://www.youtube.com/results?{q}",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                with _urlopen(req, timeout=5.0) as r:
                    html = r.read().decode("utf-8", "ignore")
                m = re.search(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', html)
                if m:
                    yt_id = m.group(1)
            except Exception:
                yt_id = ""
            if len(self._yt_cache) > 48:
                self._yt_cache.clear()
            self._yt_cache[ck] = yt_id
        return {"ok": bool(mp4_url or yt_id), "mp4_url": mp4_url, "youtube_id": yt_id}

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
                fisheye_effect = getattr(eng, "fisheye_effect", "Auto Mix")
                script_mode = eng.script_mode
                font_scale = eng.font_scale
                offset_sec = eng.offset_sec
        else:
            lines = []
            l_status = "Idle"
            accent_rgb = (236, 72, 153)
            sec_rgb = (99, 102, 241)
            style = lyr.get("style", "Fisheye Visual")
            fisheye_effect = lyr.get("fisheye_effect", "Auto Mix")
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
            "music_video_url": info.get("music_video_url", ""),
            "colors": colors,
            "accent": f"#{accent_rgb[0]:02X}{accent_rgb[1]:02X}{accent_rgb[2]:02X}",
            "secondary": f"#{sec_rgb[0]:02X}{sec_rgb[1]:02X}{sec_rgb[2]:02X}",
            "lyrics_style": style,
            "fisheye_effect": fisheye_effect,
            "script_mode": script_mode,
            "font_scale": font_scale,
            "offset_sec": offset_sec,
            "lyrics_status": l_status,
            "lyrics_enabled": bool(cfg.get("lyrics_enabled", True)),
            "glow_enabled": bool(cfg.get("ambient_enabled", True)),
            "flow_mode": amb.get("animation_mode", "Water Drop"),
            "glow_intensity": float(amb.get("glow_intensity", 1.35)),
            "gradient_mode": amb.get("gradient_mode", "Multi Colors"),
            "backdrop_mode": amb.get("album_backdrop", "Desktop Layer"),
            "backdrop_style": amb.get("backdrop_style", "2-Blob Aura"),
            "spotify_connected": bool((cfg.get("spotify") or {}).get("refresh_token") or (cfg.get("spotify") or {}).get("access_token")),
            "lyrics": lines,
            "styles": [
                "Fisheye Visual", "Fisheye", "Visual", "Ship",
                "Codestyle Visual", "Codestyle", "Branches",
                "Web", "Constellation", "Native Design",
                "Apple Design", "Minimal",
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
        elif act == "set_fisheye_effect" and isinstance(val, str) and val:
            self.cfg_mgr.config["lyrics"]["fisheye_effect"] = val
            self.cfg_mgr.save_config()
            if self.engine and hasattr(self.engine.lyrics_engine, "set_fisheye_effect"):
                self.engine.lyrics_engine.set_fisheye_effect(val)
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
        elif act == "toggle_lyrics":
            cur = bool(self.cfg_mgr.config.get("lyrics_enabled", True))
            self.cfg_mgr.config["lyrics_enabled"] = not cur
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.sync_state(
                    self.cfg_mgr.config.get("master_enabled", True),
                    self.cfg_mgr.config.get("ambient_enabled", True),
                    self.cfg_mgr.config["lyrics_enabled"],
                )
        elif act == "nudge_offset" and val is not None:
            cur_ms = int(self.cfg_mgr.config["lyrics"].get("sync_offset_ms", 0))
            nxt_ms = max(-5000, min(5000, cur_ms + int(val)))
            self.cfg_mgr.config["lyrics"]["sync_offset_ms"] = nxt_ms
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.lyrics_engine.set_offset_ms(nxt_ms)
        elif act == "reset_offset":
            self.cfg_mgr.config["lyrics"]["sync_offset_ms"] = 0
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.lyrics_engine.set_offset_ms(0)
        elif act == "set_flow_mode" and val in ("Water Drop", "Liquid Flow", "Aurora Wave", "Neon Prism", "Beat Pulse", "Breathing", "Static"):
            self.cfg_mgr.config["ambient"]["animation_mode"] = val
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.ambient_engine.set_animation_mode(val)
        elif act == "set_glow_intensity" and val is not None:
            gi = max(0.2, min(3.0, round(float(val), 2)))
            self.cfg_mgr.config["ambient"]["glow_intensity"] = gi
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.ambient_engine.set_intensity(gi)
        elif act == "set_gradient_mode" and val in ("Multi Colors", "1 Color"):
            self.cfg_mgr.config["ambient"]["gradient_mode"] = val
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.ambient_engine.set_gradient_mode(val)
        elif act == "set_backdrop_style" and val in ("2-Blob Aura", "Video Reel", "Music Video"):
            self.cfg_mgr.config["ambient"]["backdrop_style"] = val
            self.cfg_mgr.save_config()
            if self.engine:
                self.engine.backdrop_engine.set_backdrop_style(val)
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
                elif path == "/api/music_video":
                    from urllib.parse import parse_qs
                    qs = parse_qs(urlparse(self.path).query)
                    title_q = (qs.get("title") or [""])[0]
                    artist_q = (qs.get("artist") or [""])[0]
                    res = srv._lookup_music_video(title_q, artist_q)
                    self._send(200, "application/json; charset=utf-8", json.dumps(res).encode("utf-8"))
                elif path == "/spotify_connect":
                    auth_url = srv.build_spotify_auth_url()
                    if not auth_url:
                        html_err = b"<html><body style='background:#090812;color:#f8fafc;font-family:sans-serif;padding:40px'><h2>Spotify Client ID Missing</h2><p>Set your Spotify Developer Client ID in SoulsLights Screen settings first.</p></body></html>"
                        self._send(400, "text/html; charset=utf-8", html_err)
                    else:
                        self.send_response(302)
                        self.send_header("Location", auth_url)
                        self.end_headers()
                elif path == "/spotify_callback":
                    from urllib.parse import parse_qs
                    qs = parse_qs(urlparse(self.path).query)
                    code = (qs.get("code") or [""])[0]
                    err = (qs.get("error") or [""])[0]
                    ok_sp, msg_sp = srv.complete_spotify_auth(code, err)
                    col = "#22c55e" if ok_sp else "#f43f5e"
                    body_html = f"""<!doctype html><html><body style="margin:0;background:#07060d;color:#f8fafc;font-family:-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh"><div style="max-width:420px;text-align:center;padding:28px;border-radius:20px;background:#131122;border:1px solid {col}55"><h2 style="color:{col};margin-top:0">{'Spotify Connected!' if ok_sp else 'Spotify Auth Failed'}</h2><p style="color:#cbd5e1;line-height:1.5">{msg_sp}</p><p style="color:#94a3b8;font-size:13px">You can close this browser tab and return to SoulsLights.</p></div></body></html>""".encode("utf-8")
                    self._send(200 if ok_sp else 400, "text/html; charset=utf-8", body_html)
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
