import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request

from core.platform_utils import IS_MAC, IS_WIN
from core.version import APP_VERSION, GITHUB_REPO

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = None


def parse_version(v: str) -> tuple:
    clean = (v or "").strip().lstrip("vV")
    parts = []
    for seg in clean.split("."):
        num = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


class AutoUpdater:
    """Checks GitHub Releases for newer builds and performs safe self-replacement & relaunch."""

    def __init__(self, repo: str = GITHUB_REPO, current_version: str = APP_VERSION):
        self.repo = repo
        self.current_version = current_version
        self.latest_info = None

    def _urlopen(self, url: str, timeout: int = 8):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"SoulsLights/{self.current_version}",
                "Accept": "application/vnd.github+json",
            },
        )
        if _SSL_CTX is not None:
            return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
        return urllib.request.urlopen(req, timeout=timeout)

    def check_for_update(self) -> dict:
        """Checks GitHub Releases API; returns dict with 'available', 'version', 'url', 'notes'."""
        api = f"https://api.github.com/repos/{self.repo}/releases/latest"
        try:
            with self._urlopen(api, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"available": False, "error": str(e)}

        tag = (data.get("tag_name") or "").strip()
        if not tag:
            return {"available": False}

        is_newer = parse_version(tag) > parse_version(self.current_version)
        assets = data.get("assets") or []
        dl_url = ""
        asset_name = ""

        if IS_WIN:
            for a in assets:
                name = (a.get("name") or "").lower()
                if name.endswith(".exe"):
                    dl_url = a.get("browser_download_url", "")
                    asset_name = a.get("name", "")
                    break
        elif IS_MAC:
            for a in assets:
                name = (a.get("name") or "").lower()
                if name.endswith(".zip") and "app" in name:
                    dl_url = a.get("browser_download_url", "")
                    asset_name = a.get("name", "")
                    break
            if not dl_url:
                for a in assets:
                    name = (a.get("name") or "").lower()
                    if name.endswith(".zip") or name.endswith(".dmg"):
                        dl_url = a.get("browser_download_url", "")
                        asset_name = a.get("name", "")
                        break

        info = {
            "available": bool(is_newer and dl_url),
            "version": tag,
            "url": dl_url,
            "asset_name": asset_name,
            "notes": (data.get("body") or "")[:300],
            "html_url": data.get("html_url", f"https://github.com/{self.repo}/releases/latest"),
        }
        self.latest_info = info
        return info

    def can_self_replace(self) -> bool:
        return bool(getattr(sys, "frozen", False))

    def download_and_apply_update(self, url: str) -> tuple[bool, str]:
        """Downloads release asset and spawns detached self-updater to swap & relaunch."""
        if not url:
            return False, "No download URL"

        try:
            if IS_WIN:
                if not getattr(sys, "frozen", False):
                    return False, "Self-update only applies to packaged SoulsLights.exe"
                target_exe = sys.executable
                tmp_dir = tempfile.gettempdir()
                dl_exe = os.path.join(tmp_dir, "SoulsLights_update.exe")
                with self._urlopen(url, timeout=60) as resp:
                    raw = resp.read()
                if len(raw) < 100000 or raw[:2] != b"MZ":
                    return False, "Downloaded file is not a valid Windows executable"
                with open(dl_exe, "wb") as f:
                    f.write(raw)

                bat_path = os.path.join(tmp_dir, "sl_apply_update.bat")
                pid = os.getpid()
                bat_content = (
                    "@echo off\r\n"
                    f"taskkill /F /PID {pid} >nul 2>&1\r\n"
                    "timeout /t 2 /nobreak >nul\r\n"
                    f'copy /Y "{dl_exe}" "{target_exe}" >nul\r\n'
                    "if errorlevel 1 (\r\n"
                    "  timeout /t 2 /nobreak >nul\r\n"
                    f'  copy /Y "{dl_exe}" "{target_exe}" >nul\r\n'
                    ")\r\n"
                    f'start "" "{target_exe}"\r\n'
                    f'del "{dl_exe}" >nul 2>&1\r\n'
                    'del "%~f0" >nul 2>&1\r\n'
                )
                with open(bat_path, "w", encoding="utf-8") as bf:
                    bf.write(bat_content)

                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                subprocess.Popen(["cmd.exe", "/c", bat_path], creationflags=creation_flags, close_fds=True)
                return True, "Applying update and restarting..."

            if IS_MAC:
                if not getattr(sys, "frozen", False):
                    return False, "Self-update only applies to packaged SoulsLights.app"
                # sys.executable -> .../SoulsLights.app/Contents/MacOS/SoulsLights
                app_bundle = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
                if not app_bundle.endswith(".app"):
                    return False, "Could not locate SoulsLights.app bundle"
                tmp_dir = tempfile.gettempdir()
                dl_zip = os.path.join(tmp_dir, "SoulsLights_update.zip")
                with self._urlopen(url, timeout=60) as resp:
                    raw = resp.read()
                if len(raw) < 100000:
                    return False, "Downloaded macOS update archive is too small"
                with open(dl_zip, "wb") as f:
                    f.write(raw)

                sh_path = os.path.join(tmp_dir, "sl_apply_mac_update.sh")
                pid = os.getpid()
                sh_content = (
                    "#!/bin/bash\n"
                    f"kill -9 {pid} 2>/dev/null || true\n"
                    "sleep 1\n"
                    "rm -rf /tmp/sl_upd_extract && mkdir -p /tmp/sl_upd_extract\n"
                    f'ditto -xk "{dl_zip}" /tmp/sl_upd_extract\n'
                    'NEW_APP=$(find /tmp/sl_upd_extract -maxdepth 3 -name "SoulsLights.app" | head -n 1)\n'
                    'if [ -n "$NEW_APP" ]; then\n'
                    f'  rm -rf "{app_bundle}"\n'
                    f'  ditto "$NEW_APP" "{app_bundle}"\n'
                    f'  xattr -cr "{app_bundle}" 2>/dev/null || true\n'
                    f'  open -n "{app_bundle}"\n'
                    "fi\n"
                    f'rm -rf /tmp/sl_upd_extract "{dl_zip}" "{sh_path}"\n'
                )
                with open(sh_path, "w", encoding="utf-8") as sf:
                    sf.write(sh_content)
                os.chmod(sh_path, 0o755)
                subprocess.Popen(["/bin/bash", sh_path], start_new_session=True)
                return True, "Applying macOS update and restarting..."

            return False, "Unsupported platform"
        except Exception as e:
            return False, f"Update failed: {e}"
