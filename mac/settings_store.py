"""Saves settings. The API key goes in the macOS Keychain (via `keyring`);
if the Keychain is unavailable it falls back to a private file (chmod 600)."""
import json
import os
import sys

SERVICE = "CursorAI"
ACCOUNT = "anthropic_api_key"
ACCOUNT_GH = "github_token"   # optional read-only token for updates from a private repository

DEFAULTS = {
    "model": "claude-sonnet-5-5",
    "instruction": "Reply with only the final answer — no explanation, no reasoning, no extra words. Answer this image:",
    "capture_hotkey": "<ctrl>+<shift>+a",
    "toggle_hotkey": "<ctrl>+<shift>+h",
    "color_hotkey": "<ctrl>+<shift>+c",
    "max_tokens": 4096,
    "dark_text": False,
    "opacity": 0.85,          # new installs; any valid saved value is kept
    "always_on_top": True,
    "auto_update_check": True,
    "update_last_check": 0,
}
OPACITY_MIN = 0.10  # 10 %
OPACITY_MAX = 1.0
MODELS = ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-1"]


def clamp_opacity(value, fallback=DEFAULTS["opacity"]):
    """Opacity as a fraction in [OPACITY_MIN, OPACITY_MAX], in 1 % steps."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = fallback
    if v != v:   # NaN
        v = fallback
    return round(min(OPACITY_MAX, max(OPACITY_MIN, v)), 2)


def default_dir():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/CursorAI")
    return os.path.expanduser("~/.config/cursor-ai")


class SettingsStore:
    def __init__(self, directory=None, keyring_module="auto"):
        self.dir = directory or default_dir()
        os.makedirs(self.dir, exist_ok=True)
        self.settings_path = os.path.join(self.dir, "settings.json")
        self.key_path = os.path.join(self.dir, "api_key.txt")
        if keyring_module == "auto":
            try:
                import keyring as keyring_module
            except Exception:
                keyring_module = None
        self.kr = keyring_module

    # ---- settings ----
    def load(self):
        data = dict(DEFAULTS)
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in DEFAULTS})
            # Older versions saved 300, which is too small once the model reasons before answering.
            if not isinstance(data["max_tokens"], int) or data["max_tokens"] < 1024:
                data["max_tokens"] = DEFAULTS["max_tokens"]
        except (OSError, ValueError):
            pass
        op = data["opacity"]
        data["opacity"] = clamp_opacity(op)
        data["always_on_top"] = bool(data["always_on_top"])
        return data

    def save(self, values):
        data = self.load()
        data.update({k: v for k, v in values.items() if k in DEFAULTS})
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.settings_path)

    # ---- secrets (API key, optional GitHub token): Keychain first, private file as fallback ----
    def _get(self, account, path):
        if self.kr:
            try:
                v = self.kr.get_password(SERVICE, account)
                if v:
                    return v
            except Exception:
                pass
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip() or None
        except OSError:
            return None

    def _set(self, account, path, value):
        """Returns where it was stored: 'keychain' or 'file'."""
        value = (value or "").strip()
        if not value:
            raise ValueError("The value is empty.")
        if self.kr:
            try:
                self.kr.set_password(SERVICE, account, value)
                self._rm(path)
                return "keychain"
            except Exception:
                pass
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
        os.chmod(path, 0o600)
        return "file"

    def _del(self, account, path):
        if self.kr:
            try:
                self.kr.delete_password(SERVICE, account)
            except Exception:
                pass
        self._rm(path)

    @staticmethod
    def _rm(path):
        try:
            os.remove(path)
        except OSError:
            pass

    # ---- API key ----
    def get_key(self):
        return self._get(ACCOUNT, self.key_path)

    def set_key(self, key):
        try:
            return self._set(ACCOUNT, self.key_path, key)
        except ValueError:
            raise ValueError("The key is empty.") from None

    def delete_key(self):
        self._del(ACCOUNT, self.key_path)

    # ---- GitHub token (only needed when releases live in a private repository) ----
    @property
    def gh_path(self):
        return os.path.join(self.dir, "github_token.txt")

    def get_token(self):
        return self._get(ACCOUNT_GH, self.gh_path)

    def set_token(self, token):
        return self._set(ACCOUNT_GH, self.gh_path, token)

    def delete_token(self):
        self._del(ACCOUNT_GH, self.gh_path)


def mask(key):
    if not key:
        return ""
    return key[:7] + "…" + key[-4:] if len(key) > 14 else "•" * len(key)
