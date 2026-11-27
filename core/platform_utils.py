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
            ("Devanagari Sangam MN.ttc", "any"),
            ("DevanagariMT.ttc", "any"),
            ("Malayalam Sangam MN.ttc", "any"),
            ("Malayalam MN.ttc", "any"),
            ("Tamil Sangam MN.ttc", "any"),
            ("Tamil MN.ttc", "any"),
            ("NotoSansMalayalam.ttc", "any"),
            ("NotoSansDevanagari.ttc", "any"),
            ("NotoSansTamil.ttc", "any"),
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


# ---- Native OS OpenType Complex-Script Shaping (Malayalam, Hindi/Devanagari, Tamil, Arabic, etc.) ----
import threading as _threading
from PIL import Image as _Image

_SHAPE_LOCK = _threading.Lock()
_SHAPE_MEASURE_CACHE = {}
_SHAPE_MASK_CACHE = {}
_WIN_GDI_STATE = {}
_WIN_FONT_CACHE = {}


def needs_complex_shaping(text: str) -> bool:
    """Returns True when text contains Indic/Arabic/Thai scripts requiring OpenType GSUB/GPOS shaping."""
    if not text or text.isascii():
        return False
    for ch in text:
        o = ord(ch)
        if (0x0900 <= o <= 0x0DF7) or (0x0600 <= o <= 0x06FF) or (0x0E00 <= o <= 0x0E7F) or (0x1000 <= o <= 0x109F):
            return True
    return False


def font_is_bold(font) -> bool:
    if font is None:
        return True
    fpath = (getattr(font, "path", "") or "").lower()
    if any(k in fpath for k in ("bold", "bd.", "segoeuib", "seguisb", "calibrib", "timesbd", "arialbd", "georgiab")):
        return True
    if any(k in fpath for k in ("segoeui.ttf", "calibri.ttf", "arial.ttf", "times.ttf", "georgia.ttf", "helvetica")):
        return False
    return int(getattr(font, "size", 24)) >= 25


def _win_get_hdc_and_font(size_px: int, bold: bool):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    if not _WIN_GDI_STATE:
        class RECT_G(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class BMIH_G(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32),
            ]

        class LOGFONTW(ctypes.Structure):
            _fields_ = [
                ("lfHeight", ctypes.c_int32), ("lfWidth", ctypes.c_int32), ("lfEscapement", ctypes.c_int32),
                ("lfOrientation", ctypes.c_int32), ("lfWeight", ctypes.c_int32), ("lfItalic", ctypes.c_ubyte),
                ("lfUnderline", ctypes.c_ubyte), ("lfStrikeOut", ctypes.c_ubyte), ("lfCharSet", ctypes.c_ubyte),
                ("lfOutPrecision", ctypes.c_ubyte), ("lfClipPrecision", ctypes.c_ubyte), ("lfQuality", ctypes.c_ubyte),
                ("lfPitchAndFamily", ctypes.c_ubyte), ("lfFaceName", ctypes.c_wchar * 32),
            ]

        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.DrawTextW.argtypes = [wintypes.HDC, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(RECT_G), ctypes.c_uint]
        user32.DrawTextW.restype = ctypes.c_int
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateFontIndirectW.argtypes = [ctypes.POINTER(LOGFONTW)]
        gdi32.CreateFontIndirectW.restype = wintypes.HFONT
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.SetTextColor.argtypes = [wintypes.HDC, ctypes.c_uint32]
        gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BMIH_G), ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, ctypes.c_uint32]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]

        hdc_scr = user32.GetDC(0)
        hdc = gdi32.CreateCompatibleDC(hdc_scr)
        user32.ReleaseDC(0, hdc_scr)
        gdi32.SetBkMode(hdc, 1)
        gdi32.SetTextColor(hdc, 0x00FFFFFF)
        _WIN_GDI_STATE.update({
            "user32": user32, "gdi32": gdi32, "hdc": hdc,
            "RECT": RECT_G, "BMIH": BMIH_G, "LOGFONTW": LOGFONTW,
        })

    fkey = (int(size_px), bool(bold))
    hfont = _WIN_FONT_CACHE.get(fkey)
    if hfont is None:
        LOGFONTW = _WIN_GDI_STATE["LOGFONTW"]
        lf = LOGFONTW(
            lfHeight=-max(8, int(size_px)),
            lfWeight=700 if bold else 400,
            lfCharSet=1,
            lfQuality=4,  # ANTIALIASED_QUALITY (grayscale alpha, zero ClearType color fringes!)
            lfFaceName="Nirmala UI",
        )
        hfont = _WIN_GDI_STATE["gdi32"].CreateFontIndirectW(ctypes.byref(lf))
        if len(_WIN_FONT_CACHE) > 96:
            _WIN_FONT_CACHE.clear()
        _WIN_FONT_CACHE[fkey] = hfont
    return _WIN_GDI_STATE, hfont


def _win_shape_render(text: str, size_px: int, bold: bool):
    import ctypes
    st, hfont = _win_get_hdc_and_font(size_px, bold)
    u32, g32, hdc, RECT_G, BMIH_G = st["user32"], st["gdi32"], st["hdc"], st["RECT"], st["BMIH"]
    old_f = g32.SelectObject(hdc, hfont)
    rc_calc = RECT_G(0, 0, 0, 0)
    # DT_CALCRECT (0x400) | DT_NOPREFIX (0x800) | DT_SINGLELINE (0x20)
    u32.DrawTextW(hdc, text, -1, ctypes.byref(rc_calc), 0x0C20)
    raw_w = max(4, int(rc_calc.right - rc_calc.left))
    raw_h = max(8, int(rc_calc.bottom - rc_calc.top))

    pad_x = max(6, int(size_px * 0.22))
    pad_y = max(4, int(size_px * 0.14))
    dib_w = raw_w + pad_x * 2
    dib_h = raw_h + pad_y * 2
    bmi = BMIH_G(ctypes.sizeof(BMIH_G), dib_w, -dib_h, 1, 32, 0)
    ppv = ctypes.c_void_p()
    hbmp = g32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(ppv), None, 0)
    old_b = g32.SelectObject(hdc, hbmp)
    ctypes.memset(ppv.value, 0, dib_w * dib_h * 4)
    rc_draw = RECT_G(pad_x, pad_y, dib_w, dib_h)
    u32.DrawTextW(hdc, text, -1, ctypes.byref(rc_draw), 0x0820)
    raw_buf = ctypes.string_at(ppv.value, dib_w * dib_h * 4)
    g32.SelectObject(hdc, old_b)
    g32.DeleteObject(hbmp)
    g32.SelectObject(hdc, old_f)

    mask = _Image.frombytes("RGB", (dib_w, dib_h), raw_buf, "raw", "BGRX").convert("L")
    bb = mask.getbbox()
    if bb:
        x0 = max(0, bb[0] - 1)
        x1 = min(dib_w, bb[2] + 1)
        mask = mask.crop((x0, 0, x1, dib_h))
    else:
        mask = mask.crop((pad_x, 0, min(dib_w, pad_x + raw_w), dib_h))
    return mask


def _mac_shape_render(text: str, size_px: int, bold: bool):
    try:
        import CoreText
        import Quartz
        import Foundation

        font_name = "HelveticaNeue-Bold" if bold else "HelveticaNeue"
        ct_font = CoreText.CTFontCreateWithName(font_name, float(size_px), None)
        if ct_font is None:
            ct_font = CoreText.CTFontCreateWithName("Helvetica", float(size_px), None)
        attrs = Foundation.NSDictionary.dictionaryWithObjectsAndKeys_(
            ct_font, CoreText.kCTFontAttributeName,
            Foundation.NSNumber.numberWithBool_(True), CoreText.kCTForegroundColorFromContextAttributeName,
            None,
        )
        attr_str = Foundation.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        line = CoreText.CTLineCreateWithAttributedString(attr_str)
        typ_w, asc, desc, _lead = CoreText.CTLineGetTypographicBounds(line, 0.0, 0.0, 0.0)
        pad_x = max(6, int(size_px * 0.22))
        pad_y = max(4, int(size_px * 0.14))
        w = max(8, int(round(typ_w)) + pad_x * 2)
        h = max(10, int(round(asc + desc)) + pad_y * 2)

        cs = Quartz.CGColorSpaceCreateDeviceGray()
        ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w, cs, Quartz.kCGImageAlphaNone)
        if ctx is None:
            return None
        Quartz.CGContextSetGrayFillColor(ctx, 0.0, 1.0)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
        Quartz.CGContextSetGrayFillColor(ctx, 1.0, 1.0)
        Quartz.CGContextSetTextMatrix(ctx, Quartz.CGAffineTransformIdentity)
        Quartz.CGContextSetTextPosition(ctx, float(pad_x), float(desc) + float(pad_y))
        CoreText.CTLineDraw(line, ctx)
        ptr = Quartz.CGBitmapContextGetData(ctx)
        ns_d = Foundation.NSData.dataWithBytes_length_(ptr, w * h)
        mask = _Image.frombytes("L", (w, h), bytes(ns_d))
        bb = mask.getbbox()
        if bb:
            mask = mask.crop((max(0, bb[0] - 1), 0, min(w, bb[2] + 1), h))
        return mask
    except Exception:
        return None


def shape_render_mask(text: str, size_px: int, bold: bool = True):
    """Returns a cached antialiased 'L' alpha mask with native OS Indic OpenType shaping."""
    if not text:
        return None
    q = max(8, min(260, int(round(size_px))))
    key = (text, q, bool(bold))
    with _SHAPE_LOCK:
        cached = _SHAPE_MASK_CACHE.get(key)
        if cached is not None:
            return cached
        mask = None
        if IS_WIN:
            try:
                mask = _win_shape_render(text, q, bool(bold))
            except Exception:
                mask = None
        elif IS_MAC:
            mask = _mac_shape_render(text, q, bool(bold))
        if mask is not None:
            if len(_SHAPE_MASK_CACHE) > 600:
                _SHAPE_MASK_CACHE.clear()
            _SHAPE_MASK_CACHE[key] = mask
            _SHAPE_MEASURE_CACHE[key] = (mask.width, mask.height)
        return mask


def shape_measure_text(text: str, size_px: int, bold: bool = True):
    """Returns exact OpenType shaped (width, height) for Indic / complex text."""
    q = max(8, min(260, int(round(size_px))))
    key = (text, q, bool(bold))
    with _SHAPE_LOCK:
        cached = _SHAPE_MEASURE_CACHE.get(key)
        if cached is not None:
            return cached
    mask = shape_render_mask(text, q, bool(bold))
    if mask is not None:
        return (mask.width, mask.height)
    return None

