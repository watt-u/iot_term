"""Tests for ai_caption.py with every HTTP call mocked (httpx.MockTransport)."""

import base64
import json
import threading

import httpx
import pytest

import ai_caption
from ai_caption import PROMPT, UNAVAILABLE, CaptionError, Captioner, caption_jpeg

JPEG = b"\xff\xd8\xff\xe0fakejpeg\xff\xd9"
B64 = base64.b64encode(JPEG).decode()


def mock_client(handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), seen


# ---------------------------------------------------------------- providers
def test_gemini_request_and_parse():
    client, seen = mock_client(
        lambda r: httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "The driver's eyes are closed. "}]}}]},
        )
    )
    out = caption_jpeg(JPEG, "gemini", "k123", client=client)
    assert out == "The driver's eyes are closed."
    req = seen[0]
    assert req.url.host == "generativelanguage.googleapis.com"
    assert req.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert req.headers["x-goog-api-key"] == "k123"
    assert "k123" not in str(req.url)  # key is not in the URL
    body = json.loads(req.content)
    parts = body["contents"][0]["parts"]
    assert parts[0]["inline_data"] == {"mime_type": "image/jpeg", "data": B64}
    assert parts[1]["text"] == PROMPT


def test_anthropic_request_and_parse():
    client, seen = mock_client(
        lambda r: httpx.Response(
            200,
            json={
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {"type": "text", "text": "The driver looks drowsy with eyes half closed."},
                ],
                "stop_reason": "end_turn",
            },
        )
    )
    out = caption_jpeg(JPEG, "anthropic", "sk-test", client=client)
    assert out == "The driver looks drowsy with eyes half closed."
    req = seen[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "sk-test"
    assert req.headers["anthropic-version"] == ai_caption.ANTHROPIC_VERSION
    body = json.loads(req.content)
    assert body["model"] == "claude-opus-5-5"
    assert "temperature" not in body
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": B64}}
    assert content[1] == {"type": "text", "text": PROMPT}


def test_anthropic_refusal_is_error():
    client, _ = mock_client(lambda r: httpx.Response(200, json={"content": [], "stop_reason": "refusal"}))
    with pytest.raises(CaptionError):
        caption_jpeg(JPEG, "anthropic", "k", client=client)


def test_openai_request_and_parse():
    client, seen = mock_client(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "Alert driver, eyes open."}}]})
    )
    out = caption_jpeg(JPEG, "openai", "sk-o", model="gpt-x", client=client)
    assert out == "Alert driver, eyes open."
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-o"
    body = json.loads(req.content)
    assert body["model"] == "gpt-x"
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": PROMPT}
    assert content[1]["image_url"]["url"] == f"data:image/jpeg;base64,{B64}"


def test_custom_model_used():
    client, seen = mock_client(lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "x"}]}}]}))
    caption_jpeg(JPEG, "gemini", "k", model="gemini-other", client=client)
    assert seen[0].url.path.endswith("/gemini-other:generateContent")


def test_http_error_raises():
    client, _ = mock_client(lambda r: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(httpx.HTTPStatusError):
        caption_jpeg(JPEG, "openai", "k", client=client)


def test_empty_caption_raises():
    client, _ = mock_client(lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": []}}]}))
    with pytest.raises(CaptionError):
        caption_jpeg(JPEG, "gemini", "k", client=client)


def test_unknown_provider_and_missing_key():
    with pytest.raises(CaptionError):
        caption_jpeg(JPEG, "nope", "k")
    with pytest.raises(CaptionError):
        caption_jpeg(JPEG, "gemini", "")


# ---------------------------------------------------------------- Captioner
@pytest.fixture
def snap(tmp_path):
    p = tmp_path / "drowsy.jpg"
    p.write_bytes(JPEG)
    return str(p)


def test_captioner_background_success(snap, monkeypatch):
    calls = []

    def fake(jpeg, provider, key, model, timeout):
        calls.append((jpeg, provider, key, model, threading.current_thread().name))
        return "Eyes closed, head down."

    monkeypatch.setattr(ai_caption, "caption_jpeg", fake)
    c = Captioner(provider="anthropic", api_key="k", model="")
    results = []
    assert c.submit(snap, lambda cap, lat: results.append((cap, lat)))
    c.join(timeout=5)
    assert results[0][0] == "Eyes closed, head down."
    assert results[0][1] >= 0
    assert calls[0][:3] == (JPEG, "anthropic", "k")
    assert calls[0][4] == "ai-caption"  # ran on the worker thread
    assert len(c.latencies) == 1


def test_captioner_network_error_gives_unavailable(snap, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no internet")

    monkeypatch.setattr(ai_caption, "caption_jpeg", boom)
    c = Captioner(provider="gemini", api_key="k")
    results = []
    c.submit(snap, lambda cap, lat: results.append(cap))
    c.join(timeout=5)
    assert results == [UNAVAILABLE]
    assert c.latencies == []


def test_captioner_missing_file_gives_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_caption, "read_snapshot", lambda p: (_ for _ in ()).throw(CaptionError("missing")))
    c = Captioner(provider="gemini", api_key="k")
    assert c.caption_path(str(tmp_path / "nope.jpg"))[0] == UNAVAILABLE


def test_captioner_no_key_gives_unavailable(snap):
    c = Captioner(provider="gemini", api_key="")
    assert c.caption_path(snap)[0] == UNAVAILABLE


def test_submit_does_not_block(snap, monkeypatch):
    gate = threading.Event()

    def slow(*a, **k):
        gate.wait(5)
        return "ok"

    monkeypatch.setattr(ai_caption, "caption_jpeg", slow)
    c = Captioner(provider="gemini", api_key="k", max_queue=1)
    results = []
    c.submit(snap, lambda cap, lat: results.append(cap))  # taken by the worker
    import time

    time.sleep(0.05)
    t0 = time.monotonic()
    c.submit(snap, lambda cap, lat: results.append(cap))  # fills the queue
    c.submit(snap, lambda cap, lat: results.append(cap))  # queue full -> unavailable at once
    assert time.monotonic() - t0 < 0.5
    assert results == [UNAVAILABLE]
    gate.set()
    c.join(timeout=5)
    assert results == [UNAVAILABLE, "ok", "ok"]


def test_read_snapshot_waits_for_file(tmp_path):
    p = tmp_path / "late.jpg"
    threading.Timer(0.2, lambda: p.write_bytes(JPEG)).start()
    assert ai_caption.read_snapshot(str(p), wait_s=2) == JPEG


def test_read_snapshot_times_out(tmp_path):
    with pytest.raises(CaptionError):
        ai_caption.read_snapshot(str(tmp_path / "never.jpg"), wait_s=0.2)
