"""Cross-platform global hotkeys for Windows (RegisterHotKey) and macOS (Carbon/AppKit)."""
import sys
import threading


class GlobalHotkeys:
    def __new__(cls, *args, **kwargs):
        if sys.platform == "darwin":
            return _MacGlobalHotkeys(*args, **kwargs)
        if sys.platform == "win32":
            return _WinGlobalHotkeys(*args, **kwargs)
        return _NoopGlobalHotkeys(*args, **kwargs)


class _NoopGlobalHotkeys:
    def __init__(self, on_toggle_edge=None, on_toggle_lyrics=None, on_show_window=None, on_toggle_backdrop=None):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class _WinGlobalHotkeys:
    def __init__(self, on_toggle_edge=None, on_toggle_lyrics=None, on_show_window=None, on_toggle_backdrop=None):
        self.on_toggle_edge = on_toggle_edge
        self.on_toggle_lyrics = on_toggle_lyrics
        self.on_show_window = on_show_window
        self.on_toggle_backdrop = on_toggle_backdrop
        self.running = False
        self.thread = None
        self.thread_id = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._msg_loop, daemon=True)
        self.thread.start()

    def stop(self):
        import ctypes
        self.running = False
        if self.thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            except Exception:
                pass

    def _msg_loop(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostThreadMessageW.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]

        MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000
        HOTKEY_ID_EDGE, HOTKEY_ID_LYRICS, HOTKEY_ID_STAGE, HOTKEY_ID_BACKDROP = 101, 102, 103, 104
        VK_L, VK_V, VK_U, VK_B = 0x4C, 0x56, 0x55, 0x42
        WM_HOTKEY = 0x0312

        self.thread_id = kernel32.GetCurrentThreadId()
        user32.RegisterHotKey(None, HOTKEY_ID_EDGE, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_L)
        user32.RegisterHotKey(None, HOTKEY_ID_LYRICS, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_V)
        user32.RegisterHotKey(None, HOTKEY_ID_STAGE, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_U)
        user32.RegisterHotKey(None, HOTKEY_ID_BACKDROP, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_B)

        msg = wintypes.MSG()
        while self.running:
            b_ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if b_ret <= 0:
                break
            if msg.message == WM_HOTKEY:
                hk_id = msg.wParam
                if hk_id == HOTKEY_ID_EDGE and self.on_toggle_edge:
                    self.on_toggle_edge()
                elif hk_id == HOTKEY_ID_LYRICS and self.on_toggle_lyrics:
                    self.on_toggle_lyrics()
                elif hk_id == HOTKEY_ID_STAGE and self.on_show_window:
                    self.on_show_window()
                elif hk_id == HOTKEY_ID_BACKDROP and self.on_toggle_backdrop:
                    self.on_toggle_backdrop()

            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnregisterHotKey(None, HOTKEY_ID_EDGE)
        user32.UnregisterHotKey(None, HOTKEY_ID_LYRICS)
        user32.UnregisterHotKey(None, HOTKEY_ID_STAGE)
        user32.UnregisterHotKey(None, HOTKEY_ID_BACKDROP)


class _MacGlobalHotkeys:
    """macOS Carbon HIToolbox + AppKit hotkey listener for Ctrl+Shift+L/V/U/B."""

    def __init__(self, on_toggle_edge=None, on_toggle_lyrics=None, on_show_window=None, on_toggle_backdrop=None):
        self.on_toggle_edge = on_toggle_edge
        self.on_toggle_lyrics = on_toggle_lyrics
        self.on_show_window = on_show_window
        self.on_toggle_backdrop = on_toggle_backdrop
        self._running = False
        self._hotkey_refs = []
        self._handler_ref = None
        self._handler_cb = None
        self._local_mon = None

    def start(self):
        if self._running:
            return
        self._running = True
        try:
            from core.mac_utils import run_on_main
            run_on_main(self._install_on_main, wait=False)
        except Exception:
            pass

    def _fire_id(self, hk_id: int):
        if hk_id == 101 and self.on_toggle_edge:
            self.on_toggle_edge()
        elif hk_id == 102 and self.on_toggle_lyrics:
            self.on_toggle_lyrics()
        elif hk_id == 103 and self.on_show_window:
            self.on_show_window()
        elif hk_id == 104 and self.on_toggle_backdrop:
            self.on_toggle_backdrop()

    def _install_on_main(self):
        if not self._running:
            return
        carbon_ok = False
        try:
            import ctypes
            carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")

            class EventHotKeyID(ctypes.Structure):
                _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

            class EventTypeSpec(ctypes.Structure):
                _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

            kEventClassKeyboard = 0x6B657962  # 'keyb'
            kEventHotKeyPressed = 6
            kEventParamDirectObject = 0x2D2D2D2D  # '----'
            typeEventHotKeyID = 0x686B6964  # 'hkid'

            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            carbon.InstallEventHandler.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                ctypes.POINTER(EventTypeSpec), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
            ]
            carbon.InstallEventHandler.restype = ctypes.c_int32
            carbon.GetEventParameter.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
            ]
            carbon.GetEventParameter.restype = ctypes.c_int32
            carbon.RegisterEventHotKey.argtypes = [
                ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID,
                ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
            ]
            carbon.RegisterEventHotKey.restype = ctypes.c_int32

            HANDLER_PROC = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

            def _on_carbon_event(next_handler, event_ref, user_data):
                hk = EventHotKeyID()
                st = carbon.GetEventParameter(
                    event_ref, kEventParamDirectObject, typeEventHotKeyID,
                    None, ctypes.sizeof(hk), None, ctypes.byref(hk),
                )
                if st == 0:
                    self._fire_id(int(hk.id))
                return 0

            self._handler_cb = HANDLER_PROC(_on_carbon_event)
            spec = EventTypeSpec(kEventClassKeyboard, kEventHotKeyPressed)
            handler_out = ctypes.c_void_p()
            target = carbon.GetApplicationEventTarget()
            if carbon.InstallEventHandler(target, self._handler_cb, 1, ctypes.byref(spec), None, ctypes.byref(handler_out)) == 0:
                self._handler_ref = (carbon, handler_out)
                mods = 0x1000 | 0x0200  # controlKey | shiftKey
                # Carbon virtual keycodes: L=37, V=9, U=32, B=11
                for hid, vk in ((101, 37), (102, 9), (103, 32), (104, 11)):
                    href = ctypes.c_void_p()
                    hk_id = EventHotKeyID(0x534C484B, hid)  # 'SLHK'
                    if carbon.RegisterEventHotKey(vk, mods, hk_id, target, 0, ctypes.byref(href)) == 0 and href.value:
                        self._hotkey_refs.append((carbon, href))
                carbon_ok = len(self._hotkey_refs) > 0
        except Exception:
            carbon_ok = False

        if not carbon_ok:
            try:
                import AppKit
                mask = AppKit.NSEventMaskKeyDown
                ctrl_shift = AppKit.NSEventModifierFlagControl | AppKit.NSEventModifierFlagShift

                def _local_handler(event):
                    try:
                        flags = event.modifierFlags()
                        if (flags & ctrl_shift) == ctrl_shift:
                            ch = str(event.charactersIgnoringModifiers() or "").lower()
                            mp = {"l": 101, "v": 102, "u": 103, "b": 104}
                            if ch in mp:
                                self._fire_id(mp[ch])
                    except Exception:
                        pass
                    return event

                self._local_mon = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, _local_handler)
            except Exception:
                pass

    def stop(self):
        self._running = False
        try:
            from core.mac_utils import run_on_main
            def _cleanup():
                for carbon, href in self._hotkey_refs:
                    try:
                        carbon.UnregisterEventHotKey(href)
                    except Exception:
                        pass
                self._hotkey_refs.clear()
                if self._handler_ref:
                    carbon, h = self._handler_ref
                    try:
                        carbon.RemoveEventHandler(h)
                    except Exception:
                        pass
                    self._handler_ref = None
                if self._local_mon:
                    try:
                        import AppKit
                        AppKit.NSEvent.removeMonitor_(self._local_mon)
                    except Exception:
                        pass
                    self._local_mon = None
            run_on_main(_cleanup, wait=False)
        except Exception:
            pass
