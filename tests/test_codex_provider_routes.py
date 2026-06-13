import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.codex_provider_routes as codex_provider_routes


def _client(monkeypatch):
    monkeypatch.setattr(codex_provider_routes, "_require_loopback", lambda request: None)
    app = FastAPI()
    app.include_router(codex_provider_routes.setup_codex_provider_routes())
    return TestClient(app)


def test_codex_provider_models(monkeypatch):
    async def fake_models():
        return ["gpt-test", "gpt-test-mini"]

    monkeypatch.setattr(codex_provider_routes, "list_codex_models", fake_models)
    response = _client(monkeypatch).get("/api/codex-provider/v1/models")

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {"id": "gpt-test", "object": "model"},
            {"id": "gpt-test-mini", "object": "model"},
        ],
    }


def test_codex_provider_non_streaming_chat(monkeypatch):
    async def fake_stream(messages, model):
        yield {"type": "text", "text": "hello"}
        yield {"type": "text", "text": " odysseus"}

    monkeypatch.setattr(codex_provider_routes, "stream_codex_chat", fake_stream)
    response = _client(monkeypatch).post(
        "/api/codex-provider/v1/chat/completions",
        json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "gpt-test"
    assert data["choices"][0]["message"] == {
        "role": "assistant",
        "content": "hello odysseus",
    }


def test_codex_provider_streaming_chat(monkeypatch):
    async def fake_stream(messages, model):
        yield {"type": "text", "text": "hello"}
        yield {"type": "usage", "usage": {"inputTokens": 3, "outputTokens": 2, "totalTokens": 5}}

    monkeypatch.setattr(codex_provider_routes, "stream_codex_chat", fake_stream)
    response = _client(monkeypatch).post(
        "/api/codex-provider/v1/chat/completions",
        json={
            "model": "gpt-test",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    chunks = [json.loads(line[6:]) for line in lines if line != "data: [DONE]"]
    assert chunks[0]["choices"][0]["delta"]["content"] == "hello"
    assert chunks[1]["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    assert lines[-1] == "data: [DONE]"
