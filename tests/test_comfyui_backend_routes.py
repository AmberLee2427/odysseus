from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.comfyui_routes import setup_comfyui_routes


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {"content-type": "application/json"}
        self.content = b"{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_comfyui_status_uses_backend_route(monkeypatch):
    calls = []

    async def fake_get(path, *, params=None):
        calls.append((path, params))
        if path == "/queue":
            return _FakeResponse({"queue_running": [1], "queue_pending": [2, 3]})
        if path == "/system_stats":
            return _FakeResponse({"system": {"os": "test"}})
        raise AssertionError(path)

    monkeypatch.setattr("routes.comfyui_routes._comfy_get", fake_get)

    app = FastAPI()
    app.include_router(setup_comfyui_routes())

    response = TestClient(app).get("/api/comfyui/status")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["queue_running"] == 1
    assert response.json()["queue_pending"] == 2
    assert calls == [("/queue", None), ("/system_stats", None)]


def test_comfyui_images_return_same_origin_view_urls(monkeypatch):
    history = {
        "prompt-a": {
            "status": {"status_str": "success"},
            "prompt": [None, None, {}],
            "outputs": {
                "9": {
                    "images": [
                        {
                            "filename": "ComfyUI_00001_.png",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                }
            },
        }
    }

    async def fake_get(path, *, params=None):
        assert path == "/history"
        return _FakeResponse(history)

    monkeypatch.setattr("routes.comfyui_routes._comfy_get", fake_get)

    app = FastAPI()
    app.include_router(setup_comfyui_routes())

    response = TestClient(app).get("/api/comfyui/images")

    assert response.status_code == 200
    image = response.json()["images"][0]
    assert image["url"].startswith("/api/comfyui/view?")
    assert "http://" not in image["url"]
    assert image["filename"] == "ComfyUI_00001_.png"
