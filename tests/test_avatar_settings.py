import base64
import io
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from routes import prefs_routes
from routes.prefs_routes import _validate_pref


ROOT = Path(__file__).resolve().parents[1]


def test_account_settings_exposes_avatar_controls():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="settings-avatar-input"' in html
    assert 'id="settings-avatar-upload"' in html
    assert 'id="settings-avatar-remove"' in html


def test_avatar_is_a_per_user_pref_and_rendered_safely():
    settings = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "fetch('/api/prefs/avatar'" in settings
    assert "fetch('/api/prefs/avatar/upload'" in settings
    assert "safeRasterDataUrl(pref.value)" in settings
    assert settings.index("initAccount();") < settings.index("initDefaultChat();")
    assert "/api/prefs/avatar" in app
    assert "odysseus-avatar-changed" in app


def test_avatar_pref_validation_rejects_non_images_and_oversized_values():
    avatar = "data:image/webp;base64,AAAA"
    assert _validate_pref("avatar", avatar) == avatar
    assert _validate_pref("avatar", "") == ""
    assert _validate_pref("theme", {"custom": True}) == {"custom": True}

    with pytest.raises(HTTPException):
        _validate_pref("avatar", "https://example.com/avatar.png")
    with pytest.raises(HTTPException):
        _validate_pref("avatar", "data:image/webp;base64," + ("A" * 512_000))


def test_avatar_multipart_upload_is_resized_and_saved_per_user(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_routes, "PREFS_FILE", str(tmp_path / "prefs.json"))
    app = FastAPI()

    @app.middleware("http")
    async def attach_user(request, call_next):
        request.state.current_user = "amber"
        return await call_next(request)

    app.include_router(prefs_routes.setup_prefs_routes())
    image = Image.new("RGB", (800, 400), "#8a4fff")
    source = io.BytesIO()
    image.save(source, "PNG")

    client = TestClient(app)
    response = client.post(
        "/api/prefs/avatar/upload",
        files={"file": ("avatar.png", source.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    value = response.json()["value"]
    assert value.startswith("data:image/webp;base64,")
    saved = client.get("/api/prefs/avatar").json()["value"]
    assert saved == value
    decoded = Image.open(io.BytesIO(base64.b64decode(value.split(",", 1)[1])))
    assert decoded.size == (256, 256)
