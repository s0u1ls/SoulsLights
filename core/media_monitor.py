import asyncio
import ctypes
import io
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import colorsys
from PIL import Image

from core.platform_utils import IS_MAC, IS_WIN, get_app_data_dir

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


def _urlopen(req_or_url, timeout: float = 3.5):
    return urllib.request.urlopen(req_or_url, timeout=timeout, context=_SSL_CTX)

MUSIC_APP_HINTS = (
    "spotify", "applemusic", "itunes", "music", "tidal",
    "foobar", "musicbee", "aimp", "youtubemusic", "deezer", "qobuz", "vlc",
)


def _is_music_app(source_id: str) -> bool:
    s = (source_id or "").lower()
    return any(h in s for h in MUSIC_APP_HINTS)


def _format_source_name(source_id: str) -> str:
    if not source_id:
        return "System Media"
    low = source_id.lower()
    if "spotify" in low:
        return "Spotify"
    if "applemusic" in low or "itunes" in low or "com.apple.music" in low:
        return "Apple Music"
    if "chrome" in low:
        return "Chrome"
    if "msedge" in low or "edge" in low:
        return "Edge"
    if "safari" in low:
        return "Safari"
    if "arc" in low or "thebrowser" in low:
        return "Arc"
    if "firefox" in low:
        return "Firefox"
    if "vlc" in low:
        return "VLC"
    if "music" in low:
        return "Music"
    name = source_id.split("!")[0].split(".")[-1]
    return name.replace(".exe", "")[:18]


def _boost_vibrancy(r, g, b, sat_mul=1.38):
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    s = min(1.0, max(0.35, s * sat_mul)) if s > 0.05 else s
    v = min(1.0, max(0.50, v * 1.12))
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    return int(nr * 255), int(ng * 255), int(nb * 255)


def _extract_colors_from_pil(img: Image.Image):
    default_colors = ["#6366F1", "#EC4899", "#8B5CF6"]
    if img is None:
        return default_colors, None
    try:
        img = img.convert("RGB")
        small_img = img.resize((40, 40), Image.Resampling.BILINEAR)
        q = small_img.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = q.getpalette() or []
        counts = q.getcolors() or []
        counts.sort(key=lambda x: x[0], reverse=True)

        hex_colors = []
        for _, color_idx in counts:
            base = color_idx * 3
            if base + 2 >= len(palette):
                continue
            r, g, b = palette[base], palette[base + 1], palette[base + 2]
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            if 20 < luminance < 240:
                vr, vg, vb = _boost_vibrancy(r, g, b)
                hx = f"#{vr:02X}{vg:02X}{vb:02X}"
                if hx not in hex_colors:
                    hex_colors.append(hx)
            if len(hex_colors) >= 3:
                break

        if not hex_colors:
            hex_colors = list(default_colors)
        elif len(hex_colors) == 1:
            r, g, b = int(hex_colors[0][1:3], 16), int(hex_colors[0][3:5], 16), int(hex_colors[0][5:7], 16)
            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.14) % 1.0, min(1.0, s * 1.1), max(0.35, v * 0.7))
            hex_colors.append(f"#{int(r2*255):02X}{int(g2*255):02X}{int(b2*255):02X}")

        while len(hex_colors) < 3:
            hex_colors.append(hex_colors[0])

        return hex_colors[:3], img
    except Exception:
        return default_colors, None


class MediaMonitor:
    """Universal media state & album artwork monitor (Windows SMTC + macOS + optional Spotify OAuth API)."""

    def __init__(self, on_update_callback=None, player_preference="Music Apps First", config_manager=None):
        self.on_update_callback = on_update_callback
        self.player_preference = player_preference
        self.cfg_mgr = config_manager
        self.running = False
        self.thread = None
        self.loop = None
        self.manager = None
        self._active_session = None

        # macOS / media cache state
        self._mac_active_app = ""
        self._mac_art_cache = {}  # key -> (colors, PIL.Image)
        self._mv_cache = {}       # (artist, title) -> mp4/m4v url

        self._anchor_pos_sec = 0.0
        self._anchor_mono = time.perf_counter()
        self._is_playing = False
        self._duration_sec = 0.0

        self.current_info = {
            "title": "No Active Music",
            "artist": "Play a track in Spotify, Apple Music, or browser",
            "album": "",
            "source": "Idle",
            "status": "Idle",
            "is_playing": False,
            "position_sec": 0.0,
            "duration_sec": 0.0,
            "position_str": "0:00",
            "duration_str": "0:00",
            "progress": 0.0,
            "colors": ["#6366F1", "#EC4899", "#8B5CF6"],
            "thumbnail_img": None,
            "music_video_url": "",
            "track_changed": False,
        }

    def fetch_music_video_url(self, title: str, artist: str = "") -> str:
        """Looks up an official 1080p HTTPS music video stream matching title + artist."""
        clean_t = (title or "").strip()
        clean_a = (artist or "").split(",")[0].strip()
        if not clean_t or clean_t in ("No Active Music", "No Media Playing", "Unknown Track"):
            return ""
        ck = (clean_a.lower(), clean_t.lower())
        if ck in self._mv_cache:
            return self._mv_cache[ck]

        import re as _re
        t_norm = _re.sub(r"\s*[\(\[].*?[\)\]]", "", clean_t).strip() or clean_t
        t_toks = [w for w in _re.findall(r"[a-z0-9]+", t_norm.lower()) if len(w) >= 2]
        a_toks = [w for w in _re.findall(r"[a-z0-9]+", clean_a.lower()) if len(w) >= 2]

        best_url = ""
        best_score = -1
        for query in (f"{clean_a} {t_norm}".strip(), t_norm):
            try:
                q = urllib.parse.urlencode({"term": query, "entity": "musicVideo", "limit": 6})
                req = urllib.request.Request(
                    f"https://itunes.apple.com/search?{q}",
                    headers={"User-Agent": "SoulsLights/2.3"},
                )
                with _urlopen(req, timeout=4.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                for item in (data.get("results") or []):
                    pv = (item.get("previewUrl") or "").strip()
                    if not pv:
                        continue
                    it_t = (item.get("trackName") or "").lower()
                    it_a = (item.get("artistName") or "").lower()
                    t_hits = sum(1 for tk in t_toks if tk in it_t)
                    a_hits = sum(1 for ak in a_toks if ak in it_a)
                    if t_toks and t_hits == 0:
                        continue
                    if a_toks and a_hits == 0:
                        continue
                    score = t_hits * 3 + a_hits * 4
                    if "official" in it_t or t_norm.lower() in it_t:
                        score += 2
                    if score > best_score:
                        best_score = score
                        best_url = pv
                if best_url:
                    break
            except Exception:
                continue

        if len(self._mv_cache) > 48:
            self._mv_cache.clear()
        self._mv_cache[ck] = best_url
        return best_url

    def _refresh_spotify_token(self) -> str:
        if not self.cfg_mgr:
            return ""
        sp = self.cfg_mgr.config.get("spotify", {})
        cid = (sp.get("client_id") or "").strip()
        tok = (sp.get("access_token") or "").strip()
        ref = (sp.get("refresh_token") or "").strip()
        exp = float(sp.get("expires_at") or 0)
        if tok and time.time() * 1000 < exp - 60000:
            return tok
        if not (cid and ref):
            return ""
        try:
            body = urllib.parse.urlencode({
                "client_id": cid,
                "grant_type": "refresh_token",
                "refresh_token": ref,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://accounts.spotify.com/api/token",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "SoulsLights/2.3"},
                method="POST",
            )
            with _urlopen(req, timeout=5.0) as resp:
                d = json.loads(resp.read().decode("utf-8"))
            if d.get("access_token"):
                sp["access_token"] = d["access_token"]
                if d.get("refresh_token"):
                    sp["refresh_token"] = d["refresh_token"]
                sp["expires_at"] = int(time.time() * 1000 + float(d.get("expires_in", 3600)) * 1000)
                self.cfg_mgr.save_config()
                return sp["access_token"]
        except Exception:
            pass
        return ""

    def _poll_spotify_web_api(self):
        tok = self._refresh_spotify_token()
        if not tok:
            return None
        try:
            req = urllib.request.Request(
                "https://api.spotify.com/v1/me/player?additional_types=track",
                headers={"Authorization": f"Bearer {tok}", "User-Agent": "SoulsLights/2.3"},
            )
            with _urlopen(req, timeout=4.0) as resp:
                if resp.status == 204:
                    return None
                p = json.loads(resp.read().decode("utf-8"))
            item = (p or {}).get("item")
            if not item:
                return None
            title = (item.get("name") or "").strip() or "Unknown Track"
            artist = ", ".join(a.get("name", "") for a in (item.get("artists") or []) if a.get("name")) or "Unknown Artist"
            album = ((item.get("album") or {}).get("name") or "").strip()
            imgs = (item.get("album") or {}).get("images") or []
            art_url = imgs[0].get("url", "") if imgs else ""
            is_playing = bool(p.get("is_playing", False))
            pos_sec = float(p.get("progress_ms") or 0) / 1000.0
            dur_sec = float(item.get("duration_ms") or 0) / 1000.0
            return {
                "title": title,
                "artist": artist,
                "album": album,
                "art_url": art_url,
                "status": "Playing" if is_playing else "Paused",
                "is_playing": is_playing,
                "position_sec": pos_sec,
                "duration_sec": dur_sec,
                "app_key": "spotify",
                "source": "Spotify",
            }
        except Exception:
            return None

    def set_player_preference(self, pref: str):
        self.player_preference = pref

    def get_live_position_sec(self) -> float:
        if self._is_playing:
            elapsed = max(0.0, time.perf_counter() - self._anchor_mono)
            pos = self._anchor_pos_sec + elapsed
        else:
            pos = self._anchor_pos_sec
        if self._duration_sec > 0:
            pos = min(self._duration_sec, pos)
        return max(0.0, pos)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _run_loop(self):
        if IS_MAC:
            self._poll_loop_mac()
            return
        if not IS_WIN:
            return
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._poll_loop_win())
        finally:
            self.loop.close()

    def _commit_idle_state(self, last_status):
        self._is_playing = False
        self._anchor_pos_sec = 0.0
        self._duration_sec = 0.0
        if last_status != "Idle":
            self.current_info["title"] = "No Active Music"
            self.current_info["artist"] = "Play a track in Spotify, Apple Music, or browser"
            self.current_info["album"] = ""
            self.current_info["source"] = "Idle"
            self.current_info["status"] = "Idle"
            self.current_info["is_playing"] = False
            self.current_info["position_sec"] = 0.0
            self.current_info["duration_sec"] = 0.0
            self.current_info["position_str"] = "0:00"
            self.current_info["duration_str"] = "0:00"
            self.current_info["progress"] = 0.0
            self.current_info["thumbnail_img"] = None
            self.current_info["music_video_url"] = ""
            self.current_info["colors"] = ["#6366F1", "#EC4899", "#8B5CF6"]
            self.current_info["track_changed"] = True
            if self.on_update_callback:
                self.on_update_callback(dict(self.current_info))
            return "Idle", None
        return last_status, None

    # ---- Windows WinRT SMTC Implementation ----
    def _pick_best_session_win(self):
        if not self.manager:
            return None
        try:
            sessions = list(self.manager.get_sessions())
        except Exception:
            sessions = []

        if not sessions:
            try:
                return self.manager.get_current_session()
            except Exception:
                return None

        pref = self.player_preference
        scored = []
        for s in sessions:
            try:
                pb = s.get_playback_info()
                playing = bool(pb and int(pb.playback_status) == 4)
                paused = bool(pb and int(pb.playback_status) == 5)
                src = s.source_app_user_model_id or ""
                is_music = _is_music_app(src)
                is_spotify = "spotify" in src.lower()

                if pref == "Music Apps Only" and not is_music:
                    continue

                score = 0
                if playing:
                    score += 100
                elif paused:
                    score += 20
                if pref in ("Music Apps First", "Music Apps Only"):
                    if is_music:
                        score += 40
                    if is_spotify:
                        score += 10
                scored.append((score, s))
            except Exception:
                continue

        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _resolve_mv_async(self, track_sig, title: str, artist: str):
        def _run():
            mv_url = self.fetch_music_video_url(title, artist)
            cur_sig = (self.current_info.get("title", ""), self.current_info.get("artist", ""), self.current_info.get("album", ""))
            if cur_sig[:2] == track_sig[:2] and mv_url:
                self.current_info["music_video_url"] = mv_url
                self.current_info["track_changed"] = False
                if self.on_update_callback:
                    self.on_update_callback(dict(self.current_info))
        threading.Thread(target=_run, daemon=True).start()

    async def _poll_loop_win(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SMTCManager
        try:
            self.manager = await SMTCManager.request_async()
        except Exception as e:
            print(f"[MediaMonitor] Manager init error: {e}")
            return

        last_track_sig = None
        last_status = None
        last_sp_poll = 0.0
        cached_sp = None

        while self.running:
            try:
                session = self._pick_best_session_win()
                self._active_session = session

                if session:
                    props = await session.try_get_media_properties_async()
                    pb = session.get_playback_info()
                    timeline = session.get_timeline_properties()

                    status_str = "Stopped"
                    is_playing = False
                    if pb:
                        code = int(pb.playback_status)
                        if code == 4:
                            status_str = "Playing"
                            is_playing = True
                        elif code == 5:
                            status_str = "Paused"

                    source_app = _format_source_name(session.source_app_user_model_id)
                    title = (props.title if props and props.title else "").strip() or "Unknown Track"
                    artist = (props.artist if props and props.artist else "").strip() or "Unknown Artist"
                    album = (props.album_title if props and props.album_title else "").strip()

                    base_pos = timeline.position.total_seconds() if timeline and timeline.position else 0.0
                    end_sec = timeline.end_time.total_seconds() if timeline and timeline.end_time else 0.0
                    live_pos = base_pos

                    if is_playing and timeline and timeline.last_updated_time:
                        try:
                            lu = timeline.last_updated_time
                            if lu.tzinfo is None:
                                lu = lu.replace(tzinfo=timezone.utc)
                            delta = (datetime.now(timezone.utc) - lu).total_seconds()
                            if -2.0 <= delta < 14400.0:
                                live_pos = base_pos + max(0.0, delta)
                        except Exception:
                            pass

                    if end_sec > 0:
                        live_pos = min(end_sec, max(0.0, live_pos))

                    track_sig = (title, artist, album)
                    track_changed = (track_sig != last_track_sig)
                    status_changed = (status_str != last_status)

                    if is_playing and not track_changed and not status_changed:
                        pred_pos = self.get_live_position_sec()
                        err = live_pos - pred_pos
                        if abs(err) <= 0.45:
                            self._anchor_pos_sec = pred_pos + err * 0.28
                        else:
                            self._anchor_pos_sec = live_pos
                    else:
                        self._anchor_pos_sec = live_pos
                    self._anchor_mono = time.perf_counter()
                    self._is_playing = is_playing
                    self._duration_sec = end_sec

                    if track_changed:
                        last_track_sig = track_sig
                        colors, thumb_img = await self._extract_colors_and_thumb_win(props)
                        self.current_info["colors"] = colors
                        self.current_info["thumbnail_img"] = thumb_img
                        self.current_info["music_video_url"] = ""
                        self._resolve_mv_async(track_sig, title, artist)

                    last_status = status_str
                    progress = (live_pos / end_sec) if end_sec > 0 else 0.0

                    self.current_info["title"] = title
                    self.current_info["artist"] = artist
                    self.current_info["album"] = album
                    self.current_info["source"] = source_app
                    self.current_info["status"] = status_str
                    self.current_info["is_playing"] = is_playing
                    self.current_info["position_sec"] = live_pos
                    self.current_info["duration_sec"] = end_sec
                    self.current_info["position_str"] = f"{int(live_pos // 60)}:{int(live_pos % 60):02d}"
                    self.current_info["duration_str"] = f"{int(end_sec // 60)}:{int(end_sec % 60):02d}"
                    self.current_info["progress"] = min(1.0, max(0.0, progress))
                    self.current_info["track_changed"] = track_changed or status_changed

                    if self.on_update_callback:
                        self.on_update_callback(dict(self.current_info))
                else:
                    now_sp = time.perf_counter()
                    if now_sp - last_sp_poll >= 1.25:
                        last_sp_poll = now_sp
                        cached_sp = self._poll_spotify_web_api()
                    if cached_sp:
                        trk = cached_sp
                        title, artist, album = trk["title"], trk["artist"], trk["album"]
                        status_str, is_playing = trk["status"], trk["is_playing"]
                        live_pos, end_sec = trk["position_sec"], trk["duration_sec"]
                        track_sig = (title, artist, album)
                        track_changed = (track_sig != last_track_sig)
                        status_changed = (status_str != last_status)
                        self._anchor_pos_sec = live_pos
                        self._anchor_mono = time.perf_counter()
                        self._is_playing = is_playing
                        self._duration_sec = end_sec
                        if track_changed:
                            last_track_sig = track_sig
                            colors, thumb_img = self._fetch_mac_art_and_colors(trk)
                            self.current_info["colors"] = colors
                            self.current_info["thumbnail_img"] = thumb_img
                            self.current_info["music_video_url"] = ""
                            self._resolve_mv_async(track_sig, title, artist)
                        last_status = status_str
                        progress = (live_pos / end_sec) if end_sec > 0 else 0.0
                        self.current_info.update({
                            "title": title, "artist": artist, "album": album,
                            "source": "Spotify", "status": status_str, "is_playing": is_playing,
                            "position_sec": live_pos, "duration_sec": end_sec,
                            "position_str": f"{int(live_pos // 60)}:{int(live_pos % 60):02d}",
                            "duration_str": f"{int(end_sec // 60)}:{int(end_sec % 60):02d}",
                            "progress": min(1.0, max(0.0, progress)),
                            "track_changed": track_changed or status_changed,
                        })
                        if self.on_update_callback:
                            self.on_update_callback(dict(self.current_info))
                    else:
                        last_status, last_track_sig = self._commit_idle_state(last_status)
            except Exception:
                pass
            await asyncio.sleep(0.4)

    async def _extract_colors_and_thumb_win(self, props):
        from winrt.windows.storage.streams import DataReader
        default_colors = ["#6366F1", "#EC4899", "#8B5CF6"]
        if not props or not props.thumbnail:
            return default_colors, None
        try:
            stream = await props.thumbnail.open_read_async()
            size = int(stream.size)
            if size <= 0:
                return default_colors, None
            reader = DataReader(stream)
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            img = Image.open(io.BytesIO(buf)).convert("RGB")
            return _extract_colors_from_pil(img)
        except Exception:
            return default_colors, None

    # ---- macOS Multi-Source Media Monitor (Spotify + Apple Music + MediaRemote fallback) ----
    def _mac_running_bundle_ids(self) -> set:
        try:
            import AppKit
            apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications()
            return {str(a.bundleIdentifier() or "") for a in apps if a}
        except Exception:
            out = set()
            for pname, bid in (("Spotify", "com.spotify.client"), ("Music", "com.apple.Music")):
                try:
                    if subprocess.run(["pgrep", "-x", pname], capture_output=True).returncode == 0:
                        out.add(bid)
                except Exception:
                    pass
            return out

    def _run_osascript(self, script: str, timeout: float = 1.5) -> str:
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=timeout,
            )
            if res.returncode == 0:
                return (res.stdout or "").strip()
        except Exception:
            pass
        return ""

    def _query_mac_spotify(self):
        script = (
            'tell application "Spotify"\n'
            'if not running then return ""\n'
            'set ps to (player state as string)\n'
            'if ps is "stopped" then return "stopped"\n'
            'set t to name of current track\n'
            'set ar to artist of current track\n'
            'set al to album of current track\n'
            'set d to duration of current track\n'
            'set p to player position\n'
            'set u to ""\n'
            'try\nset u to artwork url of current track\nend try\n'
            'return ps & "||~||" & t & "||~||" & ar & "||~||" & al & "||~||" & d & "||~||" & p & "||~||" & u\n'
            'end tell'
        )
        raw = self._run_osascript(script)
        if not raw or raw == "stopped":
            return None
        parts = raw.split("||~||")
        if len(parts) < 6:
            return None
        ps, title, artist, album, dur_s, pos_s = parts[:6]
        art_url = parts[6] if len(parts) > 6 else ""
        try:
            dur = float(dur_s.replace(",", ".")) / 1000.0
        except Exception:
            dur = 0.0
        try:
            pos = float(pos_s.replace(",", "."))
        except Exception:
            pos = 0.0
        is_play = (ps.lower() == "playing")
        status = "Playing" if is_play else ("Paused" if ps.lower() == "paused" else "Stopped")
        return {
            "app_key": "spotify",
            "source": "Spotify",
            "status": status,
            "is_playing": is_play,
            "title": title.strip() or "Unknown Track",
            "artist": artist.strip() or "Unknown Artist",
            "album": album.strip(),
            "duration_sec": max(0.0, dur),
            "position_sec": max(0.0, pos),
            "art_url": art_url.strip(),
        }

    def _query_mac_music(self):
        script = (
            'tell application "Music"\n'
            'if not running then return ""\n'
            'set ps to (player state as string)\n'
            'if ps is "stopped" then return "stopped"\n'
            'set t to name of current track\n'
            'set ar to artist of current track\n'
            'set al to album of current track\n'
            'set d to duration of current track\n'
            'set p to player position\n'
            'return ps & "||~||" & t & "||~||" & ar & "||~||" & al & "||~||" & d & "||~||" & p\n'
            'end tell'
        )
        raw = self._run_osascript(script)
        if not raw or raw == "stopped":
            return None
        parts = raw.split("||~||")
        if len(parts) < 6:
            return None
        ps, title, artist, album, dur_s, pos_s = parts[:6]
        try:
            dur = float(dur_s.replace(",", "."))
        except Exception:
            dur = 0.0
        try:
            pos = float(pos_s.replace(",", "."))
        except Exception:
            pos = 0.0
        is_play = (ps.lower() == "playing")
        status = "Playing" if is_play else ("Paused" if ps.lower() == "paused" else "Stopped")
        return {
            "app_key": "music",
            "source": "Apple Music",
            "status": status,
            "is_playing": is_play,
            "title": title.strip() or "Unknown Track",
            "artist": artist.strip() or "Unknown Artist",
            "album": album.strip(),
            "duration_sec": max(0.0, dur),
            "position_sec": max(0.0, pos),
            "art_url": "",
        }

    def _fetch_mac_art_and_colors(self, track: dict):
        default_colors = ["#6366F1", "#EC4899", "#8B5CF6"]
        url = (track.get("art_url") or "").strip()
        cache_key = url or f"{track['app_key']}::{track['artist']}::{track['title']}"
        if cache_key in self._mac_art_cache:
            return self._mac_art_cache[cache_key]

        img = None
        if url:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SoulsLights/2.2"})
                with _urlopen(req, timeout=3.5) as resp:
                    img = Image.open(io.BytesIO(resp.read())).convert("RGB")
            except Exception:
                img = None

        if img is None and track["app_key"] == "music":
            tmp_art = os.path.join(get_app_data_dir(), "_apple_cover.bin")
            art_script = (
                f'set fp to POSIX file "{tmp_art}"\n'
                'tell application "Music"\n'
                'if (count of artworks of current track) > 0 then\n'
                'set artData to raw data of artwork 1 of current track\n'
                'set refNum to open for access fp with write permission\n'
                'set eof refNum to 0\n'
                'write artData to refNum\n'
                'close access refNum\n'
                'return "ok"\n'
                'end if\n'
                'end tell'
            )
            if self._run_osascript(art_script, timeout=2.5) == "ok" and os.path.exists(tmp_art):
                try:
                    img = Image.open(tmp_art).convert("RGB")
                except Exception:
                    img = None

        if img is None and track.get("title"):
            try:
                q = urllib.parse.urlencode({
                    "term": f"{track.get('artist', '')} {track['title']}",
                    "entity": "song",
                    "limit": 1,
                })
                req = urllib.request.Request(
                    f"https://itunes.apple.com/search?{q}",
                    headers={"User-Agent": "SoulsLights/2.2"},
                )
                with _urlopen(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results") or []
                if results:
                    aw = (results[0].get("artworkUrl100") or "").replace("100x100", "600x600")
                    if aw:
                        with _urlopen(aw, timeout=3.5) as r2:
                            img = Image.open(io.BytesIO(r2.read())).convert("RGB")
            except Exception:
                img = None

        res = _extract_colors_from_pil(img) if img is not None else (default_colors, None)
        if len(self._mac_art_cache) > 24:
            self._mac_art_cache.clear()
        self._mac_art_cache[cache_key] = res
        return res

    def _pick_best_mac_track(self):
        running = self._mac_running_bundle_ids()
        candidates = []
        if "com.spotify.client" in running:
            sp = self._query_mac_spotify()
            if sp:
                sc = (100 if sp["is_playing"] else 20) + 50
                candidates.append((sc, sp))
        if "com.apple.Music" in running:
            am = self._query_mac_music()
            if am:
                sc = (100 if am["is_playing"] else 20) + 40
                candidates.append((sc, am))
        if not candidates:
            return None
        candidates.sort(key=lambda it: it[0], reverse=True)
        return candidates[0][1]

    def _poll_loop_mac(self):
        last_track_sig = None
        last_status = None
        last_sp_poll = 0.0
        cached_sp = None
        while self.running:
            try:
                trk = self._pick_best_mac_track()
                if not trk:
                    now_sp = time.perf_counter()
                    if now_sp - last_sp_poll >= 1.25:
                        last_sp_poll = now_sp
                        cached_sp = self._poll_spotify_web_api()
                    trk = cached_sp
                if trk:
                    self._mac_active_app = trk["app_key"]
                    title = trk["title"]
                    artist = trk["artist"]
                    album = trk["album"]
                    status_str = trk["status"]
                    is_playing = trk["is_playing"]
                    live_pos = trk["position_sec"]
                    end_sec = trk["duration_sec"]
                    if end_sec > 0:
                        live_pos = min(end_sec, max(0.0, live_pos))

                    track_sig = (title, artist, album, trk["app_key"])
                    track_changed = (track_sig != last_track_sig)
                    status_changed = (status_str != last_status)

                    if is_playing and not track_changed and not status_changed:
                        pred_pos = self.get_live_position_sec()
                        err = live_pos - pred_pos
                        if abs(err) <= 0.65:
                            self._anchor_pos_sec = pred_pos + err * 0.25
                        else:
                            self._anchor_pos_sec = live_pos
                    else:
                        self._anchor_pos_sec = live_pos
                    self._anchor_mono = time.perf_counter()
                    self._is_playing = is_playing
                    self._duration_sec = end_sec

                    if track_changed:
                        last_track_sig = track_sig
                        colors, thumb_img = self._fetch_mac_art_and_colors(trk)
                        self.current_info["colors"] = colors
                        self.current_info["thumbnail_img"] = thumb_img
                        self.current_info["music_video_url"] = ""
                        self._resolve_mv_async(track_sig, title, artist)

                    last_status = status_str
                    progress = (live_pos / end_sec) if end_sec > 0 else 0.0
                    self.current_info["title"] = title
                    self.current_info["artist"] = artist
                    self.current_info["album"] = album
                    self.current_info["source"] = trk["source"]
                    self.current_info["status"] = status_str
                    self.current_info["is_playing"] = is_playing
                    self.current_info["position_sec"] = live_pos
                    self.current_info["duration_sec"] = end_sec
                    self.current_info["position_str"] = f"{int(live_pos // 60)}:{int(live_pos % 60):02d}"
                    self.current_info["duration_str"] = f"{int(end_sec // 60)}:{int(end_sec % 60):02d}"
                    self.current_info["progress"] = min(1.0, max(0.0, progress))
                    self.current_info["track_changed"] = track_changed or status_changed
                    if self.on_update_callback:
                        self.on_update_callback(dict(self.current_info))
                else:
                    self._mac_active_app = ""
                    last_status, last_track_sig = self._commit_idle_state(last_status)
            except Exception:
                pass
            time.sleep(0.45)

    # ---- Playback Commands ----
    def _mac_transport(self, cmd: str):
        app = "Spotify" if self._mac_active_app == "spotify" else ("Music" if self._mac_active_app == "music" else "")
        if not app:
            running = self._mac_running_bundle_ids()
            if "com.spotify.client" in running:
                app = "Spotify"
            elif "com.apple.Music" in running:
                app = "Music"
        if app:
            threading.Thread(target=lambda: self._run_osascript(f'tell application "{app}" to {cmd}'), daemon=True).start()

    def send_play_pause(self):
        if IS_MAC:
            self._mac_transport("playpause")
            return
        if self.loop and self.manager:
            asyncio.run_coroutine_threadsafe(self._do_play_pause(), self.loop)

    async def _do_play_pause(self):
        try:
            s = self._active_session or self.manager.get_current_session()
            if s:
                pb = s.get_playback_info()
                if pb and int(pb.playback_status) == 4:
                    await s.try_pause_async()
                else:
                    await s.try_play_async()
        except Exception:
            pass

    def send_next(self):
        if IS_MAC:
            self._mac_transport("next track")
            return
        if self.loop and self.manager:
            asyncio.run_coroutine_threadsafe(self._do_next(), self.loop)

    async def _do_next(self):
        try:
            s = self._active_session or self.manager.get_current_session()
            if s:
                await s.try_skip_next_async()
        except Exception:
            pass

    def send_previous(self):
        if IS_MAC:
            self._mac_transport("previous track")
            return
        if self.loop and self.manager:
            asyncio.run_coroutine_threadsafe(self._do_prev(), self.loop)

    async def _do_prev(self):
        try:
            s = self._active_session or self.manager.get_current_session()
            if s:
                await s.try_skip_previous_async()
        except Exception:
            pass
