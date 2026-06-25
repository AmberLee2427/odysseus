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


def test_comfyui_panel_is_wired_into_gallery_tab_and_deep_link():
    root = Path(__file__).resolve().parent.parent
    index = (root / "static/index.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    panel_js = (root / "static/js/comfyui.js").read_text(encoding="utf-8")

    assert 'id="tool-comfyui-btn"' not in index
    assert 'id="rail-comfyui"' not in index
    assert "toolComfyuiBtn" not in app_js
    assert "'/comfyui':   () => galleryModule.openGallery({ tab: 'comfyui' })" in app_js
    assert "/api/comfyui/status" in panel_js
    assert "/api/comfyui/images" in panel_js
    assert "/api/comfyui/prompt" in panel_js
    assert "/api/comfyui/workflows/image_krea2_turbo_t2i.json" in panel_js
    assert "/api/gallery/library?tag=comfyui" in panel_js
    assert "COMFY_APPS" in panel_js
    assert "Krea 2" in panel_js
    assert "Ideogram 4" in panel_js
    assert "comfyui-krea-form" in panel_js
    assert "<h2>Workflow</h2>" not in panel_js
    assert "No iframe required" not in panel_js
    assert "Loaded through Odysseus" not in panel_js
    gallery_js = (root / "static/js/gallery.js").read_text(encoding="utf-8")
    assert 'data-tab="comfyui"' in gallery_js
    assert 'id="gallery-comfyui-container"' in gallery_js
    assert 'id="gallery-comfy-apps-settings"' in gallery_js
    assert "comfyuiModule.mountInto(comfyuiContainer)" in gallery_js
