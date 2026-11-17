// background.js — service worker
// Edit the CONFIG block below with your own Anthropic (Claude) API key / model.
// There is no popup UI — this file is the settings screen.

const CONFIG = {
  apiKey: "YOUR_ANTHROPIC_API_KEY_HERE",
  apiUrl: "https://api.anthropic.com/v1/messages",
  apiVersion: "2023-06-01",
  // Model IDs: "claude-sonnet-5-5" (default, strong all-rounder),
  // "claude-haiku-5-5" (fastest / cheapest), "claude-opus-5-5" (most capable, slower).
  model: "claude-sonnet-5-5",
  maxTokens: 4096
};

function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

// `rect` is in CSS pixels of the top page's viewport; viewportWidth/Height are that
// viewport's CSS size. The screenshot's pixels-per-CSS-pixel is derived from the real
// image size (per axis), so browser zoom and Retina displays can't skew the crop.
// Returns bare base64 PNG data (no "data:image/png;base64," prefix).
async function cropScreenshot(dataUrl, rect) {
  const resp = await fetch(dataUrl);
  const blob = await resp.blob();
  const bitmap = await createImageBitmap(blob);

  const kx = bitmap.width / (rect.viewportWidth || bitmap.width);
  const ky = bitmap.height / (rect.viewportHeight || bitmap.height);

  let sx = Math.round(rect.left * kx);
  let sy = Math.round(rect.top * ky);
  let sw = Math.round(rect.width * kx);
  let sh = Math.round(rect.height * ky);

  sx = Math.max(0, Math.min(sx, bitmap.width - 1));
  sy = Math.max(0, Math.min(sy, bitmap.height - 1));
  sw = Math.max(1, Math.min(sw, bitmap.width - sx));
  sh = Math.max(1, Math.min(sh, bitmap.height - sy));

  const canvas = new OffscreenCanvas(sw, sh);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, sx, sy, sw, sh, 0, 0, sw, sh);

  const outBlob = await canvas.convertToBlob({ type: "image/png" });
  const buf = await outBlob.arrayBuffer();
  return arrayBufferToBase64(buf);
}

async function callClaude({ promptText, base64Image }) {
  if (!CONFIG.apiKey || CONFIG.apiKey === "YOUR_ANTHROPIC_API_KEY_HERE") {
    throw new Error("Set your API key in background.js (CONFIG.apiKey).");
  }

  let maxTokens = CONFIG.maxTokens;
  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await fetch(CONFIG.apiUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": CONFIG.apiKey,
        "anthropic-version": CONFIG.apiVersion,
        // Required for requests that originate from a browser context (extensions included).
        "anthropic-dangerous-direct-browser-access": "true"
      },
      body: JSON.stringify({
        model: CONFIG.model,
        max_tokens: maxTokens,
        messages: [
          {
            role: "user",
            content: [
              { type: "image", source: { type: "base64", media_type: "image/png", data: base64Image } },
              { type: "text", text: promptText }
            ]
          }
        ]
      })
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`API error ${res.status}: ${errText.slice(0, 300)}`);
    }

    const data = await res.json();
    const answer = (data.content || [])
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("")
      .trim();

    if (answer) return answer; // a truncated answer is still shown

    // The model can spend the whole budget on reasoning before writing text: retry once with more room.
    if (data.stop_reason === "max_tokens" && attempt === 0) {
      maxTokens = Math.min(maxTokens * 6, 16000);
      continue;
    }
    // e.g. stop_reason "refusal" — surface it instead of a bare "no answer".
    throw new Error(data.stop_reason ? `No answer (stop_reason: ${data.stop_reason})` : "No answer returned by the API.");
  }
}

async function handleScreenshotRequest(payload, sender) {
  const dataUrl = await new Promise((resolve, reject) => {
    chrome.tabs.captureVisibleTab(sender.tab && sender.tab.windowId, { format: "png" }, (url) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(url);
    });
  });

  // The picture has been taken, so the page can now show "Thinking…" without it ending up in the shot.
  if (sender.tab) {
    chrome.tabs.sendMessage(sender.tab.id, { type: "CAPTURED" }, { frameId: 0 }, () => void chrome.runtime.lastError);
  }

  const base64Image = await cropScreenshot(dataUrl, payload);

  const promptText =
    "Reply with only the final answer — no explanation, no reasoning, no extra words. Answer this image:";

  return callClaude({ promptText, base64Image });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return false;

  // A key pressed inside an iframe: pass it up to the top frame, which owns all the state.
  if (message.type === "FRAME_KEY") {
    if (sender.tab && sender.frameId !== 0) {
      chrome.tabs.sendMessage(
        sender.tab.id,
        { type: "KEY_EVENT", key: message.key, down: !!message.down },
        { frameId: 0 },
        () => void chrome.runtime.lastError
      );
    }
    return false;
  }

  if (message.type === "ASK_AI") {
    (async () => {
      try {
        const answer = await handleScreenshotRequest(message.payload, sender);
        sendResponse({ ok: true, answer });
      } catch (err) {
        sendResponse({ ok: false, error: err.message || String(err) });
      }
    })();
    return true; // keep the message channel open for the async response
  }

  return false;
});
