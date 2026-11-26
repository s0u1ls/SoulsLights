import io
import os
import sys
import threading
from PIL import Image, ImageDraw

from core.platform_utils import IS_MAC, get_resource_path


def create_tray_icon_image(size=64):
    if IS_MAC:
        png = get_resource_path(os.path.join("assets", "app_icon.png"))
        if png:
            try:
                return Image.open(png).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            except Exception:
                pass
    ico = get_resource_path("app_icon.ico")
    if ico:
        try:
            return Image.open(ico).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass
    img = Image.new("RGBA", (size, size), (18, 18, 20, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, size - 5, size - 5], radius=12, outline=(212, 226, 238, 230), width=3)
    cx, cy = size // 2, size // 2
    d.polygon(
        [(cx, 12), (cx + 7, cy - 7), (size - 12, cy), (cx + 7, cy + 7), (cx, size - 12), (cx - 7, cy + 7), (12, cy), (cx - 7, cy - 7)],
        fill=(212, 226, 238, 255),
    )
    return img


class SystemTrayManager:
    """Windows system tray (pystray) & native macOS menu bar extra (NSStatusBar)."""

    def __init__(
        self,
        on_show_dashboard,
        on_toggle_master,
        on_toggle_ambient,
        on_toggle_lyrics,
        on_toggle_lock_lyrics,
        on_select_preset,
        on_restart_engines,
        on_exit_all,
        on_toggle_backdrop=None,
    ):
        self.on_show_dashboard = on_show_dashboard
        self.on_toggle_master = on_toggle_master
        self.on_toggle_ambient = on_toggle_ambient
        self.on_toggle_lyrics = on_toggle_lyrics
        self.on_toggle_lock_lyrics = on_toggle_lock_lyrics
        self.on_select_preset = on_select_preset
        self.on_restart_engines = on_restart_engines
        self.on_exit_all = on_exit_all
        self.on_toggle_backdrop = on_toggle_backdrop

        self.icon = None
        self.thread = None
        self._mac_status_item = None
        self._mac_delegate = None

    def start(self):
        if IS_MAC:
            self._start_mac()
            return
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run_win, daemon=True)
        self.thread.start()

    def _run_win(self):
        import pystray
        img = create_tray_icon_image()
        items = [
            pystray.MenuItem("Open SoulsLights", lambda: self.on_show_dashboard(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Toggle Live Stage", lambda: self.on_toggle_master()),
            pystray.MenuItem("Toggle Edge Light", lambda: self.on_toggle_ambient()),
            pystray.MenuItem("Toggle Synced Lyrics", lambda: self.on_toggle_lyrics()),
        ]
        if self.on_toggle_backdrop:
            items.append(pystray.MenuItem("Cycle 2-Blob Backdrop", lambda: self.on_toggle_backdrop()))
        items.extend([
            pystray.MenuItem("Lock Lyrics Position", lambda: self.on_toggle_lock_lyrics()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Focus Scenes", pystray.Menu(
                pystray.MenuItem("Cinema Immersion", lambda: self.on_select_preset("studio")),
                pystray.MenuItem("Edge Glow Only", lambda: self.on_select_preset("ambient_only")),
                pystray.MenuItem("Karaoke Stage", lambda: self.on_select_preset("karaoke")),
                pystray.MenuItem("Night Dim", lambda: self.on_select_preset("night_mode")),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart Stage", lambda: self.on_restart_engines()),
            pystray.MenuItem("Quit SoulsLights", lambda: self.on_exit_all()),
        ])
        menu = pystray.Menu(*items)
        self.icon = pystray.Icon("SoulsLights", img, "SoulsLights", menu)
        self.icon.run()

    def _start_mac(self):
        """Creates a native macOS menu bar NSStatusItem safely on the AppKit main thread."""
        try:
            from core.mac_utils import run_on_main
            run_on_main(self._setup_mac_menu_on_main, wait=False)
        except Exception:
            pass

    def _setup_mac_menu_on_main(self):
        try:
            import objc
            import Foundation
            import AppKit

            mgr = self

            class SoulsLightsMenuTarget(Foundation.NSObject):
                def onShow_(self, _sender):
                    mgr.on_show_dashboard()

                def onToggleMaster_(self, _sender):
                    mgr.on_toggle_master()

                def onToggleAmbient_(self, _sender):
                    mgr.on_toggle_ambient()

                def onToggleLyrics_(self, _sender):
                    mgr.on_toggle_lyrics()

                def onToggleBackdrop_(self, _sender):
                    if mgr.on_toggle_backdrop:
                        mgr.on_toggle_backdrop()

                def onToggleLock_(self, _sender):
                    mgr.on_toggle_lock_lyrics()

                def onPreset_(self, sender):
                    key = str(sender.representedObject() or "studio")
                    mgr.on_select_preset(key)

                def onRestart_(self, _sender):
                    mgr.on_restart_engines()

                def onQuit_(self, _sender):
                    mgr.on_exit_all()

            delegate = SoulsLightsMenuTarget.alloc().init()
            self._mac_delegate = delegate

            status_bar = AppKit.NSStatusBar.systemStatusBar()
            item = status_bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
            self._mac_status_item = item

            pil_img = create_tray_icon_image(size=36)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            raw = buf.getvalue()
            ns_data = Foundation.NSData.dataWithBytes_length_(raw, len(raw))
            ns_img = AppKit.NSImage.alloc().initWithData_(ns_data)
            if ns_img is not None:
                ns_img.setSize_(AppKit.NSMakeSize(18.0, 18.0))
                item.button().setImage_(ns_img)
            else:
                item.button().setTitle_("✦")
            item.button().setToolTip_("SoulsLights")

            menu = AppKit.NSMenu.alloc().init()

            def _add(title, sel, obj=None):
                mi = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
                mi.setTarget_(delegate)
                if obj is not None:
                    mi.setRepresentedObject_(obj)
                menu.addItem_(mi)
                return mi

            _add("Open SoulsLights", "onShow:")
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            _add("Toggle Live Stage", "onToggleMaster:")
            _add("Toggle Edge Light", "onToggleAmbient:")
            _add("Toggle Synced Lyrics", "onToggleLyrics:")
            if self.on_toggle_backdrop:
                _add("Cycle 2-Blob Backdrop", "onToggleBackdrop:")
            _add("Lock Lyrics Position", "onToggleLock:")
            menu.addItem_(AppKit.NSMenuItem.separatorItem())

            sub_parent = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Focus Scenes", None, "")
            sub = AppKit.NSMenu.alloc().init()
            for title, pkey in (
                ("Cinema Immersion", "studio"),
                ("Edge Glow Only", "ambient_only"),
                ("Karaoke Stage", "karaoke"),
                ("Night Dim", "night_mode"),
            ):
                si = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "onPreset:", "")
                si.setTarget_(delegate)
                si.setRepresentedObject_(pkey)
                sub.addItem_(si)
            menu.addItem_(sub_parent)
            menu.setSubmenu_forItem_(sub, sub_parent)

            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            _add("Restart Stage", "onRestart:")
            _add("Quit SoulsLights", "onQuit:")
            item.setMenu_(menu)
        except Exception:
            pass

    def stop(self):
        if IS_MAC:
            if self._mac_status_item is not None:
                item = self._mac_status_item
                self._mac_status_item = None
                try:
                    from core.mac_utils import run_on_main
                    run_on_main(lambda: __import__("AppKit").NSStatusBar.systemStatusBar().removeStatusItem_(item), wait=False)
                except Exception:
                    pass
            return
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
