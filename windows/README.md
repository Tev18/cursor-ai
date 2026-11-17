# Cursor AI for Windows

Paste your Claude API key into the window, press **Save key**, and it is remembered (stored in
Windows Credential Manager, never in a plain settings file).

## Build it (on a Windows PC - an .exe can only be built on Windows)
1. Install Python 3 from https://www.python.org/downloads/windows/ - tick **Add python.exe to PATH**.
2. Unzip this folder, then double-click **build_windows.bat**.
3. When it finishes you have `dist\Cursor AI.exe`. It is one file: copy it anywhere or to another PC.
   First launch: if SmartScreen says "Windows protected your PC", click **More info -> Run anyway**
   (the exe is not code-signed).
To skip building: `py -m pip install -r requirements.txt` then `py app.py`.

## Use
1. Paste your key (console.anthropic.com -> API keys), **Save key**, optionally **Test key**.
2. Press **Ctrl+Shift+A** (or *Capture now*). The screen freezes and the cursor stays the normal arrow:
   click one corner, then the opposite corner (no dragging, nothing is drawn). Esc or right-click cancels.
   All monitors are covered.
3. The answer appears in a transparent, always-on-top popup: drag it by the handle or the text, resize
   from the corner mark, **Aa** flips white/black text, **x** hides it.
   **Ctrl+Shift+H** shows/hides it, **Ctrl+Shift+C** flips the text colour.
Hotkeys are recorded, not typed: click the hotkey button and press the keys you want (Esc cancels).
Letters, digits, space, `[`, `]` and `\` work with Ctrl/Shift/Alt (and Win).

## Notes
- No special Windows permissions are needed. Hotkeys use the Win32 RegisterHotKey API, so they work
  while any app is in front. If Windows refuses a combo, another program owns it - record another.
- The X button **minimises** the window (the app keeps running so hotkeys keep working). **Quit** exits.
- The popup background is truly see-through (Windows colour-key transparency). Clicks on fully
  transparent pixels fall through to the window behind, so grab the popup by the handle or the text.
  Text edges can look slightly rough; the **Aa** button flips white/black for readability.
- Token limit is 4096 with one automatic retry if the model spends it all reasoning.
- Each capture sends one cropped image to Anthropic and is billed to your API account.

## Verified vs not
Tested on Linux with a virtual display and a fake Win32 layer: key storage, API handling, hotkey
parsing and registration logic, selector maths including multi-monitor negative origins, the
recorder, popup logic, 34 automated checks. NOT tested on real Windows: the .bat build, the real
RegisterHotKey calls, ImageGrab on multiple monitors, DPI scaling, and colour-key transparency.
If anything fails, send me the exact message or a screenshot.

## Popup opacity slider
The **Popup opacity** slider in the settings window (20% to 100%) fades the whole popup, text included.
It updates live, is remembered, and if the popup is hidden it flashes a short preview when you let go
of the slider. It is separate from the white/black text colour.


## API key field (v1.0.0)
The key field is always visible. The saved key is loaded from the Credential Manager into the field, masked with dots; **Show**
reveals the real key and **Hide** masks it again. It is masked every time the window is reopened, and it is cleared
from the text field while the window is closed (it is read from the Credential Manager again when you reopen). Edit the field and
press **Save Key** to replace it. Saving other settings never touches the key. Keys are never logged or committed.

## Updates (v1.0.0)
**Updates** card: installed vs latest version, *Check for Updates*, *Install Update* (download progress, verification,
confirmation, relaunch), release notes, and an automatic-check switch. Updates are read from this project's GitHub Releases;
see `../docs/RELEASING.md` for the one-time setup (private repo token, signing key, Apple credentials). Installing only
works from the packaged app, not `python3 app.py`.
