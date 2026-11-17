"""Remote on/off per device.

The person who shares the app keeps `access.json` in the GitHub repo. Each install has a Device ID (a short hash of
the computer's hardware ID, never the raw ID) and a device name. The app reads the file and refuses to capture while
this device is switched off.

This is a soft control meant for people you gave the app to: it is open source and checked on the user's own
computer, so someone who edits the code or never goes online can get around it. It is not security.

access.json:
  {"enabled": true,                      # false = everyone is switched off
   "mode": "blocklist",                  # "blocklist": allowed unless listed as off | "allowlist": only listed-on devices
   "message": "Shown to blocked devices",
   "devices": {"a1b2c3d4e5f6": {"name": "Ali's MacBook", "enabled": false}}}
"""
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

import settings_store as ss
import updater
import version

DEFAULT_MESSAGE = "Access to Cursor AI was turned off for this device. Contact the person who gave you the app."
REFRESH_SECONDS = 15 * 60


def raw_machine_id():
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        elif sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:
        pass
    return "mac-%012x" % uuid.getnode()


def device_id(raw=None):
    """12 hex characters; stable per computer, reveals nothing about the hardware ID."""
    return hashlib.sha256(("cursorai:" + (raw or raw_machine_id())).encode()).hexdigest()[:12]


def device_name():
    try:
        return socket.gethostname() or "Unknown device"
    except Exception:
        return "Unknown device"


def policy_url(repo=None):
    return "https://raw.githubusercontent.com/%s/main/access.json" % (repo or version.REPO)


def evaluate(policy, dev_id):
    """-> (allowed, message)"""
    if not isinstance(policy, dict) or not policy:
        return True, ""
    msg = str(policy.get("message") or DEFAULT_MESSAGE)
    if policy.get("enabled", True) is False:
        return False, msg
    devices = policy.get("devices") if isinstance(policy.get("devices"), dict) else {}
    entry = devices.get(dev_id)
    on = entry.get("enabled", True) if isinstance(entry, dict) else None
    if str(policy.get("mode", "blocklist")).lower() == "allowlist":
        return (on is True), msg
    return (on is not False), msg


def fetch(url=None, timeout=10, opener=None):
    """Policy dict from GitHub. A missing file (404) means 'no restrictions'. Other errors raise."""
    req = urllib.request.Request(url or policy_url(), headers={"User-Agent": "CursorAI-access", "Cache-Control": "no-cache"})
    try:
        if opener is not None:
            resp = opener(req, timeout)
        else:
            resp = urllib.request.urlopen(req, timeout=timeout, context=updater.ssl_context())
        with resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise


class Access:
    def __init__(self, directory=None, fetcher=fetch, dev_id=None, name=None):
        self.dir = directory or ss.default_dir()
        self.cache_path = os.path.join(self.dir, "access_cache.json")
        self.fetcher = fetcher
        self.device_id = dev_id or device_id()
        self.device_name = name or device_name()
        self.allowed, self.message = True, ""
        self.state = "unknown"        # "allowed" | "blocked" | "unknown" (never reached the server and no saved copy)
        self.checked_at = 0.0
        self.source = "none"          # "online" | "saved" | "none"
        self._load_cache()

    def _apply(self, policy):
        self.allowed, self.message = evaluate(policy, self.device_id)
        self.state = "allowed" if self.allowed else "blocked"

    def _load_cache(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            self._apply(data.get("policy") or {})
            self.checked_at, self.source = float(data.get("at") or 0), "saved"
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _save_cache(self, policy):
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"at": time.time(), "policy": policy}, f)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass

    def refresh(self):
        """Fetch the latest policy. Offline: keep the saved copy (so a blocked device stays blocked)."""
        try:
            policy = self.fetcher()
        except Exception:
            return self.state
        self._apply(policy)
        self.checked_at, self.source = time.time(), "online"
        self._save_cache(policy)
        return self.state

    def stale(self):
        return time.time() - self.checked_at > REFRESH_SECONDS
