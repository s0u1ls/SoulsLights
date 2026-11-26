import os
import sys
import threading
import time
import math
import colorsys
import traceback
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageChops

from core.platform_utils import IS_MAC, IS_WIN, get_app_data_dir, get_monitors

if IS_WIN:
    import ctypes
    from ctypes import wintypes
    from core.win32_utils import (
        user32, kernel32, is_foreground_fullscreen,
        ScaledBlitSurface, SystemAudioMeter, WNDCLASSEXW,
        enable_high_res_timer, disable_high_res_timer,
        WS_POPUP, WS_VISIBLE, WS_EX_LAYERED, WS_EX_TRANSPARENT,
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE,
        HWND_TOP, HWND_BOTTOM, LWA_ALPHA, SW_HIDE, SW_SHOWNOACTIVATE,
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE, WM_CLOSE
    )
else:
    from core.mac_utils import (
        MacScaledBlitSurface as ScaledBlitSurface,
        MacOverlayWindow,
        SystemAudioMeter,
        enable_high_res_timer,
        disable_high_res_timer,
    )

_CLASS_NAME = "SoulsLightsAlbumBackdrop"
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


def _hex_to_rgb(hx, fallback=(99, 102, 241)):
    s = (hx or "").lstrip("#")
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return fallback


def _tune_blob_rgb(rgb, lum_mul: float, sat_boost: float = 1.18):
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, max(0.45, s * sat_boost)) if s > 0.04 else 0.55
    v = max(0.18, min(1.0, max(0.55, v) * lum_mul))
    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
    return (int(nr * 255), int(ng * 255), int(nb * 255))


def _make_radial_blob(w: int, h: int, rgb: tuple, power: float = 1.85) -> Image.Image:
    """Pre-bakes a velvety radial-falloff luminous blob sprite once per track."""
    # Draw analytical super-smooth falloff directly at target sprite size
    buf = bytearray(w * h * 3)
    cx = w * 0.5
    cy = h * 0.5
    inv_rx = 1.0 / max(1.0, cx)
    inv_ry = 1.0 / max(1.0, cy)
    rr, gg, bb = rgb
    pos = 0
    for y in range(h):
        dy = (y + 0.5 - cy) * inv_ry
        dy2 = dy * dy
        for x in range(w):
            dx = (x + 0.5 - cx) * inv_rx
            d2 = dx * dx + dy2
            if d2 >= 1.0:
                buf[pos] = 0
                buf[pos + 1] = 0
                buf[pos + 2] = 0
            else:
                k = (1.0 - math.sqrt(d2)) ** power
                # Smooth cosine shoulder right at core
                k = min(1.0, k * 1.18)
                buf[pos] = int(rr * k)
                buf[pos + 1] = int(gg * k)
                buf[pos + 2] = int(bb * k)
            pos += 3
    return Image.frombytes("RGB", (w, h), bytes(buf))


class AlbumBackdropEngine:
    """Renders a 60 FPS darkened 2-blob animated album backdrop underneath ambient light & lyrics."""

    SRC_W = 192
    SRC_H = 108

    def __init__(self, config_manager=None):
        self.cfg_mgr = config_manager
        self.running = False
        self.thread = None
        self._lock = threading.Lock()
        self._hwnds = []

        self.mode = "Desktop Layer"       # Desktop Layer, Cinema Stage, Off
        self.darkness = 0.34              # 0.15 .. 0.65 (brightness multiplier)
        self.target_displays = "All Displays"
        self.show_over_fullscreen = True
        self.audio_reactive = True

        self._thumb_img = None
        self._colors = ["#6366F1", "#EC4899", "#8B5CF6"]
        self._is_playing = False
        self._has_media = False
        self._dirty_art = True
        self._dirty_monitors = False
        self._dirty_mode = True

        # Pre-baked animated cover art + 2 matching luminous blobs built once per song
        self._base_bg = None
        self._cover_src = None
        self._blob_1 = None
        self._blob_2 = None
        self._tmp_a = Image.new("RGB", (self.SRC_W, self.SRC_H), (0, 0, 0))
        self._tmp_b = Image.new("RGB", (self.SRC_W, self.SRC_H), (0, 0, 0))
        self._vig_mul = self._build_vignette_mul()

        self.reload_from_config()

    def _build_vignette_mul(self):
        """Builds an RGB corner/edge darkening mask so outer ambient rim pops strongly."""
        vig = Image.new("L", (self.SRC_W, self.SRC_H), 145)
        ImageDraw.Draw(vig).rounded_rectangle([14, 10, self.SRC_W - 15, self.SRC_H - 11], radius=22, fill=255)
        vig = vig.filter(ImageFilter.GaussianBlur(radius=14))
        return Image.merge("RGB", (vig, vig, vig))

    def reload_from_config(self):
        if not self.cfg_mgr:
            return
        a = self.cfg_mgr.config.get("ambient", {})
        with self._lock:
            new_mode = str(a.get("album_backdrop", "Desktop Layer"))
            new_dark = max(0.12, min(1.0, float(a.get("backdrop_darkness", 0.34))))
            new_disp = str(a.get("target_displays", "All Displays"))
            if new_disp != self.target_displays:
                self._dirty_monitors = True
            if new_mode != self.mode:
                self._dirty_mode = True
            if abs(new_dark - self.darkness) > 0.01:
                self._dirty_art = True
            self.mode = new_mode
            self.darkness = new_dark
            self.target_displays = new_disp
            self.show_over_fullscreen = bool(a.get("show_over_fullscreen", True))
            self.audio_reactive = bool(a.get("audio_reactive", True))

    def set_mode(self, mode_str: str):
        with self._lock:
            if self.mode != mode_str:
                self.mode = mode_str
                self._dirty_mode = True

    def set_darkness(self, val: float):
        with self._lock:
            self.darkness = max(0.12, min(1.0, float(val)))
            self._dirty_art = True

    def set_target_displays(self, target: str):
        with self._lock:
            if self.target_displays != target:
                self.target_displays = target
                self._dirty_monitors = True

    def set_show_over_fullscreen(self, enable: bool):
        with self._lock:
            self.show_over_fullscreen = bool(enable)

    def set_audio_reactive(self, enable: bool):
        with self._lock:
            self.audio_reactive = bool(enable)

    def update_media_state(self, thumb_img, colors, is_playing: bool, has_media: bool):
        with self._lock:
            art_changed = (thumb_img is not self._thumb_img) or (list(colors or []) != self._colors)
            self._thumb_img = thumb_img
            if colors:
                self._colors = list(colors)
            self._is_playing = bool(is_playing)
            self._has_media = bool(has_media)
            if art_changed:
                self._dirty_art = True

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

    def _rebuild_blurred_art_canvases(self, thumb_img, colors, darkness: float):
        """Precomputes an oversized softly-blurred album cover + 2 matching luminous blobs once per song."""
        c1 = _hex_to_rgb(colors[0] if colors else "#6366F1", (99, 102, 241))
        c2 = _hex_to_rgb(colors[1] if len(colors) > 1 else "#EC4899", (236, 72, 153))

        # Oversized (240x135) aspect-filled blurred album cover so we can smoothly pan & zoom in real time
        cov_w, cov_h = 240, 135
        if thumb_img is not None:
            try:
                src_rgb = thumb_img.convert("RGB")
                sw, sh = src_rgb.size
                target_ar = cov_w / cov_h
                src_ar = sw / max(1, sh)
                if src_ar > target_ar:
                    nw = int(sh * target_ar)
                    x0 = (sw - nw) // 2
                    src_rgb = src_rgb.crop((x0, 0, x0 + nw, sh))
                elif src_ar < target_ar:
                    nh = int(sw / target_ar)
                    y0 = (sh - nh) // 2
                    src_rgb = src_rgb.crop((0, y0, sw, y0 + nh))
                cover = src_rgb.resize((cov_w, cov_h), Image.Resampling.BILINEAR)
                cover = cover.filter(ImageFilter.GaussianBlur(radius=7.5))
                cover = ImageEnhance.Brightness(cover).enhance(max(0.18, min(1.0, darkness)))
                cover = ImageEnhance.Color(cover).enhance(1.16)
                self._cover_src = cover
                self._base_bg = cover.crop((24, 13, 24 + self.SRC_W, 13 + self.SRC_H))
                # Sample two rich, album-matched colors directly from opposite quadrants of the blurred cover
                c1 = cover.getpixel((int(cov_w * 0.30), int(cov_h * 0.32)))
                c2 = cover.getpixel((int(cov_w * 0.70), int(cov_h * 0.68)))
            except Exception:
                self._cover_src = None
                self._base_bg = None
        else:
            self._cover_src = None
            self._base_bg = None

        if self._base_bg is None:
            self._base_bg = Image.new("RGB", (self.SRC_W, self.SRC_H), _tune_blob_rgb(c1, darkness * 0.25, 0.90))

        # Tune the 2 blobs to match the album cover's palette, sized so they stay cleanly apart
        blob_lum = max(0.24, min(1.0, darkness * 1.05))
        rgb1 = _tune_blob_rgb(c1, blob_lum, 1.18)
        rgb2 = _tune_blob_rgb(c2, blob_lum * 0.95, 1.20)
        self._blob_1 = _make_radial_blob(92, 82, rgb1, power=2.05)
        self._blob_2 = _make_radial_blob(90, 90, rgb2, power=2.10)

    def _create_windows(self, monitors, mode_str):
        overlays = []
        hwnds = []
        if IS_WIN:
            ex_style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            z_anchor = HWND_TOP if mode_str == "Cinema Stage" else HWND_BOTTOM
            for mon in monitors:
                hwnd = user32.CreateWindowExW(
                    ex_style, _CLASS_NAME, f"SoulsLightsBackdrop_{mon['device']}",
                    WS_POPUP,
                    mon["x"], mon["y"], mon["w"], mon["h"],
                    None, None, kernel32.GetModuleHandleW(None), None
                )
                if hwnd:
                    user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)
                    user32.SetWindowPos(hwnd, z_anchor, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                    surf = ScaledBlitSurface(self.SRC_W, self.SRC_H)
                    overlays.append({
                        "mon": mon,
                        "hwnd": hwnd,
                        "win": None,
                        "surf": surf,
                        "visible": False,
                    })
                    hwnds.append(hwnd)
        else:
            role = "cinema" if mode_str == "Cinema Stage" else "desktop"
            for mon in monitors:
                win_obj = MacOverlayWindow(mon["x"], mon["y"], mon["w"], mon["h"], role=role, click_through=True)
                surf = ScaledBlitSurface(self.SRC_W, self.SRC_H)
                overlays.append({
                    "mon": mon,
                    "hwnd": None,
                    "win": win_obj,
                    "surf": surf,
                    "visible": False,
                })
        self._hwnds = hwnds
        return overlays

    def _destroy_windows(self, overlays):
        for ov in overlays:
            try:
                ov["surf"].dispose()
            except Exception:
                pass
            try:
                if IS_WIN and ov.get("hwnd"):
                    user32.DestroyWindow(ov["hwnd"])
                elif ov.get("win"):
                    ov["win"].dispose()
            except Exception:
                pass
        self._hwnds = []

    def _render_anim_frame(self, t_anim: float, peak: float = 0.0, bloom: float = 0.0):
        """Composites 2 fluid album-matched blobs over the smoothly panning/zooming album cover."""
        if self._base_bg is None or self._blob_1 is None or self._blob_2 is None:
            return None

        # Animate the blurred album cover with slow Ken-Burns pan + beat-reactive zoom
        if self._cover_src is not None:
            cw, ch = self._cover_src.size
            zoom_k = 0.88 + 0.06 * math.sin(t_anim * 0.31) - min(0.06, bloom * 0.05)
            win_w = max(120, min(cw - 4, int(self.SRC_W * zoom_k)))
            win_h = max(68, min(ch - 4, int(self.SRC_H * zoom_k)))
            max_ox = max(1, cw - win_w)
            max_oy = max(1, ch - win_h)
            ox = int(max_ox * (0.5 + 0.45 * math.sin(t_anim * 0.22)))
            oy = int(max_oy * (0.5 + 0.45 * math.cos(t_anim * 0.17)))
            base = self._cover_src.crop((ox, oy, ox + win_w, oy + win_h)).resize(
                (self.SRC_W, self.SRC_H), Image.Resampling.BILINEAR
            )
        else:
            base = self._base_bg

        # Slight breathing zoom on beat bloom (clamped so blobs never grow enough to touch)
        scale1 = 0.94 + 0.08 * math.sin(t_anim * 0.48) + min(0.08, bloom * 0.08)
        scale2 = 0.94 + 0.08 * math.cos(t_anim * 0.42 + 1.1) + min(0.08, bloom * 0.08)

        b1_w = max(60, int(self._blob_1.width * scale1))
        b1_h = max(56, int(self._blob_1.height * scale1))
        b2_w = max(60, int(self._blob_2.width * scale2))
        b2_h = max(56, int(self._blob_2.height * scale2))

        b1 = self._blob_1.resize((b1_w, b1_h), Image.Resampling.BILINEAR)
        b2 = self._blob_2.resize((b2_w, b2_h), Image.Resampling.BILINEAR)

        # Opposing separated orbits (left-side vs right-side) so the 2 blobs never touch or overlap
        cx1 = int(self.SRC_W * (0.19 + 0.05 * math.sin(t_anim * 0.34)))
        cy1 = int(self.SRC_H * (0.36 + 0.22 * math.cos(t_anim * 0.27)))
        cx2 = int(self.SRC_W * (0.81 - 0.05 * math.sin(t_anim * 0.34)))
        cy2 = int(self.SRC_H * (0.64 - 0.22 * math.cos(t_anim * 0.27)))

        self._tmp_a.paste((0, 0, 0), (0, 0, self.SRC_W, self.SRC_H))
        self._tmp_a.paste(b1, (cx1 - b1_w // 2, cy1 - b1_h // 2))

        self._tmp_b.paste((0, 0, 0), (0, 0, self.SRC_W, self.SRC_H))
        self._tmp_b.paste(b2, (cx2 - b2_w // 2, cy2 - b2_h // 2))

        scene = ImageChops.screen(base, self._tmp_a)
        scene = ImageChops.screen(scene, self._tmp_b)
        return ImageChops.multiply(scene, self._vig_mul)

    def _run_loop(self):
        enable_high_res_timer()
        try:
            self._run_loop_impl()
        except Exception:
            try:
                log_p = os.path.join(get_app_data_dir(), "app.log")
                with open(log_p, "a", encoding="utf-8") as f:
                    f.write(f"[AlbumBackdropEngine ERROR]\n{traceback.format_exc()}\n")
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
            mode_str = self.mode
        overlays = self._create_windows(monitors, mode_str)
        if not overlays:
            audio.dispose()
            self.running = False
            return

        msg = wintypes.MSG() if IS_WIN else None
        last_t = time.perf_counter()
        anim_t = 0.0
        fade_alpha = 0.0
        last_z_sync = 0.0
        target_dt = 1.0 / 60.0
        next_frame = last_t + target_dt
        dark_bg = Image.new("RGB", (self.SRC_W, self.SRC_H), (8, 9, 14))

        try:
            while self.running:
                if IS_WIN:
                    for ov in overlays:
                        while user32.PeekMessageW(ctypes.byref(msg), ov["hwnd"], 0, 0, 1):
                            user32.TranslateMessage(ctypes.byref(msg))
                            user32.DispatchMessageW(ctypes.byref(msg))

                now = time.perf_counter()
                dt = max(0.004, min(0.08, now - last_t))
                last_t = now

                with self._lock:
                    rebuild_mons = self._dirty_monitors
                    rebuild_art = self._dirty_art
                    mode_dirty = self._dirty_mode
                    self._dirty_monitors = False
                    self._dirty_art = False
                    self._dirty_mode = False

                    mode_str = self.mode
                    darkness = self.darkness
                    thumb = self._thumb_img
                    colors = list(self._colors)
                    has_media = self._has_media
                    is_playing = self._is_playing
                    audio_on = self.audio_reactive
                    if rebuild_mons:
                        new_mons = self._select_monitors()

                if rebuild_mons:
                    self._destroy_windows(overlays)
                    overlays = self._create_windows(new_mons, mode_str)
                    mode_dirty = True

                if rebuild_art:
                    self._rebuild_blurred_art_canvases(thumb, colors, darkness)

                want_visible = (mode_str != "Off") and has_media
                target_alpha = 248.0 if (want_visible and mode_str == "Cinema Stage") else (228.0 if want_visible else 0.0)
                fade_step = dt * (420.0 if target_alpha > fade_alpha else 480.0)
                if fade_alpha < target_alpha:
                    fade_alpha = min(target_alpha, fade_alpha + fade_step)
                else:
                    fade_alpha = max(target_alpha, fade_alpha - fade_step)

                if fade_alpha <= 2.0 and (mode_str == "Off" or not has_media):
                    for ov in overlays:
                        if ov["visible"]:
                            ov["visible"] = False
                            if IS_WIN:
                                user32.ShowWindow(ov["hwnd"], SW_HIDE)
                            else:
                                ov["win"].set_visible(False)
                    time.sleep(0.06)
                    next_frame = time.perf_counter() + target_dt
                    continue

                if mode_dirty or (now - last_z_sync > 0.6):
                    last_z_sync = now
                    if IS_WIN:
                        z_anchor = HWND_TOP if mode_str == "Cinema Stage" else HWND_BOTTOM
                        for ov in overlays:
                            user32.SetWindowPos(ov["hwnd"], z_anchor, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                    elif mode_dirty:
                        role = "cinema" if mode_str == "Cinema Stage" else "desktop"
                        for ov in overlays:
                            ov["win"].set_role(role)

                peak, bloom = audio.sample() if (audio_on and is_playing) else (0.0, 0.0)
                anim_t += dt * ((1.0 + bloom * 0.9) if is_playing else 0.25)
                frame_rgb = self._render_anim_frame(anim_t, peak, bloom) or dark_bg

                a_byte = max(0, min(255, int(round(fade_alpha))))
                for ov in overlays:
                    if IS_WIN:
                        if not ov["visible"]:
                            ov["visible"] = True
                            user32.ShowWindow(ov["hwnd"], SW_SHOWNOACTIVATE)
                            z_anchor = HWND_TOP if mode_str == "Cinema Stage" else HWND_BOTTOM
                            user32.SetWindowPos(ov["hwnd"], z_anchor, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                        ov["surf"].upload_rgb(frame_rgb)
                        user32.SetLayeredWindowAttributes(ov["hwnd"], 0, a_byte, LWA_ALPHA)
                        ov["surf"].present_stretched(ov["hwnd"], ov["mon"]["w"], ov["mon"]["h"])
                    else:
                        if not ov["visible"]:
                            ov["visible"] = True
                            ov["win"].set_visible(True)
                        ov["surf"].upload_rgb(frame_rgb)
                        ov["surf"].present_stretched(ov["win"], ov["mon"]["w"], ov["mon"]["h"], master_alpha=a_byte)

                now_end = time.perf_counter()
                rem_sleep = next_frame - now_end
                if rem_sleep > 0.001:
                    time.sleep(rem_sleep)
                    next_frame += target_dt
                else:
                    next_frame = now_end + target_dt
        finally:
            self._destroy_windows(overlays)
            audio.dispose()
