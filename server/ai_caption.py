"""AI caption for drowsy snapshots (milestone M5).

`Captioner.submit(path, on_done)` reads the JPEG and asks a cloud vision model
for a one-sentence description in a background worker thread, then calls
`on_done(caption, latency_s)`. The rules loop never waits for it.

Provider is chosen with AI_PROVIDER = gemini | anthropic | openai, using plain
HTTPS calls (httpx), the key in AI_API_KEY and the model in AI_MODEL (empty =
the default below). On any error (no internet, bad key, refusal, timeout) the
caption is "unavailable"; the local alert never depends on the cloud.
"""

from __future__ import annotations

import base64
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import httpx

log = logging.getLogger("ai_caption")

PROMPT = (
    "This is a driver-facing car camera frame. In one sentence, describe the driver's "
    "alertness (eyes, head pose, yawning, phone use)."
)
UNAVAILABLE = "unavailable"

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-4.1-mini",
}

ANTHROPIC_VERSION = "2026-10-21"


class CaptionError(Exception):
    pass


# ---------------------------------------------------------------- providers
def _gemini(client: httpx.Client, key: str, model: str, b64: str) -> str:
    r = client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                        {"text": PROMPT},
                    ],
                }
            ]
        },
    )
    r.raise_for_status()
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as e:
        raise CaptionError(f"no candidates in response: {str(data)[:200]}") from e
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _anthropic(client: httpx.Client, key: str, model: str, b64: str) -> str:
    r = client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            # Server-side refusal fallback: a declined request is retried on another model.
            "anthropic-beta": "server-side-fallback-2026-07-01",
        },
        json={
            "model": model,
            "max_tokens": 2048,
            "output_config": {"effort": "low"},
            "fallbacks": "default",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        },
    )
    r.raise_for_status()
    data = r.json()
    if data.get("stop_reason") == "refusal":
        raise CaptionError(f"refusal: {data.get('stop_details')}")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _openai(client: httpx.Client, key: str, model: str, b64: str) -> str:
    r = client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "max_completion_tokens": 300,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
        },
    )
    r.raise_for_status()
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise CaptionError(f"no choices in response: {str(data)[:200]}") from e


PROVIDERS: dict[str, Callable[[httpx.Client, str, str, str], str]] = {
    "gemini": _gemini,
    "anthropic": _anthropic,
    "openai": _openai,
}


# ------------------------------------------------------------------- public
def caption_jpeg(
    jpeg: bytes,
    provider: str,
    api_key: str,
    model: str | None = None,
    timeout: float = 20.0,
    client: httpx.Client | None = None,
) -> str:
    """Caption one JPEG. Raises on any failure (Captioner turns that into "unavailable")."""
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise CaptionError(f"unknown AI_PROVIDER {provider!r} (use gemini, anthropic or openai)")
    if not api_key:
        raise CaptionError("AI_API_KEY is empty")
    model = model or DEFAULT_MODELS[provider]
    b64 = base64.b64encode(jpeg).decode("ascii")
    own = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        text = PROVIDERS[provider](client, api_key, model, b64)
    finally:
        if own:
            client.close()
    text = " ".join(text.split())
    if not text:
        raise CaptionError("empty caption")
    return text


def read_snapshot(path: str, wait_s: float = 1.0) -> bytes:
    """Read the JPEG, waiting briefly in case the writer has not finished yet."""
    p = Path(path)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            data = p.read_bytes()
            if data:
                return data
        except FileNotFoundError:
            pass
        if time.monotonic() >= deadline:
            raise CaptionError(f"snapshot not readable: {path}")
        time.sleep(0.1)


class Captioner:
    """One background worker that captions snapshots in arrival order."""

    def __init__(
        self,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_queue: int = 8,
    ):
        self.provider = (provider if provider is not None else os.getenv("AI_PROVIDER", "gemini")).strip().lower()
        self.api_key = api_key if api_key is not None else os.getenv("AI_API_KEY", "")
        self.model = model if model is not None else (os.getenv("AI_MODEL") or None)
        self.timeout = timeout if timeout is not None else float(os.getenv("AI_TIMEOUT", "20"))
        self.latencies: list[float] = []
        self._q: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._run, name="ai-caption", daemon=True)
        self._thread.start()

    @property
    def model_name(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.provider, "?")

    def submit(self, path: str, on_done: Callable[[str, float], None]) -> bool:
        """Queue a snapshot. Returns False (and reports "unavailable") if the queue is full."""
        try:
            self._q.put_nowait((path, on_done))
            return True
        except queue.Full:
            log.warning("caption queue full, skipping %s", path)
            on_done(UNAVAILABLE, 0.0)
            return False

    def caption_path(self, path: str) -> tuple[str, float]:
        """Caption synchronously; never raises. Returns (caption, latency_s)."""
        t0 = time.monotonic()
        try:
            jpeg = read_snapshot(path)
            caption = caption_jpeg(jpeg, self.provider, self.api_key, self.model, self.timeout)
            latency = time.monotonic() - t0
            self.latencies.append(latency)
            avg = sum(self.latencies) / len(self.latencies)
            log.info(
                "caption ok provider=%s model=%s latency=%.2fs avg=%.2fs n=%d: %s",
                self.provider, self.model_name, latency, avg, len(self.latencies), caption,
            )
            return caption, latency
        except Exception as e:  # noqa: BLE001 - any failure means "unavailable"
            latency = time.monotonic() - t0
            log.warning(
                "caption unavailable provider=%s model=%s latency=%.2fs: %s",
                self.provider, self.model_name, latency, _describe(e),
            )
            return UNAVAILABLE, latency

    def join(self, timeout: float | None = None) -> None:
        """Wait until the queue is empty (tests and shutdown)."""
        end = None if timeout is None else time.monotonic() + timeout
        while self._q.unfinished_tasks:
            if end is not None and time.monotonic() > end:
                return
            time.sleep(0.01)

    def _run(self) -> None:
        while True:
            path, on_done = self._q.get()
            try:
                caption, latency = self.caption_path(path)
                try:
                    on_done(caption, latency)
                except Exception:  # noqa: BLE001
                    log.exception("caption callback failed")
            finally:
                self._q.task_done()


def _describe(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    return f"{type(e).__name__}: {e}"
