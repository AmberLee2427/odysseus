from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shared_speech_controls_are_initialized():
    app_js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "import speechControlsModule from './js/speechControls.js';" in app_js
    assert "speechControlsModule.init();" in app_js


def test_voice_recorder_can_target_non_chat_editors():
    recorder = (ROOT / "static/js/voiceRecorder.js").read_text(encoding="utf-8")
    assert "startRecording(onFileCreated, showToast, showError, target = null)" in recorder
    assert "insertTranscription(transcript, showToast, target)" in recorder
    assert "input.isContentEditable" in recorder


def test_speech_controls_support_configured_browser_local_and_endpoint_providers():
    controls = (ROOT / "static/js/speechControls.js").read_text(encoding="utf-8")
    assert "voiceRecorderModule._sttProvider" in controls
    assert "window.aiTTSManager?.available" in controls

    stt = (ROOT / "services/stt/stt_service.py").read_text(encoding="utf-8")
    tts = (ROOT / "services/tts/tts_service.py").read_text(encoding="utf-8")
    for provider in ('"browser"', '"local"', '"endpoint:<id>"'):
        assert provider in stt
        assert provider in tts


def test_speech_settings_are_visible_and_chat_tts_can_be_shown():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert 'id="speech-tts-settings"' in html
    assert 'id="speech-stt-settings"' in html
    assert 'id="set-sttProviderSelect"' in html
    assert 'id="set-ttsBrowserVoiceSelect"' in html
    assert 'id="overflow-tts-btn" style="display:none"' in html
    assert 'id="overflow-tts-btn" hidden' not in html


def test_browser_voice_picker_uses_voice_uri_and_async_voice_loading():
    settings = (ROOT / "static/js/settings.js").read_text(encoding="utf-8")
    tts = (ROOT / "static/js/tts-ai.js").read_text(encoding="utf-8")
    assert "populateBrowserVoices" in settings
    assert "voiceschanged" in settings
    assert "voice.voiceURI || voice.name" in settings
    assert "(v.voiceURI || '').toLowerCase() === target" in tts
    assert "_waitForBrowserVoices" in tts
    assert "synth.addEventListener('voiceschanged', finish)" in tts
    assert "await this._waitForBrowserVoices()" in tts
