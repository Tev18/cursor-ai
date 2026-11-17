# Cursor AI for Mac

A small Mac app. Paste your Claude API key into the window, press **Save key**, and it's
remembered (stored in the macOS Keychain, never in a plain settings file).

## Build it (on your Mac — it can't be built anywhere else)
1. Install Python 3 from https://www.python.org/downloads/macos/ (it includes a modern Tk).
2. In Terminal: `cd` into this folder, then `./build_mac.sh`
3. Drag `dist/Cursor AI.app` into Applications. First launch: **right-click → Open**
   (the app isn't notarized by Apple).
(To skip building: `pip3 install -r requirements.txt && python3 app.py`.)

## Use
1. Paste your key (console.anthropic.com → API keys), **Save Key**, optionally **Test Connection**.
2. Press **Ctrl+Shift+A** (or the *Capture now* button). The screen freezes as it is and the cursor stays the normal arrow: click one corner, then click the opposite corner (no dragging, nothing is drawn). Esc or right-click cancels.
3. The answer appears in a small floating window: drag the top bar, resize from ◢,
   **Aa** flips white/black text, **×** hides it. **Ctrl+Shift+H** shows/hides it.
Hotkeys are recorded, not typed: click the hotkey button, then press the keys you want (Esc cancels). Letters, digits, space, `[`, `]` and `\` work, combined with Ctrl/Shift/Option/Cmd (e.g. Ctrl + ]). A bare `]` isn't allowed: Mac apps can't swallow a global key, so it would also type a bracket into the app in front. Model and instruction are editable in the window.

## Window behaviour
When you capture (hotkey or button) the settings window hides, so only the answer popup shows. Closing the settings window keeps the app running in the background (hotkeys still work); click the Dock icon to bring the settings back, Cmd+Q to quit.

## Permissions (macOS asks once)
- **Screen Recording** — to take the screenshot. The *macOS Permissions* card shows whether it is granted and
  has a button that opens the right Settings page. Quit and reopen the app after granting.
The shortcuts use Carbon hotkeys, which need no extra permission. Only if macOS refuses Carbon and the app has to
fall back to a key monitor will the status bar at the bottom tell you what to enable.

## Differences from the Chrome extension
It uses a hotkey and a two-click selection instead of "hold ] and click two corners",
because a normal Mac app can't intercept clicks in other apps without much broader
permissions. It captures anything on screen, not just a browser tab.

## Verified vs not
- Tested here on Linux: key storage (Keychain + fallback), API request/response handling
  (mocked), capture wrapper and downscaling (mocked `screencapture`), hotkey validation,
  and the window logic under a virtual display. 21 automated checks.
- NOT tested on a real Mac: the PyInstaller build, real Keychain, real `screencapture`,
  and the permission prompts. If something fails, tell me the exact message.
- Each capture sends an image to Anthropic and is billed to your API account.

## Make a .dmg
After `./build_mac.sh`, run `./build_dmg.sh` -> `dist/Cursor-AI.dmg`.
Open it and drag *Cursor AI* onto *Applications*. The app is only ad-hoc signed, so on
other Macs users must right-click -> Open the first time (or run
`xattr -dr com.apple.quarantine "/Applications/Cursor AI.app"`).

## Troubleshooting
- Crash on launch with `dispatch_assert_queue_fail` / `TSMGetInputSourceProperty` in the report:
  that was pynput's hotkey thread on recent macOS. Fixed in this version - hotkeys now use
  Cocoa's key monitor on the main thread (needs `pip3 install -r requirements.txt` again,
  and a rebuild if you use the .app).
- Hotkey does nothing: grant Input Monitoring to the app (or to Terminal if you run `python3 app.py`),
  then restart it. The Capture now button works without it.

## How capture works
Pressing the hotkey takes one silent screenshot of your **main display**, shows that frozen copy
full-screen and lets you click two corners on it (no outline, no fill, no dragging). Only the
cropped rectangle is sent to Claude. Other monitors are not captured. The `screencapture -x`
call needs Screen Recording permission; without it macOS returns a blank desktop.

## Popup stays on screen
The answer popup is pinned above every window, on every Space and over full-screen apps, and
it does not hide when you click another app (it is re-asserted every second). It only goes away
when you press its x, press the show/hide hotkey, or start a new capture.

## Hotkeys work in the background
All three hotkeys (capture Ctrl+Shift+A, show/hide Ctrl+Shift+H, text colour Ctrl+Shift+C by default)
are global: they work while another app is in front and while the settings window is closed
(closing it only hides it; the app keeps running - check the Dock). The app also opts out of
macOS "App Nap" so hotkeys aren't delayed when it has no visible window. The hotkeys do not work if the app is
quit (Cmd+Q) - it must be running.

### How the hotkeys are registered
On macOS the hotkeys use Carbon `RegisterEventHotKey` (the same mechanism as Rectangle/Alfred): they
work whichever app is in front and need NO Input Monitoring permission (Screen Recording is still
needed for the screenshot). If macOS refuses (for example another app already owns the combo), the app
falls back to a key monitor that does need Input Monitoring, and the status line says why.
Pick a combo other apps don't use if you see that message.

## "No answer (stop_reason: max_tokens)"
Newer models can spend part of the token limit reasoning before they write the answer. The limit used
to be 300, which was sometimes all used up before any text appeared. It is now 4096, and if an answer
still comes back empty for that reason the app retries once with a bigger limit (up to 16000).
You only pay for tokens actually used. Older saved settings of 300 are upgraded automatically.

## Flicker when capturing
The full-screen selection window is now built hidden and fully transparent, and only shown once the
frozen screenshot is loaded (the PNG step is also faster), so there is no blank flash before the picture.
If you still see a flicker, note what it looks like (black flash, menu bar changing, the settings window
disappearing, a Space switch) - macOS switches the menu bar to this app when it becomes active.

## Esc cancels silently
While the frozen screen is showing, a bare **Esc** (or right-click) cancels. Esc is registered as a
temporary global hotkey for exactly that time, so it works even if macOS doesn't give the full-screen
window keyboard focus, and it is released again afterwards. Cancelling shows nothing: no popup, no
settings window, and macOS's "reopen" poke right after a capture is ignored for 2 seconds.

## Popup opacity slider
The **Popup Opacity** slider (Appearance card, 10% to 100% in 1% steps, 85% on a fresh install) fades the
whole popup, text included. It updates the popup live, is remembered, and if the popup is hidden it flashes a
short preview when you let go. Saved values from older versions are kept (values outside 10–100% are clamped).
At 10% the popup is very faint on purpose; raise it if you can't see it. The **Always on Top** switch next to it
turns the popup's stay-above-everything behaviour on or off.

## Interface (black & gold)
The settings window is drawn by `ui_kit.py` (rounded canvas widgets: cards, buttons, fields, dropdown,
slider, switch, shortcut buttons) in the palette #0D0D0F / #191919 / #252525 / gold #D4AF37. Shortcut buttons
show macOS symbols (⌃ ⌥ ⇧ ⌘); click one, press the new combination (Esc cancels, a combination already used
by another shortcut is refused). Cancel discards unsaved edits; the slider and the Always on Top switch apply
and save immediately. `permissions.py` reads the Screen Recording status.


## API key field (v1.0.0)
The key field is always visible. The saved key is loaded from the Keychain into the field, masked with dots; **Show**
reveals the real key and **Hide** masks it again. It is masked every time the window is reopened, and it is cleared
from the text field while the window is closed (it is read from the Keychain again when you reopen). Edit the field and
press **Save Key** to replace it. Saving other settings never touches the key. Keys are never logged or committed.

## Updates (v1.0.0)
**Updates** card: installed vs latest version, *Check for Updates*, *Install Update* (download progress, verification,
confirmation, relaunch), release notes, and an automatic-check switch. Updates are read from this project's GitHub Releases;
see `../docs/RELEASING.md` for the one-time setup (private repo token, signing key, Apple credentials). Installing only
works from the packaged app, not `python3 app.py`.
