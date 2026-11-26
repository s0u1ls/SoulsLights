"""macOS native AppKit / Quartz / CoreGraphics backend for SoulsLights overlays."""
import os
import sys
import math
import time
import queue
import threading
import collections
from PIL import Image, ImageChops

HAS_MAC_OBJC = False
HAS_QUARTZ = False

AppKit = None
Foundation = None
Quartz = None
objc = None

if sys.platform == "darwin":
    try:
        import objc as _objc
        import Foundation as _Foundation
        import AppKit as _AppKit
        objc = _objc
        Foundation = _Foundation
        AppKit = _AppKit
        HAS_MAC_OBJC = True
    except Exception:
        pass
    try:
        import Quartz as _Quartz
        Quartz = _Quartz
        HAS_QUARTZ = True
    except Exception:
        pass


def enable_high_res_timer():
    """No-op on macOS (mach timer dispatch is already sub-millisecond)."""
    return


def disable_high_res_timer():
    return


def _primary_screen_height() -> float:
    if HAS_MAC_OBJC:
        try:
            screens = AppKit.NSScreen.screens()
            if screens and len(screens) > 0:
                return float(screens[0].frame().size.height)
        except Exception:
            pass
    return 1080.0


def get_monitors() -> list:
    """Returns active displays normalized to top-left desktop coordinates (points)."""
    mons = []
    if HAS_MAC_OBJC:
        try:
            screens = AppKit.NSScreen.screens()
            if screens and len(screens) > 0:
                prim_h = float(screens[0].frame().size.height)
                for idx, scr in enumerate(screens):
                    f = scr.frame()
                    x = int(round(float(f.origin.x)))
                    w = int(round(float(f.size.width)))
                    h = int(round(float(f.size.height)))
                    # Flip Cocoa bottom-left Y -> desktop top-left Y
                    y = int(round(prim_h - (float(f.origin.y) + float(f.size.height))))
                    name = ""
                    try:
                        if hasattr(scr, "localizedName"):
                            name = str(scr.localizedName() or "")
                    except Exception:
                        name = ""
                    if not name:
                        name = f"Display {idx + 1}"
                    try:
                        scale = float(scr.backingScaleFactor())
                    except Exception:
                        scale = 1.0
                    mons.append({
                        "device": name,
                        "primary": (idx == 0),
                        "x": x,
                        "y": y,
                        "w": max(1, w),
                        "h": max(1, h),
                        "scale": scale,
                    })
        except Exception:
            mons = []

    if not mons and HAS_QUARTZ:
        try:
            err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
            if err == 0 and count:
                for idx, did in enumerate(ids[:count]):
                    r = Quartz.CGDisplayBounds(did)
                    mons.append({
                        "device": f"Display {idx + 1}",
                        "primary": bool(Quartz.CGDisplayIsMain(did)),
                        "x": int(r.origin.x),
                        "y": int(r.origin.y),
                        "w": max(1, int(r.size.width)),
                        "h": max(1, int(r.size.height)),
                        "scale": 1.0,
                    })
        except Exception:
            pass

    if not mons:
        mons.append({"device": "Built-in Display", "primary": True, "x": 0, "y": 0, "w": 1512, "h": 982, "scale": 2.0})
    return mons


def get_cursor_pos():
    """Returns global cursor position in top-left desktop coordinates."""
    if HAS_MAC_OBJC:
        try:
            loc = AppKit.NSEvent.mouseLocation()
            prim_h = _primary_screen_height()
            return int(round(float(loc.x))), int(round(prim_h - float(loc.y)))
        except Exception:
            pass
    return None


def is_foreground_fullscreen(mon: dict, ignore_hwnds=None) -> bool:
    """Checks if a non-shell foreground macOS window covers the entire given display."""
    if not (HAS_MAC_OBJC and HAS_QUARTZ):
        return False
    try:
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front:
            return False
        bid = str(front.bundleIdentifier() or "")
        if bid in ("com.apple.finder", "com.apple.dock", "com.apple.WindowManager"):
            return False
        fpid = int(front.processIdentifier())
        if fpid == os.getpid():
            return False

        opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        win_list = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
        for info in (win_list or []):
            if int(info.get(Quartz.kCGWindowOwnerPID, 0)) != fpid:
                continue
            if int(info.get(Quartz.kCGWindowLayer, 0)) != 0:
                continue
            b = info.get(Quartz.kCGWindowBounds)
            if not b:
                continue
            wx = float(b.get("X", 0))
            wy = float(b.get("Y", 0))
            ww = float(b.get("Width", 0))
            wh = float(b.get("Height", 0))
            if (
                wx <= mon["x"] + 2
                and wy <= mon["y"] + 2
                and (wx + ww) >= (mon["x"] + mon["w"] - 2)
                and (wy + wh) >= (mon["y"] + mon["h"] - 2)
            ):
                return True
    except Exception:
        pass
    return False


# ---- Main-thread UI / AppKit Task Dispatcher ----
_MAIN_TASKS = queue.SimpleQueue()


def _schedule_nsqueue(fn):
    if HAS_MAC_OBJC and Foundation is not None:
        try:
            Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(fn)
            return True
        except Exception:
            pass
    return False


def run_on_main(fn, wait: bool = False, timeout: float = 1.0):
    """Executes fn on the macOS AppKit / Tk main thread safely."""
    if threading.current_thread() is threading.main_thread():
        fn()
        return
    if not wait:
        if not _schedule_nsqueue(fn):
            _MAIN_TASKS.put(fn)
        return

    done = threading.Event()
    err_box = [None]

    def _wrapped():
        try:
            fn()
        except Exception as e:
            err_box[0] = e
        finally:
            done.set()

    if not _schedule_nsqueue(_wrapped):
        _MAIN_TASKS.put(_wrapped)
    done.wait(timeout=timeout)
    if err_box[0] is not None:
        raise err_box[0]


def drain_main_tasks():
    """Called periodically on main thread by UnifiedDashboard as extra fallback pump."""
    for _ in range(64):
        try:
            fn = _MAIN_TASKS.get_nowait()
        except queue.Empty:
            break
        try:
            fn()
        except Exception:
            pass


# ---- Custom NSView Supporting Click-Through Toggle & Native Dragging ----
_DRAGGABLE_VIEW_CLS = None


def _get_draggable_view_class():
    global _DRAGGABLE_VIEW_CLS
    if _DRAGGABLE_VIEW_CLS is not None or not HAS_MAC_OBJC:
        return _DRAGGABLE_VIEW_CLS

    try:
        existing = objc.lookUpClass("SoulsLightsOverlayView")
        if existing is not None:
            _DRAGGABLE_VIEW_CLS = existing
            return _DRAGGABLE_VIEW_CLS
    except Exception:
        pass

    class SoulsLightsOverlayView(AppKit.NSView):
        def initWithFrame_(self, frame):
            self = objc.super(SoulsLightsOverlayView, self).initWithFrame_(frame)
            if self is not None:
                self._py_owner = None
                self.setWantsLayer_(True)
                layer = Quartz.CALayer.layer() if HAS_QUARTZ else None
                if layer is not None:
                    layer.setContentsScale_(1.0)
                    layer.setOpaque_(False)
                    self.setLayer_(layer)
            return self

        def acceptsFirstMouse_(self, event):
            return True

        def mouseDown_(self, event):
            owner = getattr(self, "_py_owner", None)
            win = self.window()
            if not owner or not win or owner.click_through:
                return
            try:
                win.performWindowDragWithEvent_(event)
                owner._notify_moved()
            except Exception:
                pass

        def mouseUp_(self, event):
            owner = getattr(self, "_py_owner", None)
            if owner and not owner.click_through:
                owner._notify_moved()

    _DRAGGABLE_VIEW_CLS = SoulsLightsOverlayView
    return _DRAGGABLE_VIEW_CLS


def _cgimage_from_bgra_bytes(raw_bytes: bytes, w: int, h: int, opaque_rgbx: bool = False):
    if not (HAS_MAC_OBJC and HAS_QUARTZ) or w <= 0 or h <= 0 or not raw_bytes:
        return None
    ns_data = Foundation.NSData.dataWithBytes_length_(raw_bytes, len(raw_bytes))
    provider = Quartz.CGDataProviderCreateWithCFData(ns_data)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    alpha_flag = (
        Quartz.kCGImageAlphaNoneSkipFirst if opaque_rgbx else Quartz.kCGImageAlphaPremultipliedFirst
    )
    bitmap_info = Quartz.kCGBitmapByteOrder32Little | alpha_flag
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, cs, bitmap_info, provider, None, True, Quartz.kCGRenderingIntentDefault
    )


class MacOverlayWindow:
    """Thread-safe controller for a hardware-composited borderless transparent NSWindow."""

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        role: str = "lyrics",
        click_through: bool = True,
        on_move=None,
    ):
        self.x = int(x)
        self.y = int(y)
        self.w = max(1, int(w))
        self.h = max(1, int(h))
        self.role = role  # "lyrics", "glow", "cinema", "desktop"
        self.click_through = bool(click_through)
        self.on_move = on_move
        self.visible = False

        self._nswindow = None
        self._nsview = None
        self._disposed = False

        self._frame_lock = threading.Lock()
        self._pending_frame = None
        self._flush_queued = False

        run_on_main(self._create_on_main, wait=False)

    def _window_level(self) -> int:
        if not HAS_MAC_OBJC:
            return 0
        if self.role == "desktop" and HAS_QUARTZ:
            try:
                return int(Quartz.CGWindowLevelForKey(Quartz.kCGDesktopIconWindowLevelKey)) - 1
            except Exception:
                return int(AppKit.kCGDesktopWindowLevel) + 1
        if self.role == "cinema":
            return int(AppKit.NSFloatingWindowLevel)
        if self.role == "glow":
            return int(AppKit.NSScreenSaverWindowLevel) - 1
        return int(AppKit.NSScreenSaverWindowLevel)

    def _to_cocoa_rect(self, x: int, y: int, w: int, h: int):
        prim_h = _primary_screen_height()
        cy = prim_h - (float(y) + float(h))
        return AppKit.NSMakeRect(float(x), cy, float(w), float(h))

    def _create_on_main(self):
        if self._disposed or not HAS_MAC_OBJC:
            return
        rect = self._to_cocoa_rect(self.x, self.y, self.w, self.h)
        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        win.setOpaque_(False)
        win.setBackgroundColor_(AppKit.NSColor.clearColor())
        win.setHasShadow_(False)
        win.setReleasedWhenClosed_(False)
        win.setIgnoresMouseEvents_(self.click_through)
        win.setLevel_(self._window_level())
        behavior = (
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )
        if hasattr(AppKit, "NSWindowCollectionBehaviorFullScreenAuxiliary"):
            behavior |= AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        win.setCollectionBehavior_(behavior)

        view_cls = _get_draggable_view_class()
        view = view_cls.alloc().initWithFrame_(AppKit.NSMakeRect(0.0, 0.0, float(self.w), float(self.h)))
        view._py_owner = self
        win.setContentView_(view)

        self._nswindow = win
        self._nsview = view
        if self.visible:
            win.orderFrontRegardless()

    def _notify_moved(self):
        if not (self._nswindow and self.on_move and HAS_MAC_OBJC):
            return
        try:
            f = self._nswindow.frame()
            prim_h = _primary_screen_height()
            nx = int(round(float(f.origin.x)))
            ny = int(round(prim_h - (float(f.origin.y) + float(f.size.height))))
            self.x, self.y = nx, ny
            self.on_move(nx, ny)
        except Exception:
            pass

    def set_role(self, role: str):
        self.role = role
        def _do():
            if self._nswindow and not self._disposed:
                self._nswindow.setLevel_(self._window_level())
        run_on_main(_do)

    def set_click_through(self, enable: bool):
        self.click_through = bool(enable)
        def _do():
            if self._nswindow and not self._disposed:
                self._nswindow.setIgnoresMouseEvents_(self.click_through)
        run_on_main(_do)

    def set_visible(self, visible: bool):
        self.visible = bool(visible)
        def _do():
            if not self._nswindow or self._disposed:
                return
            if visible:
                self._nswindow.orderFrontRegardless()
            else:
                self._nswindow.orderOut_(None)
        run_on_main(_do)

    def set_geometry(self, x: int, y: int, w: int = None, h: int = None):
        self.x, self.y = int(x), int(y)
        if w is not None:
            self.w = max(1, int(w))
        if h is not None:
            self.h = max(1, int(h))
        nx, ny, nw, nh = self.x, self.y, self.w, self.h
        def _do():
            if not self._nswindow or self._disposed:
                return
            self._nswindow.setFrame_display_(self._to_cocoa_rect(nx, ny, nw, nh), True)
            if self._nsview:
                self._nsview.setFrameSize_(AppKit.NSMakeSize(float(nw), float(nh)))
        run_on_main(_do)

    def stage_present(self, raw_bytes: bytes, img_w: int, img_h: int, x: int = None, y: int = None, alpha_byte: int = 255, opaque_rgbx: bool = False):
        if self._disposed:
            return
        with self._frame_lock:
            self._pending_frame = (raw_bytes, int(img_w), int(img_h), x, y, int(alpha_byte), bool(opaque_rgbx))
            should_sched = not self._flush_queued
            self._flush_queued = True
        if should_sched:
            run_on_main(self._flush_on_main, wait=False)

    def _flush_on_main(self):
        with self._frame_lock:
            self._flush_queued = False
            frame = self._pending_frame
            self._pending_frame = None
        if frame is None or self._disposed or not self._nswindow or not self._nsview:
            return
        raw_bytes, img_w, img_h, x, y, alpha_byte, opaque_rgbx = frame
        try:
            if not self.visible:
                self.visible = True
                self._nswindow.orderFrontRegardless()
            if x is not None and y is not None and (int(x) != self.x or int(y) != self.y):
                self.x, self.y = int(x), int(y)
                self._nswindow.setFrameOrigin_(self._to_cocoa_rect(self.x, self.y, self.w, self.h).origin)

            cg_img = _cgimage_from_bgra_bytes(raw_bytes, img_w, img_h, opaque_rgbx=opaque_rgbx)
            layer = self._nsview.layer()
            if layer is not None and cg_img is not None:
                if HAS_QUARTZ:
                    Quartz.CATransaction.begin()
                    Quartz.CATransaction.setDisableActions_(True)
                    if opaque_rgbx:
                        layer.setMagnificationFilter_(Quartz.kCAFilterLinear)
                        layer.setContentsGravity_(Quartz.kCAGravityResize)
                    layer.setContents_(cg_img)
                    layer.setOpacity_(max(0.0, min(1.0, alpha_byte / 255.0)))
                    Quartz.CATransaction.commit()
                else:
                    layer.setContents_(cg_img)
            self._nswindow.setAlphaValue_(max(0.0, min(1.0, alpha_byte / 255.0)))
        except Exception:
            pass

    def dispose(self):
        self._disposed = True
        def _do():
            if self._nsview:
                try:
                    self._nsview._py_owner = None
                except Exception:
                    pass
                self._nsview = None
            if self._nswindow:
                try:
                    self._nswindow.orderOut_(None)
                    self._nswindow.close()
                except Exception:
                    pass
                self._nswindow = None
        run_on_main(_do, wait=False)


class MacLayeredSurface:
    """macOS RGBA backing buffer matching win32_utils.LayeredSurface method signatures."""

    def __init__(self, width: int, height: int):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self._buf = bytearray(self.width * self.height * 4)

    def clear_surface(self):
        self._buf[:] = b"\x00" * (self.width * self.height * 4)

    def upload_pil_rgba(self, pil_img: Image.Image):
        if pil_img.size != (self.width, self.height):
            pil_img = pil_img.resize((self.width, self.height))
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")
        raw = pil_img.tobytes("raw", "BGRa")
        self._buf[:] = raw

    def upload_rgb_alpha(self, rgb_img: Image.Image, alpha_l: Image.Image):
        if rgb_img.size != (self.width, self.height):
            rgb_img = rgb_img.resize((self.width, self.height), Image.Resampling.BILINEAR)
        if alpha_l.size != (self.width, self.height):
            alpha_l = alpha_l.resize((self.width, self.height), Image.Resampling.BILINEAR)
        out = rgb_img.convert("RGB")
        out.putalpha(alpha_l)
        self._buf[:] = out.tobytes("raw", "BGRa")

    def upload_rect_rgba(self, sub_img: Image.Image, rect, prev_rect=None):
        w, h = self.width, self.height
        stride = w * 4
        mv = memoryview(self._buf)

        if prev_rect:
            px0, py0, px1, py1 = prev_rect
            px0 = max(0, px0); py0 = max(0, py0)
            px1 = min(w, px1); py1 = min(h, py1)
            if px1 > px0 and py1 > py0:
                if px0 == 0 and px1 == w:
                    mv[py0 * stride : py1 * stride] = b"\x00" * ((py1 - py0) * stride)
                else:
                    pw4 = (px1 - px0) * 4
                    zrow = b"\x00" * pw4
                    for yy in range(py0, py1):
                        off = yy * stride + px0 * 4
                        mv[off : off + pw4] = zrow

        if sub_img is None or rect is None:
            return
        x0, y0, x1, y1 = rect
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(w, x1); y1 = min(h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        cw, ch = x1 - x0, y1 - y0
        if sub_img.size != (cw, ch):
            sub_img = sub_img.resize((cw, ch))
        if sub_img.mode != "RGBA":
            sub_img = sub_img.convert("RGBA")
        raw = memoryview(sub_img.tobytes("raw", "BGRa"))
        if x0 == 0 and x1 == w:
            mv[y0 * stride : y0 * stride + len(raw)] = raw
            return
        cw4 = cw * 4
        for yy in range(ch):
            si = yy * cw4
            di = (y0 + yy) * stride + x0 * 4
            mv[di : di + cw4] = raw[si : si + cw4]

    def present(self, win_obj: MacOverlayWindow, x: int, y: int, master_alpha: int = 255):
        if win_obj is None:
            return False
        win_obj.stage_present(
            bytes(self._buf), self.width, self.height,
            x=x, y=y, alpha_byte=max(0, min(255, int(master_alpha))), opaque_rgbx=False
        )
        return True

    def dispose(self):
        self._buf.clear()


class MacScaledBlitSurface:
    """macOS Metal/CALayer bilinear-stretched backdrop surface matching ScaledBlitSurface."""

    def __init__(self, src_w: int = 192, src_h: int = 108):
        self.width = max(1, int(src_w))
        self.height = max(1, int(src_h))
        self._raw = b"\x00" * (self.width * self.height * 4)

    def upload_rgb(self, pil_img: Image.Image):
        if pil_img.size != (self.width, self.height):
            pil_img = pil_img.resize((self.width, self.height), Image.Resampling.BILINEAR)
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        self._raw = pil_img.tobytes("raw", "BGRX")

    def present_stretched(self, win_obj: MacOverlayWindow, dst_w: int, dst_h: int, master_alpha: int = 255):
        if win_obj is None:
            return False
        win_obj.stage_present(
            self._raw, self.width, self.height,
            alpha_byte=max(0, min(255, int(master_alpha))), opaque_rgbx=True
        )
        return True

    def dispose(self):
        self._raw = b""


class SystemAudioMeter:
    """macOS audio-reactivity adapter (graceful rhythmic envelope without intrusive mic/screen prompts)."""

    def __init__(self):
        self._fast_ema = 0.0
        self._slow_ema = 0.0
        self._bloom = 0.0
        self._last_time = time.perf_counter()
        self._playing_hint = False

    def init_com(self):
        return True

    def set_playing_hint(self, is_playing: bool):
        self._playing_hint = bool(is_playing)

    def sample(self):
        """Returns (norm_level 0..1, beat_bloom 0..1)."""
        now = time.perf_counter()
        dt = max(0.001, min(0.2, now - self._last_time))
        self._last_time = now

        # Smooth multi-harmonic groove pulse synced to monotonic playback clock
        beat_phase = (now * 2.05) % 1.0  # ~123 BPM subtle musical envelope
        transient = max(0.0, 1.0 - beat_phase * 4.2) ** 2.1
        sub_groove = 0.5 + 0.5 * math.sin(now * 3.14)
        peak = 0.28 + 0.48 * transient + 0.14 * sub_groove
        bloom = min(1.0, transient * 0.72 + sub_groove * 0.18)

        k_f = min(1.0, dt * 16.0)
        self._fast_ema = self._fast_ema * (1.0 - k_f) + peak * k_f
        self._bloom = self._bloom * math.exp(-dt * 7.5)
        self._bloom = max(self._bloom, bloom)
        return min(1.0, self._fast_ema), min(1.0, self._bloom)

    def dispose(self):
        pass
