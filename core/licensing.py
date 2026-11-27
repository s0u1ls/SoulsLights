import hashlib
import json
import os
import platform
import ssl
import time
import urllib.request
import uuid

from core.platform_utils import get_app_data_dir, get_resource_path
from core.version import APP_VERSION, DEFAULT_TOKEN_API_URL

_SALT = "SL_SALT_v1:"

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = None


def get_machine_id() -> str:
    raw = f"{platform.node()}|{platform.machine()}|{uuid.getnode()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _hash_token(token: str) -> str:
    norm = (token or "").strip().upper()
    return hashlib.sha256((_SALT + norm).encode("utf-8")).hexdigest()


def _load_embedded_hashes() -> tuple[str, set]:
    p = get_resource_path(os.path.join("core", "_token_hashes.json"))
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("master", ""), set(data.get("hashes", []))
    except Exception:
        return _hash_token("7282"), set()


class LicenseManager:
    """Manages activation tokens (100 random 10-char tokens + master token 7282)."""

    def __init__(self, config_manager=None):
        self.cfg_mgr = config_manager
        self.app_dir = get_app_data_dir()
        os.makedirs(self.app_dir, exist_ok=True)
        self.license_path = os.path.join(self.app_dir, "license.json")
        self.master_hash, self.valid_hashes = _load_embedded_hashes()

    def _get_api_url(self) -> str:
        env = os.environ.get("SOULSLIGHTS_API_URL", "").strip()
        if env:
            return env.rstrip("/")
        if self.cfg_mgr:
            cfg_url = (self.cfg_mgr.config.get("system", {}).get("api_url") or "").strip()
            if cfg_url:
                return cfg_url.rstrip("/")
        return DEFAULT_TOKEN_API_URL.rstrip("/")

    def is_activated(self) -> bool:
        if not os.path.exists(self.license_path):
            return False
        try:
            with open(self.license_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("activated"):
                return False
            th = data.get("token_hash", "")
            if th == self.master_hash or th in self.valid_hashes or data.get("remote_verified"):
                return data.get("machine_id") == get_machine_id()
            return False
        except Exception:
            return False

    def get_license_summary(self) -> str:
        try:
            with open(self.license_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("activated"):
                if d.get("is_master"):
                    return "Master License Active"
                return f"Token {d.get('token_hint', '****')} Active"
        except Exception:
            pass
        return "Not Activated"

    def _save_license(self, norm_token: str, is_master: bool, remote_verified: bool, user_name: str = ""):
        hint = "MASTER" if is_master else f"{norm_token[:3]}****{norm_token[-3:]}"
        payload = {
            "activated": True,
            "is_master": is_master,
            "remote_verified": remote_verified,
            "token_hash": _hash_token(norm_token),
            "token_hint": hint,
            "user_name": (user_name or "").strip(),
            "machine_id": get_machine_id(),
            "activated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(self.license_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def check_token(self, raw_token: str) -> tuple[bool, str]:
        """Step 1: Verifies that the token is valid and unused without consuming it yet."""
        norm = (raw_token or "").strip().upper()
        if not norm:
            return False, "Please enter an activation token."
        th = _hash_token(norm)
        is_master = (th == self.master_hash)
        api_url = self._get_api_url()
        mid = get_machine_id()
        if api_url:
            try:
                body = json.dumps({
                    "token": norm,
                    "machine_id": mid,
                    "os": platform.system(),
                    "version": APP_VERSION,
                    "check_only": True,
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{api_url}/api/activate",
                    data=body,
                    headers={"Content-Type": "application/json", "User-Agent": f"SoulsLights/{APP_VERSION}"},
                    method="POST",
                )
                resp = urllib.request.urlopen(req, timeout=6, context=_SSL_CTX) if _SSL_CTX else urllib.request.urlopen(req, timeout=6)
                with resp:
                    res = json.loads(resp.read().decode("utf-8"))
                if res.get("ok"):
                    return True, "Token valid! Enter your name to continue."
                return False, res.get("error", "Invalid or already used token.")
            except urllib.error.HTTPError as he:
                try:
                    err_res = json.loads(he.read().decode("utf-8"))
                    return False, err_res.get("error", "Invalid or already used token.")
                except Exception:
                    pass
            except Exception:
                pass
        if is_master or (th in self.valid_hashes):
            return True, "Token valid! Enter your name to continue."
        return False, "Invalid activation token. Check your code and try again."

    def verify_and_activate(self, raw_token: str, user_name: str = "") -> tuple[bool, str]:
        norm = (raw_token or "").strip().upper()
        if not norm:
            return False, "Please enter an activation token."
        uname = (user_name or "").strip()[:60]

        th = _hash_token(norm)
        is_master = (th == self.master_hash)
        api_url = self._get_api_url()
        mid = get_machine_id()

        # 1. Try remote Token Server when configured (records usage + user name + enforces strict single-use)
        if api_url:
            try:
                body = json.dumps({
                    "token": norm,
                    "machine_id": mid,
                    "name": uname,
                    "os": platform.system(),
                    "version": APP_VERSION,
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{api_url}/api/activate",
                    data=body,
                    headers={"Content-Type": "application/json", "User-Agent": f"SoulsLights/{APP_VERSION}"},
                    method="POST",
                )
                resp = urllib.request.urlopen(req, timeout=6, context=_SSL_CTX) if _SSL_CTX else urllib.request.urlopen(req, timeout=6)
                with resp:
                    res = json.loads(resp.read().decode("utf-8"))
                if res.get("ok"):
                    self._save_license(norm, bool(res.get("is_master", is_master)), True, uname)
                    return True, res.get("message", "Token verified!")
                return False, res.get("error", "Invalid or already used token.")
            except urllib.error.HTTPError as he:
                try:
                    err_res = json.loads(he.read().decode("utf-8"))
                    return False, err_res.get("error", "Invalid or already used token.")
                except Exception:
                    pass
            except Exception:
                # Fall through to local hash validation when server is unreachable
                pass

        # 2. Local hash verification (7282 master + 100 generated 10-char tokens)
        if is_master or (th in self.valid_hashes):
            self._save_license(norm, is_master, False, uname)
            return True, "Master token verified!" if is_master else "Token verified! Welcome to SoulsLights."
        return False, "Invalid activation token. Check your code and try again."
