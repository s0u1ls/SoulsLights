import ctypes
from ctypes import wintypes
import uuid
import math
import time
import threading

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
ole32 = ctypes.windll.ole32
kernel32 = ctypes.windll.kernel32
winmm = ctypes.windll.winmm

_timer_lock = threading.Lock()
_timer_refs = 0


def enable_high_res_timer():
    """Requests 1ms Windows multimedia timer resolution while high-FPS overlays are active."""
    global _timer_refs
    with _timer_lock:
        if _timer_refs == 0:
            try:
                winmm.timeBeginPeriod(1)
            except Exception:
                pass
        _timer_refs += 1


def disable_high_res_timer():
    """Releases 1ms Windows multimedia timer resolution cleanly."""
    global _timer_refs
    with _timer_lock:
        if _timer_refs > 0:
            _timer_refs -= 1
            if _timer_refs == 0:
                try:
                    winmm.timeEndPeriod(1)
                except Exception:
                    pass

# ---- 64-bit safe Win32 / GDI32 / Ole32 prototypes ----
LRESULT = ctypes.c_int64

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)

# Configure argtypes/restypes for 64-bit Windows
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC

user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
    wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL

user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LRESULT

user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL

user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL

user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL

gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetStretchBltMode.restype = ctypes.c_int

gdi32.StretchBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD
]
gdi32.StretchBlt.restype = wintypes.BOOL

gdi32.GdiAlphaBlend.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD
]
gdi32.GdiAlphaBlend.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL

gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP

gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ

gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

# Win32 Constants
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

GWL_EXSTYLE = -20
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOP = wintypes.HWND(0)
HWND_BOTTOM = wintypes.HWND(1)
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)

ULW_ALPHA = 0x00000002
LWA_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
SRCCOPY = 0x00CC0020
HALFTONE = 4

WM_CLOSE = 0x0010
WM_LBUTTONDOWN = 0x0201
WM_NCLBUTTONDOWN = 0x00A1
WM_MOVE = 0x0003
HTCAPTION = 2
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4


def get_monitors():
    """Returns list of active displays with device name, bounds, and primary flag."""
    monitors = []

    def _cb(hmon, hdc, lprect, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            monitors.append({
                "device": mi.szDevice,
                "primary": bool(mi.dwFlags & 1),
                "x": int(r.left),
                "y": int(r.top),
                "w": int(r.right - r.left),
                "h": int(r.bottom - r.top),
            })
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    if not monitors:
        monitors.append({
            "device": "DISPLAY1",
            "primary": True,
            "x": 0,
            "y": 0,
            "w": user32.GetSystemMetrics(0) or 1920,
            "h": user32.GetSystemMetrics(1) or 1080,
        })
    return monitors


def is_foreground_fullscreen(mon, ignore_hwnds=None):
    """Checks if a non-shell foreground window covers the given monitor entirely."""
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    if ignore_hwnds and fg in ignore_hwnds:
        return False

    cls_buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(fg, cls_buf, 128)
    cls_name = cls_buf.value
    if cls_name in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False

    rect = RECT()
    if not user32.GetWindowRect(fg, ctypes.byref(rect)):
        return False

    return (
        rect.left <= mon["x"]
        and rect.top <= mon["y"]
        and rect.right >= mon["x"] + mon["w"]
        and rect.bottom >= mon["y"] + mon["h"]
    )


class LayeredSurface:
    """Manages a 32-bit premultiplied ARGB DIB section for UpdateLayeredWindow."""
    def __init__(self, width, height):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.hdc_screen = user32.GetDC(0)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.width
        bmi.bmiHeader.biHeight = -self.height  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        self.ppv_bits = ctypes.c_void_p()
        self.h_bitmap = gdi32.CreateDIBSection(
            self.hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(self.ppv_bits), None, 0
        )
        self.old_obj = gdi32.SelectObject(self.hdc_mem, self.h_bitmap) if self.h_bitmap else None
        self.pt_src = POINT(0, 0)
        self.size = SIZE(self.width, self.height)

    def upload_pil_rgba(self, pil_img):
        """Copies a PIL RGBA image (premultiplied BGRa) directly into the DIB."""
        if not self.ppv_bits or not self.ppv_bits.value:
            return
        if pil_img.size != (self.width, self.height):
            pil_img = pil_img.resize((self.width, self.height))
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")
        raw = pil_img.tobytes("raw", "BGRa")
        ctypes.memmove(self.ppv_bits, raw, len(raw))

    def upload_rgb_alpha(self, rgb_img, alpha_l):
        """Fast C copy for an RGB strip + L alpha mask straight into a matched DIB."""
        if not self.ppv_bits or not self.ppv_bits.value:
            return
        if rgb_img.size != (self.width, self.height):
            from PIL import Image
            rgb_img = rgb_img.resize((self.width, self.height), Image.Resampling.BILINEAR)
        if alpha_l.size != (self.width, self.height):
            from PIL import Image
            alpha_l = alpha_l.resize((self.width, self.height), Image.Resampling.BILINEAR)
        rgb_img.putalpha(alpha_l)
        raw = rgb_img.tobytes("raw", "BGRa")
        ctypes.memmove(self.ppv_bits, raw, len(raw))

    def clear_surface(self):
        """Zeroes the DIB so non-edge interior pixels remain 100% transparent."""
        if self.ppv_bits and self.ppv_bits.value:
            ctypes.memset(self.ppv_bits, 0, self.width * self.height * 4)

    def upload_rect_rgba(self, sub_img, rect, prev_rect=None):
        """Fast dirty-rectangle RGBA upload into a large DIB (zeroing only prev_rect if given)."""
        if not self.ppv_bits or not self.ppv_bits.value:
            return
        w, h = self.width, self.height
        stride = w * 4
        base_addr = self.ppv_bits.value
        dib_arr = (ctypes.c_ubyte * (h * stride)).from_address(base_addr)
        mv = memoryview(dib_arr).cast("B")

        if prev_rect:
            px0, py0, px1, py1 = prev_rect
            px0 = max(0, px0); py0 = max(0, py0)
            px1 = min(w, px1); py1 = min(h, py1)
            if px1 > px0 and py1 > py0:
                if px0 == 0 and px1 == w:
                    ctypes.memset(base_addr + py0 * stride, 0, (py1 - py0) * stride)
                else:
                    pw4 = (px1 - px0) * 4
                    zero_row = b"\x00" * pw4
                    for yy in range(py0, py1):
                        off = yy * stride + px0 * 4
                        mv[off : off + pw4] = zero_row

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
        raw_bytes = sub_img.tobytes("raw", "BGRa")
        if x0 == 0 and x1 == w:
            ctypes.memmove(base_addr + y0 * stride, raw_bytes, len(raw_bytes))
            return
        raw = memoryview(raw_bytes)
        cw4 = cw * 4
        for yy in range(ch):
            si = yy * cw4
            di = (y0 + yy) * stride + x0 * 4
            mv[di : di + cw4] = raw[si : si + cw4]

    def upload_edge_strips(self, rgb_lo, m_top, m_bot, m_left, m_right, strip_px: int, drop_lo=None):
        """Fast path for rim overlays: updates only the 4 outer border strips into the DIB."""
        if not self.ppv_bits or not self.ppv_bits.value:
            return
        from PIL import Image, ImageChops
        w, h, s = self.width, self.height, strip_px
        lw, lh = rgb_lo.size
        sl = max(1, min(lh // 2, int(round(s * lw / max(1, w)))))
        stride = w * 4
        base_addr = self.ppv_bits.value

        def _prep_alpha(box, size_wh, base_mask):
            if drop_lo is None:
                return base_mask
            d_strip = drop_lo.crop(box).resize(size_wh, Image.Resampling.BILINEAR)
            return ImageChops.multiply(base_mask, d_strip)

        # Top strip
        t_box = (0, 0, lw, sl)
        top_rgb = rgb_lo.crop(t_box).resize((w, s), Image.Resampling.BILINEAR)
        top_rgb.putalpha(_prep_alpha(t_box, (w, s), m_top))
        top_raw = top_rgb.tobytes("raw", "BGRa")
        ctypes.memmove(base_addr, top_raw, len(top_raw))

        # Bottom strip
        b_box = (0, lh - sl, lw, lh)
        bot_rgb = rgb_lo.crop(b_box).resize((w, s), Image.Resampling.BILINEAR)
        bot_rgb.putalpha(_prep_alpha(b_box, (w, s), m_bot))
        bot_raw = bot_rgb.tobytes("raw", "BGRa")
        ctypes.memmove(base_addr + (h - s) * stride, bot_raw, len(bot_raw))

        # Side strips (middle rows y = s .. h - s)
        mid_h = h - 2 * s
        if mid_h > 0:
            l_box = (0, sl, sl, lh - sl)
            left_rgb = rgb_lo.crop(l_box).resize((s, mid_h), Image.Resampling.BILINEAR)
            left_rgb.putalpha(_prep_alpha(l_box, (s, mid_h), m_left))
            left_raw = memoryview(left_rgb.tobytes("raw", "BGRa"))

            r_box = (lw - sl, sl, lw, lh - sl)
            right_rgb = rgb_lo.crop(r_box).resize((s, mid_h), Image.Resampling.BILINEAR)
            right_rgb.putalpha(_prep_alpha(r_box, (s, mid_h), m_right))
            right_raw = memoryview(right_rgb.tobytes("raw", "BGRa"))

            dib_arr = (ctypes.c_ubyte * (h * stride)).from_address(base_addr)
            mv = memoryview(dib_arr).cast("B")
            sw4 = s * 4
            row_l0 = s * stride
            row_r0 = s * stride + (w - s) * 4
            for y in range(mid_h):
                si = y * sw4
                dl = row_l0 + y * stride
                dr = row_r0 + y * stride
                mv[dl : dl + sw4] = left_raw[si : si + sw4]
                mv[dr : dr + sw4] = right_raw[si : si + sw4]

    def present(self, hwnd, x, y, master_alpha=255):
        if not hwnd or not self.hdc_mem:
            return False
        pt_dest = POINT(int(x), int(y))
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, int(max(0, min(255, master_alpha))), AC_SRC_ALPHA)
        return bool(user32.UpdateLayeredWindow(
            hwnd, self.hdc_screen, ctypes.byref(pt_dest), ctypes.byref(self.size),
            self.hdc_mem, ctypes.byref(self.pt_src), 0, ctypes.byref(blend), ULW_ALPHA
        ))

    def dispose(self):
        if self.hdc_mem and self.old_obj:
            gdi32.SelectObject(self.hdc_mem, self.old_obj)
            self.old_obj = None
        if self.h_bitmap:
            gdi32.DeleteObject(self.h_bitmap)
            self.h_bitmap = None
        if self.hdc_mem:
            gdi32.DeleteDC(self.hdc_mem)
            self.hdc_mem = None
        if self.hdc_screen:
            user32.ReleaseDC(0, self.hdc_screen)
            self.hdc_screen = None


class ScaledBlitSurface:
    """GPU-bilinear stretched DIB surface via GdiAlphaBlend (~2.5ms at 1080p) for blurry backdrops."""
    def __init__(self, src_w=192, src_h=108):
        self.width = max(1, int(src_w))
        self.height = max(1, int(src_h))
        self.hdc_screen = user32.GetDC(0)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.width
        bmi.bmiHeader.biHeight = -self.height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        self.ppv_bits = ctypes.c_void_p()
        self.h_bitmap = gdi32.CreateDIBSection(
            self.hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(self.ppv_bits), None, 0
        )
        self.old_obj = gdi32.SelectObject(self.hdc_mem, self.h_bitmap) if self.h_bitmap else None
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, 0)
        self._blend_dw = ctypes.cast(ctypes.byref(blend), ctypes.POINTER(wintypes.DWORD)).contents.value

    def upload_rgb(self, pil_img):
        if not self.ppv_bits or not self.ppv_bits.value:
            return
        if pil_img.size != (self.width, self.height):
            from PIL import Image
            pil_img = pil_img.resize((self.width, self.height), Image.Resampling.BILINEAR)
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        raw = pil_img.tobytes("raw", "BGRX")
        ctypes.memmove(self.ppv_bits, raw, len(raw))

    def present_stretched(self, hwnd, dst_w, dst_h):
        if not hwnd or not self.hdc_mem:
            return False
        hdc_win = user32.GetDC(hwnd)
        if not hdc_win:
            return False
        try:
            gdi32.SetStretchBltMode(hdc_win, 4)  # HALFTONE smooth filtering (no blocky nearest-neighbor)
            return bool(gdi32.StretchBlt(
                hdc_win, 0, 0, int(dst_w), int(dst_h),
                self.hdc_mem, 0, 0, self.width, self.height, 0x00CC0020  # SRCCOPY
            ))
        finally:
            user32.ReleaseDC(hwnd, hdc_win)

    def dispose(self):
        if self.hdc_mem and self.old_obj:
            gdi32.SelectObject(self.hdc_mem, self.old_obj)
            self.old_obj = None
        if self.h_bitmap:
            gdi32.DeleteObject(self.h_bitmap)
            self.h_bitmap = None
        if self.hdc_mem:
            gdi32.DeleteDC(self.hdc_mem)
            self.hdc_mem = None
        if self.hdc_screen:
            user32.ReleaseDC(0, self.hdc_screen)
            self.hdc_screen = None


def _guid_from_str(s):
    u = uuid.UUID(s)
    g = GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    b = u.bytes[8:]
    for i in range(8):
        g.Data4[i] = b[i]
    return g


class SystemAudioMeter:
    """Reads live system audio output peak via Windows CoreAudio COM (IAudioMeterInformation)."""
    def __init__(self):
        self._meter_ptr = None
        self._get_peak_fn = None
        self._release_fn = None
        self._initialized = False
        self._fast_ema = 0.0
        self._slow_ema = 0.0
        self._floor_ema = 0.0
        self._ceiling = 0.08
        self._bloom = 0.0
        self._last_time = time.perf_counter()

    def init_com(self):
        if self._initialized:
            return self._get_peak_fn is not None
        self._initialized = True
        try:
            ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
            clsid_enum = _guid_from_str("BCDE0395-E52F-467C-8E3D-C4579291692E")
            iid_enum = _guid_from_str("A95664D2-9614-4F35-A746-DE8DB63617E6")
            iid_meter = _guid_from_str("C02216F6-8C67-4B5B-9D00-D008E73E0064")

            ppv_enum = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid_enum), None, 23, ctypes.byref(iid_enum), ctypes.byref(ppv_enum)
            )
            if hr != 0 or not ppv_enum.value:
                return False

            enum_vtbl = ctypes.cast(ppv_enum.value, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            get_default = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
            )(enum_vtbl[4])
            enum_release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(enum_vtbl[2])

            ppv_dev = ctypes.c_void_p()
            hr2 = get_default(ppv_enum.value, 0, 1, ctypes.byref(ppv_dev))
            enum_release(ppv_enum.value)
            if hr2 != 0 or not ppv_dev.value:
                return False

            dev_vtbl = ctypes.cast(ppv_dev.value, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            activate = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
            )(dev_vtbl[3])
            dev_release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(dev_vtbl[2])

            ppv_meter = ctypes.c_void_p()
            hr3 = activate(ppv_dev.value, ctypes.byref(iid_meter), 23, None, ctypes.byref(ppv_meter))
            dev_release(ppv_dev.value)
            if hr3 != 0 or not ppv_meter.value:
                return False

            m_vtbl = ctypes.cast(ppv_meter.value, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            self._meter_ptr = ppv_meter
            self._release_fn = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(m_vtbl[2])
            self._get_peak_fn = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float)
            )(m_vtbl[3])
            return True
        except Exception:
            return False

    def sample(self):
        """Returns (norm_level 0..1, beat_bloom 0..1) with volume-adaptive transient detection."""
        now = time.perf_counter()
        dt = max(0.001, min(0.2, now - self._last_time))
        self._last_time = now

        peak = 0.0
        if self._get_peak_fn and self._meter_ptr:
            val = ctypes.c_float()
            try:
                hr = self._get_peak_fn(self._meter_ptr.value, ctypes.byref(val))
                if hr == 0:
                    peak = max(0.0, min(1.0, float(val.value)))
            except Exception:
                peak = 0.0

        # Slow macro auto-gain ceiling (smooth attack + gentle release) so beat transients aren't swallowed
        if peak > self._ceiling:
            k_c = min(1.0, dt * 2.2)
            self._ceiling = self._ceiling * (1.0 - k_c) + peak * k_c
        else:
            self._ceiling = max(0.03, self._ceiling - dt * 0.14)

        raw_rel = min(2.2, peak / max(0.03, self._ceiling))
        norm_peak = min(1.0, raw_rel)

        # Asymmetric transient follower + adaptive energy average for punchy beat detection
        prev_fast = self._fast_ema
        k_fast = min(1.0, dt * (44.0 if raw_rel >= prev_fast else 18.0))
        k_slow = min(1.0, dt * 5.5)
        self._fast_ema = prev_fast * (1.0 - k_fast) + raw_rel * k_fast
        self._slow_ema = self._slow_ema * (1.0 - k_slow) + raw_rel * k_slow

        flux_fast = max(0.0, raw_rel - prev_fast)
        flux_groove = max(0.0, self._fast_ema - self._slow_ema * 1.04)
        decayed = self._bloom * math.exp(-dt * 9.5)

        if peak > 0.004 and (flux_fast > 0.035 or flux_groove > 0.04):
            beat_hit = min(1.0, flux_fast * 3.8 + flux_groove * 3.6)
            self._bloom = max(decayed, beat_hit)
        else:
            self._bloom = 0.0 if decayed < 0.005 else decayed

        return norm_peak, self._bloom

    def dispose(self):
        if self._meter_ptr and self._release_fn:
            try:
                self._release_fn(self._meter_ptr.value)
            except Exception:
                pass
        self._meter_ptr = None
        self._get_peak_fn = None
        self._release_fn = None
