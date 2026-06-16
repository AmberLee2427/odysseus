from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_chat_has_single_stop_control_path_without_extra_buttons():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    app_js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "static/js/chat.js").read_text(encoding="utf-8")
    tts_js = (ROOT / "static/js/tts-ai.js").read_text(encoding="utf-8")

    assert 'id="generation-stop-btn"' not in html
    assert 'id="global-stop-all-btn"' not in html
    assert 'id="speech-action-btn"' in html
    assert ".generation-stop-btn" not in css
    assert ".global-stop-all-btn" not in css
    assert ".speech-action-btn" in css
    assert "mic-mode" not in css
    assert "mic-mode" not in app_js
    assert "mic-mode" not in chat_js
    assert "generationStopBtn" not in chat_js
    assert "updateSubmitButton('streaming', submitBtn);" in chat_js[
        chat_js.index("export async function resumeStream("):
    ]
    assert 'id="export-stop-all-btn"' in html
    assert "closest('#export-stop-all-btn')" in app_js
    assert "e.key !== 'Escape'" in app_js
    assert "chatModule.handleChatSubmit" in app_js
    assert "voiceRecorderModule.startRecording" in app_js
    assert "speechBtn.addEventListener('click'" in app_js
    assert "fetch('/api/chat/stop_all'" not in app_js
    assert "window.aiTTSManager?.stop?.()" in app_js
    assert "mgr._streamActive" in tts_js
