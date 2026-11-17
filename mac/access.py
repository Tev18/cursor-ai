"""Remote on/off per device.

The person who shares the app keeps `access.json` in the GitHub repo. Each install has a Device ID (a short hash of
the computer's hardware ID, never the raw ID) and a device name. The app reads the file and refuses to capture while
this device is switched off.

This is a soft control meant for people you gave the app to: it is open source and checked on the user's own
computer, so someone who edits the code or never goes online can get around it. It is not security.

access.json:
  {"server": "https://cursor-ai-devices.you.workers.dev",   # optional: the owner's device dashboard (server/README.md)
   "enabled": true,                      # false = everyone is switched off
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
REPORT_SECONDS = 60


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
        self._pol_allowed, self._pol_message, self._loaded = True, "", False
        self.remote_blocked, self.remote_message = False, ""   # set by the owner's dashboard (server), via the heartbeat
        self.server = ""                                        # owner's dashboard URL, from access.json
        self.captures, self.last_capture = 0, 0.0
        self.checked_at = 0.0
        self.source = "none"          # "online" | "saved" | "none"
        self._load_cache()

    @property
    def allowed(self):
        return self._pol_allowed and not self.remote_blocked

    @property
    def message(self):
        if self.remote_blocked:
            return self.remote_message or self._pol_message or DEFAULT_MESSAGE
        return self._pol_message

    @property
    def state(self):   # "allowed" | "blocked" | "unknown" (never reached the server and no saved copy)
        return "blocked" if not self.allowed else ("allowed" if self._loaded else "unknown")

    def _apply(self, policy):
        self._pol_allowed, self._pol_message = evaluate(policy, self.device_id)
        self._loaded = True
        srv = policy.get("server") if isinstance(policy, dict) else None
        self.server = srv.rstrip("/") if isinstance(srv, str) and srv.startswith("https://") and len(srv) < 200 else ""

    def _load_cache(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            self._apply(data.get("policy") or {})
            self.checked_at, self.source = float(data.get("at") or 0), "saved"
            rem = data.get("remote") or {}
            self.remote_blocked, self.remote_message = bool(rem.get("blocked")), str(rem.get("message") or "")
            self.captures, self.last_capture = int(data.get("captures") or 0), float(data.get("last_capture") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _save_cache(self, policy=None):
        try:
            if policy is None:
                try:
                    with open(self.cache_path, encoding="utf-8") as f:
                        policy = json.load(f).get("policy") or {}
                except (OSError, ValueError):
                    policy = {}
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"at": self.checked_at or time.time(), "policy": policy, "captures": self.captures,
                           "last_capture": self.last_capture,
                           "remote": {"blocked": self.remote_blocked, "message": self.remote_message}}, f)
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

    def note_capture(self):
        """Counts a real capture (never the image or the answer). Reported with the next heartbeat."""
        self.captures += 1
        self.last_capture = time.time()
        self._save_cache()

    def report(self, app_version, platform, display_name="", poster=None, timeout=8):
        """Heartbeat to the owner's dashboard: device name/ID, system, version, capture count. Never screenshots,
        answers, prompts or the API key. The reply can switch this device off. Silent when offline."""
        if not self.server:
            return None
        body = json.dumps({"id": self.device_id, "name": self.device_name, "display_name": (display_name or "")[:40],
                           "platform": platform, "version": app_version, "captures": self.captures,
                           "last_capture": self.last_capture}).encode()
        try:
            if poster is not None:
                data = poster(self.server + "/ping", body, timeout)
            else:
                req = urllib.request.Request(self.server + "/ping", data=body, method="POST",
                                             headers={"content-type": "application/json", "User-Agent": "CursorAI-device"})
                with urllib.request.urlopen(req, timeout=timeout, context=updater.ssl_context()) as r:
                    data = json.loads(r.read().decode("utf-8"))
            if isinstance(data, dict) and "allowed" in data:
                self.remote_blocked = data.get("allowed") is False
                self.remote_message = str(data.get("message") or "")[:200]
                self._save_cache()
            return data
        except Exception:
            return None

    def stale(self):
        return time.time() - self.checked_at > REFRESH_SECONDS
