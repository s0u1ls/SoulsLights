import tkinter as tk
import customtkinter as ctk
from tkinter import colorchooser
import os
import sys
import math
import random
import queue
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk

from core.platform_utils import (
    IS_MAC, IS_WIN, get_monitors, get_cursor_pos,
    load_pil_font, get_resource_path, UI_FONT_FAMILY
)

if IS_WIN:
    import ctypes
    from core.win32_utils import user32, RECT

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Exact 10 styles matching Picture 2 in order, with Verci atmospheric palettes & descriptions
STYLE_CATALOG = [
    ("Ship", "Kinetic type", "Words land one by one on a wall that drifts in 3D.", (6, 46, 74), (166, 84, 38)),
    ("Fisheye", "Kinetic type", "3D spherical barrel-warped hero typography with beat bounce.", (66, 16, 84), (178, 86, 46)),
    ("Visual", "Kinetic type", "Centered kinetic word stack paired with expressive icons.", (10, 74, 64), (168, 128, 42)),
    ("Fisheye Visual", "Kinetic type", "Chromatic fisheye dome with floating expressive word icons.", (64, 22, 58), (166, 98, 56)),
    ("Codestyle", "Motion scenes", "Lyrics typed live as syntax code under a blinking red cursor.", (14, 42, 68), (118, 44, 34)),
    ("Codestyle Visual", "Motion scenes", "Live-typing comment stream paired with expressive icons.", (24, 24, 64), (146, 56, 86)),
    ("Branches", "Motion scenes", "A glowing curve draws itself as each word lights a pin node.", (12, 56, 40), (48, 134, 88)),
    ("Web", "Motion scenes", "Each line spins into an orbital spiderweb around a silver spider.", (42, 26, 14), (176, 96, 36)),
    ("Constellation", "Motion scenes", "Full-line random starfield connected by glowing shooting stars.", (24, 20, 64), (92, 72, 146)),
    ("Native Design", "Phone screens", "Lyrics arrive live as a clean iOS message thread.", (12, 46, 84), (48, 118, 176)),
]

STYLE_OPTIONS = [s[0] for s in STYLE_CATALOG]
STYLE_META = {name: (cat, desc, c1, c2) for name, cat, desc, c1, c2 in STYLE_CATALOG}


def _find_icon_path() -> str:
    if IS_MAC:
        p = get_resource_path(os.path.join("assets", "app_icon.png"))
        if p:
            return p
    return get_resource_path("app_icon.ico")


def _load_font(name: str, size: int):
    return load_pil_font(name, size)


_MASK_CACHE = {}


def _rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    key = (w, h, radius)
    m = _MASK_CACHE.get(key)
    if m is None:
        if len(_MASK_CACHE) > 48:
            _MASK_CACHE.clear()
        # 2x supersampled mask for silky smooth anti-aliased corners
        m2 = Image.new("L", (w * 2, h * 2), 0)
        ImageDraw.Draw(m2).rounded_rectangle([0, 0, w * 2 - 1, h * 2 - 1], radius=radius * 2, fill=255)
        m = m2.resize((w, h), Image.Resampling.BILINEAR)
        _MASK_CACHE[key] = m
    return m


_PILL_BORDER_CACHE = {}


def _rounded_outline_overlay(w: int, h: int, radius: int, color: tuple, width: int = 1) -> Image.Image:
    key = (w, h, radius, color, width)
    cached = _PILL_BORDER_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_PILL_BORDER_CACHE) > 96:
        _PILL_BORDER_CACHE.clear()
    sc = 2
    img2 = Image.new("RGBA", (w * sc, h * sc), (0, 0, 0, 0))
    ImageDraw.Draw(img2).rounded_rectangle(
        [0, 0, w * sc - 1, h * sc - 1], radius=radius * sc, outline=color, width=max(2, width * sc)
    )
    out = img2.resize((w, h), Image.Resampling.LANCZOS)
    _PILL_BORDER_CACHE[key] = out
    return out


def _draw_frosted_pill(
    canvas_rgba: Image.Image, box: tuple, radius: int,
    tint=(24, 27, 34, 150), border_col=(255, 255, 255, 78), blur_r: int = 14
):
    """Composites a Gaussian-blurred Liquid-Glass pill with 2x LANCZOS anti-aliased border rim."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(canvas_rgba.width, x1), min(canvas_rgba.height, y1)
    if x1c <= x0c + 2 or y1c <= y0c + 2:
        return
    under = canvas_rgba.crop((x0c, y0c, x1c, y1c)).filter(ImageFilter.GaussianBlur(blur_r))
    glass = Image.new("RGBA", under.size, tint)
    blended = Image.alpha_composite(under, glass)
    r_eff = min(radius, min(under.width, under.height) // 2)
    mask = _rounded_mask(under.width, under.height, r_eff)
    canvas_rgba.paste(blended, (x0c, y0c), mask)
    if border_col and border_col[3] > 0:
        rim = _rounded_outline_overlay(under.width, under.height, r_eff, border_col, width=1)
        canvas_rgba.alpha_composite(rim, (x0c, y0c))


_ICON_CACHE = {}


def _draw_round_polyline(d: ImageDraw.ImageDraw, pts, width: float, fill):
    """Draws an anti-aliased multi-segment stroke with circular round caps & joints at 4x scale."""
    r = max(1, int(round(width * 0.5)))
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=fill, width=max(1, int(round(width))))
    for px, py in pts:
        d.ellipse([px - r, py - r, px + r, py + r], fill=fill)


def _get_hi_icon(name: str, size: int = 24, state=None) -> Image.Image:
    """Renders silky-smooth 4x supersampled LANCZOS vector icons (zero pixelation)."""
    key = (name, size, state)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_ICON_CACHE) > 96:
        _ICON_CACHE.clear()

    sc = 4
    S = size * sc
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = S * 0.5, S * 0.5
    u = S / 24.0

    if name == "spotify":
        # Authentic Spotify circular green emblem + 3 slightly-clockwise tilted arched soundbars
        pad = 0.8 * u
        d.ellipse([pad, pad, S - pad, S - pad], fill=(29, 185, 84, 255))
        tilt = math.radians(8.5)
        cos_t, sin_t = math.cos(tilt), math.sin(tilt)
        bars = [
            (-2.6, 5.9, 2.55, 2.15),
            (1.0, 4.8, 1.95, 1.85),
            (4.3, 3.7, 1.45, 1.60),
        ]
        for y_off, half_x, arch, sw in bars:
            pts = []
            for k in range(15):
                t = (k / 14.0) * 2.0 - 1.0
                lx = t * half_x * u
                ly = (y_off - arch * (1.0 - t * t)) * u
                rx = cx + lx * cos_t - ly * sin_t
                ry = cy + lx * sin_t + ly * cos_t
                pts.append((rx, ry))
            _draw_round_polyline(d, pts, sw * u, (12, 16, 14, 255))

    elif name == "music_note":
        is_play = bool(state)
        pad = 0.8 * u
        d.ellipse([pad, pad, S - pad, S - pad], fill=(56, 60, 72, 235), outline=(255, 255, 255, 42), width=int(0.8 * u))
        fg = (242, 246, 255, 245) if is_play else (200, 206, 220, 210)
        # Double eighth note cleanly centered
        d.ellipse([5.8 * u, 14.2 * u, 10.2 * u, 17.8 * u], fill=fg)
        d.ellipse([12.8 * u, 13.0 * u, 17.2 * u, 16.6 * u], fill=fg)
        _draw_round_polyline(d, [(9.5 * u, 15.8 * u), (9.5 * u, 7.2 * u)], 1.65 * u, fg)
        _draw_round_polyline(d, [(16.5 * u, 14.6 * u), (16.5 * u, 6.0 * u)], 1.65 * u, fg)
        d.polygon([(8.8 * u, 6.8 * u), (17.2 * u, 5.4 * u), (17.2 * u, 7.9 * u), (8.8 * u, 9.3 * u)], fill=fg)

    elif name in ("lock_closed", "lock_open", "lock_dark", "unlock_dark"):
        locked = ("closed" in name or name == "lock_dark")
        dark_ink = ("dark" in name)
        col = (14, 17, 24, 255) if dark_ink else (242, 246, 255, 240)
        # Smooth shackle
        sh_pts = []
        r_sh = 3.6 * u
        sx_off = 0.0 if locked else 1.4 * u
        a_start, a_end = (180, 360) if locked else (205, 390)
        for k in range(19):
            ang = math.radians(a_start + (a_end - a_start) * (k / 18.0))
            sh_pts.append((cx + sx_off + math.cos(ang) * r_sh, 10.6 * u + math.sin(ang) * r_sh))
        if locked:
            sh_pts.append((cx + r_sh, 12.2 * u))
            sh_pts.insert(0, (cx - r_sh, 12.2 * u))
        _draw_round_polyline(d, sh_pts, 1.85 * u, col)
        # Lock body
        bx0, by0, bx1, by1 = 6.2 * u, 11.2 * u, 17.8 * u, 19.6 * u
        if locked or dark_ink:
            d.rounded_rectangle([bx0, by0, bx1, by1], radius=int(2.4 * u), fill=col)
        else:
            d.rounded_rectangle([bx0, by0, bx1, by1], radius=int(2.4 * u), outline=col, width=int(1.7 * u))

    elif name == "refresh":
        col = (242, 246, 255, 240)
        rr = 6.6 * u
        pts = []
        for k in range(28):
            ang = math.radians(48 + 275 * (k / 27.0))
            pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
        _draw_round_polyline(d, pts, 1.9 * u, col)
        # Arrowhead at ~323 deg
        ax, ay = pts[-1]
        d.polygon([
            (ax + 1.4 * u, ay - 2.6 * u),
            (ax + 2.4 * u, ay + 2.2 * u),
            (ax - 2.5 * u, ay + 1.2 * u),
        ], fill=col)

    elif name == "power":
        is_on = bool(state)
        col = (48, 209, 88, 255) if is_on else (255, 105, 97, 240)
        rr = 6.4 * u
        pts = []
        for k in range(28):
            ang = math.radians(-50 + 280 * (k / 27.0))
            pts.append((cx + math.cos(ang) * rr, cy + 0.8 * u + math.sin(ang) * rr))
        _draw_round_polyline(d, pts, 2.1 * u, col)
        _draw_round_polyline(d, [(cx, cy - 6.6 * u), (cx, cy + 0.4 * u)], 2.2 * u, col)

    elif name == "pin":
        dark_ink = bool(state)
        col = (14, 17, 24, 255) if dark_ink else (232, 238, 248, 238)
        # Tilted sleek thumbtack glyph at 4x
        d.polygon([
            (13.8 * u, 5.2 * u), (18.8 * u, 10.2 * u),
            (16.6 * u, 11.4 * u), (14.4 * u, 14.8 * u),
            (9.2 * u, 9.6 * u), (12.6 * u, 7.4 * u),
        ], outline=col, fill=col if dark_ink else None, width=int(1.6 * u))
        _draw_round_polyline(d, [(11.8 * u, 12.2 * u), (6.0 * u, 18.0 * u)], 1.85 * u, col)

    elif name in ("chev_l", "chev_r"):
        col = (242, 246, 255, 225)
        if name == "chev_l":
            pts = [(15.2 * u, 4.8 * u), (7.8 * u, 12.0 * u), (15.2 * u, 19.2 * u)]
        else:
            pts = [(8.8 * u, 4.8 * u), (16.2 * u, 12.0 * u), (8.8 * u, 19.2 * u)]
        _draw_round_polyline(d, pts, 1.9 * u, col)

    elif name == "check":
        col = state if state else (14, 17, 24, 255)
        _draw_round_polyline(d, [(5.5 * u, 12.6 * u), (10.0 * u, 17.0 * u), (18.6 * u, 7.6 * u)], 2.4 * u, col)

    elif name == "win_min":
        _draw_round_polyline(d, [(5.5 * u, 12.5 * u), (18.5 * u, 12.5 * u)], 1.65 * u, (230, 236, 248, 220))

    elif name == "win_max":
        d.rounded_rectangle([6.2 * u, 6.2 * u, 17.8 * u, 17.8 * u], radius=int(2.2 * u), outline=(230, 236, 248, 220), width=int(1.6 * u))

    elif name == "win_close":
        col = state if state else (230, 236, 248, 225)
        _draw_round_polyline(d, [(6.6 * u, 6.6 * u), (17.4 * u, 17.4 * u)], 1.75 * u, col)
        _draw_round_polyline(d, [(17.4 * u, 6.6 * u), (6.6 * u, 17.4 * u)], 1.75 * u, col)

    out = img.resize((size, size), Image.Resampling.LANCZOS)
    _ICON_CACHE[key] = out
    return out


_PURPLE_FILL_CACHE = {}


def _get_purple_gradient_bar(w: int, h: int) -> Image.Image:
    key = (w, h)
    cached = _PURPLE_FILL_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_PURPLE_FILL_CACHE) > 48:
        _PURPLE_FILL_CACHE.clear()
    strip = Image.new("RGBA", (max(2, w), 1))
    px = strip.load()
    c0, c1, c2 = (109, 40, 217), (168, 85, 247), (216, 180, 254)
    for x in range(max(2, w)):
        u = x / max(1, w - 1)
        if u < 0.65:
            k = u / 0.65
            r = int(c0[0] + (c1[0] - c0[0]) * k)
            g = int(c0[1] + (c1[1] - c0[1]) * k)
            b = int(c0[2] + (c1[2] - c0[2]) * k)
        else:
            k = (u - 0.65) / 0.35
            r = int(c1[0] + (c2[0] - c1[0]) * k)
            g = int(c1[1] + (c2[1] - c1[1]) * k)
            b = int(c1[2] + (c2[2] - c1[2]) * k)
        px[x, 0] = (r, g, b, 255)
    bar = strip.resize((max(2, w), max(2, h)), Image.Resampling.BILINEAR)
    _PURPLE_FILL_CACHE[key] = bar
    return bar


_GRAD_CACHE = {}


def _make_grainy_gradient(w: int, h: int, c_left: tuple, c_right: tuple, grain: int = 16, seed: int = 7) -> Image.Image:
    """Fast dual-tone atmospheric gradient with authentic Picture 1 / 2 film grain."""
    bw, bh = max(48, w // 4), max(28, h // 4)
    grad = Image.new("RGB", (bw, bh))
    px = grad.load()
    # Add rich dark center contrast + warm copper/accent glow on right edge like Picture 1
    for x in range(bw):
        u = x / max(1, bw - 1)
        su = u ** 1.35
        r_b = c_left[0] * (1.0 - su) + c_right[0] * su
        g_b = c_left[1] * (1.0 - su) + c_right[1] * su
        b_b = c_left[2] * (1.0 - su) + c_right[2] * su
        for y in range(bh):
            v = y / max(1, bh - 1)
            # Subtle brighter band across middle-right matching Pic 1 radial spotlight
            spot = 1.0 - 0.24 * abs(v - 0.45) * 2.0 + 0.14 * math.sin(u * math.pi)
            px[x, y] = (
                max(0, min(255, int(r_b * spot))),
                max(0, min(255, int(g_b * spot))),
                max(0, min(255, int(b_b * spot))),
            )
    img = grad.resize((w, h), Image.Resampling.BILINEAR)
    rng = random.Random(seed)
    nw, nh = min(320, w), min(200, h)
    noise = Image.new("L", (nw, nh))
    nbuf = bytes(max(0, min(255, 128 + rng.randint(-grain, grain))) for _ in range(nw * nh))
    noise.frombytes(nbuf)
    if (nw, nh) != (w, h):
        noise = noise.resize((w, h), Image.Resampling.BILINEAR)
    n_rgb = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(img, n_rgb, 0.18)


def _get_cached_gradient(w: int, h: int, c_left: tuple, c_right: tuple, grain: int, seed: int, radius: int = 0) -> Image.Image:
    key = (w, h, c_left, c_right, grain, seed, radius)
    bg = _GRAD_CACHE.get(key)
    if bg is None:
        if len(_GRAD_CACHE) > 28:
            _GRAD_CACHE.clear()
        rgb = _make_grainy_gradient(w, h, c_left, c_right, grain=grain, seed=seed)
        rgba = rgb.convert("RGBA")
        if radius > 0:
            # Round outer corners smoothly for cards (Picture 2)
            out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            out.paste(rgba, (0, 0), _rounded_mask(w, h, radius))
            rgba = out
        _GRAD_CACHE[key] = rgba
    return _GRAD_CACHE[key].copy()


def _render_style_preview(style_name: str, w: int, h: int, c_left: tuple, c_right: tuple, is_hero: bool = False, t_phase: float = 0.0, radius: int = 0) -> Image.Image:
    """Renders 1:1 Verci Picture 1 hero artwork OR Picture 2 style card preview (static or animated on hover)."""
    img = _get_cached_gradient(w, h, c_left, c_right, 20 if is_hero else 16, hash(style_name) & 0xFFFF, radius=radius)
    d = ImageDraw.Draw(img)
    s = (h / 450.0) if is_hero else (h / 128.0)

    f_big = _load_font("segoeuib.ttf", max(12, int(44 * s)))
    f_med = _load_font("segoeui.ttf", max(10, int(22 * s)))
    f_sm = _load_font("segoeui.ttf", max(8, int(13 * s)))
    f_mono = _load_font("cour.ttf", max(8, int(15 * s)))

    cx = w // 2
    cy = int(h * 0.43) if is_hero else (h // 2)
    step = int(t_phase * 2.2)

    if style_name == "Ship":
        words = ["clock", "in", "the", "city", "slows", "down"]
        act_i = (3 + step) % len(words) if t_phase > 0 else 3
        drift_x = int(9 * s * math.sin(t_phase * 1.4))
        if is_hero:
            # Matches Pic 1 center preview: tilted muted "clock" + crisp bold "Every"
            if t_phase <= 0.15:
                d.text((cx - int(76 * s), cy + int(2 * s)), "clock", font=f_med, fill=(215, 228, 242, 165))
                d.text((cx - int(14 * s), cy - int(28 * s)), "Every", font=f_big, fill=(242, 248, 255, 245))
            else:
                prev_w = words[max(0, act_i - 1)]
                cur_w = words[act_i]
                d.text((cx - int(76 * s) + drift_x, cy + int(2 * s)), prev_w, font=f_med, fill=(215, 228, 242, 165))
                d.text((cx - int(10 * s) + drift_x, cy - int(28 * s)), cur_w, font=f_big, fill=(242, 248, 255, 245))
        else:
            yy = int(10 * s)
            for idx_w, wt in enumerate(words):
                bb = d.textbbox((0, 0), wt, font=f_sm)
                tw, th = bb[2] - bb[0], bb[3] - bb[1]
                dx_w = (drift_x // 2 if idx_w == act_i else 0) + (idx_w % 2 - 0.5) * 4 * s
                if idx_w == act_i:
                    px0 = int(cx - tw / 2 - 6 + dx_w)
                    py0 = int(yy - 2)
                    d.rounded_rectangle([px0, py0, px0 + tw + 12, py0 + th + 5], radius=3, fill=(244, 247, 255, 248))
                    d.text((int(cx - tw / 2 - bb[0] + dx_w), int(yy - bb[1] + 1)), wt, font=f_sm, fill=(14, 18, 26, 255))
                else:
                    d.text((int(cx - tw / 2 - bb[0] + dx_w), int(yy - bb[1])), wt, font=f_sm, fill=(225, 234, 246, 200))
                yy += int(18.5 * s)

    elif style_name in ("Fisheye", "Fisheye Visual"):
        is_vis = ("Visual" in style_name)
        rows = [("the", 0.28, False), ("moon" if is_vis else "till", 0.48, True), ("can" if is_vis else "morning", 0.68, False)]
        pulse_i = step % len(rows) if t_phase > 0 else 1
        for ri, (txt, yf, _) in enumerate(rows):
            big = (ri == pulse_i)
            f_u = f_big if (big and is_hero) else (f_med if (big or is_hero) else f_sm)
            tw = d.textlength(txt, font=f_u)
            bob = int(3 * s * math.sin(t_phase * 3.0 + ri))
            y_r = int(h * (0.28 + ri * 0.14 if is_hero else yf)) - 10 + bob
            d.text((cx - tw / 2, y_r), txt, font=f_u, fill=(255, 255, 255, 250 if big else 185))
        if is_vis:
            d.ellipse([cx + int(36 * s), int(cy - 6 * s), cx + int(46 * s), int(cy + 4 * s)], fill=(255, 238, 180, 240))

    elif style_name == "Visual":
        lines = ["water,", "fire", "in", "the"]
        act_v = step % len(lines) if t_phase > 0 else 0
        yy = int(cy - 38 * s) if is_hero else int(h * 0.16)
        f_card_b = _load_font("segoeuib.ttf", max(9, int(14 * s)))
        for idx_l, lt in enumerate(lines):
            is_a = (idx_l == act_v)
            f_u = f_big if (is_a and is_hero) else (f_med if is_hero else (f_card_b if is_a else f_sm))
            tw = d.textlength(lt, font=f_u)
            d.text((cx - tw / 2 + int(8 * s), yy), lt, font=f_u, fill=(255, 255, 255, 250 if is_a else 165))
            if idx_l <= 1 or is_a:
                r_i = int((5 if is_a else 4) * s)
                d.ellipse([cx - tw / 2 - int(9 * s), yy + 3, cx - tw / 2 - int(9 * s) + r_i * 2, yy + 3 + r_i * 2], fill=(215, 250, 235, 240 if is_a else 190))
            yy += int((36 if is_hero else 24) * s)

    elif style_name in ("Codestyle", "Codestyle Visual"):
        is_vis = ("Visual" in style_name)
        t1 = "till(the)" if is_vis else "till.the(road)"
        full_t2 = "// morning" if is_vis else "run"
        prog_c = 1.0 if t_phase <= 0.85 else (0.35 + 0.65 * ((t_phase * 0.65) % 1.0))
        t2 = full_t2[: max(1, int(math.ceil(len(full_t2) * prog_c)))]
        f_c = f_med if is_hero else f_mono
        tw1 = d.textlength(t1, font=f_c)
        tw2 = d.textlength(t2, font=f_c)
        y1 = int(cy - 18 * s)
        y2 = int(cy + 14 * s)
        d.text((cx - tw1 / 2, y1), t1, font=f_c, fill=(195, 210, 230, 175))
        if is_vis:
            r_sun = max(3, int(4 * s))
            sx = cx - tw2 / 2 - int(12 * s)
            d.ellipse([sx - r_sun, y2 + 6 - r_sun, sx + r_sun, y2 + 6 + r_sun], fill=(250, 204, 21, 240))
            d.text((cx - tw2 / 2, y2), t2, font=f_c, fill=(240, 246, 255, 245))
        else:
            d.text((cx - tw2 / 2 - 4, y2), t2, font=f_c, fill=(96, 175, 255, 250))
        if int(t_phase * 3.0) % 2 == 0:
            cur_x = cx + tw2 / 2 + 3
            d.rectangle([cur_x, y2, cur_x + max(4, int(7 * s)), y2 + max(10, int(16 * s))], fill=(239, 68, 68, 245))

    elif style_name == "Branches":
        pts = [(int(w * (0.14 + 0.18 * i)), int(cy + 11 * s * math.sin(i * 1.4 + t_phase))) for i in range(5)]
        d.line(pts, fill=(205, 242, 222, 165), width=max(1, int(2 * s)))
        lit_idx = step % len(pts) if t_phase > 0 else 2
        for bi, (px, py) in enumerate(pts):
            dy = -int(18 * s) if bi % 2 == 0 else int(18 * s)
            d.line([(px, py), (px, py + dy)], fill=(235, 250, 242, 220 if bi <= lit_idx else 110), width=1)
            rr = max(3, int((4 if bi == lit_idx else 3) * s))
            d.ellipse([px - rr, py + dy - rr, px + rr, py + dy + rr], fill=(255, 255, 255, 250 if bi == lit_idx else 170))

    elif style_name == "Web":
        mr = min(w, h) * (0.29 if is_hero else 0.38)
        rot = t_phase * 0.16
        n_sp = 10
        spokes = [rot + k * (2.0 * math.pi / n_sp) for k in range(n_sp)]
        for a in spokes:
            d.line([(cx, cy), (cx + math.cos(a) * mr, cy + math.sin(a) * mr)], fill=(235, 240, 248, 86), width=1)
        for rk in (0.28, 0.54, 0.78, 1.0):
            rr = mr * rk
            arc = []
            for k in range(n_sp):
                aa0, aa1 = spokes[k], spokes[(k + 1) % n_sp]
                if aa1 < aa0:
                    aa1 += 2.0 * math.pi
                for si in range(5):
                    u = si / 5.0
                    sag = 1.0 - 0.13 * (4.0 * u * (1.0 - u))
                    ang = aa0 + (aa1 - aa0) * u
                    arc.append((cx + math.cos(ang) * rr * sag, cy + math.sin(ang) * rr * sag))
            arc.append(arc[0])
            d.line(arc, fill=(235, 240, 248, 96), width=1)
        # Constellation-style glowing connected sung nodes around the whole web
        w_pts = [
            (int(cx + math.cos(spokes[0]) * mr * 0.72), int(cy + math.sin(spokes[0]) * mr * 0.72)),
            (int(cx + math.cos(spokes[2]) * mr * 0.65), int(cy + math.sin(spokes[2]) * mr * 0.65)),
            (int(cx + math.cos(spokes[4]) * mr * 0.75), int(cy + math.sin(spokes[4]) * mr * 0.75)),
        ]
        d.line(w_pts, fill=(255, 210, 150, 230), width=max(1, int(2 * s)))
        for wi_p, (px, py) in enumerate(w_pts):
            rt = max(3, int((5 if wi_p == 2 else 3) * s))
            d.ellipse([px - rt, py - rt, px + rt, py + rt], fill=(255, 255, 255, 245))
        d.text((w_pts[2][0] - int(14 * s), w_pts[2][1] - int(16 * s)), "paper", font=f_sm, fill=(255, 255, 255, 245))
        sc_sp = (20 if is_hero else 13) * s
        def _sp(pts):
            return [(cx + x * sc_sp, cy + y * sc_sp) for x, y in pts]
        sp_polys = [
            _sp([(-0.15, -0.06), (-0.48, -0.06), (-0.72, -0.34), (-0.52, -0.80), (-0.58, -0.44), (-0.36, -0.10)]),
            _sp([(0.15, -0.06), (0.48, -0.06), (0.72, -0.34), (0.52, -0.80), (0.58, -0.44), (0.36, -0.10)]),
            _sp([(0.0, 0.70), (-0.18, 0.02), (-0.12, -0.18), (0.0, -0.15), (0.12, -0.18), (0.18, 0.02)]),
        ]
        for poly in sp_polys:
            d.polygon(poly, fill=(242, 246, 252, 250), outline=(12, 14, 18, 255))

    elif style_name == "Constellation":
        s_pts = [(int(w * 0.28), int(cy + 16 * s)), (int(w * 0.50), int(cy - 14 * s)), (int(w * 0.72), int(cy + 8 * s))]
        d.line(s_pts, fill=(215, 225, 255, 130), width=1)
        u_m = (t_phase * 0.8) % 1.0
        mx = s_pts[0][0] + (s_pts[1][0] - s_pts[0][0]) * u_m
        my = s_pts[0][1] + (s_pts[1][1] - s_pts[0][1]) * u_m
        d.line([s_pts[0], (mx, my)], fill=(255, 250, 225, 235), width=max(1, int(2 * s)))
        for i, (px, py) in enumerate(s_pts):
            r = max(3, int((6 if i == 1 else 3) * s))
            d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 248, 220, 245 if i == 1 else 160))
        d.text((s_pts[1][0] - int(18 * s), s_pts[1][1] + int(8 * s)), "coming", font=f_sm, fill=(255, 255, 255, 245))

    elif style_name == "Native Design":
        bw = int(w * (0.36 if is_hero else 0.62))
        bx0 = (w - bw) // 2
        pop = int(3 * s * abs(math.sin(t_phase * 1.8)))
        f_tiny = _load_font("segoeui.ttf", max(6, int(7.0 * s)))
        y_top = cy - int(34 * s)
        # Mini dark Apple Maps widget card + stacked iMessage blue bubbles
        mc_h = int(36 * s)
        d.rounded_rectangle([bx0, y_top, bx0 + bw, y_top + mc_h], radius=7, fill=(24, 28, 34, 242), outline=(255, 255, 255, 42))
        d.rounded_rectangle([bx0 + 1, y_top + 1, bx0 + bw - 1, y_top + int(17 * s)], radius=6, fill=(26, 48, 36, 255))
        d.ellipse([cx - int(8 * s), y_top + int(3 * s), cx + int(8 * s), y_top + int(14 * s)], outline=(145, 155, 170, 210), width=1)
        d.ellipse([cx - 2, y_top + int(7 * s), cx + 2, y_top + int(11 * s)], fill=(56, 189, 248, 255))
        d.text((bx0 + 6, y_top + int(20 * s)), "Baby I like your style", font=f_tiny, fill=(248, 250, 255, 245))
        bh_u = max(13, int(15 * s))
        b1_y0 = y_top + mc_h + 5 - pop // 2
        d.rounded_rectangle([bx0 + int(bw * 0.24), b1_y0, bx0 + bw, b1_y0 + bh_u], radius=7, fill=(10, 132, 255, 245))
        d.text((bx0 + int(bw * 0.24) + 6, b1_y0 + int(2.5 * s)), "Grips on your waist", font=f_tiny, fill=(255, 255, 255, 245))
        b2_y0 = b1_y0 + bh_u + 4 + pop // 2
        d.rounded_rectangle([bx0 + int(bw * 0.30), b2_y0, bx0 + bw, b2_y0 + bh_u], radius=7, fill=(0, 118, 255, 255))
        d.text((bx0 + int(bw * 0.30) + 6, b2_y0 + int(2.5 * s)), "You know I don't play", font=f_tiny, fill=(255, 255, 255, 255))

    return img


class UnifiedDashboard(ctk.CTk):
    """SoulsLights Studio — 1:1 Verci Picture 1 & Picture 2 interface rendered via true PIL RGBA Liquid Glass."""

    WIN_W = 1120
    WIN_H = 780
    HERO_H = 540
    PAD_X = 24
    GRID_TOP = 600
    CARD_W = 246
    CARD_H = 134
    CARD_GAP_X = 28
    CARD_ROW_H = 196

    def __init__(self, config_manager, engine_ctrl, media_monitor, on_quit_callback=None):
        super().__init__()
        self.cfg_mgr = config_manager
        self.engine = engine_ctrl
        self.media_mon = media_monitor
        self.on_quit_callback = on_quit_callback

        self.title("SoulsLights")
        self.geometry(f"{self.WIN_W}x{self.WIN_H}")
        self.minsize(980, 660)

        ico = _find_icon_path()
        if ico:
            try:
                if IS_WIN and ico.lower().endswith(".ico"):
                    self.iconbitmap(ico)
                else:
                    ic_img = Image.open(ico).convert("RGBA").resize((128, 128), Image.Resampling.LANCZOS)
                    self._app_icon_photo = ImageTk.PhotoImage(ic_img)
                    self.iconphoto(True, self._app_icon_photo)
            except Exception:
                pass
        self._saved_geom = None

        self.COLOR_BG = "#000000"
        self.COLOR_SURFACE = "#14161C"
        self.COLOR_PILL = "#1E2129"
        self.COLOR_BORDER = "#383D4A"
        self.COLOR_PLATINUM = "#D4E2EE"
        self.COLOR_EMERALD = "#30D158"
        self.COLOR_TEXT = "#F5F5F7"
        self.COLOR_TEXT_DIM = "#8E929B"

        self.configure(fg_color=self.COLOR_BG)

        self.current_media = dict(self.media_mon.current_info)
        self._last_pushed_colors = None
        self._ui_queue = queue.SimpleQueue()
        self._active_popover = None
        self._hovered_style = None
        self._hovered_nav = None
        self._hovered_pop = None
        self._pinned_top = False
        self._is_maximized = False
        self._anim_phase = 0.0
        self._scroll_y = 0
        self._max_scroll = 360
        self._drag_origin = None
        self._active_slider = None
        self._popover_rect = None
        self._popover_hits = []
        self._popover_sliders = []

        self._hit_regions = []
        self._tk_photos = {}
        self._card_items = {}
        self._badge_items = {}

        cfg = self.cfg_mgr.config
        amb = cfg["ambient"]
        lyr = cfg["lyrics"]
        sys_cfg = cfg["system"]
        self.master_switch_var = ctk.BooleanVar(value=cfg.get("master_enabled", True))
        self.lumn_switch_var = ctk.BooleanVar(value=cfg.get("ambient_enabled", True))
        self.verci_switch_var = ctk.BooleanVar(value=cfg.get("lyrics_enabled", True))
        self.click_through_var = ctk.BooleanVar(value=lyr.get("click_through", True))
        self.auto_sync_var = ctk.BooleanVar(value=lyr.get("auto_sync_colors", True))
        self.override_var = ctk.BooleanVar(value=amb.get("override_album_color", False))
        self.audio_react_var = ctk.BooleanVar(value=amb.get("audio_reactive", True))
        self.fs_var = ctk.BooleanVar(value=amb.get("show_over_fullscreen", True))
        self.tray_var = ctk.BooleanVar(value=sys_cfg.get("minimize_to_tray", True))
        self.startup_var = ctk.BooleanVar(value=sys_cfg.get("start_with_windows", False))

        if lyr.get("style") not in STYLE_META:
            lyr["style"] = "Ship"

        self._build_canvas_ui()
        self.media_mon.on_update_callback = self._on_media_update
        self.after(40, self._apply_frameless_liquid_glass)
        self.after(80, self._tick_previews)
        self.after(60, self._poll_ui_queue)
        self.after(1000, self._periodic_status_check)
        self.protocol("WM_DELETE_WINDOW", self._on_close_window)

    def enqueue_ui(self, fn, *args, **kwargs):
        self._ui_queue.put((fn, args, kwargs))

    def _poll_ui_queue(self):
        if IS_MAC:
            try:
                from core.mac_utils import drain_main_tasks
                drain_main_tasks()
            except Exception:
                pass
        try:
            while True:
                fn, args, kwargs = self._ui_queue.get_nowait()
                try:
                    fn(*args, **kwargs)
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.after(30 if IS_MAC else 60, self._poll_ui_queue)

    def _apply_frameless_liquid_glass(self):
        """Applies clean borderless rounded styling on Windows (DWM) and Dark Aqua titlebar on macOS."""
        if IS_MAC:
            # Never call synchronous AppKit NSWindow mutations inside Tk PythonCmd:
            # defer lightweight appearance/titlebar polish onto NSOperationQueue.mainQueue()
            # so Cocoa runs safely outside _tkinter's non-reentrant PythonCmd frame.
            try:
                import Foundation
                import AppKit

                def _style_mac():
                    try:
                        dark_name = getattr(AppKit, "NSAppearanceNameDarkAqua", "NSAppearanceNameDarkAqua")
                        dark_app = AppKit.NSAppearance.appearanceNamed_(dark_name)
                        if dark_app is not None:
                            AppKit.NSApp.setAppearance_(dark_app)
                        for win in AppKit.NSApp.windows():
                            if str(win.title() or "") == "SoulsLights":
                                if dark_app is not None:
                                    win.setAppearance_(dark_app)
                                win.setTitlebarAppearsTransparent_(True)
                                win.setTitleVisibility_(getattr(AppKit, "NSWindowTitleHidden", 1))
                                win.setBackgroundColor_(AppKit.NSColor.blackColor())
                                break
                    except Exception:
                        pass

                Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(_style_mac)
            except Exception:
                pass
            return
        if not IS_WIN:
            return
        try:
            hwnd = self.get_native_hwnd()
            if not hwnd:
                return
            GWL_STYLE = -16
            WS_CAPTION = 0x00C00000
            SWP_FRAMECHANGED = 0x0020
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            st = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            if st & WS_CAPTION:
                user32.SetWindowLongPtrW(hwnd, GWL_STYLE, st & ~WS_CAPTION)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
            dwm.DwmSetWindowAttribute.restype = ctypes.c_long
            for attr, val in ((20, 1), (33, 2)):
                c_val = ctypes.c_int(val)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(c_val), ctypes.sizeof(c_val))
        except Exception:
            pass

    def _build_canvas_ui(self):
        self.canvas = tk.Canvas(self, bg="#000000", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.hero_item = self.canvas.create_image(0, 0, anchor="nw")
        self.all_styles_lbl_item = self.canvas.create_text(
            self.PAD_X, 566, text="All styles", anchor="nw",
            fill="#F5F5F7", font=(UI_FONT_FAMILY, 17, "bold")
        )
        self.status_txt_item = self.canvas.create_text(
            self.WIN_W - self.PAD_X, 572, text="", anchor="ne",
            fill="#8E929B", font=(UI_FONT_FAMILY, 10)
        )

        # Create 4-column style cards
        for idx_s, (sname, cat, _desc, _c1, _c2) in enumerate(STYLE_CATALOG):
            r_i, c_i = divmod(idx_s, 4)
            cx0 = self.PAD_X + c_i * (self.CARD_W + self.CARD_GAP_X)
            cy0 = self.GRID_TOP + r_i * self.CARD_ROW_H
            item_img = self.canvas.create_image(cx0, cy0, anchor="nw")
            item_lbl = self.canvas.create_text(
                cx0 + 2, cy0 + self.CARD_H + 10, text=sname, anchor="nw",
                fill="#F5F5F7", font=(UI_FONT_FAMILY, 11, "bold")
            )
            item_cat = self.canvas.create_text(
                cx0 + 2, cy0 + self.CARD_H + 30, text=cat, anchor="nw",
                fill="#8E929B", font=(UI_FONT_FAMILY, 10)
            )
            self._card_items[sname] = (item_img, item_lbl, item_cat, cx0, cy0)

        # Sticky Liquid-Glass Floating Header + Floating Liquid-Glass Popover Sheet (zero opaque CTk boxes!)
        self.header_item = self.canvas.create_image(0, 0, anchor="nw")
        self.popover_item = self.canvas.create_image(0, 0, anchor="nw", state="hidden")

        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", self._on_mouse_click)
        self.canvas.bind("<Button-3>", self._on_mouse_right_click)
        if IS_MAC:
            self.canvas.bind("<Button-2>", self._on_mouse_right_click)
            self.canvas.bind("<Control-Button-1>", self._on_mouse_right_click)
            self.bind("<Command-w>", lambda _e: self._on_close_window())
            self.bind("<Command-q>", lambda _e: self.quit_app())
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_release)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Configure>", self._on_resize)

        self._render_all_cards()
        self._render_hero_stage()
        self._render_sticky_header()

    def _cur_size(self):
        w = max(920, self.winfo_width() if self.winfo_width() > 200 else self.WIN_W)
        h = max(620, self.winfo_height() if self.winfo_height() > 200 else self.WIN_H)
        return w, h

    def _on_resize(self, _evt=None):
        w, _h = self._cur_size()
        if abs(w - getattr(self, "_last_w", w)) > 8:
            self._last_w = w
            self._reposition_grid()
            self._render_hero_stage()
            self._render_sticky_header()
            if self._active_popover:
                self._render_popover()

    def _reposition_grid(self):
        w, h = self._cur_size()
        col_gap = max(16, (w - 2 * self.PAD_X - 4 * self.CARD_W) // 3)
        sy = self._scroll_y
        self.canvas.coords(self.hero_item, 0, -sy)
        self.canvas.coords(self.all_styles_lbl_item, self.PAD_X, 566 - sy)
        self.canvas.coords(self.status_txt_item, w - self.PAD_X, 572 - sy)
        max_y = 600
        for idx_s, (sname, _cat, _desc, _c1, _c2) in enumerate(STYLE_CATALOG):
            r_i, c_i = divmod(idx_s, 4)
            cx0 = self.PAD_X + c_i * (self.CARD_W + col_gap)
            cy0 = self.GRID_TOP + r_i * self.CARD_ROW_H - sy
            item_img, item_lbl, item_cat, _, _ = self._card_items[sname]
            self.canvas.coords(item_img, cx0, cy0)
            self.canvas.coords(item_lbl, cx0 + 2, cy0 + self.CARD_H + 10)
            self.canvas.coords(item_cat, cx0 + 2, cy0 + self.CARD_H + 30)
            self._card_items[sname] = (item_img, item_lbl, item_cat, cx0, cy0 + sy)
            max_y = max(max_y, self.GRID_TOP + (r_i + 1) * self.CARD_ROW_H + 20)
        self._max_scroll = max(0, max_y - h)

    def _render_single_card(self, sname: str, t_phase: float = 0.0):
        cat, _desc, c1, c2 = STYLE_META[sname]
        cur_style = self.cfg_mgr.config["lyrics"].get("style", "Ship")
        is_sel = (sname == cur_style)
        is_hov = (sname == self._hovered_style)

        card_pil = _render_style_preview(sname, self.CARD_W, self.CARD_H, c1, c2, is_hero=False, t_phase=t_phase, radius=14)
        d = ImageDraw.Draw(card_pil)
        if is_sel:
            rim = _rounded_outline_overlay(self.CARD_W, self.CARD_H, 14, (255, 255, 255, 240), width=2)
            card_pil.alpha_composite(rim, (0, 0))
            d = ImageDraw.Draw(card_pil)
            # Picture 2 crisp white 4x vector-checkmark + "Selected" pill at top right
            f_b = _load_font("segoeuib.ttf", 11)
            bx1, by0 = self.CARD_W - 10, 10
            bx0, by1 = bx1 - 78, by0 + 22
            pill_m = _rounded_mask(bx1 - bx0, by1 - by0, 11)
            card_pil.paste(Image.new("RGBA", (bx1 - bx0, by1 - by0), (255, 255, 255, 248)), (bx0, by0), pill_m)
            card_pil.alpha_composite(_get_hi_icon("check", 14, (14, 17, 24, 255)), (bx0 + 6, by0 + 4))
            d = ImageDraw.Draw(card_pil)
            d.text((bx0 + 23, by0 + 4), "Selected", font=f_b, fill=(14, 17, 24, 255))
        elif is_hov:
            card_pil.alpha_composite(_rounded_outline_overlay(self.CARD_W, self.CARD_H, 14, (216, 180, 254, 195), width=2), (0, 0))
        else:
            card_pil.alpha_composite(_rounded_outline_overlay(self.CARD_W, self.CARD_H, 14, (255, 255, 255, 38), width=1), (0, 0))

        tk_img = ImageTk.PhotoImage(card_pil)
        self._tk_photos[f"card_{sname}"] = tk_img
        item_img = self._card_items[sname][0]
        self.canvas.itemconfig(item_img, image=tk_img)

    def _render_all_cards(self):
        for sname in STYLE_OPTIONS:
            self._render_single_card(sname, t_phase=self._anim_phase if sname == self._hovered_style else 0.0)
        self._reposition_grid()

    def _render_hero_stage(self):
        """Renders Picture 1 Hero banner onto a single clean PIL RGBA image (zero opaque box artifacts)."""
        w, _ = self._cur_size()
        hh = self.HERO_H
        cur_style = self.cfg_mgr.config["lyrics"].get("style", "Ship")
        cat, desc, c1, c2 = STYLE_META.get(cur_style, STYLE_META["Ship"])

        hero = _render_style_preview(cur_style, w, hh, c1, c2, is_hero=True, t_phase=self._anim_phase, radius=0)
        # Smooth alpha-composited dark fade at bottom edge into #000000 (keeps alpha=255!)
        fade_band = Image.new("RGBA", (w, 42), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fade_band)
        for y in range(42):
            a = int(255 * (y / 41.0) ** 1.4)
            fd.line([(0, y), (w, y)], fill=(0, 0, 0, a))
        hero.alpha_composite(fade_band, (0, hh - 42))
        d = ImageDraw.Draw(hero)

        # Left < and Right > 4x supersampled smooth vector chevrons (matching Pic 1)
        hero.alpha_composite(_get_hi_icon("chev_l", 32), (16, hh // 2 - 16))
        hero.alpha_composite(_get_hi_icon("chev_r", 32), (w - 48, hh // 2 - 16))
        d = ImageDraw.Draw(hero)

        # Bottom-Left Category + Large Georgia Serif Title + Subtitle (matching Pic 1)
        f_cat = _load_font("segoeui.ttf", 12)
        f_title = _load_font("georgiab.ttf", 36)
        f_desc = _load_font("segoeui.ttf", 13)
        x_info = 48
        d.text((x_info, hh - 178), cat, font=f_cat, fill=(210, 222, 234, 195))
        d.text((x_info, hh - 158), cur_style, font=f_title, fill=(255, 255, 255, 252))
        d.text((x_info, hh - 110), desc, font=f_desc, fill=(215, 226, 238, 195))

        # White "🔒 Unlock" pill + Frosted Circular Pin Button (matching Pic 1, 2x/4x smooth!)
        is_locked = self.click_through_var.get()
        cta_x0, cta_y0, cta_x1, cta_y1 = x_info, hh - 80, x_info + 114, hh - 40
        cta_m = _rounded_mask(cta_x1 - cta_x0, cta_y1 - cta_y0, 20)
        hero.paste(Image.new("RGBA", (cta_x1 - cta_x0, cta_y1 - cta_y0), (255, 255, 255, 250)), (cta_x0, cta_y0), cta_m)
        hero.alpha_composite(_get_hi_icon("lock_dark" if is_locked else "unlock_dark", 18), (cta_x0 + 14, cta_y0 + 11))
        d = ImageDraw.Draw(hero)
        f_cta = _load_font("segoeuib.ttf", 13)
        d.text((cta_x0 + 38, cta_y0 + 11), "Unlock" if is_locked else "Lock", font=f_cta, fill=(14, 17, 24, 255))

        # Circular Liquid Glass Pin button next to Unlock
        px0, py0, px1, py1 = cta_x1 + 10, cta_y0, cta_x1 + 50, cta_y1
        if self._pinned_top:
            pm = _rounded_mask(40, 40, 20)
            hero.paste(Image.new("RGBA", (40, 40), (255, 255, 255, 248)), (px0, py0), pm)
        else:
            _draw_frosted_pill(hero, (px0, py0, px1, py1), radius=20, tint=(30, 34, 42, 140), border_col=(255, 255, 255, 82))
        hero.alpha_composite(_get_hi_icon("pin", 20, self._pinned_top), (px0 + 10, py0 + 10))
        d = ImageDraw.Draw(hero)

        # Bottom-center 10 pagination dots
        dot_span = (len(STYLE_OPTIONS) - 1) * 16
        dx_start = w // 2 - dot_span // 2
        dy_dot = hh - 24
        for idx_d, nm in enumerate(STYLE_OPTIONS):
            dx = dx_start + idx_d * 16
            r_d = 3 if nm == cur_style else 2
            col_d = (255, 255, 255, 245) if nm == cur_style else (255, 255, 255, 85)
            d.ellipse([dx - r_d, dy_dot - r_d, dx + r_d, dy_dot + r_d], fill=col_d)

        tk_hero = ImageTk.PhotoImage(hero)
        self._tk_photos["hero"] = tk_hero
        self.canvas.itemconfig(self.hero_item, image=tk_hero)
        self._hero_hits = [
            ("step_prev", (10, hh // 2 - 40, 66, hh // 2 + 40)),
            ("step_next", (w - 66, hh // 2 - 40, w - 10, hh // 2 + 40)),
            ("toggle_lock", (cta_x0, cta_y0, cta_x1, cta_y1)),
            ("toggle_pin", (px0, py0, px1, py1)),
        ]
        for idx_d, nm in enumerate(STYLE_OPTIONS):
            dx = dx_start + idx_d * 16
            self._hero_hits.append((f"select:{nm}", (dx - 7, dy_dot - 7, dx + 7, dy_dot + 7)))

    def _render_sticky_header(self):
        """Renders Picture 1's floating Liquid-Glass top bar with 4x smooth icons & purple accents."""
        w, _ = self._cur_size()
        hdr_h = 56
        cur_style = self.cfg_mgr.config["lyrics"].get("style", "Ship")
        _, _, c1, c2 = STYLE_META.get(cur_style, STYLE_META["Ship"])

        if self._scroll_y < self.HERO_H - hdr_h:
            base = _get_cached_gradient(w, self.HERO_H, c1, c2, 20, hash(cur_style) & 0xFFFF).crop((0, self._scroll_y, w, self._scroll_y + hdr_h))
        else:
            base = Image.new("RGBA", (w, hdr_h), (6, 7, 10, 255))

        d = ImageDraw.Draw(base)
        f_brand = _load_font("segoeui.ttf", 12)
        d.text((18, 19), "SoulsLights", font=f_brand, fill=(235, 240, 248, 225))

        # Center Liquid-Glass Nav Capsule: Lyrics | Glow | Screen | Options
        nav_w = 340
        nx0, ny0, nx1, ny1 = w // 2 - nav_w // 2, 10, w // 2 + nav_w // 2, 46
        _draw_frosted_pill(base, (nx0, ny0, nx1, ny1), radius=18, tint=(20, 18, 30, 152), border_col=(216, 180, 254, 72))

        nav_hits = []
        f_nav = _load_font("segoeuib.ttf", 12)
        f_nav_r = _load_font("segoeui.ttf", 12)
        items = ("Lyrics", "Glow", "Screen", "Options")
        slot_w = nav_w // len(items)
        for ii, label in enumerate(items):
            sx0 = nx0 + ii * slot_w
            sx1 = sx0 + slot_w
            is_act = (self._active_popover == label)
            is_hov = (self._hovered_nav == label)
            if is_act or is_hov:
                pw_s, ph_s = sx1 - sx0 - 8, ny1 - ny0 - 8
                pm = _rounded_mask(pw_s, ph_s, 14)
                fill_col = (147, 51, 234, 138) if is_act else (255, 255, 255, 28)
                base.paste(Image.new("RGBA", (pw_s, ph_s), fill_col), (sx0 + 4, ny0 + 4), pm)
                if is_act:
                    base.alpha_composite(_rounded_outline_overlay(pw_s, ph_s, 14, (216, 180, 254, 135)), (sx0 + 4, ny0 + 4))
            d = ImageDraw.Draw(base)
            f_u = f_nav if is_act else f_nav_r
            tw = d.textlength(label, font=f_u)
            d.text((sx0 + (slot_w - tw) / 2, ny0 + 10), label, font=f_u, fill=(255, 255, 255, 252 if (is_act or is_hov) else 215))
            nav_hits.append((f"nav:{label}", (sx0, ny0, sx1, ny1)))

        # Right Liquid-Glass Pills (shift right on macOS since native titlebar holds traffic lights)
        right_edge = w - 20 if IS_MAC else w - 102
        ap_x1 = right_edge
        ap_x0 = ap_x1 - 88
        mp_x1 = ap_x0 - 8
        mp_x0 = mp_x1 - 76

        # Right Liquid-Glass Pill 1: Authentic Spotify Emblem + Double Eighth Music Note (4x smooth!)
        _draw_frosted_pill(base, (mp_x0, 10, mp_x1, 46), radius=18, tint=(20, 18, 30, 152), border_col=(255, 255, 255, 76))
        is_play = (self.current_media.get("status") == "Playing")
        base.alpha_composite(_get_hi_icon("spotify", 24), (mp_x0 + 8, 16))
        base.alpha_composite(_get_hi_icon("music_note", 24, is_play), (mp_x0 + 42, 16))
        # Crisp 2x smoothed active status indicator dot
        dot_4 = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        ImageDraw.Draw(dot_4).ellipse([2, 2, 30, 30], fill=(48, 209, 88, 255) if is_play else (142, 146, 155, 230), outline=(14, 16, 22, 255), width=4)
        base.alpha_composite(dot_4.resize((8, 8), Image.Resampling.LANCZOS), (mp_x0 + 26, 33))
        nav_hits.append(("media_toggle", (mp_x0, 10, mp_x1, 46)))

        # Right Liquid-Glass Pill 2: Lock + Refresh + Power (all 4x supersampled!)
        _draw_frosted_pill(base, (ap_x0, 10, ap_x1, 46), radius=18, tint=(20, 18, 30, 152), border_col=(255, 255, 255, 76))
        is_lk = self.click_through_var.get()
        is_pwr = self.master_switch_var.get()
        base.alpha_composite(_get_hi_icon("lock_closed" if is_lk else "lock_open", 18), (ap_x0 + 11, 19))
        base.alpha_composite(_get_hi_icon("refresh", 18), (ap_x0 + 36, 19))
        base.alpha_composite(_get_hi_icon("power", 18, is_pwr), (ap_x0 + 61, 19))
        nav_hits.append(("toggle_lock", (ap_x0, 10, ap_x0 + 32, 46)))
        nav_hits.append(("refresh_lyrics", (ap_x0 + 33, 10, ap_x0 + 58, 46)))
        nav_hits.append(("toggle_power", (ap_x0 + 59, 10, ap_x1, 46)))

        if IS_WIN:
            # Minimal 4x antialiased top-right window controls (— □ ×) on frameless Windows window
            base.alpha_composite(_get_hi_icon("win_min", 18), (w - 86, 19))
            base.alpha_composite(_get_hi_icon("win_max", 18), (w - 58, 19))
            base.alpha_composite(_get_hi_icon("win_close", 18), (w - 31, 19))
            nav_hits.append(("win_min", (w - 92, 6, w - 66, 42)))
            nav_hits.append(("win_max", (w - 65, 6, w - 38, 42)))
            nav_hits.append(("win_close", (w - 37, 6, w - 8, 42)))

        tk_hdr = ImageTk.PhotoImage(base)
        self._tk_photos["header"] = tk_hdr
        self.canvas.itemconfig(self.header_item, image=tk_hdr)
        self._header_hits = nav_hits

    # ---- Mouse Interaction (Hover Preview, Popover Sliders, Drag, Scroll, Clicks) ----
    def _hit_test(self, x: int, y: int):
        if self._active_popover and self._popover_rect:
            px0, py0, px1, py1 = self._popover_rect
            if px0 <= x <= px1 and py0 <= y <= py1:
                for sid, (sx0, sy0, sx1, sy1), smin, smax in self._popover_sliders:
                    if sx0 - 10 <= x <= sx1 + 10 and sy0 - 8 <= y <= sy1 + 8:
                        return f"slider:{sid}"
                for act, (ax0, ay0, ax1, ay1) in self._popover_hits:
                    if ax0 <= x <= ax1 and ay0 <= y <= ay1:
                        return act
                return "popover_bg"
        for act, (x0, y0, x1, y1) in getattr(self, "_header_hits", []):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return act
        hy = y + self._scroll_y
        for act, (x0, y0, x1, y1) in getattr(self, "_hero_hits", []):
            if x0 <= x <= x1 and y0 <= hy <= y1:
                return act
        for sname, (_i1, _i2, _i3, cx0, cy0) in self._card_items.items():
            if cx0 <= x <= cx0 + self.CARD_W and (cy0 - self._scroll_y) <= y <= (cy0 - self._scroll_y + self.CARD_H):
                return f"select:{sname}"
        if y <= 60 or (self._scroll_y == 0 and y <= 105):
            return "drag_hdr"
        return None

    def _on_mouse_move(self, evt):
        hit = self._hit_test(evt.x, evt.y)
        new_hov = hit[7:] if (hit and hit.startswith("select:") and evt.y + self._scroll_y >= self.HERO_H and not (hit and hit.startswith("pop:"))) else None
        new_nav = hit[4:] if (hit and hit.startswith("nav:")) else None
        new_pop = hit if (hit and (hit.startswith("pop:") or hit.startswith("slider:"))) else None

        if new_hov != self._hovered_style:
            old = self._hovered_style
            self._hovered_style = new_hov
            if old:
                self._render_single_card(old, t_phase=0.0)
            if new_hov:
                self._render_single_card(new_hov, t_phase=self._anim_phase)
        if new_nav != self._hovered_nav:
            self._hovered_nav = new_nav
            self._render_sticky_header()
        if new_pop != self._hovered_pop:
            self._hovered_pop = new_pop
            if self._active_popover:
                self._render_popover()

        if hit and hit.startswith("slider:"):
            self.canvas.configure(cursor="sb_h_double_arrow")
        elif hit and hit not in ("drag_hdr", "popover_bg"):
            self.canvas.configure(cursor="hand2")
        else:
            self.canvas.configure(cursor="")

    def _cursor_xy(self, evt):
        return get_cursor_pos(evt)

    def _slider_by_id(self, sid: str):
        for item in self._popover_sliders:
            if item[0] == sid:
                return item
        return None

    def _apply_slider_x(self, sid: str, mouse_x: int, save: bool = False):
        spec = self._slider_by_id(sid)
        if not spec:
            return
        _, (sx0, _sy0, sx1, _sy1), vmin, vmax = spec
        u = max(0.0, min(1.0, (mouse_x - sx0) / max(1, sx1 - sx0)))
        val = vmin + u * (vmax - vmin)
        if sid == "font_scale":
            sc = round(val * 20.0) / 20.0
            self.cfg_mgr.config["lyrics"]["font_scale"] = sc
            self.engine.lyrics_engine.set_font_scale(sc)
        elif sid == "sync_offset":
            ms = int(round(val / 25.0) * 25)
            self.cfg_mgr.config["lyrics"]["sync_offset_ms"] = ms
            self.engine.lyrics_engine.set_offset_ms(ms)
        elif sid == "glow_intensity":
            gi = round(val, 2)
            self.cfg_mgr.config["ambient"]["glow_intensity"] = gi
            self.engine.ambient_engine.set_intensity(gi)
        elif sid == "color_balance":
            bal = round(val, 2)
            self.cfg_mgr.config["ambient"]["color_balance"] = bal
            self.engine.ambient_engine.set_balance(bal)
        elif sid == "bg_depth":
            bd = round(val, 2)
            self.cfg_mgr.config["ambient"]["backdrop_darkness"] = bd
            self.engine.backdrop_engine.set_darkness(bd)
        if save:
            self.cfg_mgr.save_config()
        self._render_popover()

    def _on_mouse_click(self, evt):
        self._drag_origin = None
        self._active_slider = None
        hit = self._hit_test(evt.x, evt.y)

        if hit and hit.startswith("slider:"):
            sid = hit[7:]
            self._active_slider = sid
            self._apply_slider_x(sid, evt.x, save=False)
            return

        if hit and hit.startswith("pop:"):
            self._handle_popover_action(hit[4:])
            return

        if hit == "popover_bg":
            return

        if self._active_popover and not (hit and hit.startswith("nav:")):
            self._close_popover()

        if hit == "drag_hdr":
            try:
                if self._is_maximized:
                    self._toggle_maximize()
                    self.update_idletasks()
                cx, cy = self._cursor_xy(evt)
                if IS_WIN:
                    hwnd = self.get_native_hwnd()
                    if hwnd:
                        rect = RECT()
                        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                            self._drag_origin = (hwnd, cx - rect.left, cy - rect.top)
                else:
                    self._drag_origin = ("tk", cx - self.winfo_rootx(), cy - self.winfo_rooty())
            except Exception:
                self._drag_origin = None
            return
        if not hit:
            return
        if hit.startswith("select:"):
            self._select_style(hit[7:])
        elif hit == "step_prev":
            self._step_style(-1)
        elif hit == "step_next":
            self._step_style(1)
        elif hit == "toggle_lock":
            self._toggle_lock()
        elif hit == "toggle_pin":
            self._toggle_pin()
        elif hit == "toggle_power":
            self._toggle_master_power()
        elif hit == "refresh_lyrics":
            self.engine.lyrics_engine.force_refresh_lyrics()
        elif hit == "media_toggle":
            self.media_mon.send_play_pause()
        elif hit.startswith("nav:"):
            self._toggle_popover(hit[4:])
        elif hit == "win_min":
            self.iconify()
        elif hit == "win_max":
            self._toggle_maximize()
        elif hit == "win_close":
            self._on_close_window()

    def _toggle_maximize(self):
        self._is_maximized = not self._is_maximized
        if IS_WIN:
            self.state("zoomed" if self._is_maximized else "normal")
            return
        if self._is_maximized:
            self._saved_geom = self.geometry()
            mons = get_monitors()
            m = (mons or [{"x": 0, "y": 28, "w": 1440, "h": 872}])[0]
            self.geometry(f"{m['w']}x{max(620, m['h'] - 32)}+{m['x']}+{m['y'] + 28}")
        elif self._saved_geom:
            self.geometry(self._saved_geom)

    def _on_mouse_right_click(self, evt):
        hit = self._hit_test(evt.x, evt.y)
        if hit and hit.startswith("pop:pick_cidx:"):
            idx_c = int(hit.split(":")[-1])
            self._remove_custom_color(idx_c)
            if self._active_popover:
                self._render_popover()

    def _on_mouse_drag(self, evt):
        if self._active_slider:
            self._apply_slider_x(self._active_slider, evt.x, save=False)
            return
        if not self._drag_origin:
            return
        try:
            target_h, off_x, off_y = self._drag_origin
            cx, cy = self._cursor_xy(evt)
            if IS_WIN and isinstance(target_h, int):
                user32.SetWindowPos(target_h, 0, cx - off_x, cy - off_y, 0, 0, 0x0001 | 0x0004 | 0x0010)
            else:
                self.geometry(f"+{cx - off_x}+{cy - off_y}")
        except Exception:
            self._drag_origin = None

    def _on_mouse_release(self, _evt):
        if self._active_slider:
            self.cfg_mgr.save_config()
            self._active_slider = None
        self._drag_origin = None

    def _on_mouse_wheel(self, evt):
        delta = (-int(evt.delta * 16)) if IS_MAC else (-int(evt.delta / 3))
        nxt = max(0, min(self._max_scroll, self._scroll_y + delta))
        if nxt != self._scroll_y:
            self._scroll_y = nxt
            self._reposition_grid()
            self._render_sticky_header()
            if self._active_popover:
                self._render_popover()

    def _tick_previews(self):
        """Smoothly animates the Hero artwork and whichever style card is hovered."""
        try:
            if self.state() != "withdrawn":
                self._anim_phase += 0.14
                if self._scroll_y < self.HERO_H:
                    self._render_hero_stage()
                if self._hovered_style:
                    self._render_single_card(self._hovered_style, t_phase=self._anim_phase)
        except Exception:
            pass
        self.after(90, self._tick_previews)

    # ---- Liquid-Glass Purple Popover Settings Sheet (100% Unified PIL Glass Canvas) ----
    def _select_style(self, style_name: str):
        self.cfg_mgr.config["lyrics"]["style"] = style_name
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_style(style_name)
        self._render_hero_stage()
        self._render_all_cards()
        self._render_sticky_header()

    def _step_style(self, delta: int):
        cur = self.cfg_mgr.config["lyrics"].get("style", "Ship")
        idx = STYLE_OPTIONS.index(cur) if cur in STYLE_OPTIONS else 0
        self._select_style(STYLE_OPTIONS[(idx + delta) % len(STYLE_OPTIONS)])

    def _close_popover(self):
        self._active_popover = None
        self._active_slider = None
        self._popover_rect = None
        self._popover_hits = []
        self._popover_sliders = []
        self.canvas.itemconfig(self.popover_item, state="hidden")
        self._render_sticky_header()

    def _toggle_popover(self, key: str):
        if self._active_popover == key:
            self._close_popover()
            return
        self._active_popover = key
        self._render_sticky_header()
        self._render_popover()

    def _compose_under_rect(self, rx0: int, ry0: int, rw: int, rh: int) -> Image.Image:
        """Composites actual scrolled background beneath (rx0, ry0, rw, rh) for genuine glass blur."""
        w, _ = self._cur_size()
        cur_style = self.cfg_mgr.config["lyrics"].get("style", "Ship")
        _, _, c1, c2 = STYLE_META.get(cur_style, STYLE_META["Ship"])
        bg = Image.new("RGBA", (rw, rh), (6, 7, 11, 255))
        sy = self._scroll_y
        # Intersection with Hero stage
        hero_vis_bottom = self.HERO_H - sy
        if hero_vis_bottom > ry0:
            y_src_0 = max(0, ry0 + sy)
            y_src_1 = min(self.HERO_H, ry0 + rh + sy)
            if y_src_1 > y_src_0:
                hero_grad = _get_cached_gradient(w, self.HERO_H, c1, c2, 20, hash(cur_style) & 0xFFFF)
                slice_h = hero_grad.crop((rx0, y_src_0, rx0 + rw, y_src_1))
                bg.paste(slice_h, (0, max(0, -ry0)))
        # Subtle glow hint from top grid cards under the bottom portion of tall popovers
        for sname, (_i1, _i2, _i3, cx0, cy0) in self._card_items.items():
            cy_s = cy0 - sy
            ix0, iy0 = max(rx0, cx0), max(ry0, cy_s)
            ix1, iy1 = min(rx0 + rw, cx0 + self.CARD_W), min(ry0 + rh, cy_s + self.CARD_H)
            if ix1 > ix0 and iy1 > iy0:
                _, _, cc1, cc2 = STYLE_META[sname]
                cg = _get_cached_gradient(self.CARD_W, self.CARD_H, cc1, cc2, 12, hash(sname) & 0xFFFF, radius=14)
                crop_c = cg.crop((ix0 - cx0, iy0 - cy_s, ix1 - cx0, iy1 - cy_s))
                bg.alpha_composite(crop_c, (ix0 - rx0, iy0 - ry0))
        return bg

    def _draw_pop_toggle(self, panel: Image.Image, px: int, py: int, label: str, is_on: bool, act: str, off_x: int, off_y: int, font_lbl):
        d = ImageDraw.Draw(panel)
        d.text((px, py + 2), label, font=font_lbl, fill=(240, 238, 250, 238))
        tw = int(d.textlength(label, font=font_lbl))
        sx = px + tw + 12
        sy = py
        sw, sh = 40, 22
        sc = 2
        swg = Image.new("RGBA", (sw * sc, sh * sc), (0, 0, 0, 0))
        sd = ImageDraw.Draw(swg)
        if is_on:
            bar = _get_purple_gradient_bar(sw * sc, sh * sc)
            m = _rounded_mask(sw * sc, sh * sc, sh)
            swg.paste(bar, (0, 0), m)
            sd = ImageDraw.Draw(swg)
            sd.rounded_rectangle([0, 0, sw * sc - 1, sh * sc - 1], radius=sh, outline=(216, 180, 254, 150), width=2)
            kx = (sw - sh + 3) * sc
        else:
            sd.rounded_rectangle([0, 0, sw * sc - 1, sh * sc - 1], radius=sh, fill=(255, 255, 255, 28), outline=(255, 255, 255, 65), width=2)
            kx = 3 * sc
        kr = (sh - 6) * sc
        sd.ellipse([kx, 3 * sc, kx + kr, 3 * sc + kr], fill=(255, 255, 255, 248))
        panel.alpha_composite(swg.resize((sw, sh), Image.Resampling.LANCZOS), (sx, sy))
        self._popover_hits.append((f"pop:{act}", (off_x + px - 4, off_y + sy - 4, off_x + sx + sw + 6, off_y + sy + sh + 4)))
        return sx + sw

    def _draw_pop_slider(self, panel: Image.Image, x0: int, y0: int, sw: int, label: str, val_text: str, norm: float, sid: str, vmin: float, vmax: float, off_x: int, off_y: int, font_lbl, font_val, reset_act: str = None):
        d = ImageDraw.Draw(panel)
        d.text((x0, y0), label, font=font_lbl, fill=(235, 232, 248, 225))
        # Purple pill readout badge on right (clicking can reset if reset_act supplied)
        vw = int(d.textlength(val_text, font=font_val)) + 18
        vx0 = x0 + sw - vw
        vy0 = y0 - 2
        vm = _rounded_mask(vw, 20, 10)
        panel.paste(Image.new("RGBA", (vw, 20), (147, 51, 234, 65)), (vx0, vy0), vm)
        panel.alpha_composite(_rounded_outline_overlay(vw, 20, 10, (192, 132, 252, 115)), (vx0, vy0))
        d = ImageDraw.Draw(panel)
        d.text((vx0 + 9, vy0 + 3), val_text, font=font_val, fill=(233, 213, 255, 248))
        if reset_act:
            self._popover_hits.append((f"pop:{reset_act}", (off_x + vx0, off_y + vy0, off_x + vx0 + vw, off_y + vy0 + 20)))

        # 2x LANCZOS smooth rounded purple track + soft glow + circular thumb
        ty = y0 + 24
        tr_h = 8
        sc = 2
        tr = Image.new("RGBA", (sw * sc, 24 * sc), (0, 0, 0, 0))
        td = ImageDraw.Draw(tr)
        mid_y = 12 * sc
        gy0, gy1 = mid_y - (tr_h * sc) // 2, mid_y + (tr_h * sc) // 2
        td.rounded_rectangle([0, gy0, sw * sc - 1, gy1], radius=(tr_h * sc) // 2, fill=(255, 255, 255, 32))
        u = max(0.0, min(1.0, float(norm)))
        fill_w = max(tr_h * sc, int(sw * sc * u))
        if u > 0.005:
            pgrad = _get_purple_gradient_bar(fill_w, tr_h * sc)
            fm = _rounded_mask(fill_w, tr_h * sc, (tr_h * sc) // 2)
            tr.paste(pgrad, (0, gy0), fm)
        # Soft purple thumb halo + smooth white knob
        kx = int(max(9 * sc, min(sw * sc - 9 * sc, sw * sc * u)))
        td.ellipse([kx - 11 * sc, mid_y - 11 * sc, kx + 11 * sc, mid_y + 11 * sc], fill=(168, 85, 247, 82))
        td.ellipse([kx - 7 * sc, mid_y - 7 * sc, kx + 7 * sc, mid_y + 7 * sc], fill=(255, 255, 255, 252), outline=(192, 132, 252, 235), width=2 * sc)
        panel.alpha_composite(tr.resize((sw, 24), Image.Resampling.LANCZOS), (x0, ty - 8))
        self._popover_sliders.append((sid, (off_x + x0, off_y + ty - 6, off_x + x0 + sw, off_y + ty + 14), vmin, vmax))

    def _draw_pop_chips(self, panel: Image.Image, x0: int, y0: int, max_w: int, options: list, cur_val: str, prefix: str, off_x: int, off_y: int, font_chip, labels_map: dict = None) -> int:
        d = ImageDraw.Draw(panel)
        cx, cy = x0, y0
        ch = 26
        gap_x, gap_y = 8, 8
        for val in options:
            disp = (labels_map.get(val, val) if labels_map else val)
            tw = int(d.textlength(disp, font=font_chip))
            cw = tw + 22
            if cx + cw > x0 + max_w and cx > x0:
                cx = x0
                cy += ch + gap_y
            act_full = f"pop:{prefix}:{val}"
            is_sel = (str(val) == str(cur_val))
            is_hov = (self._hovered_pop == act_full)
            cm = _rounded_mask(cw, ch, 13)
            if is_sel:
                bg_bar = _get_purple_gradient_bar(cw, ch)
                panel.paste(bg_bar, (cx, cy), cm)
                panel.alpha_composite(_rounded_outline_overlay(cw, ch, 13, (233, 213, 255, 195)), (cx, cy))
                tcol = (255, 255, 255, 255)
            else:
                fill_c = (147, 51, 234, 54) if is_hov else (255, 255, 255, 20)
                panel.paste(Image.new("RGBA", (cw, ch), fill_c), (cx, cy), cm)
                rim_c = (192, 132, 252, 130) if is_hov else (255, 255, 255, 48)
                panel.alpha_composite(_rounded_outline_overlay(cw, ch, 13, rim_c), (cx, cy))
                tcol = (240, 236, 252, 235 if is_hov else 205)
            d = ImageDraw.Draw(panel)
            d.text((cx + 11, cy + 5), disp, font=font_chip, fill=tcol)
            self._popover_hits.append((act_full, (off_x + cx, off_y + cy, off_x + cx + cw, off_y + cy + ch)))
            cx += cw + gap_x
        return cy + ch

    def _render_popover(self):
        key = self._active_popover
        if not key:
            return
        self._popover_hits = []
        self._popover_sliders = []

        w, _ = self._cur_size()
        cfg = self.cfg_mgr.config
        amb = cfg["ambient"]
        lyr = cfg["lyrics"]
        sys_cfg = cfg["system"]

        colors_list = list(amb.get("custom_colors") or [amb.get("color_1", "#6366F1"), amb.get("color_2", "#EC4899")])
        pop_w = 604 if key == "Glow" else 584
        extra_col_rows = max(0, (len(colors_list) + 2) // 13) if key == "Glow" else 0
        pop_h = {"Lyrics": 412, "Glow": 442 + extra_col_rows * 30, "Screen": 258, "Options": 484}.get(key, 340)
        px0 = max(18, (w - pop_w) // 2)
        py0 = 56
        self._popover_rect = (px0, py0, px0 + pop_w, py0 + pop_h)

        # True blurred refraction matching Picture 1 Liquid Glass
        under = self._compose_under_rect(px0, py0, pop_w, pop_h).filter(ImageFilter.GaussianBlur(22))
        glass = Image.new("RGBA", (pop_w, pop_h), (16, 13, 27, 200))
        panel_full = Image.alpha_composite(under, glass)
        # Smooth seamless top violet specular wash (zero horizontal cutoff line!)
        sheen = Image.new("RGBA", (pop_w, 84), (0, 0, 0, 0))
        sd_sh = ImageDraw.Draw(sheen)
        for sy_i in range(84):
            a_s = int(22 * ((1.0 - sy_i / 83.0) ** 1.6))
            sd_sh.line([(0, sy_i), (pop_w, sy_i)], fill=(168, 85, 247, a_s))
        panel_full.alpha_composite(sheen, (0, 0))
        # Mask outer shape with 2x antialiased 22px rounded corners
        panel = Image.new("RGBA", (pop_w, pop_h), (0, 0, 0, 0))
        panel.paste(panel_full, (0, 0), _rounded_mask(pop_w, pop_h, 22))
        panel.alpha_composite(_rounded_outline_overlay(pop_w, pop_h, 22, (192, 132, 252, 118), width=1), (0, 0))

        d = ImageDraw.Draw(panel)
        f_title = _load_font("segoeuib.ttf", 15)
        f_sec = _load_font("segoeuib.ttf", 11)
        f_lbl = _load_font("segoeui.ttf", 12)
        f_val = _load_font("segoeuib.ttf", 11)
        f_chip = _load_font("segoeui.ttf", 11)

        pad = 22
        inner_w = pop_w - pad * 2
        titles = {
            "Lyrics": "Lyrics Settings",
            "Glow": "Edge Glow Settings",
            "Screen": "Screen & Backdrop",
            "Options": "Keybinds & General Options",
        }
        d.text((pad, 16), titles.get(key, key), font=f_title, fill=(248, 246, 255, 250))
        cx_btn = pop_w - pad - 26
        cm_x = _rounded_mask(26, 26, 13)
        panel.paste(Image.new("RGBA", (26, 26), (255, 255, 255, 26)), (cx_btn, 14), cm_x)
        panel.alpha_composite(_get_hi_icon("win_close", 14, (235, 230, 250, 235)), (cx_btn + 6, 20))
        self._popover_hits.append(("pop:close", (px0 + cx_btn, py0 + 14, px0 + cx_btn + 26, py0 + 40)))
        d = ImageDraw.Draw(panel)
        d.line([(pad, 48), (pop_w - pad, 48)], fill=(216, 180, 254, 42), width=1)

        y = 60

        if key == "Lyrics":
            nx = self._draw_pop_toggle(panel, pad, y, "Enable Lyrics", self.verci_switch_var.get(), "toggle_lyrics", px0, py0, f_lbl)
            nx = self._draw_pop_toggle(panel, nx + 24, y, "Lock Click-Through", self.click_through_var.get(), "toggle_lock", px0, py0, f_lbl)
            self._draw_pop_toggle(panel, nx + 24, y, "Album Colors", self.auto_sync_var.get(), "toggle_lyr_sync", px0, py0, f_lbl)
            y += 38

            sc = float(lyr.get("font_scale", 1.0))
            norm_sc = (max(0.6, min(2.8, sc)) - 0.6) / 2.2
            self._draw_pop_slider(panel, pad, y, inner_w, "Lyric Size (click badge to reset)", f"{int(round(sc * 100))}%", norm_sc, "font_scale", 0.6, 2.8, px0, py0, f_lbl, f_val, reset_act="reset_scale")
            y += 50

            off_ms = int(lyr.get("sync_offset_ms", 0))
            norm_off = (max(-2000, min(2000, off_ms)) + 2000) / 4000.0
            self._draw_pop_slider(panel, pad, y, inner_w, "Sync Timing Offset (click badge to reset)", f"{off_ms:+d} ms" if off_ms else "0 ms", norm_off, "sync_offset", -2000.0, 2000.0, px0, py0, f_lbl, f_val, reset_act="reset_offset")
            y += 50

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "FONT FAMILY", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            fonts = ["Geometric", "Futura", "Didone", "Grotesque", "Rounded", "Serif"]
            y = self._draw_pop_chips(panel, pad, y, inner_w, fonts, lyr.get("font", "Geometric"), "font", px0, py0, f_chip) + 12

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "LYRICS SCRIPT  (HINDI / MALAYALAM / TAMIL)", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            script_map = {
                "Auto": "Auto (Best Match)",
                "Native": "Native Script",
                "Romanized": "Romanized (ABC)",
            }
            y = self._draw_pop_chips(panel, pad, y, inner_w, ["Auto", "Native", "Romanized"], lyr.get("script_mode", "Auto"), "script", px0, py0, f_chip, labels_map=script_map) + 12

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "MEDIA SOURCE", font=f_sec, fill=(192, 132, 252, 220))
            d.text((pad + 340, y), "STAGE ACTIONS", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            self._draw_pop_chips(panel, pad, y, 332, ["Music Apps First", "Music Apps Only", "All Media"], lyr.get("player_preference", "Music Apps First"), "lyr_act", px0, py0, f_chip)
            self._draw_pop_chips(panel, pad + 340, y, inner_w - 340, ["Reset Stage Pos", "Refresh Lyrics"], "", "lyr_act", px0, py0, f_chip)

        elif key == "Glow":
            nx = self._draw_pop_toggle(panel, pad, y, "Enable Glow", self.lumn_switch_var.get(), "toggle_glow", px0, py0, f_lbl)
            nx = self._draw_pop_toggle(panel, nx + 24, y, "Beat Sync", self.audio_react_var.get(), "toggle_beat", px0, py0, f_lbl)
            self._draw_pop_toggle(panel, nx + 24, y, "Custom Colors", self.override_var.get(), "toggle_override", px0, py0, f_lbl)
            y += 36

            gi = float(amb.get("glow_intensity", 1.35))
            self._draw_pop_slider(panel, pad, y, inner_w, "Edge Glow Intensity", f"{int(round(gi * 100))}%", max(0.0, min(1.0, gi / 3.0)), "glow_intensity", 0.0, 3.0, px0, py0, f_lbl, f_val)
            y += 46

            bal = float(amb.get("color_balance", 0.5))
            self._draw_pop_slider(panel, pad, y, inner_w, "Color Balance", f"{int(round(bal * 100))}%", (max(0.15, min(0.85, bal)) - 0.15) / 0.70, "color_balance", 0.15, 0.85, px0, py0, f_lbl, f_val)
            y += 46

            # Dynamic Multi-Color Palette Row (add unlimited colors, edit on click, remove via - / right-click)
            d = ImageDraw.Draw(panel)
            d.text((pad, y), f"CUSTOM PALETTE ({len(colors_list)} COLORS • CLICK TO EDIT, RIGHT-CLICK TO REMOVE)", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            sx, sy = pad, y
            sw_w, sw_h = 28, 22
            for ci, hx_col in enumerate(colors_list):
                if sx + sw_w > pad + inner_w - 130:
                    sx = pad
                    sy += 28
                s_clean = (hx_col or "#A855F7").lstrip("#")
                rgb = tuple(int(s_clean[k:k + 2], 16) for k in (0, 2, 4)) if len(s_clean) == 6 else (168, 85, 247)
                cm_s = _rounded_mask(sw_w, sw_h, 11)
                panel.paste(Image.new("RGBA", (sw_w, sw_h), (*rgb, 255)), (sx, sy), cm_s)
                panel.alpha_composite(_rounded_outline_overlay(sw_w, sw_h, 11, (255, 255, 255, 195)), (sx, sy))
                self._popover_hits.append((f"pop:pick_cidx:{ci}", (px0 + sx, py0 + sy, px0 + sx + sw_w, py0 + sy + sw_h)))
                sx += sw_w + 6
            # "+ Add" and "- Remove" frosted action pills inline after swatches
            act_pills = ["+ Add Color"] + (["- Remove"] if len(colors_list) > 2 else [])
            for ap in act_pills:
                d = ImageDraw.Draw(panel)
                ap_w = int(d.textlength(ap, font=f_chip)) + 18
                if sx + ap_w > pad + inner_w:
                    sx = pad
                    sy += 28
                am = _rounded_mask(ap_w, 22, 11)
                is_add = ap.startswith("+")
                fill_a = (147, 51, 234, 105) if is_add else (255, 255, 255, 22)
                rim_a = (216, 180, 254, 155) if is_add else (255, 255, 255, 58)
                panel.paste(Image.new("RGBA", (ap_w, 22), fill_a), (sx, sy), am)
                panel.alpha_composite(_rounded_outline_overlay(ap_w, 22, 11, rim_a), (sx, sy))
                d = ImageDraw.Draw(panel)
                d.text((sx + 9, sy + 3), ap, font=f_chip, fill=(248, 245, 255, 245))
                act_name = "add_color" if is_add else "rem_last_color"
                self._popover_hits.append((f"pop:{act_name}", (px0 + sx, py0 + sy, px0 + sx + ap_w, py0 + sy + 22)))
                sx += ap_w + 6
            y = sy + 32

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "THICKNESS  &  GRADIENT", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            thk_map = {"subtle": "Subtle", "normal": "Normal", "thick": "Thick", "immersive": "Immersive"}
            y_end_t = self._draw_pop_chips(panel, pad, y, 326, ["subtle", "normal", "thick", "immersive"], str(amb.get("thickness", "normal")).lower(), "thickness", px0, py0, f_chip, labels_map=thk_map)
            cur_grad = "Multi Colors" if amb.get("gradient_mode", "Multi Colors") in ("2 Colors", "Multi Colors") else "1 Color"
            self._draw_pop_chips(panel, pad + 342, y, inner_w - 342, ["Multi Colors", "1 Color"], cur_grad, "grad", px0, py0, f_chip)
            y = y_end_t + 12

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "ANIMATION MODE", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            y = self._draw_pop_chips(panel, pad, y, inner_w, ["Water Drop", "Liquid Flow", "Beat Pulse", "Breathing", "Static"], amb.get("animation_mode", "Water Drop"), "anim", px0, py0, f_chip) + 12

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "TARGET DISPLAY", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            mons = ["All Displays", "Primary Display"] + [m["device"] for m in get_monitors()]
            self._draw_pop_chips(panel, pad, y, inner_w, mons, amb.get("target_displays", "All Displays"), "display", px0, py0, f_chip)

        elif key == "Screen":
            d = ImageDraw.Draw(panel)
            d.text((pad, y), "ALBUM COVER BACKDROP MODE", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            nx_b = self._draw_pop_chips(panel, pad, y, inner_w, ["Desktop Layer", "Cinema Stage", "Off"], amb.get("album_backdrop", "Desktop Layer"), "bd_mode", px0, py0, f_chip)
            y = nx_b + 14

            bd_d = float(amb.get("backdrop_darkness", 0.34))
            self._draw_pop_slider(panel, pad, y, inner_w, "Background Depth", f"{int(round(bd_d * 100))}%", (max(0.15, min(1.0, bd_d)) - 0.15) / 0.85, "bg_depth", 0.15, 1.0, px0, py0, f_lbl, f_val)
            y += 50

            self._draw_pop_toggle(panel, pad, y, "Show Over Fullscreen Windows", self.fs_var.get(), "toggle_fs", px0, py0, f_lbl)
            y += 36

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "DISPLAY OUTPUT", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            mons = ["All Displays", "Primary Display"] + [m["device"] for m in get_monitors()]
            self._draw_pop_chips(panel, pad, y, inner_w, mons, amb.get("target_displays", "All Displays"), "display", px0, py0, f_chip)

        elif key == "Options":
            d = ImageDraw.Draw(panel)
            d.text((pad, y), "GLOBAL KEYBINDS", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            binds = [
                ("Ctrl + Shift + L", "Toggle Edge Glow"),
                ("Ctrl + Shift + V", "Toggle Lyrics"),
                ("Ctrl + Shift + B", "Cycle Backdrop"),
                ("Ctrl + Shift + U", "Show Hub"),
            ]
            col_w = (inner_w - 14) // 2
            for bi, (hk, desc_hk) in enumerate(binds):
                rx = pad + (bi % 2) * (col_w + 14)
                ry = y + (bi // 2) * 34
                km = _rounded_mask(col_w, 28, 10)
                panel.paste(Image.new("RGBA", (col_w, 28), (255, 255, 255, 16)), (rx, ry), km)
                panel.alpha_composite(_rounded_outline_overlay(col_w, 28, 10, (192, 132, 252, 72)), (rx, ry))
                km_k = _rounded_mask(108, 20, 7)
                panel.paste(Image.new("RGBA", (108, 20), (147, 51, 234, 88)), (rx + 6, ry + 4), km_k)
                d = ImageDraw.Draw(panel)
                d.text((rx + 12, ry + 7), hk, font=f_val, fill=(243, 232, 255, 250))
                d.text((rx + 122, ry + 7), desc_hk, font=f_chip, fill=(220, 222, 236, 220))
            y += 78

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "GENERAL SETTINGS", font=f_sec, fill=(192, 132, 252, 220))
            y += 20
            nx = self._draw_pop_toggle(panel, pad, y, "Master Power", self.master_switch_var.get(), "toggle_master", px0, py0, f_lbl)
            nx = self._draw_pop_toggle(panel, nx + 20, y, "Minimize to Tray", self.tray_var.get(), "toggle_tray", px0, py0, f_lbl)
            startup_lbl = "Launch at Login" if IS_MAC else "Start with Windows"
            self._draw_pop_toggle(panel, nx + 20, y, startup_lbl, self.startup_var.get(), "toggle_startup", px0, py0, f_lbl)
            y += 38

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "STUDIO PRESETS  &  UTILITIES", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            cur_pr = cfg.get("active_preset", "studio")
            pr_map = {"studio": "Studio", "ambient_only": "Glow Only", "karaoke": "Karaoke", "night_mode": "Night Dim"}
            y = self._draw_pop_chips(panel, pad, y, inner_w, ["studio", "ambient_only", "karaoke", "night_mode"], cur_pr, "preset", px0, py0, f_chip, labels_map=pr_map) + 10
            y = self._draw_pop_chips(panel, pad, y, inner_w, ["Restart Engines", "Refresh Lyrics", "Reset Lyrics Pos"], "", "util", px0, py0, f_chip) + 14

            d = ImageDraw.Draw(panel)
            d.text((pad, y), "IPAD & MOBILE COMPANION  (OPEN IN SAFARI / CHROME ON SAME WI-FI)", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            srv = getattr(self.engine, "mobile_server", None)
            mob_url = srv.get_url() if srv else "http://localhost:8765"
            url_w = inner_w - 150
            um = _rounded_mask(url_w, 28, 10)
            panel.paste(Image.new("RGBA", (url_w, 28), (255, 255, 255, 16)), (pad, y), um)
            panel.alpha_composite(_rounded_outline_overlay(url_w, 28, 10, (192, 132, 252, 85)), (pad, y))
            d = ImageDraw.Draw(panel)
            d.text((pad + 12, y + 7), mob_url, font=f_val, fill=(243, 232, 255, 250))
            y = self._draw_pop_chips(panel, pad + url_w + 10, y + 1, 140, ["Copy URL", "Open"], "", "mob", px0, py0, f_chip) + 12

            from core.version import APP_VERSION
            upd = getattr(self, "_pending_update", None)
            upd_lbl = f"Update to {upd['version']}" if (upd and upd.get("available")) else "Check Updates"
            d = ImageDraw.Draw(panel)
            d.text((pad, y), f"SOULSLIGHTS v{APP_VERSION}  •  AUTO-UPDATER", font=f_sec, fill=(192, 132, 252, 220))
            y += 18
            self._draw_pop_chips(panel, pad, y, inner_w, [upd_lbl], "", "upd", px0, py0, f_chip)

        tk_pop = ImageTk.PhotoImage(panel)
        self._tk_photos["popover"] = tk_pop
        self.canvas.coords(self.popover_item, px0, py0)
        self.canvas.itemconfig(self.popover_item, image=tk_pop, state="normal")
        self.canvas.tag_raise(self.popover_item)

    def _handle_popover_action(self, act: str):
        if act == "close":
            self._close_popover()
            return
        if act == "toggle_lyrics":
            self.verci_switch_var.set(not self.verci_switch_var.get())
            self._on_verci_toggle()
        elif act == "toggle_lock":
            self._toggle_lock()
        elif act == "toggle_lyr_sync":
            self.auto_sync_var.set(not self.auto_sync_var.get())
            self._on_auto_sync_toggle()
        elif act == "reset_scale":
            self._on_font_scale_change(1.0)
        elif act == "reset_offset":
            self._nudge_offset(0, reset=True)
        elif act.startswith("font:"):
            self._on_font_change(act[5:])
        elif act.startswith("script:"):
            self._on_script_mode_change(act[7:])
        elif act.startswith("lyr_act:"):
            sub = act[8:]
            if sub == "Reset Stage Pos":
                self.engine.lyrics_engine.reset_position()
            elif sub == "Refresh Lyrics":
                self.engine.lyrics_engine.force_refresh_lyrics()
            else:
                self._on_player_pref_change(sub)
        elif act == "toggle_glow":
            self.lumn_switch_var.set(not self.lumn_switch_var.get())
            self._on_lumn_toggle()
        elif act == "toggle_beat":
            self.audio_react_var.set(not self.audio_react_var.get())
            self._on_audio_react_toggle()
        elif act == "toggle_override":
            self.override_var.set(not self.override_var.get())
            self._on_override_toggle()
        elif act.startswith("pick_cidx:"):
            self._pick_custom_color_idx(int(act[10:]))
        elif act == "add_color":
            self._add_custom_color()
        elif act == "rem_last_color":
            self._remove_custom_color(-1)
        elif act == "pick_c1":
            self._pick_custom_color_idx(0)
        elif act == "pick_c2":
            self._pick_custom_color_idx(1)
        elif act.startswith("thickness:"):
            self._on_thickness_change(act[10:])
        elif act.startswith("grad:"):
            self._on_gradient_mode_change(act[5:])
        elif act.startswith("anim:"):
            self._on_anim_change(act[5:])
        elif act.startswith("display:"):
            self._on_display_change(act[8:])
        elif act.startswith("bd_mode:"):
            self._on_backdrop_mode_change(act[8:])
        elif act == "toggle_fs":
            self.fs_var.set(not self.fs_var.get())
            self._on_fs_toggle()
        elif act == "toggle_master":
            self._toggle_master_power()
        elif act == "toggle_tray":
            val = not self.tray_var.get()
            self.tray_var.set(val)
            self.cfg_mgr.config["system"]["minimize_to_tray"] = val
            self.cfg_mgr.save_config()
        elif act == "toggle_startup":
            self._on_startup_toggle()
        elif act.startswith("preset:"):
            self._apply_preset_key(act[7:])
        elif act.startswith("util:"):
            u = act[5:]
            if u == "Restart Engines":
                self.engine.restart_all()
            elif u == "Refresh Lyrics":
                self.engine.lyrics_engine.force_refresh_lyrics()
            elif u == "Reset Lyrics Pos":
                self.engine.lyrics_engine.reset_position()
        elif act.startswith("mob:"):
            m_act = act[4:]
            srv = getattr(self.engine, "mobile_server", None)
            mob_url = srv.get_url() if srv else "http://localhost:8765"
            if m_act == "Copy URL":
                try:
                    self.clipboard_clear()
                    self.clipboard_append(mob_url)
                except Exception:
                    pass
            elif m_act == "Open":
                try:
                    import webbrowser
                    webbrowser.open(mob_url)
                except Exception:
                    pass
        elif act.startswith("upd:"):
            self._trigger_manual_update()

        if self._active_popover:
            self._render_popover()
        self._render_sticky_header()
        self._render_hero_stage()

    # ---- Status & Handlers ----
    def set_update_info(self, info: dict):
        self._pending_update = info
        if self._active_popover == "Options":
            self._render_popover()

    def _trigger_manual_update(self):
        from tkinter import messagebox
        from core.updater import AutoUpdater
        upd = AutoUpdater()
        info = getattr(self, "_pending_update", None)
        if not info or not info.get("available"):
            info = upd.check_for_update()
        if not info.get("available"):
            messagebox.showinfo("SoulsLights Up to Date", "You are already running the latest version of SoulsLights.")
            return
        self._pending_update = info
        if self._active_popover == "Options":
            self._render_popover()
        if messagebox.askyesno(
            "Update Available",
            f"SoulsLights {info['version']} is available!\n\nDownload and restart automatically now?"
        ):
            ok, msg = upd.download_and_apply_update(info.get("url", ""))
            if ok:
                self._on_quit() if hasattr(self, "_on_quit") else self.destroy()
            else:
                import webbrowser
                webbrowser.open(info.get("html_url", "https://github.com/s0u1ls/SoulsLights/releases/latest"))

    def _sync_ui_from_config(self):
        cfg = self.cfg_mgr.config
        self.master_switch_var.set(cfg.get("master_enabled", True))
        self.lumn_switch_var.set(cfg.get("ambient_enabled", True))
        self.verci_switch_var.set(cfg.get("lyrics_enabled", True))
        self.style_var.set(cfg["lyrics"].get("style", "Fisheye Visual"))
        self.auto_sync_var.set(cfg["lyrics"].get("auto_sync_colors", True))
        if self._active_popover:
            self._render_popover()
        self._render_sticky_header()
        self._render_hero_stage()

    def _on_media_update(self, info):
        colors = tuple(info.get("colors", ["#D4E2EE", "#6B7280"]))
        if colors != self._last_pushed_colors:
            self._last_pushed_colors = colors
        self.engine.apply_media_state(info)
        self.enqueue_ui(self._render_media_update, info)

    def _render_media_update(self, info):
        self.current_media = info
        self._render_sticky_header()

    def _periodic_status_check(self):
        l_status = self.engine.get_lyrics_status()
        amb_on = self.engine.is_ambient_active()
        lyr_on = self.engine.is_lyrics_active()
        self.canvas.itemconfig(
            self.status_txt_item,
            text=f"Edge Light: {'On' if amb_on else 'Off'}  •  Lyrics: {l_status if lyr_on else 'Off'}"
        )
        self.after(1000, self._periodic_status_check)

    def _toggle_lock(self):
        val = not self.click_through_var.get()
        self.click_through_var.set(val)
        self.cfg_mgr.config["lyrics"]["click_through"] = val
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_click_through(val)
        self._render_hero_stage()
        self._render_sticky_header()

    def _toggle_pin(self):
        self._pinned_top = not self._pinned_top
        try:
            self.attributes("-topmost", self._pinned_top)
        except Exception:
            pass
        self._render_hero_stage()

    def _on_verci_toggle(self):
        val = self.verci_switch_var.get()
        self.cfg_mgr.config["lyrics_enabled"] = val
        self.cfg_mgr.save_config()
        if val and self.master_switch_var.get():
            self.engine.start_lyrics()
        else:
            self.engine.stop_lyrics()

    def _toggle_master_power(self):
        val = not self.master_switch_var.get()
        self.master_switch_var.set(val)
        self._on_master_toggle()

    def _on_master_toggle(self):
        val = bool(self.master_switch_var.get())
        self.cfg_mgr.config["master_enabled"] = val
        self.cfg_mgr.save_config()
        self.engine.sync_state(val, self.lumn_switch_var.get(), self.verci_switch_var.get())
        self._render_sticky_header()

    def _on_click_through_toggle(self):
        val = bool(self.click_through_var.get())
        self.cfg_mgr.config["lyrics"]["click_through"] = val
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_click_through(val)
        self._render_hero_stage()
        self._render_sticky_header()

    def _cycle_backdrop_mode(self):
        modes = ["Desktop Layer", "Cinema Stage", "Off"]
        cur = self.cfg_mgr.config["ambient"].get("album_backdrop", "Desktop Layer")
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "Desktop Layer"
        self._on_backdrop_mode_change(nxt)

    def _apply_preset_key(self, key: str):
        self.cfg_mgr.apply_preset(key)
        cfg = self.cfg_mgr.config
        st = cfg["lyrics"].get("style", "Ship")
        if st not in STYLE_META:
            st = "Native Design" if st == "Apple Design" else "Ship"
            cfg["lyrics"]["style"] = st
        self.master_switch_var.set(cfg.get("master_enabled", True))
        self.lumn_switch_var.set(cfg.get("ambient_enabled", True))
        self.verci_switch_var.set(cfg.get("lyrics_enabled", True))
        self.engine.lyrics_engine.set_style(st)
        self.engine.sync_state(cfg.get("master_enabled", True), cfg.get("ambient_enabled", True), cfg.get("lyrics_enabled", True))
        self._render_hero_stage()
        self._render_all_cards()
        self._render_sticky_header()

    def _on_lumn_toggle(self):
        val = self.lumn_switch_var.get()
        self.cfg_mgr.config["ambient_enabled"] = val
        self.cfg_mgr.save_config()
        if val and self.master_switch_var.get():
            self.engine.start_ambient()
        else:
            self.engine.stop_ambient()

    def _on_lumn_intensity_change(self, val):
        self.cfg_mgr.config["ambient"]["glow_intensity"] = round(float(val), 2)
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_intensity(val)

    def _on_thickness_change(self, val: str):
        self.cfg_mgr.config["ambient"]["thickness"] = val.lower()
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_thickness(val)

    def _on_gradient_mode_change(self, val: str):
        self.cfg_mgr.config["ambient"]["gradient_mode"] = val
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_gradient_mode(val)

    def _on_anim_change(self, val):
        self.cfg_mgr.config["ambient"]["animation_mode"] = val
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_animation_mode(val)

    def _on_backdrop_mode_change(self, val):
        self.cfg_mgr.config["ambient"]["album_backdrop"] = val
        self.cfg_mgr.save_config()
        self.engine.backdrop_engine.set_mode(val)
        if val == "Off":
            self.engine.stop_backdrop()
        elif self.master_switch_var.get():
            self.engine.start_backdrop()

    def _on_backdrop_darkness_change(self, val):
        d = round(float(val), 2)
        self.cfg_mgr.config["ambient"]["backdrop_darkness"] = d
        self.cfg_mgr.save_config()
        self.engine.backdrop_engine.set_darkness(d)

    def _on_override_toggle(self):
        val = self.override_var.get()
        self.cfg_mgr.config["ambient"]["override_album_color"] = val
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_override_album(val)

    def _sync_custom_palette(self, colors_list):
        clean = [c.upper() for c in colors_list if c]
        if not clean:
            clean = ["#6366F1", "#EC4899"]
        amb = self.cfg_mgr.config["ambient"]
        amb["custom_colors"] = clean
        amb["color_1"] = clean[0]
        amb["color_2"] = clean[1] if len(clean) > 1 else clean[0]
        amb["override_album_color"] = True
        self.override_var.set(True)
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_custom_palette(clean)
        self.engine.ambient_engine.set_override_album(True)

    def _add_custom_color(self):
        colors_list = list(self.cfg_mgr.config["ambient"].get("custom_colors") or [self.cfg_mgr.config["ambient"]["color_1"], self.cfg_mgr.config["ambient"]["color_2"]])
        seed = colors_list[-1] if colors_list else "#A855F7"
        chosen = colorchooser.askcolor(color=seed, title=f"Add Glow Color #{len(colors_list) + 1}")
        if chosen and chosen[1]:
            colors_list.append(chosen[1].upper())
            self._sync_custom_palette(colors_list)

    def _pick_custom_color_idx(self, idx_c: int):
        colors_list = list(self.cfg_mgr.config["ambient"].get("custom_colors") or [self.cfg_mgr.config["ambient"]["color_1"], self.cfg_mgr.config["ambient"]["color_2"]])
        while len(colors_list) <= idx_c:
            colors_list.append("#A855F7")
        chosen = colorchooser.askcolor(color=colors_list[idx_c], title=f"Choose Glow Color #{idx_c + 1}")
        if chosen and chosen[1]:
            colors_list[idx_c] = chosen[1].upper()
            self._sync_custom_palette(colors_list)

    def _remove_custom_color(self, idx_c: int):
        colors_list = list(self.cfg_mgr.config["ambient"].get("custom_colors") or [self.cfg_mgr.config["ambient"]["color_1"], self.cfg_mgr.config["ambient"]["color_2"]])
        if len(colors_list) <= 2:
            return
        if idx_c < 0 or idx_c >= len(colors_list):
            colors_list.pop()
        else:
            colors_list.pop(idx_c)
        self._sync_custom_palette(colors_list)

    def _pick_ambient_color(self, slot):
        self._pick_custom_color_idx(max(0, int(slot) - 1))

    def _on_display_change(self, val):
        self.cfg_mgr.config["ambient"]["target_displays"] = val
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_target_displays(val)
        self.engine.backdrop_engine.set_target_displays(val)

    def _on_audio_react_toggle(self):
        val = self.audio_react_var.get()
        self.cfg_mgr.config["ambient"]["audio_reactive"] = val
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_audio_reactive(val)
        self.engine.backdrop_engine.set_audio_reactive(val)

    def _on_fs_toggle(self):
        val = self.fs_var.get()
        self.cfg_mgr.config["ambient"]["show_over_fullscreen"] = val
        self.cfg_mgr.save_config()
        self.engine.ambient_engine.set_show_over_fullscreen(val)
        self.engine.backdrop_engine.set_show_over_fullscreen(val)

    def _on_startup_toggle(self):
        val = not self.startup_var.get()
        self.startup_var.set(val)
        exe_p = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py"))
        self.cfg_mgr.set_startup_registry(val, exe_p)

    def _on_auto_sync_toggle(self):
        val = self.auto_sync_var.get()
        self.cfg_mgr.config["lyrics"]["auto_sync_colors"] = val
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_auto_sync_colors(val)

    def _on_font_change(self, val):
        self.cfg_mgr.config["lyrics"]["font"] = val
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_font(val)

    def _on_script_mode_change(self, val):
        self.cfg_mgr.config["lyrics"]["script_mode"] = val
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_script_mode(val)

    def _on_font_scale_change(self, val):
        sc = round(float(val), 2)
        self.cfg_mgr.config["lyrics"]["font_scale"] = sc
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_font_scale(sc)

    def _nudge_offset(self, delta, reset=False):
        new_val = 0 if reset else (self.cfg_mgr.config["lyrics"].get("sync_offset_ms", 0) + delta)
        new_val = max(-5000, min(5000, int(new_val)))
        self.cfg_mgr.config["lyrics"]["sync_offset_ms"] = new_val
        self.cfg_mgr.save_config()
        self.engine.lyrics_engine.set_offset_ms(new_val)

    def _on_player_pref_change(self, val):
        self.cfg_mgr.config["lyrics"]["player_preference"] = val
        self.cfg_mgr.save_config()
        self.media_mon.set_player_preference(val)

    def _on_close_window(self):
        if self.cfg_mgr.config["system"].get("minimize_to_tray", True):
            self.withdraw()
        else:
            self.quit_app()

    def quit_app(self):
        if self.on_quit_callback:
            self.on_quit_callback()
        else:
            self.destroy()

    def get_native_hwnd(self) -> int:
        if not IS_WIN:
            try:
                return int(self.winfo_id())
            except Exception:
                return 0
        try:
            self.update_idletasks()
            return int(user32.GetParent(self.winfo_id()) or self.winfo_id())
        except Exception:
            return 0

    def show_window(self):
        try:
            self.deiconify()
            if IS_WIN:
                self.state("normal")
            self.update_idletasks()
            self.lift()
            self.focus_force()
            if IS_MAC:
                try:
                    import AppKit
                    AppKit.NSRunningApplication.currentApplication().activateWithOptions_(2)
                except Exception:
                    pass
            self.attributes("-topmost", True)
            self.after(150, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
