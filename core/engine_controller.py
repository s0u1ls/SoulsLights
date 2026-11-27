import time
from engine.ambient_glow import AmbientGlowEngine
from engine.album_backdrop import AlbumBackdropEngine
from engine.synced_lyrics import SyncedLyricsOverlay
from core.mobile_server import MobileCompanionServer


class EngineController:
    """Standalone coordinator for SoulsLights Edge Light, 2-Blob Backdrop, and Lyrics Stage."""

    def __init__(self, config_manager, media_monitor):
        self.cfg_mgr = config_manager
        self.media_mon = media_monitor
        self.ambient_engine = AmbientGlowEngine(config_manager)
        self.backdrop_engine = AlbumBackdropEngine(config_manager)
        self.lyrics_engine = SyncedLyricsOverlay(config_manager, media_monitor)
        self.mobile_server = MobileCompanionServer(config_manager, self, media_monitor)

    def start_ambient(self):
        self.ambient_engine.reload_from_config()
        self.ambient_engine.start()

    def stop_ambient(self):
        self.ambient_engine.stop()

    def restart_ambient(self):
        self.stop_ambient()
        time.sleep(0.2)
        self.start_ambient()

    def start_backdrop(self):
        self.backdrop_engine.reload_from_config()
        self.backdrop_engine.start()

    def stop_backdrop(self):
        self.backdrop_engine.stop()

    def start_lyrics(self):
        self.lyrics_engine.reload_from_config()
        self.lyrics_engine.start()

    def stop_lyrics(self):
        self.lyrics_engine.stop()

    def restart_lyrics(self):
        self.stop_lyrics()
        time.sleep(0.2)
        self.start_lyrics()

    def restart_all(self):
        cfg = self.cfg_mgr.config
        self.stop_all()
        time.sleep(0.2)
        self.sync_state(
            cfg.get("master_enabled", True),
            cfg.get("ambient_enabled", True),
            cfg.get("lyrics_enabled", True)
        )

    def stop_all(self):
        self.stop_ambient()
        self.stop_backdrop()
        self.stop_lyrics()

    def sync_state(self, master_enabled: bool, ambient_enabled: bool, lyrics_enabled: bool):
        if not master_enabled:
            self.stop_ambient()
            self.stop_backdrop()
            self.stop_lyrics()
            return

        if ambient_enabled:
            self.start_ambient()
        else:
            self.stop_ambient()

        bd_mode = self.cfg_mgr.config.get("ambient", {}).get("album_backdrop", "Desktop Layer")
        if bd_mode != "Off":
            self.start_backdrop()
        else:
            self.stop_backdrop()

        if lyrics_enabled:
            self.start_lyrics()
        else:
            self.stop_lyrics()

    def is_ambient_active(self) -> bool:
        return bool(self.ambient_engine.running)

    def is_backdrop_active(self) -> bool:
        return bool(self.backdrop_engine.running) and (self.backdrop_engine.mode != "Off")

    def is_lyrics_active(self) -> bool:
        return bool(self.lyrics_engine.running)

    def get_lyrics_status(self) -> str:
        return self.lyrics_engine.lyrics_status

    def cycle_backdrop_mode(self) -> str:
        order = ("Desktop Layer", "Cinema Stage", "Off")
        cur = self.cfg_mgr.config.get("ambient", {}).get("album_backdrop", "Desktop Layer")
        idx = (order.index(cur) + 1) % len(order) if cur in order else 0
        nxt = order[idx]
        self.cfg_mgr.config["ambient"]["album_backdrop"] = nxt
        self.cfg_mgr.save_config()
        self.backdrop_engine.set_mode(nxt)
        if nxt == "Off":
            self.stop_backdrop()
        elif self.cfg_mgr.config.get("master_enabled", True):
            self.start_backdrop()
        return nxt

    def apply_media_colors(self, colors):
        if colors and len(colors) >= 2:
            self.ambient_engine.update_album_colors(colors[0], colors[1])
            self.lyrics_engine.set_album_palette(colors[0], colors[1])

    def apply_media_state(self, info: dict):
        if not info:
            return
        colors = info.get("colors")
        if colors and len(colors) >= 2:
            self.ambient_engine.update_album_colors(colors[0], colors[1])
            self.lyrics_engine.set_album_palette(colors[0], colors[1])
        thumb = info.get("thumbnail_img")
        status = info.get("status", "Idle")
        is_playing = bool(info.get("is_playing", status == "Playing"))
        has_media = (status != "Idle") and (info.get("source", "Idle") != "Idle")
        self.backdrop_engine.update_media_state(thumb, colors, is_playing, has_media)
