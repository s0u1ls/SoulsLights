import os
import sys
import threading
import time
import json
import math
import random
import ssl
import traceback
import urllib.request
import urllib.parse
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# SSL context for frozen EXE / app bundle (certifi CA bundle)
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    try:
        _SSL_CTX = ssl.create_default_context()
    except Exception:
        _SSL_CTX = None

from core.platform_utils import (
    IS_MAC, IS_WIN, get_app_data_dir, get_monitors,
    get_lyric_font_paths, get_fallback_font_entries,
    load_truetype_safe, load_scalable_default_font
)

if IS_WIN:
    import ctypes
    from ctypes import wintypes
    from core.win32_utils import (
        user32, kernel32, LayeredSurface, SystemAudioMeter,
        enable_high_res_timer, disable_high_res_timer,
        WNDCLASSEXW, WNDPROC, RECT,
        WS_POPUP, WS_VISIBLE, WS_EX_LAYERED, WS_EX_TRANSPARENT,
        WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_NOACTIVATE,
        GWL_EXSTYLE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED,
        HWND_TOPMOST, WM_CLOSE, WM_LBUTTONDOWN, WM_NCLBUTTONDOWN, HTCAPTION
    )
else:
    from core.mac_utils import (
        MacLayeredSurface as LayeredSurface,
        MacOverlayWindow,
        SystemAudioMeter,
        enable_high_res_timer,
        disable_high_res_timer,
    )

_CLASS_NAME = "SoulsLightsLyricsOverlay"
_NO_MEDIA_TITLES = {"No Active Music", "No Media Playing", "Unknown Track", ""}
_GENERIC_ARTISTS = {"", "unknown artist", "youtube", "chrome", "edge", "firefox", "system media", "vlc"}
_NON_MUSIC_PREFIXES = ("prime video:", "netflix:", "hotstar:", "disney+:", "twitch:")
_SOCIAL_FEED_TITLES = {
    "instagram", "tiktok", "facebook", "reddit", "twitter", "x",
    "threads", "snapchat", "youtube", "twitch", "netflix", "prime video", "spotify",
}
_JUNK_TITLE_RE = re.compile(
    r"\s*[\(\[](?:official\s*(?:music\s*)?video|official\s*(?:lyric\s*)?(?:audio|video)|"
    r"lyric(?:s)?(?:\s*video)?|audio(?:\s*only)?|visualizer|mv|hd|4k|explicit|"
    r"from\s+[\"'\u201c\u2018]?[^\"\'\)\]]+[\"'\u201d\u2019]?|original\s+motion\s+picture\s+soundtrack|"
    r"live(?:\s+at\s+[^\)\]]+)?|remaster(?:ed)?(?:\s*\d+)?|\d{4}\s+remaster)[\)\]]",
    re.IGNORECASE,
)
_FEAT_RE = re.compile(r"\s*[\(\[](?:feat\.?|ft\.?|featuring)\s+[^\)\]]+[\)\]]", re.IGNORECASE)

_class_registered = False

# Curated Word Visuals mapping (reproducing Verci's expressive word icon index)
WORD_VISUALS = {
    "love": "❤️", "loved": "❤️", "loving": "❤️", "lover": "❤️", "heart": "💓", "hearts": "💓",
    "broken": "💔", "heartbreak": "💔", "fire": "🔥", "burn": "🔥", "burning": "🔥", "flame": "🔥",
    "flames": "🔥", "hot": "🔥", "star": "⭐", "stars": "✨", "starboy": "⭐", "shine": "✨", "shining": "✨",
    "sparkle": "✨", "magic": "✨", "soul": "✨", "believe": "✨", "moon": "🌙", "night": "🌙", "midnight": "🌙",
    "tonight": "🌙", "sun": "☀️", "sunshine": "☀️", "morning": "🌅", "dawn": "🌅", "sunset": "🌇",
    "day": "☀️", "light": "💡", "lights": "💡", "flash": "📸", "flashing": "📸", "shoot": "📸", "shootin": "📸", "shooting": "📸",
    "glow": "✨", "bright": "🌟", "dark": "🌑", "darkness": "🌑", "shadow": "🌑", "shadows": "🌑",
    "black": "🖤", "white": "🤍", "blue": "💙", "red": "❤️", "gold": "🪙", "golden": "✨",
    "yellow": "💛", "green": "💚", "purple": "💜", "pink": "🩷", "rain": "🌧️", "raining": "🌧️",
    "storm": "⛈️", "thunder": "⚡", "lightning": "⚡", "electric": "⚡", "energy": "⚡",
    "cry": "💧", "crying": "💧", "tear": "💧", "tears": "💧", "water": "💧",
    "ocean": "🌊", "sea": "🌊", "wave": "🌊", "waves": "🌊", "river": "🌊",
    "sky": "☁️", "cloud": "☁️", "clouds": "☁️", "heaven": "☁️", "fly": "🕊️", "flying": "🕊️",
    "wing": "🪶", "wings": "🪶", "angel": "👼", "angels": "👼", "devil": "😈", "demon": "😈",
    "ghost": "👻", "ghosts": "👻", "dream": "💭", "dreams": "💭", "dreaming": "💭", "sleep": "😴",
    "wake": "👀", "eyes": "👁️", "eye": "👁️", "look": "👀", "looking": "👀", "see": "👀",
    "watch": "👀", "blind": "🕶️", "music": "🎵", "song": "🎵", "sing": "🎤", "singing": "🎤",
    "voice": "🎙️", "sound": "🔊", "dance": "💃", "dancing": "💃", "party": "🎉", "drink": "🥂",
    "wine": "🍷", "kiss": "💋", "kissing": "💋", "lips": "💋", "smile": "😊", "laugh": "😄",
    "happy": "😊", "sad": "😔", "lonely": "🥀", "alone": "🥀", "rose": "🌹", "roses": "🌹",
    "flower": "🌸", "flowers": "🌸", "bloom": "🌺", "wood": "🌳", "tree": "🌳", "forest": "🌲", "leaf": "🍃",
    "wind": "💨", "air": "💨", "breathe": "🌬️", "breath": "🌬️", "cold": "❄️", "ice": "🧊",
    "snow": "❄️", "winter": "❄️", "summer": "🌴", "spring": "🌷", "fall": "🍂", "time": "⏳",
    "clock": "🕰️", "hour": "⏳", "hours": "⏳", "wait": "⏳", "waiting": "⏳", "forever": "♾️",
    "always": "♾️", "world": "🌍", "earth": "🌍", "city": "🏙️", "street": "🛣️", "road": "🛣️",
    "highway": "🛣️", "drive": "🚗", "car": "🚗", "cars": "🚗", "wagon": "🚙", "shoe": "👟", "shoes": "👠",
    "run": "🏃", "running": "🏃", "home": "🏠", "house": "🏠", "crib": "🏠", "floor": "🪵", "floors": "🪵",
    "door": "🚪", "window": "🪟", "room": "🛋️", "bed": "🛏️", "hand": "✋", "hands": "🤲",
    "hold": "🤝", "touch": "✨", "mind": "🧠", "head": "🧠", "thought": "💭", "thoughts": "💭",
    "memory": "🎞️", "memories": "🎞️", "king": "👑", "queen": "👑", "crown": "👑", "legend": "🏆",
    "diamond": "💎", "diamonds": "💎", "money": "💵", "cash": "💵", "rich": "💎", "lavish": "💎", "win": "🏆",
    "phone": "📱", "call": "📞", "calling": "📞", "message": "💬", "text": "💬", "letter": "✉️",
    "book": "📖", "story": "📖", "write": "✍️", "word": "💬", "words": "💬", "truth": "🔆",
    "lie": "🎭", "lies": "🎭", "mask": "🎭", "fight": "⚔️", "war": "⚔️", "sword": "⚔️",
    "gun": "💥", "shot": "💥", "boom": "💥", "bandit": "🏴‍☠️", "fast": "💨", "slow": "🐢", "high": "🚀",
    "space": "🪐", "planet": "🪐", "rocket": "🚀", "galaxy": "🌌", "universe": "🌌", "blood": "🩸",
    "pain": "🩹", "hurt": "🩹", "heal": "🌿", "peace": "🕊️", "pray": "🙏", "god": "✨",
    "coffee": "☕", "tea": "🍵", "baby": "👶", "boy": "🧑", "girl": "👩", "mama": "🫶", "friend": "🫂",
    "friends": "🫂", "family": "🏡", "stay": "🫂", "gone": "💨", "bye": "👋", "hello": "👋",
    "grocery": "🛒", "new": "✨", "tease": "😏",
}

FONT_MAP = {
    "Geometric": ("segoeuib.ttf", "segoeui.ttf"),
    "Futura": ("calibrib.ttf", "calibri.ttf"),
    "Didone": ("timesbd.ttf", "times.ttf"),
    "Grotesque": ("arialbd.ttf", "arial.ttf"),
    "Rounded": ("seguisb.ttf", "segoeui.ttf"),
    "Serif": ("georgiab.ttf", "georgia.ttf"),
}


def _hex_to_rgb(hx, fallback=(236, 72, 153)):
    s = (hx or "").lstrip("#")
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return fallback


def _word_icon(word: str):
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    return WORD_VISUALS.get(cleaned)


_INSTRUMENTAL_LINE_RE = re.compile(r"^[\s\u2669-\u266f\U0001f3b5\U0001f3b6\u2022\u00b7\u2026\.\-\u2014\u2013~_*|/\\()\[\]]+$")
_INSTRUMENTAL_WORDS = {"instrumental", "music", "interlude", "intro", "outro", "solo", "break", "vocal break", "instrumental break"}
_MUSIC_SYMBOL_STRIP_RE = re.compile(r"[\u2669-\u266f\U0001f3b5\U0001f3b6\u200b-\u200f\ufeff\ufe0e\ufe0f\xad]+")
_ELONGATED_WORD_RE = re.compile(r"([aeiouy])\1{1,}|^(o+h+|a+h+|m+h*m+|h+m+|e+h+|u+h+|w+h+o+a+|y+e+a+h+|h+e+y+)$", re.IGNORECASE)
_LIGHT_FUNC_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "of", "for", "and", "or",
    "but", "is", "am", "are", "be", "it", "its", "by", "as", "from", "with",
}


def _is_instrumental_marker(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _INSTRUMENTAL_LINE_RE.match(t):
        return True
    bare = re.sub(r"[\(\)\[\]\.\-\u2014\u2013~_*\u2669-\u266f\U0001f3b5\U0001f3b6]+", " ", t).strip().lower()
    return not bare or bare in _INSTRUMENTAL_WORDS


def _sanitize_lyric_text(text: str) -> str:
    cleaned = _MUSIC_SYMBOL_STRIP_RE.sub("", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _slow_cue_weight(word: str, is_final: bool, gap: float, n_words: int) -> float:
    """Estimates relative sung duration with slow-cue hold, melisma, punctuation, and function-word lightness."""
    core = re.sub(r"[^A-Za-z0-9]", "", word)
    alpha_len = len(core)
    vowel_groups = len(re.findall(r"[aeiouy]+", core.lower())) or 1
    w_base = max(1.4, float(alpha_len) * 0.72 + vowel_groups * 1.15)

    low = core.lower()
    has_punct_slow = ("..." in word) or ("\u2026" in word) or ("\u2014" in word) or ("\u2013" in word) or ("~" in word)
    has_pause_punct = word.endswith((",", ";", ":", "?", "!"))
    has_melisma = ("-" in word.strip("-")) or bool(_ELONGATED_WORD_RE.search(core))

    if low in _LIGHT_FUNC_WORDS and not (is_final or has_punct_slow or has_pause_punct or has_melisma):
        w_base *= 0.62

    if has_melisma:
        w_base += 4.2
    if has_punct_slow:
        w_base += 4.6
    elif has_pause_punct:
        w_base += 2.6

    if is_final:
        # Only allocate excess time beyond natural multi-word speech onto the sustained closing word
        expected_spoken = max(1.1, n_words * 0.58)
        excess_tail = max(0.0, gap - expected_spoken)
        hold_factor = 1.38 + min(3.8, excess_tail * 0.72)
        w_base = w_base * hold_factor + excess_tail * 2.1
    return max(0.9, w_base)


_YRC_CREDIT_RE = re.compile(
    r"^(?:\u4f5c\u8bcd|\u4f5c\u66f2|\u7f16\u66f2|\u5236\u4f5c\u4eba|\u6df7\u97f3|\u6bcd\u5e26|"
    r"\u5f55\u97f3|\u7edf\u7b79|\u76d1\u5236|\u548c\u58f0|\u5409\u4ed6|\u8d1d\u65af|\u9f13|"
    r"\u51fa\u54c1|\u53d1\u884c|lyrics?\s*by|composed\s*by|produced\s*by|written\s*by)\s*[:\uff1a]",
    re.IGNORECASE,
)


def _is_yrc_metadata_line(text: str, title: str = "", artist: str = "") -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _YRC_CREDIT_RE.match(t):
        return True
    low = t.lower()
    if re.fullmatch(r"[\(\uff08\[].{0,40}\b(?:feat|ft)\.?\b.{0,40}[\)\uff09\]]", low):
        return True
    if low.endswith(" lyrics") and len(t) <= 80:
        t_tok = _tokens(t)
        if t_tok & (_tokens(title) | _tokens(artist)):
            return True
    return False


def _clean_track_meta(title: str, artist: str):
    t = (title or "").strip()
    a = (artist or "").strip()
    if a.lower().endswith(" - topic"):
        a = a[:-8].strip()
    clean_a = "" if a.lower() in _GENERIC_ARTISTS else a
    if not clean_a and " - " in t:
        parts = t.split(" - ", 1)
        if len(parts[0].strip()) >= 2 and len(parts[1].strip()) >= 2:
            clean_a, t = parts[0].strip(), parts[1].strip()
    t_no_junk = _JUNK_TITLE_RE.sub("", t).strip() or t
    t_no_feat = _FEAT_RE.sub("", t_no_junk).strip() or t_no_junk
    return t, t_no_junk, t_no_feat, clean_a


def _tokens(s: str):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _ease_out_cubic(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return 1.0 - (1.0 - u) ** 3


def _ease_out_back(u: float) -> float:
    u = max(0.0, min(1.0, u))
    c1 = 1.75
    c3 = c1 + 1.0
    return 1.0 + c3 * ((u - 1.0) ** 3) + c1 * ((u - 1.0) ** 2)


def _lerp_color(c1, c2, u: float):
    u = max(0.0, min(1.0, u))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * u) for i in range(len(c1)))


def _build_fisheye_mesh(w: int, h: int, k_strength: float, zoom_base: float = 0.72):
    """Builds a spherical barrel fisheye warp grid (Image.Transform.MESH) in pixel coordinates."""
    nx, ny = 12, 6
    cx, cy = w * 0.5, h * 0.5
    rx, ry = max(1.0, w * 0.5), max(1.0, h * 0.5)
    cw, ch = w / nx, h / ny

    def _inv(dx_px, dy_px):
        nx_n = (dx_px - cx) / rx
        ny_n = (dy_px - cy) / ry
        r2 = nx_n * nx_n + ny_n * ny_n
        factor = zoom_base + k_strength * r2
        return cx + nx_n * factor * rx, cy + ny_n * factor * ry

    mesh = []
    for j in range(ny):
        y0, y1 = j * ch, (j + 1) * ch
        for i in range(nx):
            x0, x1 = i * cw, (i + 1) * cw
            box = (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))
            nw = _inv(x0, y0)
            sw = _inv(x0, y1)
            se = _inv(x1, y1)
            ne = _inv(x1, y0)
            mesh.append((box, (nw[0], nw[1], sw[0], sw[1], se[0], se[1], ne[0], ne[1])))
    return mesh


class LyricsFetcher:
    """Multi-provider LRC lyrics fetcher (LRCLIB primary + NetEase fallback) with legacy cache migration."""

    def __init__(self, cache_dir=None):
        if cache_dir is None:
            cache_dir = get_app_data_dir()
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, "lyrics_cache.json")
        self.debug_log = os.path.join(cache_dir, "lyrics_debug.log")
        self._cache_lock = threading.Lock()
        self.cache = self._load_cache()

    def _log(self, msg):
        try:
            ts = time.strftime("%H:%M:%S")
            with open(self.debug_log, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def _load_cache(self):
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return {}
            cleaned = {}
            dirty = False
            for k, v in raw.items():
                if any(p in k.lower() for p in _NON_MUSIC_PREFIXES):
                    dirty = True
                    continue
                if isinstance(v, dict) and v.get("cache_v", 1) < 5:
                    # Invalidate pre-v5 cache entries so tracks upgrade to verbatim YRC word-sync where available
                    dirty = True
                    continue
                if isinstance(v, list):
                    entries = []
                    for item in v:
                        if isinstance(item, dict) and "time" in item and "text" in item:
                            entries.append((float(item["time"]), str(item["text"])))
                    if entries:
                        entries.sort(key=lambda x: x[0])
                        cleaned[k] = {"source": "Cache (Synced)", "lines": self._build_word_timings(entries)}
                    dirty = True
                elif isinstance(v, dict) and isinstance(v.get("lines"), list) and v["lines"]:
                    lines = v["lines"]
                    if "words" not in lines[0]:
                        entries = [(float(x["time"]), str(x["text"])) for x in lines if "time" in x and "text" in x]
                        if entries:
                            entries.sort(key=lambda x: x[0])
                            cleaned[k] = {"source": v.get("source", "Cache"), "lines": self._build_word_timings(entries)}
                        dirty = True
                    else:
                        for line in lines:
                            for w in line.get("words", []):
                                w["icon"] = _word_icon(w.get("word", ""))
                        cleaned[k] = v
                else:
                    dirty = True
            if dirty:
                self._write_cache(cleaned)
            return cleaned
        except Exception as e:
            self._log(f"Cache load failed: {e}")
            return {}

    def _write_cache(self, data):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self._log(f"Cache save error: {e}")

    def _save_cache(self):
        with self._cache_lock:
            self._write_cache(self.cache)

    def _urlopen(self, req, timeout=6):
        contexts = [_SSL_CTX] if _SSL_CTX else []
        contexts.append(None)
        last_err = None
        for ctx in contexts:
            try:
                if ctx is not None:
                    return urllib.request.urlopen(req, timeout=timeout, context=ctx)
                return urllib.request.urlopen(req, timeout=timeout)
            except ssl.SSLError as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                break
        if last_err:
            self._log(f"HTTP error {req.full_url[:80]}: {last_err}")
        return None

    def get_lyrics(self, title, artist, album="", duration=0, force_refresh=False):
        t_low = (title or "").lower().strip()
        a_low = (artist or "").lower().strip()
        t_no_notif = re.sub(r"^\(\d+\)\s*", "", t_low).strip()
        if any(t_low.startswith(p) for p in _NON_MUSIC_PREFIXES):
            return [], "Non-music stream"
        if a_low in _GENERIC_ARTISTS and t_no_notif in _SOCIAL_FEED_TITLES:
            return [], "Social/Browser feed"

        key = f"{a_low} - {t_low}"
        with self._cache_lock:
            cached = None if force_refresh else self.cache.get(key)
        if isinstance(cached, dict) and cached.get("lines"):
            return cached["lines"], cached.get("source", "Cache")
        if isinstance(cached, list) and cached:
            entries = [(float(x["time"]), str(x["text"])) for x in cached if isinstance(x, dict) and "time" in x and "text" in x]
            if entries:
                lines = self._build_word_timings(sorted(entries, key=lambda x: x[0]))
                with self._cache_lock:
                    self.cache[key] = {"source": "Cache (Synced)", "lines": lines}
                self._save_cache()
                return lines, "Cache (Synced)"

        self._log(f"Fetching lyrics for '{artist}' - '{title}' (dur={duration:.1f}s)")
        lrc_res = [([], "None")]
        ne_res = [([], "None")]

        def _run_lrc():
            lrc_res[0] = self._fetch_from_lrclib(title, artist, album, duration)

        def _run_ne():
            ne_res[0] = self._fetch_from_netease(title, artist, duration)

        t1 = threading.Thread(target=_run_lrc, daemon=True)
        t2 = threading.Thread(target=_run_ne, daemon=True)
        t1.start(); t2.start()
        t1.join(timeout=8.0); t2.join(timeout=8.0)

        lrc_lines, lrc_src = lrc_res[0]
        ne_lines, ne_src = ne_res[0]

        if ne_lines and "Word Synced" in ne_src:
            if lrc_lines:
                lines, source = self._merge_yrc_with_lrc(ne_lines, lrc_lines, lrc_src)
            else:
                lines, source = ne_lines, ne_src
        elif lrc_lines and "Synced" in lrc_src:
            lines, source = lrc_lines, lrc_src
        elif ne_lines:
            lines, source = ne_lines, ne_src
        else:
            lines, source = lrc_lines, lrc_src

        if lines:
            with self._cache_lock:
                self.cache[key] = {"cache_v": 5, "source": source, "lines": lines}
            self._save_cache()
            self._log(f"Resolved {len(lines)} lines via {source} for '{title}'")
        else:
            self._log(f"No lyrics found for '{artist}' - '{title}'")
        return lines, source

    def _merge_yrc_with_lrc(self, yrc_lines, lrc_lines, lrc_src):
        """Uses studio YRC word-sync when time-aligned with LRCLIB, backfilling any missing chorus hooks."""
        # Check median time delta on lexically similar lines to guard against alternate edits/offsets
        deltas = []
        lrc_toks = [(_tokens(l["text"]), l["time"]) for l in lrc_lines]
        for yl in yrc_lines[:24]:
            yt = _tokens(yl["text"])
            if not yt:
                continue
            for lt, l_time in lrc_toks:
                if abs(l_time - yl["time"]) <= 4.0 and len(yt & lt) >= max(2, min(len(yt), len(lt)) // 2):
                    deltas.append(yl["time"] - l_time)
                    break
        if deltas:
            deltas.sort()
            med_delta = deltas[len(deltas) // 2]
            if abs(med_delta) > 2.5:
                return lrc_lines, lrc_src
        elif yrc_lines and lrc_lines and abs(yrc_lines[0]["time"] - lrc_lines[0]["time"]) > 4.5:
            return lrc_lines, lrc_src

        # Backfill LRCLIB lines in gaps not covered within +-2.2s of any YRC vocal line
        merged = list(yrc_lines)
        added = 0
        for ll in lrc_lines:
            if not any(abs(yl["time"] - ll["time"]) <= 2.2 or (yl["time"] <= ll["time"] <= yl["end"] + 0.6) for yl in yrc_lines):
                merged.append(ll)
                added += 1
        if added:
            merged.sort(key=lambda x: x["time"])
            return merged, "NetEase + LRCLIB (Word Synced)"
        return yrc_lines, "NetEase (Word Synced)"

    def _fetch_from_lrclib(self, title, artist, album, duration):
        raw_t, clean_t, bare_t, clean_a = _clean_track_meta(title, artist)
        seen_t = []
        for cand_t in (raw_t, clean_t, bare_t):
            if cand_t and cand_t not in seen_t:
                seen_t.append(cand_t)

        artist_cands = []
        if clean_a:
            artist_cands.append(clean_a)
            primary_a = re.split(r"[,&/;]|\bfeat\.?\b|\bft\.?\b", clean_a, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            if primary_a and primary_a not in artist_cands:
                artist_cands.append(primary_a)

        for cand_a in artist_cands:
            for cand_t in seen_t:
                params = {"track_name": cand_t, "artist_name": cand_a}
                if album and cand_a == clean_a:
                    params["album_name"] = album
                if duration > 10:
                    params["duration"] = int(round(duration))
                url = "https://lrclib.net/api/get?" + urllib.parse.urlencode(params)
                req = urllib.request.Request(url, headers={"User-Agent": "SoulsLights/2.2"})
                resp = self._urlopen(req, timeout=6)
                if resp:
                    try:
                        with resp:
                            data = json.loads(resp.read().decode("utf-8"))
                        if isinstance(data, dict):
                            if data.get("syncedLyrics"):
                                parsed = self._parse_lrc(data["syncedLyrics"])
                                if parsed:
                                    return parsed, "LRCLIB (Synced)"
                            if data.get("plainLyrics"):
                                parsed = self._fallback_plain(data["plainLyrics"], duration)
                                if parsed:
                                    return parsed, "LRCLIB (Timed Est.)"
                    except Exception as e:
                        self._log(f"LRCLIB get parse error: {e}")

        t_tokens = _tokens(bare_t or clean_t)
        a_tokens = _tokens(clean_a)
        queries = []
        for cand_a in (artist_cands or [""]):
            for cand_t in (bare_t, clean_t, raw_t):
                q = f"{cand_t} {cand_a}".strip()
                if q and q not in queries:
                    queries.append(q)
        if bare_t and bare_t not in queries:
            queries.append(bare_t)

        for q in queries[:3]:
            search_url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"q": q})
            req = urllib.request.Request(search_url, headers={"User-Agent": "SoulsLights/2.2"})
            resp = self._urlopen(req, timeout=6)
            if not resp:
                continue
            try:
                with resp:
                    results = json.loads(resp.read().decode("utf-8"))
                if not isinstance(results, list) or not results:
                    continue

                def _score(item):
                    has_sync = 100 if item.get("syncedLyrics") else (20 if item.get("plainLyrics") else -1000)
                    it_name = _tokens(item.get("trackName", ""))
                    it_art = _tokens(item.get("artistName", ""))
                    t_ov = (len(t_tokens & it_name) * 15) if t_tokens else 0
                    a_ov = (len(a_tokens & it_art) * 20) if a_tokens else 0
                    dur_diff = abs(float(item.get("duration") or 0) - duration) if duration > 10 and item.get("duration") else 0
                    dur_bonus = max(-25, 15 - int(dur_diff))
                    karaoke_pen = -40 if ("karaoke" in item.get("artistName", "").lower() and "karaoke" not in clean_a.lower()) else 0
                    return has_sync + t_ov + a_ov + dur_bonus + karaoke_pen

                best = sorted(results, key=_score, reverse=True)[0]
                if best.get("syncedLyrics"):
                    parsed = self._parse_lrc(best["syncedLyrics"])
                    if parsed:
                        return parsed, "LRCLIB Search (Synced)"
                if best.get("plainLyrics"):
                    parsed = self._fallback_plain(best["plainLyrics"], duration)
                    if parsed:
                        return parsed, "LRCLIB Search (Est.)"
            except Exception as e:
                self._log(f"LRCLIB search parse error: {e}")

        return [], "None"

    def _fetch_from_netease(self, title, artist, duration=0.0):
        raw_t, clean_t, bare_t, clean_a = _clean_track_meta(title, artist)
        q = f"{bare_t or clean_t} {clean_a}".strip()
        if not q:
            return [], "None"
        t_tokens = _tokens(bare_t or clean_t)
        a_tokens = _tokens(clean_a)
        try:
            search_url = "https://music.163.com/api/search/get?" + urllib.parse.urlencode({"s": q, "type": 1, "limit": 6})
            req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com"})
            resp = self._urlopen(req, timeout=6)
            if not resp:
                return [], "None"
            with resp:
                data = json.loads(resp.read().decode("utf-8"))
            songs = (data.get("result") or {}).get("songs") or []

            def _ne_score(song):
                sname = song.get("name", "")
                if t_tokens and len(t_tokens & _tokens(sname)) == 0:
                    return -1000
                art_str = " ".join(ar.get("name", "") for ar in (song.get("artists") or song.get("ar") or []))
                dur_s = float(song.get("duration") or song.get("dt") or 0) / 1000.0
                if duration > 15 and dur_s > 15 and abs(dur_s - duration) > 8.5:
                    return -500
                t_ov = len(t_tokens & _tokens(sname)) * 20
                a_ov = len(a_tokens & _tokens(art_str)) * 25
                dur_b = max(-20, 15 - int(abs(dur_s - duration))) if (duration > 15 and dur_s > 15) else 0
                pen = -40 if ("remix" in sname.lower() or "live" in sname.lower() or "sped" in sname.lower()) and not any(k in raw_t.lower() for k in ("remix", "live", "sped")) else 0
                return t_ov + a_ov + dur_b + pen

            ranked = sorted(songs, key=_ne_score, reverse=True)
            best_lrc = None
            for song in ranked[:3]:
                if _ne_score(song) < -100:
                    continue
                sid = song.get("id")
                if not sid:
                    continue
                lrc_url = f"https://music.163.com/api/song/lyric?id={sid}&lv=1&yv=1"
                req2 = urllib.request.Request(lrc_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com"})
                resp2 = self._urlopen(req2, timeout=6)
                if not resp2:
                    continue
                with resp2:
                    ldata = json.loads(resp2.read().decode("utf-8"))
                yrc_str = (ldata.get("yrc") or {}).get("lyric", "")
                if yrc_str:
                    parsed_yrc = self._parse_yrc(yrc_str, title=bare_t or clean_t, artist=clean_a)
                    if parsed_yrc:
                        return parsed_yrc, "NetEase (Word Synced)"
                if best_lrc is None:
                    lrc_str = (ldata.get("lrc") or {}).get("lyric", "")
                    if lrc_str:
                        parsed = self._parse_lrc(lrc_str)
                        if parsed:
                            best_lrc = (parsed, "NetEase (Synced)")
            if best_lrc:
                return best_lrc
        except Exception as e:
            self._log(f"NetEase error: {e}")
        return [], "None"

    def _parse_yrc(self, yrc_text, title="", artist=""):
        """Parses NetEase YRC verbatim word-by-word lyrics, joining contractions & stripping metadata."""
        line_re = re.compile(r"^\[(\d+),(\d+)\](.+)$")
        word_re = re.compile(r"\((\d+),(\d+),\d+\)([^\(]+)")
        attach_right_punc = {"'", "\u2019", ",", ".", "!", "?", ";", ":", "\u201d", ")", "]", "\uff09"}
        attach_left_open = {'"', "\u201c", "(", "[", "\uff08"}
        raw_lines = []
        for raw_line in yrc_text.splitlines():
            m = line_re.match(raw_line.strip())
            if not m:
                continue
            l_start = int(m.group(1)) / 1000.0
            l_dur = int(m.group(2)) / 1000.0
            body = m.group(3)
            words = []
            prev_had_trail_space = True
            pending_prefix = ""
            for wm in word_re.finditer(body):
                ws = int(wm.group(1)) / 1000.0
                wd = max(0.08, int(wm.group(2)) / 1000.0)
                raw_chunk = wm.group(3)
                has_lead_sp = raw_chunk[:1].isspace()
                has_trail_sp = raw_chunk[-1:].isspace()
                wtxt = _sanitize_lyric_text(raw_chunk.strip())
                if not wtxt or _is_instrumental_marker(wtxt):
                    if words and (not wtxt or wtxt in attach_right_punc):
                        words[-1]["end"] = max(words[-1]["end"], ws + wd)
                    prev_had_trail_space = has_trail_sp
                    continue

                # Replace curly apostrophe with crisp standard ASCII apostrophe
                wtxt = wtxt.replace("\u2019", "'").replace("\u2018", "'")

                if wtxt in attach_left_open:
                    pending_prefix += "(" if wtxt == "\uff08" else wtxt
                    prev_had_trail_space = False
                    continue

                if wtxt in attach_right_punc and words:
                    if wtxt == "\uff09":
                        wtxt = ")"
                    words[-1]["word"] += wtxt
                    words[-1]["end"] = max(words[-1]["end"], ws + wd)
                    words[-1]["icon"] = _word_icon(words[-1]["word"])
                    prev_had_trail_space = has_trail_sp or wtxt not in {"'", "\u2019"}
                    continue

                # Join split contraction fragments (e.g. "It" + "'" + "s" or "wouldn" + "'" + "t")
                if (
                    words and not prev_had_trail_space and not has_lead_sp
                    and (words[-1]["word"].endswith("'") or wtxt.lower() in {"s", "t", "d", "m", "re", "ve", "ll", "em"})
                ):
                    words[-1]["word"] += wtxt
                    words[-1]["end"] = max(words[-1]["end"], ws + wd)
                    words[-1]["icon"] = _word_icon(words[-1]["word"])
                    prev_had_trail_space = has_trail_sp
                    continue

                if pending_prefix:
                    wtxt = pending_prefix + wtxt
                    pending_prefix = ""

                words.append({
                    "word": wtxt,
                    "start": ws,
                    "end": ws + wd,
                    "icon": _word_icon(wtxt),
                })
                prev_had_trail_space = has_trail_sp

            if pending_prefix and words:
                words[-1]["word"] += pending_prefix

            joined = " ".join(w["word"] for w in words)
            if words and not _is_instrumental_marker(joined) and not _is_yrc_metadata_line(joined, title, artist):
                # Stretch premature word endings across short intra-line vocal sustain gaps
                for wi in range(len(words) - 1):
                    nxt_ws = words[wi + 1]["start"]
                    if nxt_ws > words[wi]["end"] and (nxt_ws - words[wi]["end"]) <= 2.6:
                        words[wi]["end"] = max(words[wi]["end"], nxt_ws - 0.04)
                l_end = max(l_start + l_dur, words[-1]["end"])
                raw_lines.append({
                    "time": l_start,
                    "end": l_end,
                    "text": joined,
                    "words": words,
                })
            elif raw_lines and l_start > raw_lines[-1]["time"]:
                raw_lines[-1]["end"] = min(raw_lines[-1]["end"], l_start - 0.05)

        for li in range(len(raw_lines) - 1):
            nxt_t = raw_lines[li + 1]["time"]
            cur_ln = raw_lines[li]
            if cur_ln["words"]:
                tail_gap = nxt_t - cur_ln["words"][-1]["end"]
                if 0.0 < tail_gap <= 5.5:
                    cur_ln["words"][-1]["end"] = max(cur_ln["words"][-1]["end"], nxt_t - 0.10)
                    cur_ln["end"] = max(cur_ln["end"], cur_ln["words"][-1]["end"])
        return raw_lines

    def _parse_lrc(self, lrc_text):
        parsed_rows = []
        offset_sec = 0.0
        off_m = re.search(r"\[offset:\s*([+-]?\d+)\]", lrc_text, re.IGNORECASE)
        if off_m:
            try:
                offset_sec = int(off_m.group(1)) / 1000.0
            except ValueError:
                pass

        ts_pattern = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
        word_ts_pattern = re.compile(r"<(\d+):(\d+(?:[.:]\d+)?)>")
        for raw_line in lrc_text.splitlines():
            timestamps = list(ts_pattern.finditer(raw_line))
            if not timestamps:
                continue
            raw_body = ts_pattern.sub("", raw_line).strip()
            is_inst = _is_instrumental_marker(word_ts_pattern.sub("", raw_body))

            # Parse enhanced LRC (<mm:ss.xx>word) timestamps when present
            inline_words = None
            if not is_inst and word_ts_pattern.search(raw_body):
                parts = word_ts_pattern.split(raw_body)
                parsed_iw = []
                if parts[0].strip():
                    for w in _sanitize_lyric_text(parts[0]).split():
                        parsed_iw.append((None, w))
                for pi in range(1, len(parts), 3):
                    try:
                        wt = max(0.0, int(parts[pi]) * 60.0 + float(parts[pi + 1].replace(":", ".")) - offset_sec)
                    except (ValueError, IndexError):
                        wt = None
                    seg = _sanitize_lyric_text(parts[pi + 2]) if pi + 2 < len(parts) else ""
                    for wi_s, w in enumerate(seg.split()):
                        parsed_iw.append((wt if wi_s == 0 else None, w))
                if parsed_iw:
                    inline_words = parsed_iw

            text = "" if is_inst else _sanitize_lyric_text(word_ts_pattern.sub("", raw_body))
            if not is_inst and (not text or _is_instrumental_marker(text)):
                is_inst = True
                text = ""

            for m in timestamps:
                try:
                    mins = int(m.group(1))
                    secs = float(m.group(2).replace(":", "."))
                    t = max(0.0, mins * 60.0 + secs - offset_sec)
                    parsed_rows.append((t, text, inline_words, is_inst))
                except ValueError:
                    continue

        parsed_rows.sort(key=lambda x: x[0])
        raw_entries = []
        for t, text, inline_words, is_inst in parsed_rows:
            if is_inst:
                # Use instrumental marker timestamp as explicit vocal stop hint on preceding line
                if raw_entries and raw_entries[-1][3] is None and t > raw_entries[-1][0]:
                    prev_t, prev_txt, prev_iw, _ = raw_entries[-1]
                    raw_entries[-1] = (prev_t, prev_txt, prev_iw, t)
                continue
            raw_entries.append((t, text, inline_words, None))
        return self._build_word_timings(raw_entries)

    def _fallback_plain(self, plain_text, duration):
        raw_lines = [_sanitize_lyric_text(l) for l in plain_text.splitlines()]
        raw_lines = [l for l in raw_lines if l and not _is_instrumental_marker(l)]
        if not raw_lines:
            return []
        dur = duration if duration > 10 else max(60.0, len(raw_lines) * 3.5)
        step = dur / len(raw_lines)
        entries = [(i * step, txt, None, None) for i, txt in enumerate(raw_lines)]
        return self._build_word_timings(entries)

    def _build_word_timings(self, entries):
        lines = []
        for idx, entry in enumerate(entries):
            t_start, text = entry[0], _sanitize_lyric_text(entry[1])
            if not text or _is_instrumental_marker(text):
                continue
            inline_words = entry[2] if len(entry) > 2 else None
            stop_hint = entry[3] if len(entry) > 3 else None
            t_next = entries[idx + 1][0] if idx + 1 < len(entries) else (t_start + 4.2)
            has_explicit_stop = (stop_hint is not None and stop_hint > t_start)
            cap_next = min(t_next, stop_hint) if has_explicit_stop else t_next
            gap = max(0.55, cap_next - t_start)

            # Use exact enhanced-LRC per-word timestamps if available
            if inline_words and any(wt is not None for wt, _ in inline_words):
                words = []
                n_iw = len(inline_words)
                for wi, (wt, w) in enumerate(inline_words):
                    ws = wt if wt is not None else (t_start if wi == 0 else words[-1]["end"])
                    ws = max(t_start, ws)
                    nxt_t = None
                    for k in range(wi + 1, n_iw):
                        if inline_words[k][0] is not None:
                            nxt_t = inline_words[k][0]
                            break
                    if nxt_t is not None:
                        span_cnt = k - wi
                        we = ws + max(0.12, (nxt_t - ws) / span_cnt)
                    else:
                        # Allow the closing word to sustain cleanly until cap_next instead of clamping to 0.65s
                        rem_to_next = max(0.35, cap_next - ws)
                        tail_dur = rem_to_next * 0.90 if rem_to_next <= 7.5 else min(6.5, rem_to_next * 0.78)
                        we = min(cap_next - 0.05, ws + max(0.45, tail_dur))
                    words.append({
                        "word": w,
                        "start": ws,
                        "end": max(ws + 0.10, we),
                        "icon": _word_icon(w),
                    })
                line_end = max(t_start + 0.4, words[-1]["end"]) if words else (t_start + gap)
                lines.append({
                    "time": t_start,
                    "end": line_end,
                    "text": text,
                    "words": words,
                    "has_stop_marker": has_explicit_stop,
                })
                continue

            words_raw = text.split()
            main_text = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", text).strip()
            n_main = max(1, len(main_text.split())) if main_text else len(words_raw)
            if gap <= 8.5:
                line_dur = max(0.55, gap * 0.94)
            elif gap <= 12.0:
                line_dur = min(gap * 0.88, max(5.6, n_main * 0.68 + 2.8))
            else:
                line_dur = min(gap * 0.84, max(3.6, min(8.0, n_main * 0.60 + 2.4)))

            # Identify final main sung word (or line final word) for trailing slow-cue hold absorption
            final_idx = len(words_raw) - 1
            weights = [
                _slow_cue_weight(w, wi_r == final_idx, line_dur, len(words_raw))
                for wi_r, w in enumerate(words_raw)
            ]
            total_w = sum(weights) or 1.0
            words = []
            cursor = t_start
            for w, wt in zip(words_raw, weights):
                w_dur = line_dur * (wt / total_w)
                words.append({
                    "word": w,
                    "start": cursor,
                    "end": cursor + w_dur,
                    "icon": _word_icon(w),
                })
                cursor += w_dur
            lines.append({
                "time": t_start,
                "end": t_start + line_dur,
                "text": text,
                "words": words,
                "has_stop_marker": has_explicit_stop,
            })
        return lines


class SyncedLyricsOverlay:
    """Standalone Verci Lyrics Engine: spherical MESH Fisheye warp + full-screen random Constellation + kinetic styles."""

    def __init__(self, config_manager=None, media_monitor=None):
        self.cfg_mgr = config_manager
        self.media_mon = media_monitor
        self.fetcher = LyricsFetcher()

        mons = get_monitors()
        prim = [m for m in mons if m["primary"]] or mons[:1]
        self._mon = prim[0]
        self.CENTER_W = min(1440, max(820, int(self._mon["w"] * 0.86)))
        self.CENTER_H = min(720, max(440, int(self._mon["h"] * 0.74)))
        self.OVERLAY_W = self.CENTER_W
        self.OVERLAY_H = self.CENTER_H

        self.running = False
        self.thread = None
        self.hwnd = None
        self.mac_win = None
        self._lock = threading.Lock()
        self._wnd_proc_ref = None

        self.current_lyrics = []
        self._flat_words = []
        self._constellation_nodes = {}  # memoized random full-screen coords per g_idx
        self._constellation_seed = 1
        self._bg_stars = []
        self.lyrics_status = "Idle"
        self.current_track_key = ""
        self.active_index = -1

        # Settings
        self.style = "Fisheye Visual"
        self.auto_sync_colors = True
        self.accent_color = (236, 72, 153)
        self.secondary_color = (99, 102, 241)
        self.custom_accent = (236, 72, 153)
        self.text_color = (255, 255, 255)
        self.font_name = "Geometric"
        self.font_scale = 1.0
        self.offset_sec = 0.0
        self.click_through = True
        self.pos_x = None
        self.pos_y = None

        self._dirty_style = False
        self._dirty_font = True
        self._font_paths = {}
        self._font_cache = {}
        self._sized_fonts = {}
        self._mesh_cache = {}
        self._icon_patch_cache = {}
        self._audio_peak = 0.0
        self._audio_bloom = 0.0

        # Reused full-screen canvases for fast Constellation dirty-rect rendering
        self._full_canvas = None
        self._full_draw = None
        self._full_glow = None
        self._full_glow_draw = None
        self._prev_dirty_rect = None

        self.reload_from_config()

    def _is_fullscreen_style(self, style_name: str) -> bool:
        return style_name == "Constellation"

    def reload_from_config(self):
        if not self.cfg_mgr:
            return
        v = self.cfg_mgr.config.get("lyrics", {})
        with self._lock:
            self.style = v.get("style", "Fisheye Visual")
            self.auto_sync_colors = bool(v.get("auto_sync_colors", True))
            self.custom_accent = _hex_to_rgb(v.get("custom_accent_color", "#EC4899"))
            self.text_color = _hex_to_rgb(v.get("custom_text_color", "#FFFFFF"), (255, 255, 255))
            self.font_name = v.get("font", "Geometric")
            self.font_scale = max(0.6, min(2.8, float(v.get("font_scale", 1.0))))
            self.offset_sec = float(v.get("sync_offset_ms", 0)) / 1000.0
            self.click_through = bool(v.get("click_through", True))
            self.pos_x = v.get("pos_x")
            self.pos_y = v.get("pos_y")
            self._dirty_font = True
            self._dirty_style = True

    def force_refresh_lyrics(self):
        """Clears cached lyrics for the active track and triggers an immediate re-fetch."""
        if not self.media_mon:
            return
        info = self.media_mon.current_info
        title = (info.get("title", "") or "").strip()
        artist = (info.get("artist", "") or "").strip()
        album = (info.get("album", "") or "").strip()
        dur = float(info.get("duration_sec", 0.0))
        if not title or title in _NO_MEDIA_TITLES:
            return
        with self._lock:
            self.current_lyrics = []
            self._flat_words = []
            self.active_index = -1
            self.lyrics_status = "Refreshing lyrics..."
            self._dirty_style = True
        threading.Thread(
            target=self._fetch_worker,
            args=(title, artist, album, dur, True),
            daemon=True,
        ).start()

    def start(self):
        if self.running:
            return
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        self.running = True
        self.thread = threading.Thread(target=self._run_overlay, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if IS_WIN and self.hwnd:
            try:
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)

    def set_style(self, style_name: str):
        with self._lock:
            self.style = style_name
            self._dirty_style = True

    def set_font(self, font_name: str):
        with self._lock:
            self.font_name = font_name
            self._dirty_font = True

    def set_font_scale(self, scale: float):
        with self._lock:
            self.font_scale = max(0.6, min(2.8, float(scale)))
            self._dirty_font = True

    def set_offset_ms(self, ms: int):
        with self._lock:
            self.offset_sec = ms / 1000.0

    def set_auto_sync_colors(self, enable: bool):
        with self._lock:
            self.auto_sync_colors = bool(enable)

    def set_album_palette(self, hex1: str, hex2: str = None):
        with self._lock:
            self.accent_color = _hex_to_rgb(hex1)
            self.secondary_color = _hex_to_rgb(hex2) if hex2 else self.accent_color

    def set_custom_accent(self, hex_color: str):
        with self._lock:
            self.custom_accent = _hex_to_rgb(hex_color)

    def set_click_through(self, enable: bool):
        with self._lock:
            self.click_through = bool(enable)
            hwnd = self.hwnd
            mac_win = self.mac_win
            eff_ct = bool(enable) or self._is_fullscreen_style(self.style)
        if IS_WIN and hwnd:
            self._apply_ex_style(hwnd, eff_ct)
        elif mac_win:
            mac_win.set_click_through(eff_ct)

    def reset_position(self):
        mons = get_monitors()
        prim = [m for m in mons if m["primary"]] or mons[:1]
        m = prim[0]
        self._mon = m
        nx = m["x"] + (m["w"] - self.CENTER_W) // 2
        ny = m["y"] + (m["h"] - self.CENTER_H) // 2
        with self._lock:
            self.pos_x = nx
            self.pos_y = ny
            if self.cfg_mgr:
                self.cfg_mgr.config["lyrics"]["pos_x"] = nx
                self.cfg_mgr.config["lyrics"]["pos_y"] = ny
                self.cfg_mgr.save_config()
            hwnd = self.hwnd
            mac_win = self.mac_win
            fs = self._is_fullscreen_style(self.style)
        if IS_WIN and hwnd and not fs:
            user32.SetWindowPos(hwnd, HWND_TOPMOST, nx, ny, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        elif mac_win and not fs:
            mac_win.set_geometry(nx, ny)

    def retry_fetch(self):
        if not self.media_mon:
            return
        info = self.media_mon.current_info
        title = (info.get("title", "") or "").strip()
        artist = (info.get("artist", "") or "").strip()
        album = (info.get("album", "") or "").strip()
        dur = float(info.get("duration_sec", 0.0))
        if title and title not in _NO_MEDIA_TITLES:
            with self._lock:
                self.current_track_key = f"{artist} - {title}"
                self.current_lyrics = []
                self._flat_words = []
                self._constellation_nodes.clear()
                self.active_index = -1
                self.lyrics_status = "Searching lyrics..."
                self._dirty_style = True
            threading.Thread(
                target=self._fetch_worker,
                args=(title, artist, album, dur, True),
                daemon=True
            ).start()

    def _apply_ex_style(self, hwnd, click_through):
        if not IS_WIN:
            if self.mac_win:
                self.mac_win.set_click_through(click_through)
            return
        try:
            style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if click_through:
                style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE)
            else:
                style &= ~WS_EX_TRANSPARENT
                style |= (WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass

    def _ensure_fonts(self):
        self._font_paths = get_lyric_font_paths(self.font_name)
        self._fallback_font_paths = get_fallback_font_entries()
        self._notdef_cache = {}
        self._glyph_ok_cache = {}
        self._safe_font_cache = {}
        self._sized_fonts = {}
        s = self.font_scale
        self._font_cache = {
            "hero": self._get_font("bold", int(58 * s)),
            "active": self._get_font("bold", int(36 * s)),
            "active_compact": self._get_font("bold", int(26 * s)),
            "sub": self._get_font("reg", int(22 * s)),
            "small": self._get_font("reg", int(15 * s)),
            "code": self._get_font("mono", int(26 * s)),
            "emoji_hero": self._get_font("emoji", int(46 * s)) if self._font_paths.get("emoji") else None,
            "emoji": self._get_font("emoji", int(30 * s)) if self._font_paths.get("emoji") else None,
            "emoji_compact": self._get_font("emoji", int(24 * s)) if self._font_paths.get("emoji") else None,
        }
        self._dirty_font = False

    def _get_font(self, kind: str, size_px: int):
        q = max(10, min(260, int(round(size_px / 2.0) * 2)))
        key = (kind, q)
        f = self._sized_fonts.get(key)
        if f is None:
            path = self._font_paths.get(kind) or ("" if kind == "emoji" else self._font_paths.get("bold"))
            f = load_truetype_safe(path, q) if path else None
            if f is None and kind != "emoji":
                f = load_scalable_default_font(q)
            if f is not None:
                self._sized_fonts[key] = f
        return f

    def _font_has_char(self, font, ch: str) -> bool:
        if ord(ch) < 128:
            return True
        fpath = getattr(font, "path", "")
        key = (fpath, ord(ch))
        cached = self._glyph_ok_cache.get(key)
        if cached is not None:
            return cached
        try:
            f32 = self._sized_fonts.get(("__chk", fpath))
            if f32 is None:
                f32 = ImageFont.truetype(fpath, 28) if fpath else font
                self._sized_fonts[("__chk", fpath)] = f32
            nd_b = self._notdef_cache.get(fpath)
            if nd_b is None:
                im_nd = Image.new("L", (40, 40), 0)
                ImageDraw.Draw(im_nd).text((2, 2), "\uffff", font=f32, fill=255)
                nd_b = im_nd.tobytes()
                self._notdef_cache[fpath] = nd_b
            im_ch = Image.new("L", (40, 40), 0)
            ImageDraw.Draw(im_ch).text((2, 2), ch, font=f32, fill=255)
            ok = (im_ch.tobytes() != nd_b) and (im_ch.getbbox() is not None)
        except Exception:
            ok = True
        if len(self._glyph_ok_cache) > 2000:
            self._glyph_ok_cache.clear()
        self._glyph_ok_cache[key] = ok
        return ok

    def _safe_font(self, font, text: str):
        """Returns font unchanged for ASCII/supported text, or picks a script-capable Windows fallback without tofu."""
        if font is None or not text or text.isascii():
            return font
        fpath = getattr(font, "path", "")
        need = tuple(sorted({ch for ch in text if ord(ch) >= 128 and not ch.isspace()}))
        if not need:
            return font
        if all(self._font_has_char(font, ch) for ch in need):
            return font
        skey = (fpath, font.size, need)
        cached = self._safe_font_cache.get(skey)
        if cached is not None:
            return cached
        for fn, fp, _w in getattr(self, "_fallback_font_paths", []):
            fb_key = ("__fb", fp, font.size)
            fb_f = self._sized_fonts.get(fb_key)
            if fb_f is None:
                try:
                    fb_f = ImageFont.truetype(fp, font.size)
                    self._sized_fonts[fb_key] = fb_f
                except Exception:
                    continue
            if all(self._font_has_char(fb_f, ch) for ch in need):
                if len(self._safe_font_cache) > 400:
                    self._safe_font_cache.clear()
                self._safe_font_cache[skey] = fb_f
                return fb_f
        self._safe_font_cache[skey] = font
        return font

    def _get_warp_mesh(self, w: int, h: int, k_strength: float, zoom_base: float = 0.78):
        qk = round(k_strength * 50.0) / 50.0
        qz = round(zoom_base, 2)
        key = (w, h, qk, qz)
        mesh = self._mesh_cache.get(key)
        if mesh is None:
            mesh = _build_fisheye_mesh(w, h, qk, zoom_base=qz)
            if len(self._mesh_cache) > 24:
                self._mesh_cache.clear()
            self._mesh_cache[key] = mesh
        return mesh

    def _register_class(self):
        if not IS_WIN:
            return

        def _wnd_proc(hwnd, msg, wp, lp):
            if msg == WM_LBUTTONDOWN and not self.click_through and not self._is_fullscreen_style(self.style):
                user32.ReleaseCapture()
                user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
                rect = RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    with self._lock:
                        self.pos_x = int(rect.left)
                        self.pos_y = int(rect.top)
                        if self.cfg_mgr:
                            self.cfg_mgr.config["lyrics"]["pos_x"] = self.pos_x
                            self.cfg_mgr.config["lyrics"]["pos_y"] = self.pos_y
                            self.cfg_mgr.save_config()
                return 0
            return user32.DefWindowProcW(hwnd, msg, wp, lp)

        self._wnd_proc_ref = WNDPROC(_wnd_proc)
        global _class_registered
        if not _class_registered:
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = ctypes.cast(self._wnd_proc_ref, ctypes.c_void_p).value
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.lpszClassName = _CLASS_NAME
            user32.RegisterClassExW(ctypes.byref(wc))
            _class_registered = True

    def _get_center_pos(self):
        with self._lock:
            if self.pos_x is not None and self.pos_y is not None:
                return int(self.pos_x), int(self.pos_y)
        m = self._mon
        return m["x"] + (m["w"] - self.CENTER_W) // 2, m["y"] + (m["h"] - self.CENTER_H) // 2

    def _build_flat_words(self, lyrics):
        flat = []
        for li, line in enumerate(lyrics):
            paren_d = 0
            sq_d = 0
            for wi, w in enumerate(line.get("words", [])):
                w_txt = w["word"]
                in_br = (paren_d > 0 or sq_d > 0
                         or "(" in w_txt or ")" in w_txt
                         or "[" in w_txt or "]" in w_txt)
                paren_d = max(0, paren_d + w_txt.count("(") - w_txt.count(")"))
                sq_d = max(0, sq_d + w_txt.count("[") - w_txt.count("]"))
                flat.append({
                    "word": w_txt,
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                    "icon": w.get("icon"),
                    "line_idx": li,
                    "word_idx": wi,
                    "g_idx": len(flat),
                    "in_brackets": in_br,
                })
        return flat

    def _init_constellation_sky(self, W, H, seed_text):
        """Precomputes a layered starfield (3 size tiers, staggered twinkle) for the full display."""
        seed = sum(ord(c) * (i + 1) for i, c in enumerate(seed_text or "soulslights"))
        self._constellation_seed = seed
        self._constellation_nodes.clear()
        rng = random.Random(seed ^ 0x5A17)
        # (x, y, phase, size_tier)  size_tier: 0=micro(r≈1), 1=small(r≈1.8), 2=medium(r≈2.6)
        self._bg_stars = []
        for _ in range(55):
            tier = rng.choices([0, 1, 2], weights=[55, 35, 10])[0]
            self._bg_stars.append((
                rng.randint(60, max(200, W - 60)),
                rng.randint(50, max(150, H - 50)),
                rng.uniform(0.0, 6.28),
                tier,
            ))

    def _get_constellation_pos(self, g_idx: int, W: int, H: int):
        """Truly random, well-spread positions — no sequential chaining, no Lissajous path.
        Each word gets a stable random spot that avoids clustering with its recent neighbours."""
        cached = self._constellation_nodes.get(g_idx)
        if cached is not None:
            return cached

        pad_x, pad_y = int(W * 0.11), int(H * 0.13)
        rng = random.Random(self._constellation_seed * 131 + g_idx * 7919 + 42)

        # Collect recent neighbours to avoid too-close placement
        recent = [self._constellation_nodes[k]
                  for k in range(max(0, g_idx - 4), g_idx)
                  if k in self._constellation_nodes]

        best_pt = (rng.randint(pad_x, W - pad_x), rng.randint(pad_y, H - pad_y))
        best_score = -1.0
        for _ in range(22):
            cx = rng.randint(pad_x, W - pad_x)
            cy = rng.randint(pad_y, H - pad_y)
            if not recent:
                best_pt = (cx, cy)
                break
            # Maximise minimum distance to any recent neighbour + reward edge usage
            min_d = min(math.hypot(cx - rx, cy - ry) for rx, ry in recent)
            edge = abs(cx - W * 0.5) / W * 180.0 + abs(cy - H * 0.5) / H * 140.0
            score = min_d + edge
            if score > best_score:
                best_score = score
                best_pt = (cx, cy)

        self._constellation_nodes[g_idx] = best_pt
        return best_pt

    def _get_line_constellation_pts(self, line_idx: int, line_words, W: int, H: int):
        """Places all words of a line at random non-overlapping positions across the screen."""
        cache_key = ("line", line_idx, W, H, round(self.font_scale, 2))
        cached = self._constellation_nodes.get(cache_key)
        if cached is not None:
            return cached

        rng = random.Random(self._constellation_seed * 131 + line_idx * 7919 + 42)
        f_max = self._get_font("bold", int(52 * self.font_scale))
        draw = self._full_draw
        placed = []  # list of (cx, cy, half_w, half_h)

        for wobj in line_words:
            txt = re.sub(r'[\(\)\[\]]', '', wobj["word"]).strip() or wobj["word"]
            if draw is not None and f_max is not None:
                bb = draw.textbbox((0, 0), txt, font=f_max)
                tw, th = bb[2] - bb[0], bb[3] - bb[1]
            else:
                tw, th = len(txt) * 28, 52
            hw = max(70, tw * 0.5 + 38)
            hh = max(48, th * 0.5 + 42)

            x_lo = int(min(W * 0.42, max(120, hw + 24)))
            x_hi = int(max(x_lo + 20, W - max(120, hw + 24)))
            y_lo = int(min(H * 0.40, max(95, hh + 28)))
            y_hi = int(max(y_lo + 20, H - max(95, hh + 28)))

            best_pt = (rng.randint(x_lo, x_hi), rng.randint(y_lo, y_hi))
            best_score = -1e12
            for _ in range(65):
                cx = rng.randint(x_lo, x_hi)
                cy = rng.randint(y_lo, y_hi)
                if not placed:
                    best_pt = (cx, cy)
                    break
                ov_area = 0.0
                min_edge_gap = 1e9
                for px, py, phw, phh in placed:
                    ox = (hw + phw) - abs(cx - px)
                    oy = (hh + phh) - abs(cy - py)
                    if ox > 0 and oy > 0:
                        ov_area += ox * oy
                    gap = math.hypot(cx - px, cy - py) - (hw + phw) * 0.5
                    if gap < min_edge_gap:
                        min_edge_gap = gap
                score = (-1e6 * ov_area) + min_edge_gap
                if score > best_score:
                    best_score = score
                    best_pt = (cx, cy)
            placed.append((best_pt[0], best_pt[1], hw, hh))

        res = [(p[0], p[1]) for p in placed]
        self._constellation_nodes[cache_key] = res
        return res

    def _run_overlay(self):
        enable_high_res_timer()
        try:
            self._run_overlay_impl()
        except Exception:
            self.fetcher._log(f"_run_overlay ERROR:\n{traceback.format_exc()}")
            self.running = False
        finally:
            disable_high_res_timer()

    def _run_overlay_impl(self):
        self._register_class()
        audio = SystemAudioMeter()
        audio.init_com()

        with self._lock:
            is_fs_mode = self._is_fullscreen_style(self.style)
            ct = self.click_through

        if is_fs_mode:
            x0, y0, w0, h0 = self._mon["x"], self._mon["y"], self._mon["w"], self._mon["h"]
            eff_ct = True
        else:
            x0, y0 = self._get_center_pos()
            w0, h0 = self.CENTER_W, self.CENTER_H
            eff_ct = ct

        self.OVERLAY_W, self.OVERLAY_H = w0, h0
        if IS_WIN:
            ex_style = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE
            if eff_ct:
                ex_style |= WS_EX_TRANSPARENT

            self.hwnd = user32.CreateWindowExW(
                ex_style, _CLASS_NAME, "SoulsLightsLyrics",
                WS_POPUP | WS_VISIBLE,
                x0, y0, w0, h0,
                None, None, kernel32.GetModuleHandleW(None), None
            )
            if not self.hwnd:
                audio.dispose()
                self.running = False
                return
            msg = wintypes.MSG()
        else:
            def _on_mac_dragged(nx, ny):
                with self._lock:
                    if self._is_fullscreen_style(self.style):
                        return
                    self.pos_x = int(nx)
                    self.pos_y = int(ny)
                    if self.cfg_mgr:
                        self.cfg_mgr.config["lyrics"]["pos_x"] = self.pos_x
                        self.cfg_mgr.config["lyrics"]["pos_y"] = self.pos_y
                        self.cfg_mgr.save_config()

            self.mac_win = MacOverlayWindow(
                x0, y0, w0, h0, role="lyrics", click_through=eff_ct, on_move=_on_mac_dragged
            )
            self.mac_win.set_visible(True)
            msg = None

        surf = LayeredSurface(w0, h0)
        last_render_sig = None
        curr_is_fs = is_fs_mode
        target_dt = 1.0 / 60.0
        next_frame = time.perf_counter() + target_dt

        try:
            while self.running:
                if IS_WIN:
                    while user32.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, 1):
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))

                title, artist, album, status, dur = "", "", "", "Idle", 0.0
                live_pos = 0.0
                spawn_fetch = None

                if self.media_mon:
                    info = self.media_mon.current_info
                    title = (info.get("title", "") or "").strip()
                    artist = (info.get("artist", "") or "").strip()
                    album = (info.get("album", "") or "").strip()
                    status = info.get("status", "Idle")
                    dur = float(info.get("duration_sec", 0.0))
                    live_pos = self.media_mon.get_live_position_sec()

                if status == "Playing":
                    self._audio_peak, self._audio_bloom = audio.sample()
                else:
                    self._audio_peak, self._audio_bloom = 0.0, 0.0

                with self._lock:
                    if self._dirty_font or not self._font_cache:
                        self._ensure_fonts()
                    style = self.style
                    accent = self.accent_color if self.auto_sync_colors else self.custom_accent
                    sec = self.secondary_color if self.auto_sync_colors else self.custom_accent
                    text_col = self.text_color
                    off_sec = self.offset_sec
                    ct = self.click_through
                    dirty_style = self._dirty_style
                    self._dirty_style = False

                    if self.media_mon:
                        tkey = f"{artist} - {title}"
                        if title in _NO_MEDIA_TITLES or status == "Idle":
                            self.current_track_key = ""
                            self.current_lyrics = []
                            self._flat_words = []
                            self._constellation_nodes.clear()
                            self.active_index = -1
                            self.lyrics_status = "Idle"
                        elif tkey != self.current_track_key:
                            self.current_track_key = tkey
                            self.current_lyrics = []
                            self._flat_words = []
                            self._init_constellation_sky(self._mon["w"], self._mon["h"], tkey)
                            self.active_index = -1
                            self.lyrics_status = "Searching lyrics..."
                            spawn_fetch = (title, artist, album, dur)

                    lyrics_snap = list(self.current_lyrics)
                    flat_snap = list(self._flat_words)
                    l_status_snap = self.lyrics_status

                want_fs = self._is_fullscreen_style(style)
                if want_fs != curr_is_fs:
                    curr_is_fs = want_fs
                    surf.dispose()
                    if want_fs:
                        nx, ny, nw, nh = self._mon["x"], self._mon["y"], self._mon["w"], self._mon["h"]
                        self._apply_ex_style(self.hwnd, True)
                    else:
                        nx, ny = self._get_center_pos()
                        nw, nh = self.CENTER_W, self.CENTER_H
                        self._apply_ex_style(self.hwnd, ct)
                    self.OVERLAY_W, self.OVERLAY_H = nw, nh
                    if IS_WIN:
                        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, nx, ny, nw, nh, SWP_NOACTIVATE)
                    elif self.mac_win:
                        self.mac_win.set_geometry(nx, ny, nw, nh)
                    surf = LayeredSurface(nw, nh)
                    surf.clear_surface()
                    self._full_canvas = None
                    self._prev_dirty_rect = None
                    last_render_sig = None

                win_x, win_y = (self._mon["x"], self._mon["y"]) if curr_is_fs else self._get_center_pos()

                if spawn_fetch:
                    threading.Thread(
                        target=self._fetch_worker,
                        args=(*spawn_fetch, False),
                        daemon=True
                    ).start()

                eff_pos = max(0.0, live_pos + off_sec)
                idx, w_idx, g_idx = self._find_active(lyrics_snap, flat_snap, eff_pos)

                anim_t = time.perf_counter()
                is_playing = (status == "Playing" and bool(title) and title not in _NO_MEDIA_TITLES)
                anim_tick = int(round(anim_t * 60.0)) if is_playing else (int(anim_t * 4) if not ct else 0)
                sig = (
                    style, idx, w_idx, g_idx, anim_tick, status, title,
                    accent, text_col, ct, dirty_style, len(lyrics_snap), l_status_snap
                )

                if sig != last_render_sig:
                    last_render_sig = sig
                    pres_target = self.hwnd if IS_WIN else self.mac_win
                    in_interlude = self._in_instrumental_gap(lyrics_snap, idx, eff_pos)
                    if curr_is_fs and lyrics_snap and idx >= 0 and flat_snap and not in_interlude:
                        sub_img, drect = self._render_constellation_dirty(
                            flat_snap, g_idx, eff_pos, anim_t, accent, sec, text_col
                        )
                        surf.upload_rect_rgba(sub_img, drect, prev_rect=self._prev_dirty_rect)
                        self._prev_dirty_rect = drect
                        surf.present(pres_target, win_x, win_y, master_alpha=255)
                    elif (not curr_is_fs) and ct and style in ("Fisheye", "Fisheye Visual") and lyrics_snap and idx >= 0 and flat_snap and not in_interlude:
                        w_u_f = 0.0
                        w_list = lyrics_snap[idx].get("words", [])
                        if w_list and 0 <= w_idx < len(w_list):
                            cw = w_list[w_idx]
                            w_u_f = max(0.0, min(1.0, (eff_pos - cw["start"]) / max(0.12, cw["end"] - cw["start"])))
                        warped, ox, oy = self._render_fisheye(
                            lyrics_snap, idx, w_idx, w_u_f, eff_pos, anim_t,
                            accent, sec, text_col, show_icons=(style == "Fisheye Visual")
                        )
                        drect = (ox, oy, ox + warped.width, oy + warped.height)
                        surf.upload_rect_rgba(warped, drect, prev_rect=self._prev_dirty_rect)
                        self._prev_dirty_rect = drect
                        surf.present(pres_target, win_x, win_y, master_alpha=255)
                    else:
                        frame = self._render_frame(
                            lyrics_snap, flat_snap, l_status_snap,
                            style, idx, w_idx, g_idx, eff_pos, anim_t,
                            status, title, artist, accent, sec, text_col, ct
                        )
                        surf.upload_pil_rgba(frame)
                        self._prev_dirty_rect = (0, 0, self.OVERLAY_W, self.OVERLAY_H)
                        surf.present(pres_target, win_x, win_y, master_alpha=255)

                now_end = time.perf_counter()
                if is_playing:
                    rem_s = next_frame - now_end
                    if rem_s > 0.001:
                        time.sleep(rem_s)
                        next_frame += target_dt
                    else:
                        next_frame = now_end + target_dt
                else:
                    time.sleep(0.05)
                    next_frame = time.perf_counter() + target_dt
        finally:
            audio.dispose()
            surf.dispose()
            if IS_WIN and self.hwnd:
                user32.DestroyWindow(self.hwnd)
                self.hwnd = None
            elif self.mac_win:
                self.mac_win.dispose()
                self.mac_win = None

    def _fetch_worker(self, title, artist, album, dur, force):
        expected = f"{artist} - {title}"
        try:
            lines, src = self.fetcher.get_lyrics(title, artist, album, dur, force_refresh=force)
            flat = self._build_flat_words(lines) if lines else []
            with self._lock:
                if self.current_track_key == expected or force:
                    self.current_lyrics = lines
                    self._flat_words = flat
                    self.active_index = -1
                    if lines:
                        self.lyrics_status = f"Synced • {len(lines)} lines ({src})"
                    else:
                        self.lyrics_status = "No synced lyrics found"
                    self._dirty_style = True
        except Exception:
            self.fetcher._log(f"_fetch_worker exception: {traceback.format_exc()}")
            with self._lock:
                if self.current_track_key == expected or force:
                    self.current_lyrics = []
                    self._flat_words = []
                    self.lyrics_status = "Lyrics lookup error"
                    self._dirty_style = True

    def _find_active(self, lyrics, flat_words, eff_pos):
        if not lyrics:
            return -1, -1, -1
        if eff_pos < lyrics[0]["time"]:
            return 0, -1, -1
        idx = 0
        for i, line in enumerate(lyrics):
            if line["time"] <= eff_pos:
                idx = i
            else:
                break
        words = lyrics[idx].get("words", [])
        w_idx = 0
        for wi, w in enumerate(words):
            if w["start"] <= eff_pos:
                w_idx = wi
            else:
                break
        g_idx = 0
        for gi, fw in enumerate(flat_words):
            if fw["start"] <= eff_pos:
                g_idx = gi
            else:
                break
        return idx, w_idx, g_idx

    def _measure_text(self, draw, txt, font):
        f_use = self._safe_font(font, txt)
        bb = draw.textbbox((0, 0), txt, font=f_use)
        return bb[2] - bb[0], bb[3] - bb[1]

    def _in_instrumental_gap(self, lyrics, idx, eff_pos) -> bool:
        if not lyrics:
            return False
        if eff_pos < lyrics[0]["time"] - 2.0:
            return True
        if idx >= 0 and idx < len(lyrics):
            cur = lyrics[idx]
            has_stop = bool(cur.get("has_stop_marker", False))
            out_thresh = 1.4 if has_stop else 4.2
            in_thresh = 1.6 if has_stop else 4.2
            if (eff_pos - cur["end"]) > out_thresh:
                if idx + 1 >= len(lyrics) or (lyrics[idx + 1]["time"] - eff_pos) > in_thresh:
                    return True
        return False

    def _get_tinted_icon(self, ico: str, emoji_font, accent_rgb, is_active: bool):
        """Renders and caches monochrome-pearl or pastel album-duotone aesthetic icons."""
        if not ico or not emoji_font:
            return None
        q_acc = (accent_rgb[0] // 8 * 8, accent_rgb[1] // 8 * 8, accent_rgb[2] // 8 * 8) if is_active else (0, 0, 0)
        key = (ico, emoji_font.size, q_acc, bool(is_active))
        cached = self._icon_patch_cache.get(key)
        if cached is not None:
            return cached

        pad = int(emoji_font.size * 0.4) + 10
        sz = int(emoji_font.size * 1.4) + pad * 2
        tmp = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((pad, pad), ico, font=emoji_font, embedded_color=True)
        bb = tmp.getbbox()
        if not bb:
            return None
        # Verify the glyph is not a .notdef tofu box
        nd_tmp = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        ImageDraw.Draw(nd_tmp).text((pad, pad), "\uffff", font=emoji_font, embedded_color=True)
        if tmp.tobytes() == nd_tmp.tobytes():
            return None
        crop = tmp.crop(bb)
        a = crop.getchannel("A")
        lum = ImageOps.autocontrast(crop.convert("L"), cutoff=2)
        if is_active:
            dark = (int(accent_rgb[0] * 0.55), int(accent_rgb[1] * 0.55), int(accent_rgb[2] * 0.55))
            mid = (int(accent_rgb[0] * 0.85 + 38), int(accent_rgb[1] * 0.85 + 38), int(accent_rgb[2] * 0.85 + 38))
            light = (min(255, int(accent_rgb[0] * 0.35 + 172)), min(255, int(accent_rgb[1] * 0.35 + 172)), min(255, int(accent_rgb[2] * 0.35 + 172)))
            colored = ImageOps.colorize(lum, black=dark, mid=mid, white=light).convert("RGBA")
        else:
            # Frosted monochrome silver-pearl aesthetic
            colored = ImageOps.colorize(lum, black=(115, 122, 138), mid=(195, 202, 215), white=(245, 247, 252)).convert("RGBA")
        colored.putalpha(a)

        if len(self._icon_patch_cache) > 240:
            self._icon_patch_cache.clear()
        self._icon_patch_cache[key] = colored
        return colored

    def _stamp_icon(self, canvas_img, x: int, y: int, ico: str, emoji_font, accent_rgb, is_active: bool, alpha_mul: float = 1.0):
        patch = self._get_tinted_icon(ico, emoji_font, accent_rgb, is_active)
        if patch is None:
            return
        if alpha_mul < 0.98:
            patch = patch.copy()
            a = patch.getchannel("A").point(lambda p: int(p * alpha_mul))
            patch.putalpha(a)
        canvas_img.alpha_composite(patch, (max(0, min(canvas_img.width - 1, int(x))), max(0, min(canvas_img.height - 1, int(y)))))

    def _icon_width(self, draw, ico, emoji_font):
        if not ico or not emoji_font:
            return 0
        patch = self._get_tinted_icon(ico, emoji_font, (220, 220, 230), False)
        if patch is not None:
            return patch.width + 6
        clean_ico = ico.replace("\ufe0f", "")
        raw_iw = self._measure_text(draw, clean_ico, emoji_font)[0]
        return min(raw_iw, int(emoji_font.size * 1.18)) + 6

    def _draw_text_shadow(self, draw, x, y, text, font, fill_rgba, shadow_alpha=215):
        f_use = self._safe_font(font, text)
        draw.text((x + 1, y + 2), text, font=f_use, fill=(0, 0, 0, shadow_alpha))
        draw.text((x, y), text, font=f_use, fill=fill_rgba)

    def _draw_centered_with_shadow(self, draw, y, text, font, fill_rgba, shadow_alpha=205):
        f_use = self._safe_font(font, text)
        tw, th = self._measure_text(draw, text, f_use)
        x = max(16, (self.OVERLAY_W - tw) // 2)
        self._draw_text_shadow(draw, x, y, text, f_use, fill_rgba, shadow_alpha)
        return tw, th

    def _draw_word_with_opt_icon(
        self, canvas_img, draw, cx_center, y_center, word_text, font, fill_rgba,
        ico=None, emoji_font=None, accent_rgb=(236, 72, 153), is_active=True,
        shadow_a=210, glow_draw=None, glow_col=None, lit_ratio=None, lit_rgba=None
    ):
        f_use = self._safe_font(font, word_text)
        bb = draw.textbbox((0, 0), word_text, font=f_use)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        iw = self._icon_width(draw, ico, emoji_font)
        total_w = tw + (iw + 8 if iw else 0)
        x = int(cx_center - total_w * 0.5 - bb[0])
        y = int(y_center - (bb[1] + bb[3]) * 0.5)
        if glow_draw is not None and glow_col is not None:
            glow_draw.text((x, y), word_text, font=f_use, fill=glow_col)
        self._draw_text_shadow(draw, x, y, word_text, f_use, fill_rgba, shadow_alpha=shadow_a)
        if lit_ratio is not None and lit_rgba is not None and word_text:
            lit_n = max(1, min(len(word_text), int(math.ceil(len(word_text) * max(0.0, min(1.0, lit_ratio))))))
            draw.text((x, y), word_text[:lit_n], font=f_use, fill=lit_rgba)
        if iw and emoji_font and canvas_img is not None:
            patch = self._get_tinted_icon(ico, emoji_font, accent_rgb, is_active)
            if patch is not None:
                ex = int(cx_center - total_w * 0.5) + tw + 10
                ey = int(y_center - patch.height * 0.5)
                self._stamp_icon(canvas_img, ex, ey, ico, emoji_font, accent_rgb, is_active, alpha_mul=fill_rgba[3] / 255.0)
        return total_w, th

    def _draw_word_line_kinetic(
        self, canvas_img, draw, y_center, words, w_idx, w_u, eff_pos, font, emoji_font,
        active_col, done_col, todo_col, accent_rgb=(236, 72, 153), show_icons=True, glow_layer=None,
        wave_amp=0.0, active_lift=0.0, active_pop=False, max_w=None, anim_t=0.0
    ):
        """Draws a line with smooth per-word wave motion, spring pop, lift, and monochrome/duotone icons."""
        max_line_w = (max_w or (self.OVERLAY_W - 80))

        def _layout(f_txt, f_emo):
            sp = self._measure_text(draw, " ", f_txt)[0]
            toks = []
            tot = 0
            for i, wobj in enumerate(words):
                f_use = f_txt
                fe_use = f_emo
                if active_pop and i == w_idx and w_idx >= 0:
                    pop_u = _ease_out_back(min(1.0, w_u * 2.4))
                    f_use = self._get_font("bold", int(f_txt.size * (1.0 + 0.16 * pop_u))) or f_txt
                    fe_use = self._get_font("emoji", int(f_emo.size * (1.0 + 0.16 * pop_u))) if f_emo else None
                w = wobj["word"]
                f_use = self._safe_font(f_use, w)
                bb = draw.textbbox((0, 0), w, font=f_use)
                ww = bb[2] - bb[0]
                ico = wobj.get("icon") if show_icons else None
                iw = self._icon_width(draw, ico, fe_use)
                toks.append((i, w, bb, ww, f_use, fe_use, ico, iw))
                tot += ww + iw + (sp if i < len(words) - 1 else 0)
            return sp, toks, tot

        space_w, tokens, total_w = _layout(font, emoji_font)
        if total_w > max_line_w:
            f_c = self._get_font("bold", int(font.size * 0.74)) or font
            fe_c = self._get_font("emoji", int(emoji_font.size * 0.74)) if emoji_font else None
            space_w, tokens, total_w = _layout(f_c, fe_c)
            font, emoji_font = f_c, fe_c
            if total_w > max_line_w:
                f_s = self._get_font("bold", int(font.size * 0.78)) or font
                space_w, tokens, total_w = _layout(f_s, fe_c)

        cx = max(24, int((self.OVERLAY_W - total_w) * 0.5))
        gd = ImageDraw.Draw(glow_layer) if glow_layer is not None else None
        for i, w, bb, ww, f_use, fe_use, ico, iw in tokens:
            is_act = (i == w_idx and w_idx >= 0)
            if w_idx < 0:
                col = todo_col
            elif i < w_idx:
                col = done_col
            elif is_act:
                col = active_col
            else:
                col = todo_col

            wy = y_center
            if wave_amp > 0.0:
                wy += math.sin(eff_pos * 4.5 + i * 0.85) * wave_amp
            if active_lift and is_act:
                lift_u = math.sin(max(0.0, min(1.0, w_u)) * math.pi)
                wy -= active_lift * (0.45 + 0.55 * lift_u)

            tx = cx - bb[0]
            ty = int(wy - (bb[1] + bb[3]) * 0.5)

            if is_act and gd is not None:
                gd.text((tx, ty), w, font=f_use, fill=(*active_col[:3], 235))

            self._draw_text_shadow(draw, tx, ty, w, f_use, col, shadow_alpha=215)
            cx += ww
            if iw and fe_use and canvas_img is not None:
                ico_dy = int(-6 * math.sin(anim_t * 8.0)) if is_act else 0
                patch = self._get_tinted_icon(ico, fe_use, accent_rgb, is_active=(w_idx >= 0 and i <= w_idx))
                if patch is not None:
                    ey = int(wy - patch.height * 0.5) + ico_dy
                    self._stamp_icon(canvas_img, cx + 6, ey, ico, fe_use, accent_rgb, is_active=(w_idx >= 0 and i <= w_idx), alpha_mul=col[3] / 255.0)
                    if is_act and gd is not None:
                        gd.ellipse([cx + 4, ey, cx + 6 + patch.width, ey + patch.height], fill=(*accent_rgb, 110))
                cx += iw
            cx += space_w

    def _draw_star(self, draw, cx, cy, r, fill, angle_rad=0.0):
        pts = []
        for k in range(8):
            rad = (r * 2.2) if (k % 2 == 0) else (r * 0.52)
            a = angle_rad + k * (math.pi / 4.0)
            pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
        draw.polygon(pts, fill=fill)

    def _render_no_lyrics_visualizer(
        self, img, d, lyrics, idx, eff_pos, anim_t, l_status, title, artist, accent, sec, text_col
    ):
        """Sleek Apple-Music-style animated loading dots & subtle beat thump for interludes / searching."""
        W, H = self.OVERLAY_W, self.OVERLAY_H
        cx, cy = W // 2, H // 2
        s = self.font_scale
        peak = self._audio_peak
        bloom = self._audio_bloom

        # 2x supersampled compact patch for ultra-crisp circular orbs without blurring the whole screen
        ss = 2
        pw, ph = int(240 * s), int(110 * s)
        patch_glow = Image.new("RGBA", (pw * ss, ph * ss), (0, 0, 0, 0))
        patch_core = Image.new("RGBA", (pw * ss, ph * ss), (0, 0, 0, 0))
        pgd = ImageDraw.Draw(patch_glow)
        pcd = ImageDraw.Draw(patch_core)

        pcx, pcy = (pw * ss) // 2, (ph * ss) // 2
        spacing = 32.0 * s * ss
        dot_cnt = 3
        start_dx = -0.5 * (dot_cnt - 1) * spacing

        for k in range(dot_cnt):
            phase = anim_t * 3.3 - k * 1.05
            wave = 0.5 + 0.5 * math.sin(phase)
            bounce_y = -6.0 * s * ss * math.sin(phase) - (3.5 * s * ss * bloom * (0.5 + 0.5 * wave))
            dx = start_dx + k * spacing
            px = pcx + dx
            py = pcy + bounce_y

            rad = (6.2 + 3.2 * (wave ** 1.35) + 2.8 * (bloom ** 0.8)) * s * ss
            lum_k = 0.25 + 0.75 * wave
            col = _lerp_color((165, 174, 194), _lerp_color((248, 250, 255), accent, 0.28 + 0.42 * bloom), lum_k)
            alpha = int(135 + 120 * lum_k)

            # Soft restrained outer glow + crisp dark backdrop halo, razor-sharp dot core on top
            if bloom > 0.08 or wave > 0.45:
                hr = rad * 1.55
                pgd.ellipse([px - hr, py - hr, px + hr, py + hr], fill=(*accent, int(65 * lum_k + 80 * bloom)))
            pcd.ellipse([px - rad, py - rad + 2 * ss, px + rad, py + rad + 2 * ss], fill=(0, 0, 0, int(95 * lum_k)))
            pcd.ellipse([px - rad, py - rad, px + rad, py + rad], fill=(*col, alpha))

        glow_blur = patch_glow.filter(ImageFilter.GaussianBlur(radius=max(2, int(6 * ss)))).resize((pw, ph), Image.Resampling.BILINEAR)
        core_crisp = patch_core.resize((pw, ph), Image.Resampling.LANCZOS)
        dots_patch = Image.alpha_composite(glow_blur, core_crisp)

        y_dots = cy - int(10 * s)
        img.alpha_composite(dots_patch, (cx - pw // 2, y_dots - ph // 2))

        # Minimal clean subtitle neatly beneath the dots
        f_sub = self._font_cache["small"]
        f_next = self._get_font("bold", int(22 * s))
        if lyrics and 0 <= idx < len(lyrics):
            next_i = 0 if eff_pos < lyrics[0]["time"] else (idx + 1 if idx + 1 < len(lyrics) else -1)
            if 0 <= next_i < len(lyrics):
                wait_s = max(0.0, lyrics[next_i]["time"] - eff_pos)
                if wait_s <= 3.8:
                    nxt_txt = lyrics[next_i]["text"][:54]
                    alpha_nxt = max(70, min(225, int(215 * (1.0 - max(0.0, wait_s - 0.4) / 3.4))))
                    self._draw_centered_with_shadow(d, cy + int(34 * s), nxt_txt, f_next, (*text_col, alpha_nxt))
                else:
                    self._draw_centered_with_shadow(d, cy + int(32 * s), f"Vocals in {max(1, int(math.ceil(wait_s)))}s", f_sub, (210, 218, 232, 165))
        elif l_status == "Searching lyrics...":
            self._draw_centered_with_shadow(d, cy + int(30 * s), "Searching synced lyrics", f_sub, (208, 216, 232, 165))
        else:
            caption = f"{title[:42]}" + (f"  •  {artist[:28]}" if artist else "")
            self._draw_centered_with_shadow(d, cy + int(30 * s), caption, f_sub, (212, 220, 234, 155))

        return img

    def _render_fisheye(
        self, lyrics, idx, w_idx, w_u, eff_pos, anim_t, accent, sec, text_col, show_icons
    ):
        """Premium Fisheye dome: bigger canvas, chromatic aberration on active word, snappier spring bounce,
        1.4× scale pop, radial beat-pulse halo, frosted upcoming whisper, stronger barrel warp."""
        W, H = self.OVERLAY_W, self.OVERLAY_H
        # Larger dome for more breathing room (scales smoothly with large font_scale up to 2.8x)
        LW, LH = min(1080, W - 20), min(580, H - 16)
        s = self.font_scale

        curr_line = lyrics[idx]
        next_text = lyrics[idx + 1]["text"] if idx + 1 < len(lyrics) else ""
        words = curr_line.get("words", [])

        # Balanced 2–3 row chunking with generous vertical spread
        n_w = len(words)
        if n_w >= 8:
            c1 = (n_w + 2) // 3
            c2 = c1 + (n_w - c1 + 1) // 2
            raw_chunks = [(words[:c1], 0), (words[c1:c2], c1), (words[c2:], c2)]
            base_pt, y_slots = 46, (0.25, 0.46, 0.67)
        elif n_w >= 4:
            split_i = (n_w + 1) // 2
            raw_chunks = [(words[:split_i], 0), (words[split_i:], split_i)]
            base_pt, y_slots = 56, (0.34, 0.58)
        else:
            raw_chunks = [(words, 0)]
            base_pt, y_slots = 64, (0.46,)

        rng = random.Random(idx * 73856093 ^ 0x4F1E)
        trans_mode = rng.choice((
            "swipe_left", "swipe_right", "swipe_up", "swipe_down",
            "diagonal_left", "diagonal_right", "zoom_burst", "split_merge"
        ))
        warp_base_k = rng.choice((0.52, 0.60, 0.68))

        # Snappy 0.26s spring entry with more overshoot for Apple-feel pop
        line_t = max(0.0, eff_pos - curr_line["time"])
        line_u = _ease_out_back(min(1.0, line_t / 0.26))
        rem = 1.0 - line_u

        dx_in, dy_in, tilt_deg = 0, 0, 0.0
        zoom_scale = 1.0
        split_dx = 0
        if trans_mode == "swipe_left":
            dx_in = int(260 * rem)
        elif trans_mode == "swipe_right":
            dx_in = int(-260 * rem)
        elif trans_mode == "swipe_up":
            dy_in = int(95 * rem)
        elif trans_mode == "swipe_down":
            dy_in = int(-95 * rem)
        elif trans_mode == "diagonal_left":
            dx_in, dy_in, tilt_deg = int(190 * rem), int(65 * rem), -7.0 * max(0.0, rem)
        elif trans_mode == "diagonal_right":
            dx_in, dy_in, tilt_deg = int(-190 * rem), int(65 * rem), 7.0 * max(0.0, rem)
        elif trans_mode == "zoom_burst":
            zoom_scale = max(0.52, 0.58 + 0.42 * line_u)
        elif trans_mode == "split_merge":
            split_dx = int(155 * rem)

        line_canvas = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))
        # Glow quarter-res layer for active word halo
        glow_q = Image.new("RGBA", (max(32, LW // 4), max(32, LH // 4)), (0, 0, 0, 0))
        qgd = ImageDraw.Draw(glow_q)
        ld = ImageDraw.Draw(line_canvas)

        atk_pulse = max(0.0, 1.0 - w_u * 2.2) if w_idx >= 0 else 0.0

        f_line = self._get_font("bold", int(base_pt * s * zoom_scale))
        f_emo = self._get_font("emoji", int(base_pt * 0.88 * s * zoom_scale)) if self._font_paths.get("emoji") else None

        saved_w, saved_h = self.OVERLAY_W, self.OVERLAY_H
        self.OVERLAY_W, self.OVERLAY_H = LW, LH

        done_tint = _lerp_color(text_col, accent, 0.38) if self.auto_sync_colors else accent
        for r_i, (row_words, base_wi) in enumerate(raw_chunks):
            ry = int(LH * y_slots[r_i]) + dy_in
            r_dx = dx_in + (split_dx if (r_i % 2) else -split_dx)
            local_wi = (w_idx - base_wi) if (w_idx >= base_wi and w_idx < base_wi + len(row_words)) else (-2 if w_idx < base_wi else 999)
            row_img = Image.new("RGBA", (LW, LH), (0, 0, 0, 0)) if r_dx != 0 else line_canvas
            row_d = ImageDraw.Draw(row_img) if r_dx != 0 else ld
            self._draw_word_line_kinetic(
                row_img, row_d, ry, row_words,
                -1 if local_wi < 0 else (999 if local_wi > len(row_words) else local_wi),
                w_u, eff_pos, f_line, f_emo,
                active_col=(255, 255, 255, 255),
                done_col=(*done_tint, 248),
                todo_col=(200, 210, 230, 148),
                accent_rgb=accent,
                show_icons=show_icons,
                glow_layer=None,
                wave_amp=5.0,
                active_lift=14.0,
                active_pop=True,
                max_w=LW - 80,
                anim_t=anim_t,
            )
            if r_dx != 0 and -LW < r_dx < LW:
                line_canvas.alpha_composite(row_img, (r_dx, 0))

        self.OVERLAY_W, self.OVERLAY_H = saved_w, saved_h

        # Also gently intensify sustain aura near completion of a held slow-cue word in Fisheye
        sustain_hold = max(0.0, (w_u - 0.55) / 0.45) if w_idx >= 0 else 0.0

        # --- Chromatic aberration on active word: red-shifted left, blue-shifted right, white center ---
        qcx = glow_q.width // 2
        if words and 0 <= w_idx < len(words):
            cw_txt = words[w_idx]["word"]
            f_glow_q = self._safe_font(self._get_font("bold", max(8, int(base_pt * s * zoom_scale // 4))), cw_txt)
            bb_q = qgd.textbbox((0, 0), cw_txt, font=f_glow_q)
            tw_q, th_q = bb_q[2] - bb_q[0], bb_q[3] - bb_q[1]
            row_hit = 0
            for ri_c, (rw_c, b_wi_c) in enumerate(raw_chunks):
                if b_wi_c <= w_idx < b_wi_c + len(rw_c):
                    row_hit = ri_c
                    break
            qy = max(8, min(glow_q.height - th_q - 8,
                            int(glow_q.height * y_slots[row_hit] - (bb_q[1] + bb_q[3]) * 0.5)))
            sh_a = int(130 + 100 * max(atk_pulse, sustain_hold * (0.75 + 0.25 * math.sin(anim_t * 3.8))))
            # Red-shifted (accent-warm, left shift)
            ca_r = _lerp_color(accent, (255, 100, 100), 0.6)
            qgd.text((max(4, qcx - tw_q // 2 - 3), qy), cw_txt, font=f_glow_q, fill=(*ca_r, sh_a))
            # Blue-shifted (sec-cool, right shift)
            ca_b = _lerp_color(sec, (100, 140, 255), 0.5)
            qgd.text((max(4, qcx - tw_q // 2 + 3), qy), cw_txt, font=f_glow_q, fill=(*ca_b, sh_a))
            # White center glow (no shift)
            qgd.text((max(4, qcx - tw_q // 2), qy), cw_txt, font=f_glow_q, fill=(255, 255, 255, int(sh_a * 0.7)))

            # Beat-pulse radial halo around active word area
            pulse_r = int((tw_q * 0.5 + 18) * (1.0 + 0.25 * atk_pulse))
            halo_a = int((60 + 80 * atk_pulse))
            qgd.ellipse([qcx - pulse_r, qy - 8, qcx + pulse_r, qy + th_q + 8],
                        outline=(*accent, halo_a), width=2)

        # Frosted upcoming whisper (soft glass row at 28% opacity)
        if next_text:
            f_next = self._get_font("reg", int(19 * s))
            tw_n, th_n = self._measure_text(ld, next_text[:48], f_next)
            whisper_x = max(40, (LW - tw_n) // 2)
            whisper_y = int(LH * 0.80) + int(5 * max(0.0, rem))
            # Frosted pill background
            ld.rounded_rectangle([whisper_x - 16, whisper_y - 6, whisper_x + tw_n + 16, whisper_y + th_n + 6],
                                  radius=12, fill=(255, 255, 255, 18))
            self._draw_text_shadow(ld, whisper_x, whisper_y, next_text[:48], f_next,
                                   (215, 220, 235, 120), shadow_alpha=140)

        if abs(tilt_deg) > 0.2:
            line_canvas = line_canvas.rotate(tilt_deg, resample=Image.Resampling.BILINEAR)

        # Glow blur — slightly stronger radius for bigger canvas
        glow_full = glow_q.filter(ImageFilter.GaussianBlur(radius=3.8)).resize((LW, LH), Image.Resampling.BILINEAR)
        lens_combined = Image.alpha_composite(glow_full, line_canvas)

        # Stronger fisheye warp + audio reactivity
        warp_k = warp_base_k + 0.09 * atk_pulse + 0.08 * self._audio_bloom + 0.025 * math.sin(anim_t * 2.6)
        mesh = self._get_warp_mesh(LW, LH, warp_k, zoom_base=0.78)
        warped = lens_combined.transform((LW, LH), Image.Transform.MESH, mesh, resample=Image.Resampling.BILINEAR)

        ox = (W - LW) // 2
        oy = (H - LH) // 2
        return warped, ox, oy

    def _ensure_full_canvases(self, W, H):
        if self._full_canvas is None or self._full_canvas.size != (W, H):
            self._full_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            self._full_draw = ImageDraw.Draw(self._full_canvas)
            self._full_glow = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
            self._full_glow_draw = ImageDraw.Draw(self._full_glow)
            self._prev_dirty_rect = None

    def _render_constellation_dirty(self, flat_words, g_idx, eff_pos, anim_t, accent, sec, text_col):
        """Premium Constellation: 3-star focus (prev · active · next), purely random positions,
        gradient beam lines, radial burst glow, spark emit, 3-tier starfield. Tight dirty-rect upload."""
        W, H = self.OVERLAY_W, self.OVERLAY_H
        self._ensure_full_canvases(W, H)
        im = self._full_canvas
        d = self._full_draw
        gl = self._full_glow
        gd = self._full_glow_draw
        s = self.font_scale

        # Clear only previous dirty region
        if self._prev_dirty_rect:
            im.paste((0, 0, 0, 0), self._prev_dirty_rect)
            px0, py0, px1, py1 = self._prev_dirty_rect
            gl.paste((0, 0, 0, 0), (max(0, px0 // 4 - 2), max(0, py0 // 4 - 2),
                                    min(W // 4, (px1 + 3) // 4 + 2), min(H // 4, (py1 + 3) // 4 + 2)))
        else:
            im.paste((0, 0, 0, 0), (0, 0, W, H))
            gl.paste((0, 0, 0, 0), (0, 0, W // 4, H // 4))

        # Show ALL non-bracket words of the current line at random non-overlapping points
        gi_safe = max(0, g_idx if g_idx >= 0 else 0)
        while gi_safe > 0 and flat_words[gi_safe].get("in_brackets"):
            gi_safe -= 1

        cur_line_idx = flat_words[gi_safe]["line_idx"]
        subset = [fw for fw in flat_words if fw["line_idx"] == cur_line_idx and not fw.get("in_brackets")]
        if not subset:
            subset = [flat_words[gi_safe]]

        rel_active = -1
        for si, fw in enumerate(subset):
            if fw["g_idx"] == gi_safe:
                rel_active = si
                break

        def _strip_brackets(txt: str) -> str:
            """Clean any stray bracket characters."""
            return re.sub(r'[\(\)\[\]]', '', txt).strip()

        # Non-overlapping random positions for the whole line + subtle float
        base_pts = self._get_line_constellation_pts(cur_line_idx, subset, W, H)
        pts = []
        for (bx, by), wobj in zip(base_pts, subset):
            gi = wobj["g_idx"]
            ox = 6.5 * math.cos(anim_t * 0.78 + gi * 1.37)
            oy = 5.0 * math.sin(anim_t * 0.95 + gi * 2.09)
            px = max(110, min(W - 110, int(bx + ox)))
            py = max(85, min(H - 85, int(by + oy)))
            pts.append((px, py, wobj))

        trans_u = 1.0
        shoot_u = 1.0
        word_prog = 1.0
        spark_fire = False
        if 0 <= gi_safe < len(flat_words) and rel_active >= 0:
            cur = flat_words[gi_safe]
            dur = max(0.14, cur["end"] - cur["start"])
            elapsed = max(0.0, eff_pos - cur["start"])
            # Fast pop-in at word start (~0.11s) so active word lands right on beat
            trans_u = _ease_out_cubic(min(1.0, elapsed / min(0.11, dur * 0.45)))
            # Smooth shooting star glide from previous star to active star (~0.24s)
            shoot_u = _ease_out_cubic(min(1.0, elapsed / min(0.24, dur * 0.70)))
            word_prog = min(1.0, elapsed / dur)
            spark_fire = (0.82 <= word_prog <= 0.98)

        # Dirty-rect bounding box around only the visible stars
        all_xs = [p[0] for p in pts]
        all_ys = [p[1] for p in pts]
        margin_x, margin_y = 220, 120
        x0 = max(0, min(all_xs) - margin_x) if all_xs else 0
        y0 = max(0, min(all_ys) - margin_y) if all_ys else 0
        x1 = min(W, max(all_xs) + margin_x) if all_xs else W
        y1 = min(H, max(all_ys) + margin_y) if all_ys else H
        if (x1 - x0) > W * 0.52:
            x0, x1 = 0, W

        # --- Layered ambient starfield (3 sizes, staggered twinkle) ---
        tier_radii = (1.0, 1.9, 2.8)
        tier_base_alpha = (85, 110, 130)
        for sx, sy, sph, tier in self._bg_stars:
            if x0 + 4 <= sx <= x1 - 4 and y0 + 4 <= sy <= y1 - 4:
                ti = int(tier)
                tw_spd = (5.5, 3.2, 1.9)[ti]
                tw = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(anim_t * tw_spd + sph))
                sr = tier_radii[ti]
                sa = int(tier_base_alpha[ti] * tw)
                d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(230, 237, 255, sa))

        # --- Gradient glow beam between consecutive visible stars ---
        def _draw_gradient_line(draw_obj, xa, ya, xb, yb, col_rgba, widths=(5, 3, 1)):
            for w_px, alpha_mul in zip(widths, (0.25, 0.55, 1.0)):
                a = int(col_rgba[3] * alpha_mul)
                draw_obj.line([(xa, ya), (xb, yb)], fill=(*col_rgba[:3], a), width=w_px)

        for i in range(len(pts) - 1):
            x_a, y_a, _ = pts[i]
            x_b, y_b, _ = pts[i + 1]
            if rel_active >= 0 and i < rel_active - 1:
                # Already-sung connection in the line — glowing accent beam
                _draw_gradient_line(d, x_a, y_a, x_b, y_b, (*accent, 165), widths=(5, 2, 1))
                gd.line([(x_a // 4, y_a // 4), (x_b // 4, y_b // 4)], fill=(*accent, 125), width=2)
            elif rel_active >= 1 and i == rel_active - 1:
                # Subtle base track
                d.line([(x_a, y_a), (x_b, y_b)], fill=(180, 195, 225, 48), width=1)
                # Entire shooting star line glows smoothly from prev -> meteor head (mx, my)
                mx = x_a + (x_b - x_a) * shoot_u
                my = y_a + (y_b - y_a) * shoot_u
                if shoot_u > 0.02:
                    for w_px, a_val in ((13, 28), (9, 55), (5, 115), (3, 195)):
                        d.line([(x_a, y_a), (int(mx), int(my))], fill=(*accent, a_val), width=w_px)
                    d.line([(x_a, y_a), (int(mx), int(my))], fill=(255, 250, 230, 230), width=2)
                if shoot_u < 0.98:
                    d.ellipse([int(mx) - 9, int(my) - 9, int(mx) + 9, int(my) + 9], fill=(*accent, 85))
                    d.ellipse([int(mx) - 5, int(my) - 5, int(mx) + 5, int(my) + 5], fill=(255, 252, 235, 255))
            else:
                # Upcoming connection in the line — subtle silver guide line
                _draw_gradient_line(d, x_a, y_a, x_b, y_b, (180, 195, 225, 52), widths=(3, 1))

        # --- Star nodes and words for the entire current line ---
        done_tint = _lerp_color(text_col, accent, 0.38)
        for i, (px, py, wobj) in enumerate(pts):
            is_act = (i == rel_active)
            is_done = (rel_active >= 0 and i < rel_active)
            display_word = _strip_brackets(wobj["word"])

            if is_act:
                sz = int((32 + 20 * trans_u) * s)
                alpha = int(175 + 80 * trans_u)
                f_w = self._get_font("bold", sz)

                self._draw_star(gd, px // 4, (py - int(28 * s)) // 4,
                                4, (*accent, int(210 * trans_u)), angle_rad=anim_t * 1.3)
                self._draw_star(d, px, py - int(28 * s),
                                8, (255, 244, 190, alpha), angle_rad=anim_t * 1.3)

                # Clean letter-hugging glow that intensifies toward the end of the word and breathes gently on long holds
                end_glow = 0.28 + 0.72 * (word_prog ** 1.35)
                if word_prog >= 0.88:
                    end_glow *= (0.88 + 0.12 * math.sin(anim_t * 3.8))
                f_gq = self._safe_font(self._get_font("bold", max(8, sz // 4)), display_word)
                bb_q = gd.textbbox((0, 0), display_word, font=f_gq)
                qx = int(px // 4 - (bb_q[2] - bb_q[0]) * 0.5 - bb_q[0])
                qy = int((py + int(6 * s)) // 4 - (bb_q[1] + bb_q[3]) * 0.5)
                gd.text((qx, qy), display_word, font=f_gq, fill=(*accent, int(225 * end_glow)))
                if word_prog > 0.55:
                    warm_a = int(185 * ((word_prog - 0.55) / 0.45))
                    gd.text((qx, qy), display_word, font=f_gq, fill=(255, 250, 225, warm_a))

                base_rgb = _lerp_color((175, 190, 218), accent, 0.35)
                lit_rgb = _lerp_color((255, 248, 215), (255, 255, 255), trans_u)
                self._draw_word_with_opt_icon(
                    im, d, px, py + int(6 * s), display_word, f_w,
                    (*base_rgb, int(alpha * 0.80)),
                    shadow_a=int(230 * trans_u + 150 * (1 - trans_u)),
                    lit_ratio=word_prog, lit_rgba=(*lit_rgb, alpha)
                )

                if spark_fire:
                    rng_sp = random.Random(int(anim_t * 24) ^ wobj["g_idx"])
                    for _ in range(7):
                        ang = rng_sp.uniform(0, 2 * math.pi)
                        dist = rng_sp.uniform(20, 56)
                        spx = int(px + math.cos(ang) * dist)
                        spy = int(py + math.sin(ang) * dist)
                        sa2 = rng_sp.randint(140, 230)
                        d.ellipse([spx - 2, spy - 2, spx + 2, spy + 2], fill=(*accent, sa2))

            elif is_done:
                # Already-sung word in this line — stays visible in soft accent tint
                is_prev = (i == rel_active - 1)
                sz = int((46 - 18 * trans_u) * s) if is_prev else int(26 * s)
                alpha = int(235 - 40 * trans_u) if is_prev else 190
                col_rgb = _lerp_color((255, 250, 220), done_tint, trans_u if is_prev else 1.0)
                f_w = self._get_font("bold", sz)
                self._draw_star(d, px, py + int(18 * s), 3.6, (*accent, alpha), angle_rad=anim_t * 0.5)
                self._draw_word_with_opt_icon(im, d, px, py - int(5 * s), display_word, f_w,
                                              (*col_rgb, alpha), shadow_a=175)

            else:
                # Upcoming word in this line — visible at its random star point, waiting to be sung
                is_next = (rel_active >= 0 and i == rel_active + 1)
                pulse = (0.5 + 0.5 * math.sin(anim_t * 3.2)) if is_next else 0.0
                alpha = int(145 + 30 * pulse)
                f_w = self._get_font("reg", int((26 if is_next else 24) * s))
                d.ellipse([px - 3, py + 15, px + 3, py + 21],
                          fill=(*sec, int(135 + 55 * pulse)) if is_next else (195, 208, 232, 120))
                self._draw_word_with_opt_icon(im, d, px, py - int(5 * s), display_word, f_w,
                                              (210, 220, 238, alpha), shadow_a=145)

        # --- Composite blurred glow around active word ---
        if 0 <= rel_active < len(pts):
            ax, ay, _ = pts[rel_active]
            gx0 = max(x0, ax - 240)
            gy0 = max(y0, ay - 120)
            gx1 = min(x1, ax + 240)
            gy1 = min(y1, ay + 120)
            if gx1 > gx0 and gy1 > gy0:
                qx0, qy0 = max(0, gx0 // 4), max(0, gy0 // 4)
                qx1, qy1 = min(W // 4, (gx1 + 3) // 4), min(H // 4, (gy1 + 3) // 4)
                if qx1 > qx0 and qy1 > qy0:
                    g_patch = gl.crop((qx0, qy0, qx1, qy1)).filter(
                        ImageFilter.GaussianBlur(2.8)
                    ).resize((gx1 - gx0, gy1 - gy0), Image.Resampling.BILINEAR)
                    bg_patch = im.crop((gx0, gy0, gx1, gy1))
                    im.paste(Image.alpha_composite(g_patch, bg_patch), (gx0, gy0))

        out = im if (x0 == 0 and y0 == 0 and x1 == W and y1 == H) else im.crop((x0, y0, x1, y1))
        return out, (x0, y0, x1, y1)

    def _render_frame(
        self, lyrics, flat_words, l_status, style, idx, w_idx, g_idx, eff_pos, anim_t,
        status, title, artist, accent, sec, text_col, click_through
    ):
        W, H = self.OVERLAY_W, self.OVERLAY_H
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        s = self.font_scale

        if not click_through and not self._is_fullscreen_style(style):
            d.rounded_rectangle([8, 8, W - 9, H - 9], radius=22, fill=(14, 17, 26, 145), outline=(*accent, 215), width=2)
            d.text((24, 16), "DRAG CENTER STAGE TO POSITION  •  Lock Click-Through in Hub when done", font=self._font_cache["small"], fill=(220, 225, 235, 225))

        if status == "Idle" or not title or title in _NO_MEDIA_TITLES:
            if not click_through and not self._is_fullscreen_style(style):
                self._draw_centered_with_shadow(d, H // 2 - 18, "SoulsLights Lyrics Stage — Ready for Music", self._font_cache["sub"], (205, 212, 225, 215))
            return img

        # Creative Audio-Reactive Visualizer whenever no lyrics are being sung (instrumental tracks, intros, & interludes!)
        if not lyrics or idx < 0 or self._in_instrumental_gap(lyrics, idx, eff_pos):
            return self._render_no_lyrics_visualizer(
                img, d, lyrics, idx, eff_pos, anim_t, l_status, title, artist, accent, sec, text_col
            )

        curr_line = lyrics[idx]
        prev_text = lyrics[idx - 1]["text"] if idx > 0 else ""
        next_text = lyrics[idx + 1]["text"] if idx + 1 < len(lyrics) else ""
        words = curr_line.get("words", [])

        f_sub = self._font_cache["sub"]
        f_sm = self._font_cache["small"]
        f_code = self._font_cache["code"]
        f_emj = self._font_cache["emoji"]

        act_col = (*accent, 255)
        done_col = (*text_col, 248)
        todo_col = (205, 212, 224, 170)

        w_u = 0.0
        if words and 0 <= w_idx < len(words):
            cw = words[w_idx]
            w_u = max(0.0, min(1.0, (eff_pos - cw["start"]) / max(0.12, cw["end"] - cw["start"])))

        # ---- 1. FISHEYE / FISHEYE VISUAL (Real C spherical barrel MESH warp + randomized swipes!) ----
        if style in ("Fisheye", "Fisheye Visual") and flat_words:
            warped, ox, oy = self._render_fisheye(
                lyrics, idx, w_idx, w_u, eff_pos, anim_t, accent, sec, text_col, show_icons=("Visual" in style)
            )
            img.alpha_composite(warped, (ox, oy))
            return img

        # ---- 2. CONSTELLATION ----
        if style == "Constellation" and flat_words:
            if not self._bg_stars:
                self._init_constellation_sky(W, H, title)
            sub_img, drect = self._render_constellation_dirty(
                flat_words, g_idx, eff_pos, anim_t, accent, sec, text_col
            )
            img.alpha_composite(sub_img, (drect[0], drect[1]))
            return img

        # ---- 3. VISUAL (1:1 Verci vertical word stack + floating monochrome/accent icon beside active word) ----
        if style == "Visual" and flat_words:
            glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
            gi_v = max(0, g_idx if g_idx >= 0 else 0)
            cur_fw = flat_words[gi_v]
            pop_u = _ease_out_cubic(min(1.0, max(0.0, (eff_pos - cur_fw["start"]) / 0.14)))
            glide = int(16 * (1.0 - pop_u))

            # Stack: prev word (-1), active word (0), next1 (+1), next2 (+2)
            slots = [(-1, -int(62 * s), 30, 145), (0, 0, 54, 255), (1, int(62 * s), 30, 155), (2, int(108 * s), 24, 95)]
            for rel_off, dy, pt_base, alpha in slots:
                wi_g = gi_v + rel_off
                if wi_g < 0 or wi_g >= len(flat_words):
                    continue
                fw = flat_words[wi_g]
                w_txt = fw["word"]
                ico = fw.get("icon")
                is_act = (rel_off == 0)
                pt = int((pt_base + (6 * pop_u if is_act else 0)) * s)
                f_v = self._safe_font(self._get_font("bold" if rel_off <= 0 else "reg", pt), w_txt)
                fe_v = self._get_font("emoji", int(pt * 0.85)) if (ico and self._font_paths.get("emoji")) else None
                yy = H // 2 + dy + glide

                bb = d.textbbox((0, 0), w_txt, font=f_v)
                tw = bb[2] - bb[0]
                iw = self._icon_width(d, ico, fe_v)
                gap_i = 12 if iw else 0
                tot_w = tw + iw + gap_i
                # Icon on LEFT side of word (matching Verci video & Pic 2)
                x0 = int(W * 0.5 - tot_w * 0.5)
                tx = x0 + iw + gap_i - bb[0]
                ty = int(yy - (bb[1] + bb[3]) * 0.5)

                col = (255, 255, 255, alpha) if is_act else ((*text_col, alpha) if rel_off < 0 else (215, 222, 236, alpha))
                if is_act:
                    sustain_glow = 0.72 + 0.28 * (0.5 + 0.5 * math.sin(anim_t * 3.5)) * (0.4 + 0.6 * w_u)
                    gd.text((tx, ty), w_txt, font=f_v, fill=(*accent, int(205 * pop_u * sustain_glow)))
                self._draw_text_shadow(d, tx, ty, w_txt, f_v, col, shadow_alpha=215 if is_act else 155)
                if iw and fe_v:
                    patch = self._get_tinted_icon(ico, fe_v, accent, is_active=is_act)
                    if patch is not None:
                        ey = int(yy - patch.height * 0.5) + (int(-4 * math.sin(anim_t * 7.0)) if is_act else 0)
                        self._stamp_icon(img, x0, ey, ico, fe_v, accent, is_active=is_act, alpha_mul=alpha / 255.0)
            glow_blur = glow_layer.filter(ImageFilter.GaussianBlur(radius=9))
            return Image.alpha_composite(glow_blur, img)

        # ---- 4. BRANCHES (1:1 Verci horizontal wave + vertical pin stems & word labels) ----
        if style == "Branches":
            glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
            y_base = int(H * 0.52)
            margin = 96
            span = W - 2 * margin
            n = max(1, len(words))

            # Build dense smooth sine curve across whole line
            curve_pts = []
            steps = max(48, n * 12)
            for si in range(steps + 1):
                u = si / steps
                cx_p = margin + span * u
                cy_p = y_base + 24.0 * math.sin(u * math.pi * 2.2 + idx * 1.1) + 8.0 * math.sin(anim_t * 1.6 + u * 4.0)
                curve_pts.append((cx_p, cy_p))
            d.line(curve_pts, fill=(195, 210, 225, 115), width=2)

            prog_u = 0.0
            if n > 1 and w_idx >= 0:
                sm_u = w_u * w_u * (3.0 - 2.0 * w_u)
                prog_u = min(1.0, (w_idx + sm_u) / max(1, n - 1))
            elif w_idx >= 0:
                prog_u = w_u * w_u * (3.0 - 2.0 * w_u)

            lit_end = max(1, int(prog_u * steps))
            lit_curve = curve_pts[: lit_end + 1]
            if len(lit_curve) > 1:
                d.line(lit_curve, fill=(245, 250, 255, 235), width=2)
                gd.line(lit_curve, fill=(*accent, 185), width=5)
            # Glowing star tip on the curve
            tip_x, tip_y = curve_pts[min(steps, lit_end)]
            d.ellipse([tip_x - 4, tip_y - 4, tip_x + 4, tip_y + 4], fill=(255, 255, 255, 255))
            gd.ellipse([tip_x - 8, tip_y - 8, tip_x + 8, tip_y + 8], fill=(*accent, 220))

            # Vertical pin stems alternating up & down
            for i in range(n):
                u_i = i / max(1, n - 1) if n > 1 else 0.5
                si_i = min(steps, int(u_i * steps))
                nx, ny = int(curve_pts[si_i][0]), int(curve_pts[si_i][1])
                dir_y = -1 if i % 2 == 0 else 1
                stem_h = int((56 + 22 * ((i * 3) % 2)) * s)
                wy = ny + dir_y * stem_h
                lit = (w_idx >= 0 and i <= w_idx)
                is_cur = (i == w_idx)
                stem_col = (240, 248, 255, 215) if lit else (195, 210, 225, 85)
                d.line([(nx, ny), (nx, wy)], fill=stem_col, width=1)
                r = 5 if is_cur else (4 if lit else 3)
                d.ellipse([nx - r, wy - r, nx + r, wy + r], fill=(255, 255, 255, 255) if is_cur else ((*accent, 225) if lit else (180, 195, 215, 115)))
                f_b = self._get_font("bold" if is_cur else "reg", int((28 if is_cur else 21) * s))
                col = (255, 255, 255, 255) if is_cur else ((230, 240, 250, 220) if lit else (190, 205, 220, 130))
                self._draw_word_with_opt_icon(img, d, nx, wy + dir_y * int(22 * s), words[i]["word"], f_b, col, shadow_a=185)

            glow_blur = glow_layer.filter(ImageFilter.GaussianBlur(radius=6))
            return Image.alpha_composite(glow_blur, img)

        # ---- 5. CODESTYLE / CODESTYLE VISUAL (1:1 floating Verci code syntax, no dark window box) ----
        if style in ("Codestyle", "Codestyle Visual"):
            show_ico = ("Visual" in style)
            f_prev = self._get_font("mono", int(18 * s))
            f_ctx = self._get_font("mono", int(24 * s))
            f_act = self._get_font("bold", int(34 * s))  # crisp bold for active code token

            # Line 1: subtle blurred previous lyric context
            if prev_text:
                pt = prev_text[:48]
                fp_u = self._safe_font(f_prev, pt)
                tw_p, _ = self._measure_text(d, pt, fp_u)
                d.text(((W - tw_p) // 2, int(H * 0.34)), pt, font=fp_u, fill=(185, 198, 220, 105))

            # Line 2: Verci dot/call notation of words leading up to active word (e.g. till.the(road) / till(the))
            ctx_words = [w["word"] for w in words[: max(0, w_idx)]] if w_idx > 0 else []
            if ctx_words:
                if len(ctx_words) == 1:
                    ctx_str = f"{ctx_words[0]}()"
                elif len(ctx_words) == 2:
                    ctx_str = f"{ctx_words[0]}({ctx_words[1]})"
                else:
                    ctx_str = ".".join(ctx_words[:-1]) + f"({ctx_words[-1]})"
                fc_u = self._safe_font(f_ctx, ctx_str)
                tw_c, _ = self._measure_text(d, ctx_str, fc_u)
                d.text(((W - tw_c) // 2, int(H * 0.42)), ctx_str, font=fc_u, fill=(195, 208, 232, 185))

            # Line 3: Active token + blinking RED cursor block
            cur_typed = ""
            cur_ico = None
            if words and 0 <= w_idx < len(words):
                cw = words[w_idx]["word"]
                n_chars = max(1, int(math.ceil(len(cw) * min(1.0, 0.10 + 0.90 * (w_u ** 0.92)))))
                cur_typed = cw[:n_chars]
                cur_ico = words[w_idx].get("icon") if show_ico else None

            ty = int(H * 0.53)
            if show_ico:
                # "[icon] // word █"
                prefix = "// "
                display_str = prefix + cur_typed
                fd_u = self._safe_font(f_code, display_str)
                tw_d, th_d = self._measure_text(d, display_str, fd_u)
                em_f = self._font_cache.get("emoji_compact")
                iw = self._icon_width(d, cur_ico, em_f) if (cur_ico and em_f) else 0
                tot_w = (iw + 8 if iw else 0) + tw_d + 16
                sx = (W - tot_w) // 2
                if iw and em_f:
                    patch = self._get_tinted_icon(cur_ico, em_f, accent, True)
                    if patch is not None:
                        self._stamp_icon(img, sx, ty + th_d // 2 - patch.height // 2, cur_ico, em_f, accent, True)
                    sx += iw + 8
                self._draw_text_shadow(d, sx, ty, display_str, fd_u, (240, 246, 255, 245), shadow_alpha=185)
                cx = sx + tw_d + 5
            else:
                # "word █" in electric blue monospace
                fd_u = self._safe_font(f_code, cur_typed)
                tw_d, th_d = self._measure_text(d, cur_typed, fd_u)
                sx = (W - tw_d - 16) // 2
                self._draw_text_shadow(d, sx, ty, cur_typed, fd_u, (78, 161, 255, 255), shadow_alpha=195)
                cx = sx + tw_d + 5

            cur_a = int(145 + 110 * (0.5 + 0.5 * math.sin(anim_t * 10.0)))
            d.rectangle([cx, ty + 2, cx + 11, ty + th_d + 2], fill=(239, 68, 68, cur_a))
            return img

        # ---- 6. FLASHBANG / FLASHBANG VISUAL ----
        if style in ("Flashbang", "Flashbang Visual") and flat_words:
            glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
            show_ico = ("Visual" in style)
            flash_k = max(0.0, 1.0 - w_u * 2.0) if w_idx >= 0 else 0.0
            pop_scale = 1.0 + 0.36 * (flash_k ** 1.4)
            gi = max(0, g_idx)
            wobj = flat_words[gi]

            shake_x = int(5.0 * flash_k * math.sin(anim_t * 58.0))
            shake_y = int(4.0 * flash_k * math.cos(anim_t * 47.0))

            if prev_text:
                self._draw_centered_with_shadow(d, int(H * 0.24), prev_text[:60], f_sub, (180, 190, 210, 115))

            f_flash = self._get_font("bold", int(68 * s * pop_scale))
            ico = wobj.get("icon") if show_ico else None
            f_em = self._get_font("emoji", int(56 * s * pop_scale)) if (ico and self._font_paths.get("emoji")) else None

            if flash_k > 0.02:
                prog = 1.0 - flash_k
                rx, ry = int(120 + 220 * prog), int(48 + 95 * prog)
                d.ellipse([W // 2 - rx, H // 2 - ry, W // 2 + rx, H // 2 + ry], outline=(255, 255, 255, int(195 * flash_k)), width=2)
                gd.ellipse([W // 2 - 200, H // 2 - 64, W // 2 + 200, H // 2 + 64], fill=(*accent, int(175 * flash_k)))
                for spk in range(10):
                    ang = spk * (2.0 * math.pi / 10.0) + gi * 0.7
                    dist = 45 + 165 * prog
                    spx = int(W * 0.5 + math.cos(ang) * dist * 1.4)
                    spy = int(H * 0.49 + math.sin(ang) * dist * 0.65)
                    d.ellipse([spx - 3, spy - 3, spx + 3, spy + 3], fill=(255, 250, 220, int(230 * flash_k)))

            word_col = _lerp_color((255, 255, 255), accent, 1.0 - flash_k * 0.75)
            self._draw_word_with_opt_icon(
                img, d, W * 0.5 + shake_x, H * 0.49 + shake_y, wobj["word"], f_flash, (*word_col, 255),
                ico=ico, emoji_font=f_em, accent_rgb=accent, is_active=True,
                shadow_a=235, glow_draw=gd, glow_col=(255, 255, 255, int(185 + 70 * flash_k))
            )
            if next_text:
                self._draw_centered_with_shadow(d, int(H * 0.70), next_text[:60], f_sub, (190, 200, 215, 135))
            glow_blur = glow_layer.filter(ImageFilter.GaussianBlur(radius=14))
            return Image.alpha_composite(glow_blur, img)

        # ---- 6b. SHIP (1:1 Verci 3D drifting wall: words land progressively with centered white focus pill) ----
        if style == "Ship":
            wall = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            wd = ImageDraw.Draw(wall)
            drift_x = int(20.0 * math.sin(anim_t * 0.65))
            drift_y = int(10.0 * math.cos(anim_t * 0.50))
            act_i = max(0, w_idx)
            pop_u = _ease_out_back(min(1.0, w_u * 2.5)) if w_idx >= 0 else 1.0
            slide_up = int(28.0 * (1.0 - min(1.0, pop_u)))

            # Stack prev 3 words above -> active word at center in white highlight block -> next 2 below
            center_y = H // 2 + drift_y
            cx_wall = W // 2 + drift_x
            offsets = [(-3, -int(116 * s), 20, 115), (-2, -int(84 * s), 25, 165), (-1, -int(52 * s), 30, 210),
                       (0, 0, 42, 255), (1, int(52 * s), 26, 145), (2, int(84 * s), 22, 95)]
            for rel_o, dy, pt_b, alpha in offsets:
                wi = act_i + rel_o
                if wi < 0 or wi >= len(words):
                    continue
                w_txt = words[wi]["word"]
                # Subtle horizontal 3D perspective skew along the wall depth
                depth_dx = int(rel_o * -10.0 * math.sin(anim_t * 0.55) * s)
                yy = center_y + dy + (slide_up // 2 if rel_o != 0 else 0)
                xx = cx_wall + depth_dx
                if rel_o == 0:
                    hold_breathe = 1.0 + 0.03 * math.sin(anim_t * 3.2) * w_u
                    f_ship = self._safe_font(self._get_font("bold", int(pt_b * s * (0.86 + 0.14 * pop_u) * hold_breathe)), w_txt)
                    bb = wd.textbbox((0, 0), w_txt, font=f_ship)
                    tw, th = bb[2] - bb[0], bb[3] - bb[1]
                    tx = int(xx - tw * 0.5 - bb[0])
                    ty = int(yy - (bb[1] + bb[3]) * 0.5)
                    px0 = int(xx - tw * 0.5 - 14)
                    py0 = int(yy - th * 0.5 - 8)
                    wd.rounded_rectangle([px0, py0, px0 + tw + 28, py0 + th + 16], radius=6, fill=(244, 247, 255, 248))
                    wd.text((tx, ty), w_txt, font=f_ship, fill=(14, 17, 24, 255))
                else:
                    f_ship = self._safe_font(self._get_font("bold" if rel_o < 0 else "reg", int(pt_b * s)), w_txt)
                    bb = wd.textbbox((0, 0), w_txt, font=f_ship)
                    tx = int(xx - (bb[2] - bb[0]) * 0.5 - bb[0])
                    ty = int(yy - (bb[1] + bb[3]) * 0.5)
                    self._draw_text_shadow(wd, tx, ty, w_txt, f_ship, (235, 242, 252, alpha), shadow_alpha=175)
            tilt = 2.8 * math.sin(anim_t * 0.48)
            if abs(tilt) > 0.2:
                wall = wall.rotate(tilt, resample=Image.Resampling.BILINEAR)
            return wall

        # ---- 6c. WEB (1:1 Verci scalloped silver spiderweb with chrome spider + node words) ----
        if style == "Web":
            cx, cy = W // 2, H // 2
            max_r = min(W * 0.36, H * 0.41)
            rot = anim_t * 0.10
            n_spokes = 10
            for k in range(n_spokes):
                ang = rot + k * (2.0 * math.pi / n_spokes)
                d.line([(cx, cy), (cx + math.cos(ang) * max_r, cy + math.sin(ang) * max_r)],
                       fill=(215, 224, 240, 82), width=1)
            # Scalloped inward-sagging silk rings (8 sub-steps per sector)
            sub_segs = 8
            for ring_k in (0.24, 0.46, 0.68, 0.88, 1.0):
                rr = max_r * ring_k
                ring_xy = []
                for k in range(n_spokes):
                    a0 = rot + k * (2.0 * math.pi / n_spokes)
                    a1 = rot + (k + 1) * (2.0 * math.pi / n_spokes)
                    for si in range(sub_segs):
                        u = si / sub_segs
                        ang = a0 + (a1 - a0) * u
                        # Parabolic inward sag at midpoint (4*u*(1-u))
                        sag = 1.0 - 0.13 * (4.0 * u * (1.0 - u))
                        ring_xy.append((cx + math.cos(ang) * rr * sag, cy + math.sin(ang) * rr * sag))
                ring_xy.append(ring_xy[0])
                d.line(ring_xy, fill=(220, 228, 244, int(58 + 32 * ring_k)), width=1)

            # Chrome 3D-shaded spider at center oriented toward active word, gliding smoothly at word completion
            n_w = max(1, len(words))
            aim_w = max(0, w_idx) + max(0.0, (w_u - 0.72) / 0.28)
            sp_ang = rot + (aim_w * (2.0 * math.pi / n_w)) - math.pi * 0.5
            # 8 articulated silver legs (femur + tibia bends)
            for side in (-1, 1):
                for leg_i, spread in enumerate((-0.75, -0.32, 0.15, 0.60)):
                    la = sp_ang + side * (math.pi * 0.46 + spread * 0.55)
                    jx = cx + math.cos(la) * 20
                    jy = cy + math.sin(la) * 20
                    tx = cx + math.cos(la + side * 0.30) * 34
                    ty = cy + math.sin(la + side * 0.30) * 34
                    d.line([(cx, cy), (jx, jy)], fill=(215, 222, 234, 230), width=3)
                    d.line([(jx, jy), (tx, ty)], fill=(248, 250, 255, 235), width=2)
            # Abdomen + highlighted cephalothorax
            ax_sp = cx - math.cos(sp_ang) * 9
            ay_sp = cy - math.sin(sp_ang) * 9
            d.ellipse([ax_sp - 10, ay_sp - 10, ax_sp + 10, ay_sp + 10], fill=(175, 184, 198, 240), outline=(245, 248, 255, 220))
            d.ellipse([ax_sp - 5, ay_sp - 6, ax_sp + 3, ay_sp + 2], fill=(248, 250, 255, 210))
            hx_sp = cx + math.cos(sp_ang) * 8
            hy_sp = cy + math.sin(sp_ang) * 8
            d.ellipse([hx_sp - 6, hy_sp - 6, hx_sp + 6, hy_sp + 6], fill=(235, 240, 248, 245), outline=(95, 105, 120, 220))

            # Hang words along web strands
            n_w = max(1, len(words))
            for wi, wobj in enumerate(words):
                is_act = (wi == w_idx)
                is_done = (w_idx >= 0 and wi < w_idx)
                ang = rot + wi * (2.0 * math.pi / n_w) - math.pi * 0.5
                node_r = max_r * (0.72 if wi % 2 == 0 else 0.48)
                nx = int(cx + math.cos(ang) * node_r)
                ny = int(cy + math.sin(ang) * node_r)
                if is_act:
                    f_w = self._get_font("bold", int(34 * s))
                    d.ellipse([nx - 4, ny + 14, nx + 4, ny + 22], fill=(*accent, 245))
                    self._draw_word_with_opt_icon(img, d, nx, ny - 6, wobj["word"], f_w, (255, 255, 255, 255), shadow_a=230)
                elif is_done:
                    f_w = self._get_font("bold", int(24 * s))
                    self._draw_word_with_opt_icon(img, d, nx, ny - 4, wobj["word"], f_w, (*text_col, 205), shadow_a=175)
                else:
                    f_w = self._get_font("reg", int(20 * s))
                    self._draw_word_with_opt_icon(img, d, nx, ny - 4, wobj["word"], f_w, (205, 215, 235, 130), shadow_a=135)
            return img

        # ---- 6d. NATIVE DESIGN (1:1 Verci iMessage conversation thread: grey bubble + stacked iOS blue bubbles) ----
        if style == "Native Design":
            l_u = _ease_out_back(min(1.0, max(0.0, (eff_pos - curr_line["time"]) / 0.22)))
            card_w = min(W - 80, int(520 * s))
            bx0 = (W - card_w) // 2
            bx1 = bx0 + card_w
            f_chat = self._get_font("reg", int(20 * s))
            f_chat_b = self._get_font("bold", int(21 * s))
            self._draw_centered_with_shadow(d, int(H * 0.22), "Today  11:22", f_sm, (175, 185, 205, 165))

            cy_cur = int(H * 0.29)
            # Older incoming grey bubble (idx - 2 or idx - 1)
            in_line = lyrics[idx - 2]["text"] if idx >= 2 else (prev_text or "")
            if in_line:
                pt = in_line[:44]
                tw, th = self._measure_text(d, pt, f_chat)
                bw = min(card_w - 40, tw + 30)
                bh = th + 18
                d.rounded_rectangle([bx0, cy_cur, bx0 + bw, cy_cur + bh], radius=17, fill=(44, 44, 48, 240))
                d.text((bx0 + 15, cy_cur + 8), pt, font=self._safe_font(f_chat, pt), fill=(242, 242, 247, 235))
                cy_cur += bh + 12

            # Previous line blue bubble if >= 2 lines in
            if idx >= 2 and prev_text:
                pt2 = prev_text[:44]
                tw_p, th_p = self._measure_text(d, pt2, f_chat)
                bw_p = min(card_w - 30, tw_p + 30)
                bh_p = th_p + 18
                d.rounded_rectangle([bx1 - bw_p, cy_cur, bx1, cy_cur + bh_p], radius=17, fill=(10, 132, 255, 225))
                d.text((bx1 - bw_p + 15, cy_cur + 8), pt2, font=self._safe_font(f_chat, pt2), fill=(255, 255, 255, 235))
                cy_cur += bh_p + 8

            # Active outgoing iOS blue bubble (word-by-word reveal)
            shown_txt = " ".join(w["word"] for w in words[: max(1, w_idx + 1)]) if w_idx >= 0 else curr_line["text"]
            shown_txt = shown_txt[:46]
            tw2, th2 = self._measure_text(d, shown_txt, f_chat_b)
            bw2 = min(card_w - 20, tw2 + 32)
            bh2 = th2 + 20
            pop_dy = int(12 * (1.0 - l_u))
            d.rounded_rectangle([bx1 - bw2, cy_cur + pop_dy, bx1, cy_cur + bh2 + pop_dy], radius=17, fill=(10, 132, 255, 252))
            d.text((bx1 - bw2 + 16, cy_cur + 9 + pop_dy), shown_txt, font=self._safe_font(f_chat_b, shown_txt), fill=(255, 255, 255, 255))
            cy_cur += bh2 + 8

            if next_text:
                nt = next_text[:44]
                tw3, th3 = self._measure_text(d, nt, f_chat)
                bw3 = min(card_w - 40, tw3 + 30)
                bh3 = th3 + 18
                d.rounded_rectangle([bx1 - bw3, cy_cur, bx1, cy_cur + bh3], radius=17, fill=(10, 132, 255, 110))
                d.text((bx1 - bw3 + 15, cy_cur + 8), nt, font=self._safe_font(f_chat, nt), fill=(235, 244, 255, 175))
            return img

        # ---- 7. APPLE DESIGN ----
        if style == "Apple Design":
            l_u = _ease_out_cubic(min(1.0, max(0.0, (eff_pos - curr_line["time"]) * 3.8)))
            glide_y = int(16 * (1.0 - l_u))
            pulse_a = int(115 + 35 * (0.5 + 0.5 * math.sin(anim_t * 2.5)))
            d.rounded_rectangle([72, int(H * 0.24), W - 72, int(H * 0.76)], radius=28, fill=(18, 20, 30, 215), outline=(*accent, pulse_a), width=1)
            if prev_text:
                self._draw_centered_with_shadow(d, int(H * 0.30) + glide_y // 2, prev_text[:62], f_sub, (165, 175, 195, int(125 + 25 * (1.0 - l_u))))
            self._draw_word_line_kinetic(
                img, d, int(H * 0.50) + glide_y, words, max(0, w_idx), w_u, eff_pos,
                self._get_font("bold", int(38 * s)), f_emj,
                (255, 255, 255, 255), (255, 255, 255, 250), (175, 185, 205, 135),
                accent_rgb=accent, show_icons=False, wave_amp=2.0, active_lift=6.0, active_pop=False, anim_t=anim_t
            )
            if next_text:
                self._draw_centered_with_shadow(d, int(H * 0.65) + glide_y // 2, next_text[:62], f_sub, (185, 195, 215, 165))
            return img

        # ---- 8. MINIMAL ----
        l_u = _ease_out_cubic(min(1.0, max(0.0, (eff_pos - curr_line["time"]) * 4.0)))
        tw, th = self._measure_text(d, curr_line["text"], f_sub)
        f_use = f_sub if tw <= W - 120 else f_sm
        tw, th = self._measure_text(d, curr_line["text"], f_use)
        pad_x, pad_y = 34, 18
        rx0 = max(24, (W - tw) // 2 - pad_x)
        rx1 = min(W - 24, (W + tw) // 2 + pad_x)
        ry0 = (H - th) // 2 - pad_y + int(12 * (1.0 - l_u))
        ry1 = ry0 + th + pad_y * 2
        d.rounded_rectangle([rx0, ry0, rx1, ry1], radius=22, fill=(14, 16, 24, int(205 * (0.4 + 0.6 * l_u))), outline=(*accent, 150), width=1)
        self._draw_word_line_kinetic(
            img, d, (ry0 + ry1) // 2 - 2, words, w_idx, w_u, eff_pos, f_use, None,
            act_col, (*text_col, int(255 * (0.45 + 0.55 * l_u))), (195, 205, 220, 175),
            accent_rgb=accent, show_icons=False, wave_amp=0.0, active_lift=3.0, active_pop=False, max_w=rx1 - rx0 - 20, anim_t=anim_t
        )
        line_prog = max(0.0, min(1.0, (eff_pos - curr_line["time"]) / max(0.3, curr_line["end"] - curr_line["time"])))
        bar_w = int((rx1 - rx0 - 32) * line_prog)
        if bar_w > 4:
            d.rounded_rectangle([rx0 + 16, ry1 - 5, rx0 + 16 + bar_w, ry1 - 3], radius=1, fill=(*accent, 220))
        return img
