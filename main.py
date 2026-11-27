import sys
import os
import json
import time
import signal
import ctypes
import threading
import traceback

if getattr(sys, "frozen", False):
    _SELF_DIR = os.path.dirname(sys.executable)
else:
    _SELF_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _SELF_DIR
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.platform_utils import IS_MAC, IS_WIN, get_app_data_dir

APP_DATA_DIR = get_app_data_dir()
os.makedirs(APP_DATA_DIR, exist_ok=True)
LOG_FILE = os.path.join(APP_DATA_DIR, "app.log")
INSTANCE_FILE = os.path.join(APP_DATA_DIR, "instance.json")
LOCK_FILE = os.path.join(APP_DATA_DIR, "SoulsLights.lock")
WAKE_FILE = os.path.join(APP_DATA_DIR, "wake.trigger")


def log(msg):
    try:
        ts = time.strftime("%H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# High-DPI support for Windows UI (macOS Retina is handled automatically via Info.plist)
if IS_WIN:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from core.config_manager import ConfigManager
from core.engine_controller import EngineController
from core.media_monitor import MediaMonitor
from core.hotkeys import GlobalHotkeys
from core.licensing import LicenseManager
from core.updater import AutoUpdater
from ui.activation_window import ActivationWindow
from ui.dashboard import UnifiedDashboard
from ui.tray import SystemTrayManager

_MUTEX_NAME = "Local\\SoulsLights.SingleInstance"
_SHOW_EVENT_NAME = "Local\\SoulsLights.ShowWindow"


def _read_instance_meta():
    try:
        if os.path.exists(INSTANCE_FILE):
            with open(INSTANCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return int(data.get("pid", 0)), int(data.get("hwnd", 0))
    except Exception:
        pass
    return 0, 0


def _write_instance_meta(hwnd: int):
    try:
        with open(INSTANCE_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "hwnd": int(hwnd)}, f)
    except Exception:
        pass


def _clear_instance_meta():
    try:
        if os.path.exists(INSTANCE_FILE):
            with open(INSTANCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if int(data.get("pid", 0)) == os.getpid():
                os.remove(INSTANCE_FILE)
    except Exception:
        pass


def _terminate_pid_win(pid: int):
    if pid <= 0 or pid == os.getpid():
        return
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    k32.TerminateProcess.restype = ctypes.c_bool
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenProcess(0x0001, False, pid)
    if h:
        k32.TerminateProcess(h, 0)
        k32.CloseHandle(h)


def _acquire_single_instance_win(start_minimized: bool):
    k32 = ctypes.windll.kernel32
    u32 = ctypes.windll.user32
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.GetLastError.restype = ctypes.c_ulong
    k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
    k32.CreateEventW.restype = ctypes.c_void_p
    k32.OpenEventW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
    k32.OpenEventW.restype = ctypes.c_void_p
    k32.SetEvent.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    u32.IsWindow.argtypes = [ctypes.c_void_p]
    u32.IsWindow.restype = ctypes.c_bool
    u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    u32.IsWindowVisible.restype = ctypes.c_bool
    u32.ShowWindowAsync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u32.ShowWindowAsync.restype = ctypes.c_bool
    u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    u32.SetForegroundWindow.restype = ctypes.c_bool
    u32.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
    u32.AllowSetForegroundWindow.restype = ctypes.c_bool

    mutex = k32.CreateMutexW(None, False, _MUTEX_NAME)
    if k32.GetLastError() == 183:
        old_pid, old_hwnd = _read_instance_meta()
        if old_pid:
            u32.AllowSetForegroundWindow(old_pid)

        ev = k32.OpenEventW(0x0002, False, _SHOW_EVENT_NAME)
        if ev:
            k32.SetEvent(ev)
            k32.CloseHandle(ev)

        if old_hwnd and u32.IsWindow(old_hwnd) and not start_minimized:
            u32.ShowWindowAsync(old_hwnd, 9)
            u32.ShowWindowAsync(old_hwnd, 5)
            u32.SetForegroundWindow(old_hwnd)

        if not start_minimized:
            became_visible = False
            deadline = time.perf_counter() + 1.8
            while time.perf_counter() < deadline:
                if old_hwnd and u32.IsWindow(old_hwnd) and u32.IsWindowVisible(old_hwnd):
                    became_visible = True
                    break
                time.sleep(0.1)

            if became_visible:
                if mutex:
                    k32.CloseHandle(mutex)
                return None, None

            log(f"Existing instance (pid={old_pid}, hwnd={old_hwnd}) did not display window; replacing.")
            if mutex:
                k32.CloseHandle(mutex)
            _terminate_pid_win(old_pid)
            time.sleep(0.45)
            mutex = k32.CreateMutexW(None, False, _MUTEX_NAME)
            if k32.GetLastError() == 183:
                if mutex:
                    k32.CloseHandle(mutex)
                return None, None
        else:
            if mutex:
                k32.CloseHandle(mutex)
            return None, None

    show_event = k32.CreateEventW(None, False, False, _SHOW_EVENT_NAME)
    return mutex, show_event


def _acquire_single_instance_posix(start_minimized: bool):
    import fcntl
    fd = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd, None
    except BlockingIOError:
        fd.close()
        old_pid, _ = _read_instance_meta()
        try:
            with open(WAKE_FILE, "w", encoding="utf-8") as wf:
                wf.write(str(time.time()))
        except Exception:
            pass
        if old_pid and old_pid != os.getpid() and not start_minimized:
            try:
                os.kill(old_pid, signal.SIGUSR1)
            except Exception:
                pass
        return None, None
    except Exception:
        return fd, None


def main():
    start_minimized = "--tray" in sys.argv or "--minimized" in sys.argv
    if IS_WIN:
        mutex, show_event = _acquire_single_instance_win(start_minimized)
    else:
        mutex, show_event = _acquire_single_instance_posix(start_minimized)

    if mutex is None:
        log("Another instance is already running; activated existing window.")
        return

    log("Starting SoulsLights...")
    tray_mgr = None
    hotkeys = None
    media_mon = None
    engine_ctrl = None
    running_flag = [True]
    posix_wake_flag = [False]

    if not IS_WIN and hasattr(signal, "SIGUSR1"):
        try:
            signal.signal(signal.SIGUSR1, lambda _s, _f: posix_wake_flag.__setitem__(0, True))
        except Exception:
            pass

    try:
        config_mgr = ConfigManager()
        license_mgr = LicenseManager(config_mgr)
        if not license_mgr.is_activated():
            log("App not activated; showing token activation gate.")
            act_win = ActivationWindow(license_mgr)
            act_win.mainloop()
            if not act_win.activated and not license_mgr.is_activated():
                log("Activation cancelled by user; exiting.")
                return

        pref = config_mgr.config.get("lyrics", {}).get("player_preference", "Music Apps First")
        media_mon = MediaMonitor(player_preference=pref)
        engine_ctrl = EngineController(config_mgr, media_mon)

        def clean_exit():
            running_flag[0] = False
            try:
                if engine_ctrl:
                    engine_ctrl.stop_all()
            except Exception:
                pass
            try:
                if hotkeys:
                    hotkeys.stop()
            except Exception:
                pass
            try:
                if media_mon:
                    media_mon.stop()
            except Exception:
                pass
            try:
                if tray_mgr:
                    tray_mgr.stop()
            except Exception:
                pass
            try:
                dashboard.destroy()
            except Exception:
                pass

        dashboard = UnifiedDashboard(config_mgr, engine_ctrl, media_mon, on_quit_callback=clean_exit)
        if getattr(engine_ctrl, "mobile_server", None):
            engine_ctrl.mobile_server.on_remote_change = lambda: dashboard.enqueue_ui(dashboard._sync_ui_from_config)
            engine_ctrl.mobile_server.start()
            log(f"iPad/Mobile companion server listening at {engine_ctrl.mobile_server.get_url()}")

        def _bg_update_check():
            time.sleep(3.5)
            upd = AutoUpdater()
            info = upd.check_for_update()
            if info.get("available"):
                log(f"Update available: {info.get('version')}")
                dashboard.enqueue_ui(lambda: dashboard.set_update_info(info))

        threading.Thread(target=_bg_update_check, daemon=True).start()
        _write_instance_meta(dashboard.get_native_hwnd())
        media_mon.start()
        engine_ctrl.apply_media_state(media_mon.current_info)

        engine_ctrl.sync_state(
            config_mgr.config.get("master_enabled", True),
            config_mgr.config.get("ambient_enabled", True),
            config_mgr.config.get("lyrics_enabled", True),
        )

        # Wake-up listener for second-instance launch
        def _watch_show_event():
            if IS_WIN:
                k32 = ctypes.windll.kernel32
                k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                k32.WaitForSingleObject.restype = ctypes.c_ulong
                while running_flag[0] and show_event:
                    try:
                        res = k32.WaitForSingleObject(show_event, 400)
                        if res == 0 and running_flag[0]:
                            log("Received ShowWindow event; restoring dashboard.")
                            dashboard.enqueue_ui(dashboard.show_window)
                    except Exception as e:
                        log(f"_watch_show_event warning: {e}")
                        time.sleep(0.2)
            else:
                last_mtime = os.path.getmtime(WAKE_FILE) if os.path.exists(WAKE_FILE) else 0.0
                while running_flag[0]:
                    try:
                        wake = posix_wake_flag[0]
                        if os.path.exists(WAKE_FILE):
                            mt = os.path.getmtime(WAKE_FILE)
                            if mt > last_mtime:
                                last_mtime = mt
                                wake = True
                        if wake:
                            posix_wake_flag[0] = False
                            log("Received POSIX wake signal; restoring dashboard.")
                            dashboard.enqueue_ui(dashboard.show_window)
                    except Exception:
                        pass
                    time.sleep(0.35)

        threading.Thread(target=_watch_show_event, daemon=True).start()

        # Thread-safe Tray / Menu Bar callbacks via enqueue_ui
        def on_tray_show():
            dashboard.enqueue_ui(dashboard.show_window)

        def on_tray_toggle_master():
            def _do():
                dashboard.master_switch_var.set(not dashboard.master_switch_var.get())
                dashboard._on_master_toggle()
            dashboard.enqueue_ui(_do)

        def on_tray_toggle_ambient():
            def _do():
                dashboard.lumn_switch_var.set(not dashboard.lumn_switch_var.get())
                dashboard._on_lumn_toggle()
            dashboard.enqueue_ui(_do)

        def on_tray_toggle_backdrop():
            dashboard.enqueue_ui(dashboard._cycle_backdrop_mode)

        def on_tray_toggle_lyrics():
            def _do():
                dashboard.verci_switch_var.set(not dashboard.verci_switch_var.get())
                dashboard._on_verci_toggle()
            dashboard.enqueue_ui(_do)

        def on_tray_lock_lyrics():
            def _do():
                dashboard.click_through_var.set(not dashboard.click_through_var.get())
                dashboard._on_click_through_toggle()
            dashboard.enqueue_ui(_do)

        def on_tray_preset(key):
            dashboard.enqueue_ui(dashboard._apply_preset_key, key)

        def on_tray_restart():
            dashboard.enqueue_ui(engine_ctrl.restart_all)

        def on_tray_exit():
            dashboard.enqueue_ui(clean_exit)

        tray_mgr = SystemTrayManager(
            on_show_dashboard=on_tray_show,
            on_toggle_master=on_tray_toggle_master,
            on_toggle_ambient=on_tray_toggle_ambient,
            on_toggle_lyrics=on_tray_toggle_lyrics,
            on_toggle_lock_lyrics=on_tray_lock_lyrics,
            on_select_preset=on_tray_preset,
            on_restart_engines=on_tray_restart,
            on_exit_all=on_tray_exit,
            on_toggle_backdrop=on_tray_toggle_backdrop,
        )
        tray_mgr.start()

        hotkeys = GlobalHotkeys(
            on_toggle_edge=on_tray_toggle_ambient,
            on_toggle_lyrics=on_tray_toggle_lyrics,
            on_show_window=on_tray_show,
            on_toggle_backdrop=on_tray_toggle_backdrop,
        )
        hotkeys.start()

        if start_minimized:
            dashboard.withdraw()
        else:
            dashboard.show_window()

        log("Running dashboard mainloop...")
        dashboard.mainloop()
    except Exception:
        log(f"FATAL ERROR: {traceback.format_exc()}")
    finally:
        running_flag[0] = False
        _clear_instance_meta()
        log("Exiting cleanly...")
        try:
            if getattr(engine_ctrl, "mobile_server", None):
                engine_ctrl.mobile_server.stop()
            if engine_ctrl:
                engine_ctrl.stop_all()
            if hotkeys:
                hotkeys.stop()
            if media_mon:
                media_mon.stop()
            if tray_mgr:
                tray_mgr.stop()
        except Exception:
            pass
        if IS_WIN:
            k32 = ctypes.windll.kernel32
            if show_event:
                k32.CloseHandle(show_event)
            if mutex:
                k32.CloseHandle(mutex)
        else:
            try:
                mutex.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
