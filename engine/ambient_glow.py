import os
import sys
import threading
import time
import math
import colorsys
import traceback
from PIL import Image, ImageDraw, ImageFilter, ImageChops

from core.platform_utils import IS_MAC, IS_WIN, get_app_data_dir, get_monitors

if IS_WIN:
    import ctypes
    from ctypes import wintypes
    from core.win32_utils import (
        user32, kernel32, is_foreground_fullscreen,
        LayeredSurface, SystemAudioMeter, WNDCLASSEXW,
        enable_high_res_timer, disable_high_res_timer,
        WS_POPUP, WS_VISIBLE, WS_EX_LAYERED, WS_EX_TRANSPARENT,
        WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_NOACTIVATE,
        SW_HIDE, SW_SHOWNOACTIVATE, WM_CLOSE
    )
else:
    from core.mac_utils import (
        is_foreground_fullscreen,
        MacLayeredSurface as LayeredSurface,
        MacOverlayWindow,
        SystemAudioMeter,
        enable_high_res_timer,
        disable_high_res_timer,
    )

_CLASS_NAME = "SoulsLightsEdgeOverlay"
_class_registered = False


def _register_class():
    if not IS_WIN:
        return
    global _class_registered
    if not _class_registered:
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(user32.DefWindowProcW, ctypes.c_void_p).value
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = _CLASS_NAME
        user32.RegisterClassExW(ctypes.byref(wc))
        _class_registered = True


def hex_to_rgb(hex_str):
    s = (hex_str or "").lstrip("#")
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return (99, 102, 241)


def _clamp_rgb(r, g, b):
    return (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))


def _boost_and_saturate(c, boost, sat_mul):
    """Applies luminance gain and strong HSV saturation lift without washing hues out to white/grey."""
    r = min(1.0, (c[0] * boost) / 255.0)
    g = min(1.0, (c[1] * boost) / 255.0)
    b = min(1.0, (c[2] * boost) / 255.0)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, max(0.70, s * sat_mul)) if s > 0.06 else s
    v = min(1.0, v)
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    return _clamp_rgb(nr * 255.0, ng * 255.0, nb * 255.0)


def _padded_inward_glow(w, h, corner_r, inset, blur_r, gain=1.0):
    """Generates a smooth analytical inward Gaussian CDF glow with seamless zero tail (no cutoff band)."""
    pad = int(max(20, math.ceil(blur_r * 3.5) + 6))
    canvas = Image.new("L", (w + 2 * pad, h + 2 * pad), 255)
    inner_r = max(2, int(corner_r - max(0, inset)))
    x0 = pad + inset
    y0 = pad + inset
    x1 = pad + w - 1 - inset
    y1 = pad + h - 1 - inset
    if x1 > x0 and y1 > y0:
        ImageDraw.Draw(canvas).rounded_rectangle([x0, y0, x1, y1], radius=inner_r, fill=0)
    blurred = canvas.filter(ImageFilter.GaussianBlur(radius=blur_r))
    cropped = blurred.crop((pad, pad, pad + w, pad + h))
    # Smoothly roll low values (<24) down with cubic/quadratic taper so kernel edge melts invisibly into 0
    lut = []
    for i in range(256):
        val = (i / 255.0) * gain
        if i < 24:
            val *= (i / 24.0) ** 0.75
        lut.append(max(0, min(255, int(val * 255.0))))
    return cropped.point(lut)


def _build_theta_lut(lw, lh):
    """Precomputes angular perimeter coordinate (0..255) around screen center."""
    cx = lw * 0.5
    cy = lh * 0.5
    buf = bytearray(lw * lh)
    for y in range(lh):
        dy = (y + 0.5 - cy) / cy
        row_off = y * lw
        for x in range(lw):
            dx = (x + 0.5 - cx) / cx
            ang = math.atan2(dy, dx)  # -pi .. pi
            buf[row_off + x] = int(((ang + math.pi) / (2.0 * math.pi)) * 255.999) % 256
    return Image.frombytes("L", (lw, lh), bytes(buf))


class AmbientGlowEngine:
    """Standalone 1:1 Lumn Plasma Rim Engine with native-res crisp bezel edge, beat surge, and audio bloom."""

    def __init__(self, config_manager=None):
        self.cfg_mgr = config_manager
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self._hwnds = []

        # Color state
        self.album_c1 = (99, 102, 241)
        self.album_c2 = (236, 72, 153)
        self.custom_c1 = (99, 102, 241)
        self.custom_c2 = (236, 72, 153)
        self.custom_palette = [self.custom_c1, self.custom_c2]
        self.curr_c1 = self.album_c1
        self.curr_c2 = self.album_c2
        self.curr_palette = [self.album_c1, self.album_c2]

        # Parameters
        self.glow_intensity = 1.2          # 0.0 .. 3.0
        self.thickness_mode = "normal"     # subtle, normal, thick, immersive
        self.gradient_mode = "Multi Colors"# Multi Colors (or legacy 2 Colors), 1 Color
        self.animation_mode = "Liquid Flow"# Liquid Flow, Beat Pulse, Breathing, Static
        self.override_album_color = False
        self.color_balance = 0.5           # 0.15 .. 0.85
        self.target_displays = "All Displays"
        self.show_over_fullscreen = True
        self.audio_reactive = True
        self.chorus_boost = True
        self.energy_boost = 0.0

        self._dirty_mask = True
        self._dirty_monitors = False
        self._dirty_pixels = True

        self.reload_from_config()

    def reload_from_config(self):
        if not self.cfg_mgr:
            return
        a = self.cfg_mgr.config.get("ambient", {})
        with self._lock:
            self.glow_intensity = float(a.get("glow_intensity", 1.2))
            self.thickness_mode = str(a.get("thickness", "normal")).lower()
            self.gradient_mode = str(a.get("gradient_mode", "2 Colors"))
            self.animation_mode = str(a.get("animation_mode", "Water Drop"))
            self.override_album_color = bool(a.get("override_album_color", False))
            self.custom_c1 = hex_to_rgb(a.get("color_1", "#6366F1"))
            self.custom_c2 = hex_to_rgb(a.get("color_2", "#EC4899"))
            pal_hex = a.get("custom_colors")
            if isinstance(pal_hex, list) and pal_hex:
                self.custom_palette = [hex_to_rgb(h) for h in pal_hex]
            else:
                self.custom_palette = [self.custom_c1, self.custom_c2]
            self.color_balance = max(0.15, min(0.85, float(a.get("color_balance", 0.5))))
            self.target_displays = str(a.get("target_displays", "All Displays"))
            self.show_over_fullscreen = bool(a.get("show_over_fullscreen", True))
            self.audio_reactive = bool(a.get("audio_reactive", True))
            self.chorus_boost = bool(a.get("chorus_boost", True))
            self._dirty_mask = True
            self._dirty_pixels = True

    def start(self):
        if self.running:
            return
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if IS_WIN:
            for hwnd in list(self._hwnds):
                try:
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                except Exception:
                    pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)

    def update_album_colors(self, hex1, hex2=None):
        with self._lock:
            self.album_c1 = hex_to_rgb(hex1)
            self.album_c2 = hex_to_rgb(hex2) if hex2 else self.album_c1
            self._dirty_pixels = True

    def set_custom_colors(self, hex1, hex2):
        with self._lock:
            self.custom_c1 = hex_to_rgb(hex1)
            self.custom_c2 = hex_to_rgb(hex2)
            if len(self.custom_palette) <= 2:
                self.custom_palette = [self.custom_c1, self.custom_c2]
            else:
                self.custom_palette[0] = self.custom_c1
                self.custom_palette[1] = self.custom_c2
            self._dirty_pixels = True

    def set_custom_palette(self, hex_list):
        with self._lock:
            pts = [hex_to_rgb(h) for h in (hex_list or []) if h]
            if not pts:
                pts = [self.custom_c1, self.custom_c2]
            self.custom_palette = pts
            self.custom_c1 = pts[0]
            self.custom_c2 = pts[1] if len(pts) > 1 else pts[0]
            self._dirty_pixels = True

    def set_override_album(self, enable: bool):
        with self._lock:
            self.override_album_color = bool(enable)
            self._dirty_pixels = True

    def set_intensity(self, val: float):
        with self._lock:
            self.glow_intensity = max(0.0, min(3.0, float(val)))
            self._dirty_mask = True
            self._dirty_pixels = True

    def set_thickness(self, mode_str: str):
        with self._lock:
            self.thickness_mode = str(mode_str).lower()
            self._dirty_mask = True
            self._dirty_pixels = True

    def set_gradient_mode(self, mode_str: str):
        with self._lock:
            self.gradient_mode = str(mode_str)
            self._dirty_pixels = True

    def set_animation_mode(self, mode_str: str):
        with self._lock:
            self.animation_mode = str(mode_str)
            self._dirty_pixels = True

    def set_balance(self, bal: float):
        with self._lock:
            self.color_balance = max(0.15, min(0.85, float(bal)))
            self._dirty_pixels = True

    def set_target_displays(self, target: str):
        with self._lock:
            if self.target_displays != target:
                self.target_displays = target
                self._dirty_monitors = True

    def set_show_over_fullscreen(self, show: bool):
        with self._lock:
            self.show_over_fullscreen = bool(show)

    def set_audio_reactive(self, enable: bool):
        with self._lock:
            self.audio_reactive = bool(enable)

    def set_chorus_boost(self, enable: bool):
        with self._lock:
            self.chorus_boost = bool(enable)

    def set_energy_boost(self, val: float):
        with self._lock:
            self.energy_boost = max(0.0, min(1.0, float(val)))

    def _select_monitors(self):
        all_mons = get_monitors()
        target = self.target_displays
        if target == "All Displays":
            return all_mons
        if target == "Primary Display":
            prim = [m for m in all_mons if m["primary"]]
            return prim or all_mons[:1]
        matched = [m for m in all_mons if m["device"] == target]
        return matched or all_mons[:1]

    def _build_alpha_masks(self, w, h, thickness_mode, glow_val):
        """Precomputes crisp, non-hazy native-res rim masks with exponential falloff."""
        dpi_s = max(0.75, min(2.2, w / 1920.0))
        thick_cfg = {
            # (core_px, collar_inset_half, collar_blur_half, bloom_blur_half)
            "subtle":    (2.2, 0, 2.2, 4.2),
            "normal":    (3.2, 1, 3.4, 6.2),
            "thick":     (4.5, 2, 5.2, 9.0),
            "immersive": (6.2, 3, 7.6, 12.5),
        }
        core_px, collar_in, collar_b, bloom_b = thick_cfg.get(thickness_mode, thick_cfg["normal"])
        glow_c = max(0.0, min(3.0, glow_val))

        corner_r = int(round(22 * dpi_s))
        hw, hh = max(64, w // 2), max(64, h // 2)

        # 1. Native-resolution razor-sharp outer rim core (tight micro-feather only, zero haze)
        rim_w = max(2, int(round(core_px * dpi_s)))
        core_hi = Image.new("L", (w, h), 0)
        ImageDraw.Draw(core_hi).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=corner_r, outline=255, width=rim_w
        )
        rim_inner = Image.new("L", (w, h), 0)
        ImageDraw.Draw(rim_inner).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=corner_r, outline=255, width=max(2, rim_w + int(round(1.5 * dpi_s)))
        )
        rim_inner = rim_inner.filter(ImageFilter.GaussianBlur(radius=max(0.8, 1.0 * dpi_s)))
        core_hi = ImageChops.lighter(core_hi, rim_inner)

        # Outer corner clip mask so rounded bezel corners stay clean (0 alpha in extreme triangle corner)
        corner_clip = Image.new("L", (w, h), 0)
        ImageDraw.Draw(corner_clip).rounded_rectangle([0, 0, w - 1, h - 1], radius=corner_r, fill=255)

        if glow_c <= 0.02:
            base = ImageChops.darker(core_hi, corner_clip)
            return base, base

        # Concave power-curve falloff eliminates wide milky/hazy Gaussian shoulders while keeping lush edge richness
        collar_lut = [int(((i / 255.0) ** 1.38) * 255) for i in range(256)]
        bloom_lut = [int(((i / 255.0) ** 2.0) * 255) for i in range(256)]

        # 2. Tight electric inner plasma collar (half-res padded CDF -> punchy non-hazy edge glow)
        collar_gain = min(1.95, 1.02 + glow_c * 0.48)
        collar = _padded_inward_glow(
            hw, hh, corner_r // 2,
            inset=max(0, int(round(collar_in * dpi_s))),
            blur_r=max(2.2, collar_b * dpi_s * (0.85 + 0.22 * min(1.5, glow_c))),
            gain=collar_gain,
        ).point(collar_lut).resize((w, h), Image.Resampling.BILINEAR)

        # 3. Clean resting edge halo + soft ambient corner spill
        rest_bloom_blur = max(3.6, bloom_b * dpi_s * (0.72 + glow_c * 0.26))
        rest_bloom_gain = min(0.84, 0.28 + glow_c * 0.24)
        bloom_rest = _padded_inward_glow(
            hw, hh, corner_r // 2,
            inset=max(0, int(round(collar_in * dpi_s))),
            blur_r=rest_bloom_blur,
            gain=rest_bloom_gain,
        ).point(bloom_lut).resize((w, h), Image.Resampling.BILINEAR)

        base = ImageChops.lighter(core_hi, collar)
        base = ImageChops.lighter(base, bloom_rest)

        # Soft rounded-corner radial luminance lift so bezel corners glow lush & balanced
        if glow_c >= 0.35:
            cr_map = Image.new("L", (hw, hh), 0)
            crd = ImageDraw.Draw(cr_map)
            c_rad = max(24, int(min(hw, hh) * 0.22))
            c_fill = min(135, int(42 + glow_c * 32))
            for cx_p, cy_p in ((0, 0), (hw, 0), (0, hh), (hw, hh)):
                crd.ellipse([cx_p - c_rad, cy_p - c_rad, cx_p + c_rad, cy_p + c_rad], fill=c_fill)
            cr_map = cr_map.filter(ImageFilter.GaussianBlur(radius=max(6.0, c_rad * 0.42))).resize((w, h), Image.Resampling.BILINEAR)
            base = ImageChops.lighter(base, ImageChops.darker(cr_map, bloom_rest.point(lambda p: min(255, int(p * 1.45)))))

        # 4. Surge mask for beat drops (punchy flare without wide foggy center veil)
        surge_collar = _padded_inward_glow(
            hw, hh, corner_r // 2,
            inset=max(1, int(round((collar_in + 1) * dpi_s))),
            blur_r=max(3.4, collar_b * 1.52 * dpi_s),
            gain=2.15,
        ).point(collar_lut).resize((w, h), Image.Resampling.BILINEAR)

        surge_bloom = _padded_inward_glow(
            hw, hh, corner_r // 2,
            inset=max(1, int(round((collar_in + 2) * dpi_s))),
            blur_r=max(5.2, rest_bloom_blur * 1.52),
            gain=min(1.32, rest_bloom_gain + 0.52),
        ).point(bloom_lut).resize((w, h), Image.Resampling.BILINEAR)

        surge = ImageChops.lighter(core_hi, surge_collar)
        surge = ImageChops.lighter(surge, surge_bloom)

        # Master scaling for dim < 1.0 glow settings
        if glow_c < 1.0:
            s = 0.22 + 0.78 * glow_c
            lut_dim = [int(i * s) for i in range(256)]
            base = base.point(lut_dim)
            surge = surge.point(lut_dim)

        base = ImageChops.darker(base, corner_clip)
        surge = ImageChops.darker(surge, corner_clip)
        return base, surge

    def _build_color_frame(self, theta_img, palette, gradient_mode, phase_rad, anim_time, anim_mode, balance, bloom, peak):
        """Generates vivid N-color cyclic angular plasma RGB texture (and droplet/prism spatial alpha LUT)."""
        base_boost = 1.08 + bloom * 0.48 + peak * 0.16
        sat_lift = 1.28 + bloom * 0.36
        pal_src = list(palette) if palette else [self.album_c1, self.album_c2]
        if gradient_mode == "1 Color":
            c0 = _boost_and_saturate(pal_src[0], base_boost, sat_lift)
            hot_pal = [c0, _boost_and_saturate(pal_src[0], 0.72 + bloom * 0.28, 1.35)]
        else:
            if len(pal_src) == 1:
                pal_src = [pal_src[0], pal_src[0]]
            hot_pal = [_boost_and_saturate(c, base_boost, sat_lift) for c in pal_src]
        n_cols = len(hot_pal)

        wobble_amp = 0.0
        if anim_mode == "Liquid Flow":
            wobble_amp = 0.22 + bloom * 0.22
        elif anim_mode == "Aurora Wave":
            wobble_amp = 0.26 + bloom * 0.24
        elif anim_mode == "Beat Pulse":
            wobble_amp = 0.14 + bloom * 0.30

        gamma = math.log(0.5) / math.log(max(0.08, min(0.92, 1.0 - balance))) if abs(balance - 0.5) > 0.03 else 1.0

        lut_r = [0] * 256
        lut_g = [0] * 256
        lut_b = [0] * 256
        is_drop = (anim_mode == "Water Drop")
        is_prism = (anim_mode == "Neon Prism")
        is_aurora = (anim_mode == "Aurora Wave")
        use_spatial = is_drop or is_prism
        drop_lut = [255] * 256 if use_spatial else None
        two_pi = 2.0 * math.pi
        ahead_span = 0.052
        tail_span = 0.46 + min(0.20, bloom * 0.20)

        for i in range(256):
            ang = (i / 256.0) * two_pi
            drop_val = 0.0

            if is_drop:
                trail = ((phase_rad - ang) % two_pi) / two_pi
                if trail >= 1.0 - ahead_span:
                    u_head = (trail - (1.0 - ahead_span)) / ahead_span
                    drop_val = (0.5 - 0.5 * math.cos(math.pi * u_head)) ** 1.35
                elif trail <= tail_span:
                    u_tail = trail / tail_span
                    drop_val = ((1.0 - u_tail) ** 2.25) * ((0.5 + 0.5 * math.cos(math.pi * u_tail)) ** 0.75)

                # Harmonic opposing beat ripple echo on bass kicks
                if bloom > 0.10:
                    echo_trail = ((phase_rad + math.pi - ang) % two_pi) / two_pi
                    if echo_trail <= 0.32:
                        eu = echo_trail / 0.32
                        echo_v = ((1.0 - eu) ** 2.4) * min(0.68, (bloom - 0.08) * 0.95)
                        drop_val = max(drop_val, echo_v)

                if drop_val > 0.0 and bloom > 0.02:
                    drop_val = min(1.0, drop_val * (0.88 + bloom * 0.38))
                drop_lut[i] = max(0, min(255, int(round(drop_val * 255.0))))

                raw_u = 0.0 if trail >= 1.0 - ahead_span else min(1.0, (trail / max(0.25, tail_span)) ** 0.75)
                if gamma != 1.0:
                    raw_u = raw_u ** gamma
                energy_mul = 1.0 + (drop_val ** 2.1) * (0.16 + bloom * 0.36)
                if n_cols <= 2:
                    ca, cb = hot_pal[0], hot_pal[1]
                    mix_u = raw_u
                else:
                    f_pos = raw_u * (n_cols - 1)
                    idx_a = min(n_cols - 2, int(f_pos))
                    ca, cb = hot_pal[idx_a], hot_pal[idx_a + 1]
                    mix_u = f_pos - idx_a

            elif is_prism:
                # Twin 180-deg counter-balanced high-energy prismatic comet arcs
                d1 = ((phase_rad - ang) % two_pi) / two_pi
                d2 = ((phase_rad + math.pi - ang) % two_pi) / two_pi
                arc1 = ((1.0 - d1 / 0.42) ** 1.75) if d1 <= 0.42 else (0.18 if d1 > 0.94 else 0.0)
                arc2 = ((1.0 - d2 / 0.42) ** 1.75) if d2 <= 0.42 else (0.18 if d2 > 0.94 else 0.0)
                drop_val = min(1.0, 0.24 + 0.76 * max(arc1, arc2) * (0.90 + bloom * 0.38))
                drop_lut[i] = max(0, min(255, int(round(drop_val * 255.0))))
                flow_ang = (ang - phase_rad * 1.15) % two_pi
                u_cyc = flow_ang / two_pi
                if gamma != 1.0:
                    u_cyc = u_cyc ** gamma
                f_pos = u_cyc * n_cols
                idx_a = int(f_pos) % n_cols
                idx_b = (idx_a + 1) % n_cols
                ca, cb = hot_pal[idx_a], hot_pal[idx_b]
                mix_u = f_pos - int(f_pos)
                energy_mul = 1.0 + max(arc1, arc2) * (0.24 + bloom * 0.32)

            else:
                if anim_mode == "Liquid Flow":
                    ang_w = ang + 0.30 * math.sin(2.0 * ang - anim_time * 1.25)
                    flow_ang = (ang_w - phase_rad) % two_pi
                elif is_aurora:
                    ang_w = ang + 0.42 * math.sin(2.0 * ang + anim_time * 0.95) * math.cos(ang - anim_time * 0.65)
                    flow_ang = (ang_w - phase_rad * 0.85) % two_pi
                else:
                    flow_ang = (ang - phase_rad) % two_pi

                if n_cols <= 2:
                    mix_u = 0.5 + 0.5 * math.cos(flow_ang)
                    if gamma != 1.0:
                        mix_u = mix_u ** gamma
                    ca, cb = hot_pal[0], hot_pal[1]
                else:
                    u_cyc = flow_ang / two_pi
                    if gamma != 1.0:
                        u_cyc = u_cyc ** gamma
                    f_pos = u_cyc * n_cols
                    idx_a = int(f_pos) % n_cols
                    idx_b = (idx_a + 1) % n_cols
                    ca, cb = hot_pal[idx_a], hot_pal[idx_b]
                    mix_u = f_pos - int(f_pos)

                energy_mul = 1.0
                if wobble_amp > 0.0:
                    if is_aurora:
                        w_wave = (
                            0.52 * math.sin(2.0 * ang + anim_time * 1.35)
                            + 0.34 * math.cos(5.0 * ang - anim_time * 2.05)
                            + 0.14 * math.sin(8.0 * ang + anim_time * 2.8)
                        )
                    else:
                        w_wave = (
                            0.55 * math.sin(3.0 * ang + anim_time * 2.3)
                            + 0.30 * math.sin(6.0 * ang - anim_time * 1.7)
                            + 0.15 * math.sin(9.0 * ang + anim_time * 3.1)
                        )
                    energy_mul = max(0.76, min(1.42, 1.0 + wobble_amp * w_wave))

            r = ca[0] * (1.0 - mix_u) + cb[0] * mix_u
            g = ca[1] * (1.0 - mix_u) + cb[1] * mix_u
            b = ca[2] * (1.0 - mix_u) + cb[2] * mix_u

            # Prevent complementary color stops from turning grey in the transition zone
            if gradient_mode != "1 Color":
                h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                if 0.04 < s < 0.80:
                    s = min(1.0, s + (0.80 - s) * 0.68)
                avg_sum = (ca[0] + cb[0] + ca[1] + cb[1] + ca[2] + cb[2]) / 1530.0
                v = max(v, 0.48 * avg_sum)
                mr, mg, mb_v = colorsys.hsv_to_rgb(h, s, min(1.0, v))
                r, g, b = mr * 255.0, mg * 255.0, mb_v * 255.0

            if use_spatial and drop_val > 0.72:
                # Subtle glassy crest gleam at peak without losing album hue
                crest_k = ((drop_val - 0.72) / 0.28) * (0.20 + bloom * 0.14)
                r = r + (255.0 - r) * crest_k
                g = g + (255.0 - g) * crest_k
                b = b + (255.0 - b) * crest_k

            r *= energy_mul
            g *= energy_mul
            b *= energy_mul

            # Preserve hue ratios on luminance overdrive instead of clipping individual channels to white
            peak_ch = max(r, g, b, 1.0)
            if peak_ch > 255.0:
                scale = 255.0 / peak_ch
                r *= scale
                g *= scale
                b *= scale

            lut_r[i] = max(0, min(255, int(r)))
            lut_g[i] = max(0, min(255, int(g)))
            lut_b[i] = max(0, min(255, int(b)))

        rgb_img = Image.merge("RGB", (theta_img.point(lut_r), theta_img.point(lut_g), theta_img.point(lut_b)))
        drop_lo = theta_img.point(drop_lut).filter(ImageFilter.GaussianBlur(radius=1.5)) if use_spatial else None
        return rgb_img, drop_lo

    def _slice_mask_strips(self, mask, s):
        w, h = mask.size
        s = min(s, w // 3, h // 3)
        return (
            mask.crop((0, 0, w, s)),
            mask.crop((0, h - s, w, h)),
            mask.crop((0, s, s, h - s)),
            mask.crop((w - s, s, w, h - s)),
        )

    def _dispose_strip_windows(self, ov):
        for st in ov.get("strip_wins", ()):
            try:
                st["surf"].dispose()
            except Exception:
                pass
            try:
                if IS_WIN and st.get("hwnd"):
                    user32.DestroyWindow(st["hwnd"])
                elif st.get("win"):
                    st["win"].dispose()
            except Exception:
                pass
        ov["strip_wins"] = []

    def _sync_hwnd_cache(self, overlays):
        self._hwnds = [st.get("hwnd") for ov in overlays for st in ov.get("strip_wins", ()) if st.get("hwnd")]

    def _rebuild_strip_windows(self, ov, strip_px: int):
        """Creates 4 ultra-fast perimeter strip overlay windows per display."""
        self._dispose_strip_windows(ov)
        mon = ov["mon"]
        w, h = mon["w"], mon["h"]
        s = max(8, min(strip_px, w // 3, h // 3))
        lw, lh = ov["theta"].size
        sl = max(1, min(lh // 2, int(round(s * lw / max(1, w)))))
        mid_h = max(1, h - 2 * s)

        specs = [
            ("top",   mon["x"],         mon["y"],         w, s,     (0, 0, lw, sl),         (w, s)),
            ("bot",   mon["x"],         mon["y"] + h - s, w, s,     (0, lh - sl, lw, lh),   (w, s)),
            ("left",  mon["x"],         mon["y"] + s,     s, mid_h, (0, sl, sl, lh - sl),   (s, mid_h)),
            ("right", mon["x"] + w - s, mon["y"] + s,     s, mid_h, (lw - sl, sl, lw, lh - sl), (s, mid_h)),
        ]
        strip_wins = []
        if IS_WIN:
            ex_style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE
            for idx, (tag, wx, wy, ww, wh, lbox, dst_wh) in enumerate(specs):
                hwnd = user32.CreateWindowExW(
                    ex_style, _CLASS_NAME, f"SoulsLightsEdge_{mon['device']}_{tag}",
                    WS_POPUP | (WS_VISIBLE if ov["visible"] else 0),
                    wx, wy, ww, wh,
                    None, None, kernel32.GetModuleHandleW(None), None
                )
                if hwnd:
                    strip_wins.append({
                        "idx": idx,
                        "hwnd": hwnd,
                        "win": None,
                        "x": wx,
                        "y": wy,
                        "surf": LayeredSurface(ww, wh),
                        "lbox": lbox,
                        "dst_wh": dst_wh,
                    })
        else:
            for idx, (tag, wx, wy, ww, wh, lbox, dst_wh) in enumerate(specs):
                win_obj = MacOverlayWindow(wx, wy, ww, wh, role="glow", click_through=True)
                if ov["visible"]:
                    win_obj.set_visible(True)
                strip_wins.append({
                    "idx": idx,
                    "hwnd": None,
                    "win": win_obj,
                    "x": wx,
                    "y": wy,
                    "surf": LayeredSurface(ww, wh),
                    "lbox": lbox,
                    "dst_wh": dst_wh,
                })
        ov["strip_wins"] = strip_wins

    def _prepare_overlay_strips(self, ov, thick_mode, glow_val):
        w, h = ov["mon"]["w"], ov["mon"]["h"]
        mb, ms = self._build_alpha_masks(w, h, thick_mode, glow_val)
        dpi_s = max(0.75, min(2.2, w / 1920.0))
        mid_y = h // 2
        depth = 0
        for x in range(min(w // 3, int(260 * dpi_s))):
            if ms.getpixel((x, mid_y)) > 0:
                depth = x + 1
        strip_px = max(int(36 * dpi_s), min(w // 3, h // 3, depth + 6))
        if strip_px != ov["strip_px"] or not ov["strip_wins"]:
            self._rebuild_strip_windows(ov, strip_px)
        ov["strip_px"] = strip_px
        ov["base_strips"] = self._slice_mask_strips(mb, strip_px)
        ov["surge_strips"] = self._slice_mask_strips(ms, strip_px)

    def _create_overlay_windows(self, monitors):
        overlays = []
        for mon in monitors:
            lw = 180
            lh = max(72, int(round(180 * (mon["h"] / max(1, mon["w"])))))
            overlays.append({
                "mon": mon,
                "strip_wins": [],
                "theta": _build_theta_lut(lw, lh),
                "strip_px": -1,
                "base_strips": None,
                "surge_strips": None,
                "visible": True,
            })
        return overlays

    def _destroy_overlays(self, overlays):
        for ov in overlays:
            self._dispose_strip_windows(ov)
        self._hwnds = []

    def _run_loop(self):
        enable_high_res_timer()
        try:
            self._run_loop_impl()
        except Exception:
            try:
                log_p = os.path.join(get_app_data_dir(), "app.log")
                with open(log_p, "a", encoding="utf-8") as f:
                    f.write(f"[AmbientGlowEngine ERROR]\n{traceback.format_exc()}\n")
            except Exception:
                pass
            self.running = False
        finally:
            disable_high_res_timer()

    def _run_loop_impl(self):
        _register_class()
        audio = SystemAudioMeter()
        audio.init_com()

        with self._lock:
            monitors = self._select_monitors()
            init_thick = self.thickness_mode
            init_glow = self.glow_intensity
        overlays = self._create_overlay_windows(monitors)
        if not overlays:
            audio.dispose()
            self.running = False
            return
        for ov in overlays:
            self._prepare_overlay_strips(ov, init_thick, init_glow)
        self._sync_hwnd_cache(overlays)

        msg = wintypes.MSG() if IS_WIN else None
        last_t = time.perf_counter()
        anim_time = 0.0
        phase_rad = 0.0
        last_fs_check = 0.0
        is_fs = False
        target_dt = 1.0 / 64.0
        next_frame = last_t + target_dt
        did_initial_draw = False

        while self.running:
            if IS_WIN:
                for st_hwnd in list(self._hwnds):
                    while user32.PeekMessageW(ctypes.byref(msg), st_hwnd, 0, 0, 1):
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))

            now = time.perf_counter()
            dt = max(0.004, min(0.08, now - last_t))
            last_t = now
            anim_time += dt

            with self._lock:
                rebuild_mons = self._dirty_monitors
                rebuild_mask = self._dirty_mask
                force_pixels = self._dirty_pixels
                self._dirty_monitors = False
                self._dirty_mask = False
                self._dirty_pixels = False

                target_pal = list(self.custom_palette) if self.override_album_color else [self.album_c1, self.album_c2]
                glow_val = self.glow_intensity
                thick_mode = self.thickness_mode
                grad_mode = self.gradient_mode
                anim_mode = self.animation_mode
                balance = self.color_balance
                show_fs = self.show_over_fullscreen
                audio_on = self.audio_reactive
                e_boost = self.energy_boost if self.chorus_boost else 0.0

                if rebuild_mons:
                    new_mons = self._select_monitors()

            if rebuild_mons:
                self._destroy_overlays(overlays)
                overlays = self._create_overlay_windows(new_mons)
                rebuild_mask = True
                force_pixels = True

            if now - last_fs_check > 0.4:
                last_fs_check = now
                if show_fs:
                    is_fs = False
                else:
                    ignore = set(self._hwnds)
                    is_fs = any(is_foreground_fullscreen(ov["mon"], ignore) for ov in overlays)

            for ov in overlays:
                should_show = not is_fs
                if should_show != ov["visible"]:
                    ov["visible"] = should_show
                    if IS_WIN:
                        cmd = SW_SHOWNOACTIVATE if should_show else SW_HIDE
                        for st in ov["strip_wins"]:
                            user32.ShowWindow(st["hwnd"], cmd)
                    else:
                        for st in ov["strip_wins"]:
                            st["win"].set_visible(should_show)

            if is_fs:
                time.sleep(0.06)
                next_frame = time.perf_counter() + target_dt
                continue

            peak, bloom = audio.sample() if audio_on else (0.0, 0.0)
            if e_boost > 0.02:
                bloom = min(1.0, bloom + e_boost * 0.42)
                peak = min(1.0, peak + e_boost * 0.25)

            lerp_k = min(1.0, dt * 3.6)
            if len(self.curr_palette) != len(target_pal):
                old = self.curr_palette or target_pal
                self.curr_palette = [old[min(idx_p, len(old) - 1)] for idx_p in range(len(target_pal))]
            new_pal = []
            color_lerping = False
            for idx_p, tgt in enumerate(target_pal):
                cur_c = self.curr_palette[idx_p]
                nc = tuple(int(cur_c[i] + (tgt[i] - cur_c[i]) * lerp_k) for i in range(3))
                if nc != cur_c:
                    color_lerping = True
                new_pal.append(nc)
            self.curr_palette = new_pal
            self.curr_c1 = new_pal[0]
            self.curr_c2 = new_pal[1] if len(new_pal) > 1 else new_pal[0]

            animated = anim_mode in ("Liquid Flow", "Beat Pulse", "Water Drop", "Aurora Wave", "Neon Prism")
            if anim_mode == "Water Drop":
                if audio_on or e_boost > 0.05:
                    speed = 0.58 + peak * 0.42 + (bloom ** 0.85) * 3.55 + e_boost * 0.85
                else:
                    speed = 0.88 + 0.24 * math.sin(anim_time * 1.4)
                phase_rad = (phase_rad + dt * speed) % (2.0 * math.pi)
            elif anim_mode == "Neon Prism":
                speed = 1.45 + peak * 0.85 + (bloom ** 0.78) * 4.2 + e_boost * 1.1
                phase_rad = (phase_rad + dt * speed) % (2.0 * math.pi)
            elif anim_mode == "Aurora Wave":
                speed = 0.65 + bloom * 1.65 + peak * 0.45 + e_boost * 0.75
                phase_rad = (phase_rad + dt * speed) % (2.0 * math.pi)
            elif anim_mode == "Liquid Flow":
                speed = 1.15 + bloom * 2.5 + peak * 0.65 + e_boost * 0.9
                phase_rad = (phase_rad + dt * speed) % (2.0 * math.pi)
            elif anim_mode == "Beat Pulse" and (audio_on or e_boost > 0.05):
                phase_rad = (phase_rad + dt * (0.30 + bloom * 2.4)) % (2.0 * math.pi)

            if rebuild_mask:
                for ov in overlays:
                    self._prepare_overlay_strips(ov, thick_mode, glow_val)
                self._sync_hwnd_cache(overlays)
                force_pixels = True

            # Upload every frame during animation (~64 FPS) since 4 thin strip HWNDs cost only ~2.5ms total
            need_upload = (not did_initial_draw) or force_pixels or color_lerping or animated or e_boost > 0.04 or (audio_on and (bloom > 0.015 or peak > 0.03))
            if need_upload:
                did_initial_draw = True
                b_val = min(1.0, (bloom if audio_on else 0.0) + e_boost * 0.36)
                p_val = min(1.0, (peak if audio_on else 0.0) + e_boost * 0.22)
                if anim_mode == "Water Drop":
                    surge_mix = min(1.0, 0.18 + p_val * 0.22 + (b_val ** 0.72) * 0.84) if (audio_on or e_boost > 0.05) else (0.24 + 0.14 * math.sin(anim_time * 2.0))
                elif anim_mode == "Neon Prism":
                    surge_mix = min(1.0, 0.30 + p_val * 0.28 + (b_val ** 0.68) * 0.82) if (audio_on or e_boost > 0.05) else (0.42 + 0.24 * math.sin(anim_time * 2.8))
                elif anim_mode == "Aurora Wave":
                    surge_mix = min(1.0, 0.26 + 0.22 * math.sin(anim_time * 1.35) + b_val * 0.78 + p_val * 0.25)
                elif anim_mode == "Beat Pulse":
                    surge_mix = min(1.0, (b_val ** 0.65) * 0.94 + p_val * 0.35) if (audio_on or e_boost > 0.05) else (0.5 + 0.5 * math.sin(anim_time * 3.0)) ** 4
                elif anim_mode == "Breathing":
                    surge_mix = min(1.0, 0.48 + 0.46 * math.sin(anim_time * 1.8) + e_boost * 0.32)
                elif anim_mode == "Liquid Flow":
                    surge_mix = min(1.0, 0.16 + 0.14 * math.sin(anim_time * 1.9) + b_val * 0.88 + p_val * 0.28)
                else:
                    surge_mix = min(1.0, e_boost * 0.45)

                for ov in overlays:
                    if ov["base_strips"] is None:
                        self._prepare_overlay_strips(ov, thick_mode, glow_val)
                        self._sync_hwnd_cache(overlays)

                    rgb_lo, drop_lo = self._build_color_frame(
                        ov["theta"], self.curr_palette,
                        grad_mode, phase_rad, anim_time, anim_mode, balance, b_val, p_val
                    )
                    bs = ov["base_strips"]
                    ss = ov["surge_strips"]
                    use_surge = (surge_mix > 0.02 and ss is not None)
                    for st in ov["strip_wins"]:
                        i_s = st["idx"]
                        mask_s = Image.blend(bs[i_s], ss[i_s], surge_mix) if use_surge else bs[i_s]
                        if drop_lo is not None:
                            d_strip = drop_lo.crop(st["lbox"]).resize(st["dst_wh"], Image.Resampling.BILINEAR)
                            mask_s = ImageChops.multiply(mask_s, d_strip)
                        rgb_s = rgb_lo.crop(st["lbox"]).resize(st["dst_wh"], Image.Resampling.BILINEAR)
                        st["surf"].upload_rgb_alpha(rgb_s, mask_s)

            base_alpha = min(255, int(222 + min(1.0, (glow_val + e_boost * 0.45) / 2.5) * 33))
            if anim_mode == "Static":
                mod = 1.0
            elif anim_mode == "Water Drop":
                mod = min(1.0, 0.50 + peak * 0.20 + (bloom ** 0.68) * 0.50) if audio_on else (0.76 + 0.24 * (0.5 + 0.5 * math.sin(anim_time * 2.2)))
            elif anim_mode == "Neon Prism":
                mod = min(1.0, 0.64 + peak * 0.22 + (bloom ** 0.64) * 0.48) if audio_on else (0.82 + 0.18 * (0.5 + 0.5 * math.sin(anim_time * 2.8)))
            elif anim_mode == "Aurora Wave":
                mod = min(1.0, 0.78 + 0.14 * math.sin(anim_time * 1.3) + (bloom * 0.34 + peak * 0.14 if audio_on else 0.0))
            elif anim_mode == "Breathing":
                mod = 0.70 + 0.30 * (0.5 + 0.5 * math.sin(anim_time * 1.8))
            elif anim_mode == "Beat Pulse":
                idle_pulse = 0.58 + 0.16 * math.sin(anim_time * 2.6)
                spike = ((bloom ** 0.68) * 0.72 + peak * 0.32) if audio_on else 0.34 * (math.sin(anim_time * 3.0) ** 4)
                mod = min(1.0, idle_pulse + spike)
            else:  # Liquid Flow
                breath = 0.85 + 0.10 * math.sin(anim_time * 1.6)
                mod = min(1.0, breath + (bloom * 0.36 + peak * 0.16 if audio_on else 0.0))

            final_alpha = max(25, min(255, int(base_alpha * mod)))
            for ov in overlays:
                for st in ov["strip_wins"]:
                    target_w = st["hwnd"] if IS_WIN else st["win"]
                    st["surf"].present(target_w, st["x"], st["y"], master_alpha=final_alpha)

            now_end = time.perf_counter()
            if anim_mode == "Static" and not audio_on:
                time.sleep(0.04)
                next_frame = time.perf_counter() + target_dt
            else:
                rem_sleep = next_frame - now_end
                if rem_sleep > 0.001:
                    time.sleep(rem_sleep)
                    next_frame += target_dt
                else:
                    next_frame = now_end + target_dt

        self._destroy_overlays(overlays)
        audio.dispose()
