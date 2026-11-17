# Cursor AI Lookup (Chrome Extension)

Hold **]** and click one corner of the area you want, then click the opposite
corner. The extension screenshots that rectangle and sends it to Claude. The
answer shows up in a movable, resizable widget with no background box — just
plain white (or black, toggleable) text over the page.

It works on normal pages, inside iframes (including cross-origin ones), and on
canvas-based web apps such as PowerPoint/Word/Excel for the web, Google
Docs/Slides, and Figma.

There's no popup UI — settings are edited directly in `background.js`.

## Install (unpacked, for personal use)

1. Unzip this folder somewhere permanent (don't delete it afterward — Chrome
   loads the extension from this location).
2. Open `background.js` and edit the `CONFIG` block near the top:
   ```js
   const CONFIG = {
     apiKey: "sk-ant-...",             // your Anthropic API key
     apiUrl: "https://api.anthropic.com/v1/messages",
     apiVersion: "2023-06-01",
     model: "claude-sonnet-5-5",
     maxTokens: 4096
   };
   ```
   Get a key at https://console.anthropic.com/ (Settings → API keys). API usage
   is billed separately from a Claude.ai subscription.
   Other model options: `claude-haiku-5-5` (fastest/cheapest) or
   `claude-opus-5-5` (most capable, slower).
3. Go to `chrome://extensions`.
4. Turn on **Developer mode** (top-right toggle).
5. Click **Load unpacked** and select this folder.

**After updating or reloading the extension, refresh any tabs that were already
open.** Tabs opened before the reload keep an orphaned copy of the old script;
it will tell you to refresh the page.

## Use

1. **Press and hold `]`.** A transparent layer covers the page and the cursor
   becomes a crosshair.
2. **Click** one corner of the area you want. You can let go of `]` now.
   A blue rectangle follows your cursor.
3. **Click** the opposite corner. The area is screenshotted and sent to Claude;
   the widget shows "Thinking…" and then the answer.
4. **Escape** cancels at any point while marking. Releasing `]` before placing
   the first corner also cancels.

Keys are watched in every frame, so it doesn't matter whether keyboard focus is
on the page or inside an embedded editor.

Widget controls:
- **Drag** it by the thin header bar to move it.
- **Resize** it from the small corner mark (bottom-right).
- Position/size persist across page loads.
- Press **\\** to hide the widget if it's showing, or bring it back if it's
  hidden. Edit `CONFIG.toggleKey` at the top of `content.js` to change the key.
- Press **[** to flip the widget's text between white (default) and black.
  This preference is remembered.
- `[` and `\` are ignored while you're typing in a text box, and none of these
  keys react when Cmd/Ctrl/Alt is held (so browser shortcuts like Cmd+[ are
  untouched).

## Changing settings later

Edit `background.js` (API key, model) or `content.js` (toggle key), then
reload the extension from `chrome://extensions` (refresh icon on its card) and
refresh your open tabs.

## How it works

- `content.js` is injected into **every frame** of every page
  (`all_frames: true`). All the logic lives in the **top frame**; iframes only
  pass the `]`, `[`, `\` and Escape key presses up to it via the background
  script (which a web page can't spoof).
- While `]` is held, the top frame puts a transparent full-viewport "shield"
  over the page. The shield receives the two clicks itself, so the page —
  and any iframe inside it — never gets the chance to swallow them, and the
  coordinates are always in the top page's viewport space, so iframe offsets
  don't matter.
- Before the screenshot, the selection layer and any earlier answer are
  removed from the page so they can't end up in the picture; "Thinking…"
  appears only once the background script reports the screenshot is taken.
- `background.js` (the service worker) uses `chrome.tabs.captureVisibleTab`
  to grab the visible tab, crops the rectangle with `OffscreenCanvas`
  (scale taken from the real image size, so Retina screens and browser zoom
  are handled), and sends it as a base64 image to Anthropic's Messages API
  (`/v1/messages`) with a short "give only the final answer" instruction.
- The widget (`content.css`) has no background box. There's no automatic
  contrast detection (an earlier version tried `mix-blend-mode: difference`,
  but that only blends within the page's own CSS stacking context, and most
  real sites break out of it), so **[** is the manual fix.

### Why marking used to fail on some sites

Three separate problems, all fixed, none specific to one site:

1. **The script only ran in the top page.** Apps like PowerPoint for the web
   (especially when opened from OneDrive/SharePoint), Google Docs and Figma
   put their editing surface in a nested iframe, where no code was listening.
2. **Marking depended on the `click` event**, which canvas/SVG-based editors can
   swallow when they redraw or capture the pointer mid-press.
3. **Keyboard focus inside an iframe** meant the top page never learned `]` was
   held.

## Notes / limitations

- Only captures the **visible viewport** of the current tab — nothing
  outside the browser window, and nothing scrolled off-screen.
- Chrome doesn't allow extensions on some pages: `chrome://` pages, the Chrome
  Web Store, and Chrome's built-in PDF viewer. The key presses do nothing there.
- While marking, the shield intercepts all mouse input, including scrolling.
  A few sites close menus or dialogs when they see a click "outside" them; if
  that happens while you mark, mark again with the menu already in the state you
  want captured, or hit Escape first.
- If a page puts something in the browser's top layer (a `<dialog>` opened with
  `showModal()`, popovers), it can sit above the shield; clicks on it then reach
  the page instead of the selection.
- `<all_urls>` host permission is required for injection + tab capture on
  any site. Normal for a personal-use unpacked extension.
- Your API key sits in plain text in `background.js` on your machine —
  don't share this folder with the key filled in, and never paste the key into
  a chat. It's sent in an `x-api-key` header (not the URL). The request also
  carries `anthropic-dangerous-direct-browser-access: true`, which Anthropic
  requires for calls made from a browser context; the name is a reminder that
  a key stored in extension code is readable by anyone with access to your
  machine or the extension files.
- Each captured region is one image-input API call, which generally costs
  more (and is slower) than a text-only request.

## What has and hasn't been verified

- ✅ Automated simulations (jsdom + stubbed `chrome.*`) cover: the
  hold-`]`/two-corner flow, reversed corners, tiny areas, Escape, key
  filtering, text-field and modifier handling, relaying keys from a real child
  iframe, stale-answer handling, orphaned scripts after a reload, the crop
  maths for Retina and zoom, and the Claude request/response handling.
- ⚠️ **Not yet run in a real browser against a real site such as PowerPoint
  Online.** If marking still misbehaves somewhere, open DevTools on that page
  and tell me the site plus what you see (does the crosshair appear? does the
  blue box follow the cursor?). That tells me which step is failing.
