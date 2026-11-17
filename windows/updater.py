"""Update checker / installer backed by GitHub Releases.

Flow: check_latest() -> download() -> verify_*() -> stage() -> (user confirms) -> install().
Everything here is plain functions with no Tk in it; the app runs them on a worker thread.

Security model (what is and isn't verified):
  * SHA-256: the zip must match SHA256SUMS.txt from the same release (integrity / corruption).
  * Ed25519: if the app was built with UPDATE_PUBLIC_KEY, the zip must carry a valid detached
    signature made with the matching private key, which lives only in GitHub Actions secrets.
    This is what protects against a tampered release; without a key only integrity is checked.
  * macOS: the new .app must pass `codesign --verify --deep --strict`, have the same bundle id as
    the running app, and we report what Gatekeeper (`spctl`) says so the user can decide.
Nothing here strips quarantine flags or otherwise works around Gatekeeper.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import version as ver

API = "https://api.github.com"
UA = "CursorAI-Updater"


class UpdateError(Exception):
    pass


# ---------- versions ----------
def parse_version(text):
    """'v1.2.3' / '1.2.3-beta.1' -> sortable tuple. A pre-release sorts before the same final version."""
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+](.*))?$", str(text or ""))
    if not m:
        raise UpdateError(f"Unrecognised version: {text!r}")
    major, minor, patch, pre = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), m.group(4)
    return (major, minor, patch, 0 if pre and not pre.startswith("+") else 1)


def is_newer(candidate, current):
    return parse_version(candidate) > parse_version(current)


def platform_key():
    return "macOS" if sys.platform == "darwin" else "Windows" if sys.platform == "win32" else "Linux"


def configured(repo=None):
    repo = repo or ver.REPO
    return bool(re.match(r"^[\w.-]+/[\w.-]+$", repo)) and not repo.startswith("OWNER/")


def ssl_context():
    """TLS context that trusts the certifi CA bundle. Python on macOS (python.org builds) ships without
    system certificates, which makes plain urllib fail with CERTIFICATE_VERIFY_FAILED."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# ---------- HTTP (keeps the GitHub token away from the CDN host it redirects to) ----------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _open(url, token=None, accept="application/vnd.github+json", timeout=20, opener=None, hops=5):
    opener = opener or urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl_context()))
    host0 = urlparse(url).netloc
    for _ in range(hops):
        headers = {"User-Agent": UA, "Accept": accept}
        if token and urlparse(url).netloc == host0:      # never forward the token to another host
            headers["Authorization"] = f"Bearer {token}"
        try:
            return opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.request.urljoin(url, e.headers["Location"])
                continue
            if e.code == 404:
                raise UpdateError("No release found. For a private repository, add a GitHub token with read access.") from None
            if e.code in (401, 403):
                raise UpdateError("GitHub refused the request (token missing, expired, or rate limit reached).") from None
            raise UpdateError(f"GitHub returned HTTP {e.code}.") from None
        except (urllib.error.URLError, OSError) as e:
            raise UpdateError(f"Can't reach GitHub: {getattr(e, 'reason', e)}") from None
    raise UpdateError("Too many redirects.")


def _read(url, token=None, **kw):
    with _open(url, token, **kw) as r:
        return r.read()


# ---------- check ----------
def check_latest(repo=None, token=None, current=None, api=API, opener=None):
    """Returns {'newer': bool, 'version', 'tag', 'notes', 'asset', 'sums', 'sig', 'url'} for the latest release."""
    repo = repo or ver.REPO
    current = current or ver.VERSION
    if not configured(repo):
        raise UpdateError("Updates aren't set up yet: this build has no GitHub repository configured.")
    data = json.loads(_read(f"{api}/repos/{repo}/releases/latest", token, opener=opener).decode("utf-8"))
    tag = data.get("tag_name") or ""
    latest = tag.lstrip("v")
    info = {"newer": is_newer(tag, current), "version": latest, "tag": tag, "url": data.get("html_url", ""),
            "notes": (data.get("body") or "").strip() or "No release notes.", "asset": None, "sums": None,
            "sig": None, "repo": repo}
    key = platform_key()
    assets = data.get("assets") or []
    byname = {a["name"]: a for a in assets}
    for a in assets:
        n = a["name"]
        if key.lower() in n.lower() and n.lower().endswith(".zip"):
            info["asset"] = a
            break
    info["sums"] = byname.get("SHA256SUMS.txt")
    if info["asset"]:
        info["sig"] = byname.get(info["asset"]["name"] + ".sig")
    return info


# ---------- download ----------
def download(asset, dest_dir, token=None, progress=None, cancelled=lambda: False, opener=None):
    """Streams the asset into dest_dir and returns its path. progress(done, total)."""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, os.path.basename(asset["name"]))
    total = int(asset.get("size") or 0)
    done = 0
    with _open(asset["url"], token, accept="application/octet-stream", timeout=30, opener=opener) as r, \
            open(path, "wb") as out:
        total = total or int(r.headers.get("Content-Length") or 0)
        while True:
            if cancelled():
                raise UpdateError("Download cancelled.")
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if total and done != total:
        raise UpdateError("The download was cut short. Try again.")
    return path


def fetch_text(asset, token=None, opener=None):
    return _read(asset["url"], token, accept="application/octet-stream", opener=opener)


# ---------- verification ----------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_sha256(path, sums_text, name=None):
    name = name or os.path.basename(path)
    if isinstance(sums_text, bytes):
        sums_text = sums_text.decode("utf-8", "replace")
    want = None
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            want = parts[0].lower()
    if not want:
        raise UpdateError("The release has no checksum for this download, so it was not installed.")
    if sha256_file(path) != want:
        raise UpdateError("Checksum mismatch: the download is damaged or was tampered with. Nothing was installed.")
    return True


def verify_signature(path, sig_bytes, public_key_b64=None):
    """Ed25519 detached signature over the file. Returns True when verified, False when no key is configured."""
    public_key_b64 = ver.UPDATE_PUBLIC_KEY if public_key_b64 is None else public_key_b64
    if not public_key_b64:
        return False
    if not sig_bytes:
        raise UpdateError("This release isn't signed, so it was not installed.")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        sig = base64.b64decode(sig_bytes.strip()) if len(sig_bytes.strip()) != 64 else sig_bytes.strip()
        with open(path, "rb") as f:
            data = f.read()
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(sig, data)
        return True
    except InvalidSignature:
        raise UpdateError("Signature check failed: this update was not signed by the publisher. Nothing was installed.") from None
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Couldn't verify the signature: {e}") from None


# ---------- install target ----------
def current_target():
    """Path of the installed app that would be replaced, or None when not running as a packaged app."""
    if not getattr(sys, "frozen", False):
        return None
    exe = os.path.abspath(sys.executable)
    if sys.platform == "darwin":
        m = re.match(r"^(.*?\.app)/Contents/MacOS/", exe)
        return m.group(1) if m else None
    return exe


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _bundle_id(app):
    try:
        import plistlib
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier")
    except Exception:
        return None


def stage(zip_path, target):
    """Unpacks the verified zip next to the target (same volume, so the swap is atomic).
    Returns {'new': path, 'dir': tempdir, 'notes': [warnings]}."""
    parent = os.path.dirname(target)
    if not os.access(parent, os.W_OK):
        raise UpdateError(f"No permission to write to {parent}. Move the app somewhere you own (e.g. ~/Applications) "
                          "or reinstall it manually.")
    work = tempfile.mkdtemp(prefix=".cursor-ai-update-", dir=parent)
    notes = []
    try:
        if sys.platform == "darwin":
            r = _run(["ditto", "-x", "-k", zip_path, work])    # ditto keeps symlinks / permissions intact
            if r.returncode:
                raise UpdateError("Couldn't unpack the update: " + (r.stderr or "").strip())
            apps = [p for p in os.listdir(work) if p.endswith(".app")]
            if not apps:
                raise UpdateError("The update doesn't contain an app.")
            new = os.path.join(work, apps[0])
            r = _run(["codesign", "--verify", "--deep", "--strict", new])
            if r.returncode:
                raise UpdateError("The update's code signature is invalid, so it was not installed.")
            old_id, new_id = _bundle_id(target), _bundle_id(new)
            if old_id and new_id != old_id:
                raise UpdateError("The update is a different application, so it was not installed.")
            if _run(["spctl", "--assess", "--type", "execute", new]).returncode:
                notes.append("This build is not notarized by Apple (Gatekeeper would reject it if it were downloaded "
                             "from a browser). It carries your publisher signature and passed the checksum.")
        else:
            import zipfile
            with zipfile.ZipFile(zip_path) as z:
                for member in z.namelist():
                    if member.startswith(("/", "\\")) or ".." in member.replace("\\", "/").split("/"):
                        raise UpdateError("The update archive is malformed.")
                z.extractall(work)
            exes = [p for p in os.listdir(work) if p.lower().endswith(".exe")]
            if not exes:
                raise UpdateError("The update doesn't contain an application.")
            new = os.path.join(work, exes[0])
        return {"new": new, "dir": work, "notes": notes, "target": target}
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def discard(staged):
    shutil.rmtree(staged.get("dir", ""), ignore_errors=True)


MAC_SCRIPT = r'''#!/bin/bash
# Waits for the app to quit, swaps the bundle (keeping a backup until the swap worked), relaunches.
PID="$1"; NEW="$2"; TARGET="$3"; WORK="$4"
OPEN="${OPEN_CMD:-open}"
while kill -0 "$PID" 2>/dev/null; do sleep 0.3; done
BACKUP="$TARGET.previous"
rm -rf "$BACKUP"
if mv "$TARGET" "$BACKUP" && mv "$NEW" "$TARGET"; then
  rm -rf "$BACKUP" "$WORK"
else
  [ -d "$TARGET" ] || mv "$BACKUP" "$TARGET"   # roll back
  rm -rf "$WORK"
fi
"$OPEN" "$TARGET"
rm -f "$0"
'''

WIN_SCRIPT = r'''@echo off
rem Waits for the app to quit, swaps the exe (keeping a backup until it worked), relaunches.
set PID=%~1
set NEW=%~2
set TARGET=%~3
set WORK=%~4
:wait
tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >NUL
  goto wait
)
move /Y "%TARGET%" "%TARGET%.previous" >NUL
move /Y "%NEW%" "%TARGET%" >NUL
if errorlevel 1 (
  move /Y "%TARGET%.previous" "%TARGET%" >NUL
) else (
  del /F /Q "%TARGET%.previous" >NUL 2>NUL
)
rmdir /S /Q "%WORK%" >NUL 2>NUL
start "" "%TARGET%"
(goto) 2>nul & del "%~f0"
'''


def install(staged, pid=None):
    """Starts the detached helper that swaps the app after we exit. The caller must quit right after."""
    pid = pid or os.getpid()
    if sys.platform == "win32":
        script = os.path.join(tempfile.gettempdir(), f"cursor-ai-update-{pid}.bat")
        with open(script, "w") as f:
            f.write(WIN_SCRIPT)
        cmd = ["cmd", "/c", script, str(pid), staged["new"], staged["target"], staged["dir"]]
        subprocess.Popen(cmd, creationflags=0x00000008 | 0x00000200, close_fds=True)   # DETACHED | NEW_GROUP
    else:
        script = os.path.join(tempfile.gettempdir(), f"cursor-ai-update-{pid}.sh")
        with open(script, "w") as f:
            f.write(MAC_SCRIPT)
        os.chmod(script, 0o700)
        cmd = ["/bin/bash", script, str(pid), staged["new"], staged["target"], staged["dir"]]
        subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cmd


def should_auto_check(last_check, now=None, every=24 * 3600):
    return (now or time.time()) - float(last_check or 0) >= every
