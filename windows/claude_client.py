"""Talks to Anthropic's Messages API."""
import base64

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class ClaudeError(Exception):
    pass


def _send(key, body, http=requests, timeout=60):
    try:
        r = http.post(
            API_URL,
            headers={"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"},
            json=body,
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise ClaudeError(f"Network error: {e}") from e
    if r.status_code != 200:
        msg = ""
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = (r.text or "")[:200]
        hint = " (check your API key)" if r.status_code in (401, 403) else ""
        raise ClaudeError(f"API error {r.status_code}: {msg}{hint}")
    return r.json()


def _text(data):
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _post(key, body, http=requests, timeout=60):
    data = _send(key, body, http, timeout)
    text = _text(data)
    if not text:
        sr = data.get("stop_reason")
        raise ClaudeError(f"No answer (stop_reason: {sr})" if sr else "No answer returned.")
    return text


MAX_RETRY_TOKENS = 16000


def ask_about_image(key, png_bytes, model, instruction, max_tokens=4096, http=requests):
    if not key:
        raise ClaudeError("No API key saved. Paste it in the main window and press Save.")
    media = "image/jpeg" if png_bytes[:3] == b"\xff\xd8\xff" else "image/png"
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media,
                                     "data": base64.b64encode(png_bytes).decode("ascii")}},
        {"type": "text", "text": instruction},
    ]
    tokens = int(max_tokens)
    for attempt in range(2):
        data = _send(key, {"model": model, "max_tokens": tokens,
                           "messages": [{"role": "user", "content": content}]}, http)
        text = _text(data)
        if text:
            return text   # a truncated answer is still shown
        sr = data.get("stop_reason")
        if sr == "max_tokens" and attempt == 0:
            # The model used the whole budget before writing text (reasoning counts too): retry bigger.
            tokens = min(tokens * 6, MAX_RETRY_TOKENS)
            continue
        raise ClaudeError(f"No answer (stop_reason: {sr})" if sr else "No answer returned.")


def test_key(key, model, http=requests):
    body = {"model": model, "max_tokens": 16,
            "messages": [{"role": "user", "content": "Reply with the single word: ok"}]}
    return _post(key, body, http, timeout=30)
