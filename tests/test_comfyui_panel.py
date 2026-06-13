from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.middleware import comfyui_origin_for_request


def test_comfyui_origin_uses_request_hostname_for_lan_access(monkeypatch):
    monkeypatch.delenv("COMFYUI_URL", raising=False)
    monkeypatch.setenv("COMFYUI_PORT", "8188")
    app = FastAPI()

    @app.get("/config")
    async def config(request: Request):
        return {"url": comfyui_origin_for_request(request)}

    response = TestClient(app, base_url="http://192.168.12.238:7000").get("/config")

    assert response.json() == {"url": "http://192.168.12.238:8188"}


def test_comfyui_panel_is_wired_into_sidebar_rail_and_deep_link():
    root = Path(__file__).resolve().parent.parent
    index = (root / "static/index.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    panel_js = (root / "static/js/comfyui.js").read_text(encoding="utf-8")

    assert 'id="tool-comfyui-btn"' in index
    assert 'id="rail-comfyui"' in index
    assert "'/comfyui':   () => comfyuiModule.open()" in app_js
    assert "if (_iframe && !_iframe.src) _iframe.src = url;" in panel_js
    assert "_panel.classList.add('hidden');" in panel_js
