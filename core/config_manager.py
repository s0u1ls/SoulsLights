import os
import sys
import json
import plistlib
import subprocess

from core.platform_utils import IS_MAC, IS_WIN, get_app_data_dir

DEFAULT_CONFIG = {
    "master_enabled": True,
    "ambient_enabled": True,
    "lyrics_enabled": True,
    "active_preset": "studio",

    # Ambient Lighting Engine (Lumn)
    "ambient": {
        "glow_intensity": 1.35,          # 0.0 to 3.0
        "thickness": "normal",           # subtle, normal, thick, immersive
        "gradient_mode": "Multi Colors", # Multi Colors (2+), 1 Color
        "animation_mode": "Water Drop",  # Water Drop, Liquid Flow, Beat Pulse, Breathing, Static
        "override_album_color": False,   # True = fixed custom colors, False = album art sync
        "color_1": "#6366F1",
        "color_2": "#EC4899",
        "custom_colors": ["#6366F1", "#EC4899"],
        "color_balance": 0.5,            # 0.15 to 0.85
        "target_displays": "All Displays",
        "show_over_fullscreen": True,
        "audio_reactive": True,
        "album_backdrop": "Desktop Layer",  # Desktop Layer, Cinema Stage, Off
        "backdrop_darkness": 0.34        # 0.15 to 1.0 (higher = richer brighter cover)
    },

    # Synced Lyrics Overlay Engine (Verci)
    "lyrics": {
        "style": "Fisheye Visual",
        "auto_sync_colors": True,
        "custom_accent_color": "#EC4899",
        "custom_text_color": "#FFFFFF",
        "font": "Geometric",
        "font_scale": 1.0,
        "sync_offset_ms": 0,
        "click_through": True,
        "pos_x": None,
        "pos_y": None,
        "player_preference": "Music Apps First"
    },

    # System Preferences
    "system": {
        "start_with_windows": False,
        "minimize_to_tray": True
    }
}

PRESETS = {
    "studio": {
        "name": "Cinema Immersion",
        "description": "Full atmosphere: water-drop edge glow, 2-blob album backdrop, and synced lyrics",
        "ambient_enabled": True,
        "lyrics_enabled": True,
        "ambient": {
            "glow_intensity": 1.4,
            "thickness": "normal",
            "gradient_mode": "Multi Colors",
            "animation_mode": "Water Drop",
            "audio_reactive": True,
            "override_album_color": False,
            "album_backdrop": "Desktop Layer",
            "backdrop_darkness": 0.34
        },
        "lyrics": {
            "style": "Fisheye Visual",
            "auto_sync_colors": True,
            "font_scale": 1.0
        }
    },
    "ambient_only": {
        "name": "Edge Glow Only",
        "description": "Clean perimeter light synced to your music without lyrics",
        "ambient_enabled": True,
        "lyrics_enabled": False,
        "ambient": {
            "glow_intensity": 1.7,
            "thickness": "thick",
            "gradient_mode": "Multi Colors",
            "animation_mode": "Beat Pulse",
            "audio_reactive": True,
            "override_album_color": False,
            "album_backdrop": "Desktop Layer"
        }
    },
    "karaoke": {
        "name": "Karaoke Stage",
        "description": "Clean centered typography with subtle breathing edge glow",
        "ambient_enabled": True,
        "lyrics_enabled": True,
        "ambient": {
            "glow_intensity": 0.7,
            "thickness": "subtle",
            "gradient_mode": "Multi Colors",
            "animation_mode": "Breathing",
            "audio_reactive": False,
            "album_backdrop": "Desktop Layer"
        },
        "lyrics": {
            "style": "Apple Design",
            "auto_sync_colors": True,
            "font_scale": 1.15
        }
    },
    "night_mode": {
        "name": "Night Dim",
        "description": "Low-intensity monochrome aura with distraction-free lyrics",
        "ambient_enabled": True,
        "lyrics_enabled": True,
        "ambient": {
            "glow_intensity": 0.45,
            "thickness": "subtle",
            "gradient_mode": "1 Color",
            "animation_mode": "Breathing",
            "audio_reactive": False,
            "album_backdrop": "Off"
        },
        "lyrics": {
            "style": "Minimal",
            "auto_sync_colors": True,
            "font_scale": 0.9
        }
    }
}


class ConfigManager:
    """Standalone configuration store for SoulsLights (Windows & macOS)."""

    def __init__(self, config_dir=None):
        if config_dir is None:
            self.config_dir = get_app_data_dir()
        else:
            self.config_dir = config_dir
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_path = os.path.join(self.config_dir, "config.json")
        self.config = self.load_config()

    def load_config(self):
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                if "lumn" in user_cfg and "ambient" not in user_cfg:
                    l = user_cfg["lumn"]
                    config["ambient"]["glow_intensity"] = l.get("glow_intensity", 1.2)
                    config["ambient"]["thickness"] = l.get("thickness", "normal")
                    config["ambient"]["color_1"] = l.get("custom_color_1", "#6366F1")
                    config["ambient"]["color_2"] = l.get("custom_color_2", "#EC4899")
                if "verci" in user_cfg and "lyrics" not in user_cfg:
                    v = user_cfg["verci"]
                    config["lyrics"]["style"] = v.get("lyric_style", "Fisheye Visual")
                    config["lyrics"]["auto_sync_colors"] = v.get("auto_sync_colors", True)
                    config["lyrics"]["sync_offset_ms"] = v.get("sync_offset_ms", 0)
                self._deep_update(config, user_cfg)
                amb = config["ambient"]
                if not isinstance(amb.get("custom_colors"), list) or not amb["custom_colors"]:
                    amb["custom_colors"] = [amb.get("color_1", "#6366F1"), amb.get("color_2", "#EC4899")]
                if amb.get("gradient_mode") == "2 Colors":
                    amb["gradient_mode"] = "Multi Colors"
            except Exception as e:
                print(f"[ConfigManager] Error reading config: {e}")
        return config

    def _deep_update(self, base, update):
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._deep_update(base[k], v)
            elif k in base:
                base[k] = v

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")

    def apply_preset(self, preset_key):
        if preset_key not in PRESETS:
            return
        p = PRESETS[preset_key]
        self.config["active_preset"] = preset_key
        self.config["master_enabled"] = True
        self.config["ambient_enabled"] = p["ambient_enabled"]
        self.config["lyrics_enabled"] = p["lyrics_enabled"]
        if "ambient" in p:
            self.config["ambient"].update(p["ambient"])
        if "lyrics" in p:
            self.config["lyrics"].update(p["lyrics"])
        self.save_config()

    def set_startup_registry(self, enable=True, exe_path=None):
        """Enables or disables automatic launch at login (Registry on Windows, LaunchAgent on macOS)."""
        if IS_MAC:
            return self._set_mac_launch_agent(enable=enable, exe_path=exe_path)
        if not IS_WIN:
            self.config["system"]["start_with_windows"] = bool(enable)
            self.save_config()
            return True

        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "SoulsLights"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enable and exe_path:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}" --tray')
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            self.config["system"]["start_with_windows"] = bool(enable)
            self.save_config()
            return True
        except Exception as e:
            print(f"[ConfigManager] Error setting registry startup: {e}")
            return False

    def _set_mac_launch_agent(self, enable=True, exe_path=None) -> bool:
        launch_dir = os.path.expanduser("~/Library/LaunchAgents")
        plist_path = os.path.join(launch_dir, "com.soulslights.app.plist")
        try:
            if enable:
                os.makedirs(launch_dir, exist_ok=True)
                prog_args = []
                if getattr(sys, "frozen", False):
                    prog_args = [sys.executable, "--tray"]
                elif exe_path and exe_path.endswith(".py"):
                    prog_args = [sys.executable, exe_path, "--tray"]
                elif exe_path:
                    prog_args = [exe_path, "--tray"]
                else:
                    prog_args = [sys.executable, "--tray"]

                plist_data = {
                    "Label": "com.soulslights.app",
                    "ProgramArguments": prog_args,
                    "RunAtLoad": True,
                    "KeepAlive": False,
                }
                with open(plist_path, "wb") as f:
                    f.write(plistlib.dumps(plist_data))
                subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
                subprocess.run(["launchctl", "load", plist_path], capture_output=True)
            else:
                if os.path.exists(plist_path):
                    subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
                    os.remove(plist_path)
            self.config["system"]["start_with_windows"] = bool(enable)
            self.save_config()
            return True
        except Exception as e:
            print(f"[ConfigManager] Error setting macOS LaunchAgent: {e}")
            return False
