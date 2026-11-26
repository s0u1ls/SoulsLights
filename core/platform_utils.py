"""Cross-platform environment, path, font, and monitor helpers for Windows & macOS."""
import os
import sys
import shutil
from PIL import ImageFont

IS_MAC = (sys.platform == "darwin")
IS_WIN = (sys.platform == "win32")

UI_FONT_FAMILY = "SF Pro Text" if IS_MAC else "Segoe UI"
MONO_FONT_FAMILY = "Menlo" if IS_MAC else "Consolas"
SERIF_FONT_FAMILY = "Georgia"

# Apple Color Emoji uses SBIX bitmap strikes that only open cleanly at fixed pixel sizes
_APPLE_EMOJI_STRIKES = (20, 26, 32, 40, 48, 52, 64, 96, 160)


def get_app_data_dir() -> str:
    """Returns per-user writable data/config directory for SoulsLights."""
    if IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
        target = os.path.join(base, "SoulsLights")
        legacy = os.path.join(base, "LumnVerciUnified")
    elif IS_WIN:
        base = os.environ.get("APPDATA", "") or os.path.expanduser("~")
        target = os.path.join(base, "SoulsLights")
        legacy = os.path.join(base, "LumnVerciUnified")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        target = os.path.join(base, "SoulsLights")
        legacy = os.path.join(base, "LumnVerciUnified")

    os.makedirs(target, exist_ok=True)
    if os.path.isdir(legacy):
        for fname in ("config.json", "lyrics_cache.json"):
            src = os.path.join(legacy, fname)
            dst = os.path.join(target, fname)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass
    return target


def get_resource_path(rel_path: str) -> str:
    """Resolves bundled resource paths both from source and frozen PyInstaller/py2app builds."""
    candidates = [
        getattr(sys, "_MEIPASS", ""),
        os.environ.get("RESOURCEPATH", ""),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ]
    for base in candidates:
        if not base:
            continue
        p = os.path.join(base, rel_path)
        if os.path.exists(p):
            return p
    return ""


def get_font_dirs() -> list:
    if IS_MAC:
        return [
            "/System/Library/Fonts",
            "/System/Library/Fonts/Supplemental",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts"),
        ]
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return [os.path.join(windir, "Fonts")]


def find_font_file(candidates) -> str:
    """Finds the first existing font file path from relative filenames or absolute paths."""
    if isinstance(candidates, str):
        candidates = (candidates,)
    dirs = get_font_dirs()
    for item in candidates:
        if not item:
            continue
        if os.path.isabs(item) and os.path.exists(item):
            return item
        for d in dirs:
            p = os.path.join(d, item)
            if os.path.exists(p):
                return p
    return ""


_MAC_STYLE_FONTS = {
    "Geometric": (
        ("SFNS.ttf", "HelveticaNeue.ttc", "Arial Bold.ttf"),
        ("SFNS.ttf", "HelveticaNeue.ttc", "Arial.ttf"),
    ),
    "Futura": (
        ("Futura.ttc", "SFNS.ttf", "Arial Bold.ttf"),
        ("Futura.ttc", "HelveticaNeue.ttc", "Arial.ttf"),
    ),
    "Didone": (
        ("Times New Roman Bold.ttf", "Didot.ttc", "Times.ttc", "Georgia Bold.ttf"),
        ("Times New Roman.ttf", "Didot.ttc", "Times.ttc", "Georgia.ttf"),
    ),
    "Grotesque": (
        ("Arial Bold.ttf", "Helvetica.ttc", "SFNS.ttf"),
        ("Arial.ttf", "Helvetica.ttc", "SFNS.ttf"),
    ),
    "Rounded": (
        ("SFNSRounded.ttf", "HelveticaNeue.ttc", "Arial Rounded Bold.ttf"),
        ("SFNSRounded.ttf", "HelveticaNeue.ttc", "Arial.ttf"),
    ),
    "Serif": (
        ("Georgia Bold.ttf", "NewYork.ttf", "Times New Roman Bold.ttf"),
        ("Georgia.ttf", "NewYork.ttf", "Times New Roman.ttf"),
    ),
}

_WIN_STYLE_FONTS = {
    "Geometric": (("segoeuib.ttf", "arialbd.ttf"), ("segoeui.ttf", "arial.ttf")),
    "Futura": (("calibrib.ttf", "segoeuib.ttf"), ("calibri.ttf", "segoeui.ttf")),
    "Didone": (("timesbd.ttf", "georgiab.ttf"), ("times.ttf", "georgia.ttf")),
    "Grotesque": (("arialbd.ttf", "segoeuib.ttf"), ("arial.ttf", "segoeui.ttf")),
    "Rounded": (("seguisb.ttf", "segoeuib.ttf"), ("segoeui.ttf", "arial.ttf")),
    "Serif": (("georgiab.ttf", "timesbd.ttf"), ("georgia.ttf", "times.ttf")),
}

_UI_ALIASES_MAC = {
    "segoeuib.ttf": ("SFNS.ttf", "HelveticaNeue.ttc", "Arial Bold.ttf"),
    "segoeui.ttf": ("SFNS.ttf", "HelveticaNeue.ttc", "Arial.ttf"),
    "seguisb.ttf": ("SFNSRounded.ttf", "HelveticaNeue.ttc", "Arial Bold.ttf"),
    "arialbd.ttf": ("Arial Bold.ttf", "Helvetica.ttc", "SFNS.ttf"),
    "arial.ttf": ("Arial.ttf", "Helvetica.ttc", "SFNS.ttf"),
    "georgiab.ttf": ("Georgia Bold.ttf", "Times New Roman Bold.ttf", "SFNS.ttf"),
    "georgia.ttf": ("Georgia.ttf", "Times New Roman.ttf", "SFNS.ttf"),
    "consola.ttf": ("SFNSMono.ttf", "Menlo.ttc", "Courier.ttc"),
    "cour.ttf": ("Courier New Bold.ttf", "Menlo.ttc", "Courier.ttc"),
}


def get_lyric_font_paths(font_style: str) -> dict:
    """Returns dict with keys 'bold', 'reg', 'mono', 'emoji' pointing to resolved font files."""
    if IS_MAC:
        b_cands, r_cands = _MAC_STYLE_FONTS.get(font_style, _MAC_STYLE_FONTS["Geometric"])
        bold_p = find_font_file(b_cands) or find_font_file(_MAC_STYLE_FONTS["Geometric"][0])
        reg_p = find_font_file(r_cands) or find_font_file(_MAC_STYLE_FONTS["Geometric"][1]) or bold_p
        mono_p = find_font_file(("SFNSMono.ttf", "Menlo.ttc", "Monaco.ttf", "Courier New.ttf")) or bold_p
        emoji_p = find_font_file(("Apple Color Emoji.ttc",))
    else:
        b_cands, r_cands = _WIN_STYLE_FONTS.get(font_style, _WIN_STYLE_FONTS["Geometric"])
        bold_p = find_font_file(b_cands) or find_font_file(("segoeuib.ttf", "arialbd.ttf"))
        reg_p = find_font_file(r_cands) or find_font_file(("segoeui.ttf", "arial.ttf")) or bold_p
        mono_p = find_font_file(("consola.ttf", "courbd.ttf", "cour.ttf")) or bold_p
        emoji_p = find_font_file(("seguiemj.ttf",))
    return {
        "bold": bold_p,
        "reg": reg_p,
        "mono": mono_p,
        "emoji": emoji_p,
    }


def get_fallback_font_entries() -> list:
    """Returns list of (name, abs_path, role) fallback fonts for non-Latin / symbols / emoji."""
    if IS_MAC:
        specs = (
            ("Apple Symbols.ttf", "sym"),
            ("Kohinoor.ttc", "any"),
            ("KohinoorDevanagari.ttc", "any"),
            ("PingFang.ttc", "bold"),
            ("AppleSDGothicNeo.ttc", "bold"),
            ("Hiragino Sans GB.ttc", "bold"),
            ("GeezaPro.ttc", "bold"),
            ("Arial Unicode.ttf", "any"),
            ("Arial Bold.ttf", "bold"),
            ("Apple Color Emoji.ttc", "emoji"),
        )
    else:
        specs = (
            ("Nirmala.ttc", "any"),
            ("seguisym.ttf", "sym"),
            ("arialbd.ttf", "bold"),
            ("arial.ttf", "reg"),
            ("msyhbd.ttc", "bold"),
            ("msyh.ttc", "reg"),
            ("malgunbd.ttf", "bold"),
            ("YuGothB.ttc", "bold"),
            ("seguiemj.ttf", "emoji"),
        )
    out = []
    for fn, role in specs:
        fp = find_font_file((fn,))
        if fp:
            out.append((fn, fp, role))
    return out


def nearest_emoji_strike(req_px: int) -> int:
    return min(_APPLE_EMOJI_STRIKES, key=lambda s: (abs(s - req_px), -s))


def load_truetype_safe(path: str, size_px: int):
    """Loads TrueType/SBIX font safely across Windows and macOS (handling Apple Color Emoji strikes)."""
    q = max(10, min(260, int(round(size_px))))
    if not path:
        return None
    low = path.lower()
    if "apple color emoji" in low:
        for strike in (nearest_emoji_strike(q), 64, 48, 32):
            try:
                return ImageFont.truetype(path, strike)
            except Exception:
                continue
    try:
        return ImageFont.truetype(path, q)
    except Exception:
        return None


def load_scalable_default_font(size_px: int):
    """Returns a scaled Pillow built-in fallback font when no OS font file is available."""
    q = max(10, min(260, int(round(size_px))))
    try:
        return ImageFont.load_default(size=q)
    except TypeError:
        return ImageFont.load_default()


_UI_FONT_CACHE = {}


def load_pil_font(name: str, size: int):
    """Loads a PIL TrueType font seamlessly on both Windows and macOS."""
    sz = max(6, int(size))
    key = (name, sz)
    cached = _UI_FONT_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_UI_FONT_CACHE) > 128:
        _UI_FONT_CACHE.clear()

    if IS_MAC:
        cands = list(_UI_ALIASES_MAC.get(name.lower(), ())) + [
            name, "SFNS.ttf", "HelveticaNeue.ttc", "Arial Bold.ttf", "Arial.ttf"
        ]
    else:
        cands = [name, "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf"]

    for c in cands:
        fp = find_font_file((c,)) or c
        try:
            f = ImageFont.truetype(fp, sz)
            _UI_FONT_CACHE[key] = f
            return f
        except Exception:
            continue
    f = ImageFont.load_default()
    _UI_FONT_CACHE[key] = f
    return f


def get_monitors() -> list:
    if IS_MAC:
        from core.mac_utils import get_monitors as _mac_mons
        return _mac_mons()
    if IS_WIN:
        from core.win32_utils import get_monitors as _win_mons
        return _win_mons()
    return [{"device": "DISPLAY1", "primary": True, "x": 0, "y": 0, "w": 1920, "h": 1080}]


def get_cursor_pos(evt=None) -> tuple:
    if IS_WIN:
        import ctypes
        from core.win32_utils import user32, POINT
        pt = POINT()
        if user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
    if IS_MAC:
        from core.mac_utils import get_cursor_pos as _mac_cursor
        pos = _mac_cursor()
        if pos is not None:
            return pos
    if evt is not None:
        return int(getattr(evt, "x_root", 0)), int(getattr(evt, "y_root", 0))
    return 0, 0
