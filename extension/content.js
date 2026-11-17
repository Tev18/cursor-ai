// content.js — injected into EVERY frame of every page (all_frames).
//
//  Top frame ..... owns all UI (answer widget, selection layer) and all state.
//  Child frames .. (iframes) only relay a few key presses up to the top frame
//                  through the background script, so the hotkeys work no matter
//                  which frame currently has keyboard focus.
//
// Edit CONFIG.toggleKey below to change the show/hide hotkey (no popup UI).

const IS_TOP = window === window.top;

const CONFIG = {
  toggleKey: "\\"
};

const START_KEY = "]"; // hold it, then click one corner; click the opposite corner to finish
const COLOR_KEY = "["; // flips the answer text between white and black
const WATCHED_KEYS = new Set([START_KEY, COLOR_KEY, CONFIG.toggleKey, "Escape"]);

function saveRect(rect) {
  chrome.storage.local.set({ cursorAiRect: rect });
}

function loadRect() {
  return new Promise((resolve) => {
    chrome.storage.local.get({ cursorAiRect: null }, (items) => resolve(items.cursorAiRect));
  });
}

function saveDarkText(value) {
  chrome.storage.local.set({ cursorAiDarkText: value });
}

function loadDarkText() {
  return new Promise((resolve) => {
    chrome.storage.local.get({ cursorAiDarkText: false }, (items) => resolve(items.cursorAiDarkText));
  });
}

// ---- Overlay UI: movable, resizable widget ----

let overlayEl = null;
let headerEl = null;
let contentEl = null;
let darkText = false; // false = white text (default), true = black text

if (IS_TOP) {
  loadDarkText().then((value) => {
    darkText = value;
    if (overlayEl) applyTextColorClass();
  });
}

function applyTextColorClass() {
  overlayEl.classList.toggle("cursor-ai-dark-text", darkText);
}

function defaultRect() {
  const width = 320;
  const height = 200;
  return {
    width,
    height,
    left: Math.round(window.innerWidth / 2 - width / 2),
    top: Math.round(window.innerHeight - height - 24)
  };
}

function applyRect(rect) {
  overlayEl.style.left = rect.left + "px";
  overlayEl.style.top = rect.top + "px";
  overlayEl.style.width = rect.width + "px";
  overlayEl.style.height = rect.height + "px";
}

function currentRect() {
  return {
    left: overlayEl.offsetLeft,
    top: overlayEl.offsetTop,
    width: overlayEl.offsetWidth,
    height: overlayEl.offsetHeight
  };
}

function clampToViewport() {
  const maxLeft = Math.max(0, window.innerWidth - overlayEl.offsetWidth);
  const maxTop = Math.max(0, window.innerHeight - overlayEl.offsetHeight);
  overlayEl.style.left = Math.min(Math.max(0, overlayEl.offsetLeft), maxLeft) + "px";
  overlayEl.style.top = Math.min(Math.max(0, overlayEl.offsetTop), maxTop) + "px";
}

function ensureOverlay() {
  if (overlayEl) return overlayEl;

  overlayEl = document.createElement("div");
  overlayEl.id = "cursor-ai-overlay";
  applyRect(defaultRect());

  headerEl = document.createElement("div");
  headerEl.className = "cursor-ai-header";
  headerEl.textContent = "Cursor AI";
  overlayEl.appendChild(headerEl);

  const closeBtn = document.createElement("button");
  closeBtn.className = "cursor-ai-close";
  closeBtn.textContent = "\u2715";
  closeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    hideOverlay();
  });
  headerEl.appendChild(closeBtn);

  contentEl = document.createElement("div");
  contentEl.className = "cursor-ai-content";
  overlayEl.appendChild(contentEl);

  const resizeHandle = document.createElement("div");
  resizeHandle.className = "cursor-ai-resize-handle";
  overlayEl.appendChild(resizeHandle);

  document.documentElement.appendChild(overlayEl);
  applyTextColorClass();

  makeDraggable(headerEl);
  makeResizable(resizeHandle);

  loadRect().then((rect) => {
    if (rect) applyRect(rect);
    clampToViewport();
  });

  window.addEventListener("resize", clampToViewport, { passive: true });

  return overlayEl;
}

function makeDraggable(handle) {
  let dragging = false;
  let offsetX = 0;
  let offsetY = 0;

  handle.addEventListener("mousedown", (e) => {
    if (e.target.closest(".cursor-ai-close")) return;
    dragging = true;
    offsetX = e.clientX - overlayEl.offsetLeft;
    offsetY = e.clientY - overlayEl.offsetTop;
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    e.preventDefault();
  });

  function onMove(e) {
    if (!dragging) return;
    let left = e.clientX - offsetX;
    let top = e.clientY - offsetY;
    left = Math.max(0, Math.min(left, window.innerWidth - overlayEl.offsetWidth));
    top = Math.max(0, Math.min(top, window.innerHeight - overlayEl.offsetHeight));
    overlayEl.style.left = left + "px";
    overlayEl.style.top = top + "px";
  }

  function onUp() {
    if (!dragging) return;
    dragging = false;
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    saveRect(currentRect());
  }
}

function makeResizable(handle) {
  let resizing = false;
  let startX = 0;
  let startY = 0;
  let startWidth = 0;
  let startHeight = 0;

  handle.addEventListener("mousedown", (e) => {
    resizing = true;
    startX = e.clientX;
    startY = e.clientY;
    startWidth = overlayEl.offsetWidth;
    startHeight = overlayEl.offsetHeight;
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    e.preventDefault();
    e.stopPropagation();
  });

  function onMove(e) {
    if (!resizing) return;
    let width = startWidth + (e.clientX - startX);
    let height = startHeight + (e.clientY - startY);
    width = Math.max(220, Math.min(width, window.innerWidth - overlayEl.offsetLeft - 8));
    height = Math.max(100, Math.min(height, window.innerHeight - overlayEl.offsetTop - 8));
    overlayEl.style.width = width + "px";
    overlayEl.style.height = height + "px";
  }

  function onUp() {
    if (!resizing) return;
    resizing = false;
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    saveRect(currentRect());
  }
}

function showOverlay(text, { loading = false, error = false } = {}) {
  const el = ensureOverlay();
  el.classList.toggle("cursor-ai-loading", loading);
  el.classList.toggle("cursor-ai-error", error);
  contentEl.textContent = text;
  el.classList.add("cursor-ai-visible");
}

function hideOverlay() {
  if (overlayEl) overlayEl.classList.remove("cursor-ai-visible");
}

// ---- Talking to the background script ----

function sendToBackground(message) {
  return new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendMessage(message, (response) => {
        const err = chrome.runtime.lastError;
        if (err) reject(new Error(err.message));
        else resolve(response);
      });
    } catch (e) {
      reject(e); // e.g. "Extension context invalidated" after the extension was reloaded
    }
  });
}

function describeExtensionError(err) {
  const msg = (err && err.message) || String(err);
  if (/context invalidated/i.test(msg)) {
    return "The extension was reloaded or updated — refresh this page and try again.";
  }
  return "Extension error: " + msg;
}

function nextPaint() {
  return new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
  );
}

// ---- Keyboard: every frame watches the keys; only the top frame acts on them ----

function isTypingTarget(el) {
  if (!el || el.nodeType !== 1) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable === true;
}

function relayKey(key, down) {
  try {
    chrome.runtime.sendMessage({ type: "FRAME_KEY", key, down }, () => void chrome.runtime.lastError);
  } catch (_) {
    // extension was reloaded; nothing useful to do from an orphaned script
  }
}

function onKeyEvent(e, down) {
  if (!WATCHED_KEYS.has(e.key)) return;
  if (down) {
    if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return; // ignore auto-repeat and shortcuts like Cmd+[
    // Don't hijack [ and \ while typing into a text field.
    if ((e.key === COLOR_KEY || e.key === CONFIG.toggleKey) && isTypingTarget(e.target)) return;
  } else if (e.key !== START_KEY) {
    return; // only "]" cares about key-up
  }
  if (IS_TOP) handleKey(e.key, down);
  else relayKey(e.key, down);
}

document.addEventListener("keydown", (e) => onKeyEvent(e, true), true);
document.addEventListener("keyup", (e) => onKeyEvent(e, false), true);

// ---- Top frame only: marking state + selection layer ----

let startHeld = false; // is "]" currently held down?
let marking = false; // has the first corner been placed?
let corner1 = null;
let shield = null;
let rubber = null;
let requestSeq = 0; // lets us ignore answers to superseded requests

function handleKey(key, down) {
  if (key === START_KEY) {
    startHeld = down;
    if (down) {
      if (!marking) showShield();
    } else if (!marking) {
      hideShield();
    }
    return;
  }
  if (!down) return;

  if (key === "Escape") {
    if (marking || shield) cancelMarking();
  } else if (key === CONFIG.toggleKey) {
    if (overlayEl) overlayEl.classList.toggle("cursor-ai-visible");
  } else if (key === COLOR_KEY) {
    darkText = !darkText;
    saveDarkText(darkText);
    if (overlayEl) applyTextColorClass();
  }
}

function swallow(e) {
  e.preventDefault();
  e.stopPropagation();
}

function showShield() {
  if (shield) return;
  shield = document.createElement("div");
  shield.id = "cursor-ai-shield";
  rubber = document.createElement("div");
  rubber.id = "cursor-ai-rubber";
  rubber.style.display = "none";
  shield.appendChild(rubber);

  shield.addEventListener("pointerdown", onShieldDown);
  shield.addEventListener("pointermove", onShieldMove);
  for (const type of ["mousedown", "mouseup", "pointerup", "click", "dblclick", "auxclick", "contextmenu"]) {
    shield.addEventListener(type, swallow);
  }
  document.documentElement.appendChild(shield);
}

function hideShield() {
  if (shield) shield.remove();
  shield = null;
  rubber = null;
}

function cancelMarking() {
  marking = false;
  corner1 = null;
  startHeld = false;
  hideShield();
}

function drawRubber(a, b) {
  if (!rubber) return;
  rubber.style.display = "block";
  rubber.style.left = Math.min(a.x, b.x) + "px";
  rubber.style.top = Math.min(a.y, b.y) + "px";
  rubber.style.width = Math.abs(b.x - a.x) + "px";
  rubber.style.height = Math.abs(b.y - a.y) + "px";
}

function onShieldMove(e) {
  if (marking) drawRubber(corner1, { x: e.clientX, y: e.clientY });
}

function onShieldDown(e) {
  swallow(e);
  if (e.button !== 0) return; // only the primary button places corners

  const point = { x: e.clientX, y: e.clientY };
  if (!marking) {
    marking = true;
    corner1 = point;
    drawRubber(point, point);
    return;
  }

  // Second press finishes the region.
  const first = corner1;
  marking = false;
  corner1 = null;
  hideShield();

  const left = Math.min(first.x, point.x);
  const top = Math.min(first.y, point.y);
  const width = Math.abs(point.x - first.x);
  const height = Math.abs(point.y - first.y);

  if (width < 10 || height < 10) {
    showOverlay("That area is too small — hold ] and pick two corners further apart.", { error: true });
    return;
  }

  askAboutRegion({
    left,
    top,
    width,
    height,
    // Lets the background script work out the screenshot-pixels-per-CSS-pixel
    // scale from the real image size, so browser zoom and Retina can't skew the crop.
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight
  });
}

// If the whole window loses focus (alt-tab etc.) we may never see key-up, so reset.
// "blur" also fires when focus merely moves into an iframe; document.hasFocus()
// stays true in that case, so we only reset when focus truly left the page.
if (IS_TOP) {
  window.addEventListener("blur", () => {
    setTimeout(() => {
      if (document.hasFocus()) return;
      if (marking || shield) cancelMarking();
    }, 0);
  });
}

// ---- Top frame only: capture + ask ----

async function askAboutRegion(payload) {
  const mine = ++requestSeq;

  // Keep our own widget out of the screenshot.
  if (overlayEl) overlayEl.classList.remove("cursor-ai-visible");
  await nextPaint();

  let response;
  try {
    response = await sendToBackground({ type: "ASK_AI", payload });
  } catch (err) {
    if (mine === requestSeq) showOverlay(describeExtensionError(err), { error: true });
    return;
  }
  if (mine !== requestSeq) return; // a newer request replaced this one

  if (!response) showOverlay("No response from background script.", { error: true });
  else if (response.ok) showOverlay(response.answer);
  else showOverlay("Error: " + response.error, { error: true });
}

if (IS_TOP) {
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg) return;
    if (msg.type === "KEY_EVENT") handleKey(msg.key, !!msg.down); // relayed from an iframe
    else if (msg.type === "CAPTURED") showOverlay("Thinking…", { loading: true }); // screenshot is done
  });
}
