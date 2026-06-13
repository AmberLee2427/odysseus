/**
 * Shared speech controls for substantial text fields.
 *
 * Uses the configured STT/TTS provider, so Browser, Local, and API endpoint
 * modes all work without individual panels needing speech-specific wiring.
 */

import voiceRecorderModule from './voiceRecorder.js';
import uiModule from './ui.js';
import settingsModule from './settings.js';

const MIC_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/><path d="M8 22h8"/></svg>';
const STOP_ICON = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
const SPEAKER_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>';

let toolbar = null;
let activeTarget = null;
let micButton = null;
let speakButton = null;
let repositionFrame = null;

function _eligible(target) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.id === 'message' || target.closest('.chat-input-bar')) return false;
  if (target.matches('textarea')) {
    if (target.disabled || target.hidden) return false;
  } else if (!target.isContentEditable) {
    return false;
  }
  if (target.closest(
    '#settings-modal, #admin-modal, #theme-modal, .search-overlay, ' +
    '.doc-find-bar, [data-speech-controls="off"]'
  )) return false;
  return true;
}

function _text(target) {
  if (!target) return '';
  if (target.matches('textarea')) {
    const start = target.selectionStart;
    const end = target.selectionEnd;
    return start !== end ? target.value.slice(start, end) : target.value;
  }
  const selection = window.getSelection();
  if (selection && selection.rangeCount && target.contains(selection.anchorNode) && !selection.isCollapsed) {
    return selection.toString();
  }
  return target.innerText || target.textContent || '';
}

function _position() {
  repositionFrame = null;
  if (!toolbar || !activeTarget || !activeTarget.isConnected) return;
  const rect = activeTarget.getBoundingClientRect();
  if (rect.width < 24 || rect.height < 20 || rect.bottom < 0 || rect.top > window.innerHeight) {
    toolbar.hidden = true;
    return;
  }
  toolbar.hidden = false;
  const width = toolbar.offsetWidth || 70;
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width - 6));
  const top = Math.max(8, Math.min(window.innerHeight - 38, rect.top + 6));
  toolbar.style.left = `${left}px`;
  toolbar.style.top = `${top}px`;
}

function _schedulePosition() {
  if (!repositionFrame) repositionFrame = requestAnimationFrame(_position);
}

function _syncAvailability() {
  if (!toolbar) return;
  const sttReady = voiceRecorderModule._sttProvider && voiceRecorderModule._sttProvider !== 'disabled';
  const ttsReady = !!(window.aiTTSManager?.available && window.aiTTSManager?._provider !== 'disabled');
  micButton.classList.toggle('unavailable', !sttReady);
  micButton.setAttribute('aria-disabled', sttReady ? 'false' : 'true');
  micButton.title = sttReady ? 'Dictate into this field' : 'Set up Speech to Text in Settings';
  speakButton.classList.toggle('unavailable', !ttsReady);
  speakButton.setAttribute('aria-disabled', ttsReady ? 'false' : 'true');
  speakButton.title = ttsReady ? 'Read selection or field aloud' : 'Set up Text to Speech in Settings';
}

function _openSpeechSettings(id) {
  settingsModule.open('ai');
  setTimeout(() => {
    const card = document.getElementById(id);
    card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card?.classList.add('speech-settings-highlight');
    setTimeout(() => card?.classList.remove('speech-settings-highlight'), 1600);
  }, 50);
}

function _showFor(target) {
  if (!_eligible(target)) return;
  activeTarget = target;
  _syncAvailability();
  _schedulePosition();
}

function _hideSoon() {
  setTimeout(() => {
    if (!toolbar?.matches(':hover') && document.activeElement !== activeTarget &&
        !voiceRecorderModule.getIsRecording()) {
      toolbar.hidden = true;
      activeTarget = null;
    }
  }, 120);
}

function _startDictation() {
  if (!activeTarget) return;
  if (micButton.classList.contains('unavailable')) {
    _openSpeechSettings('speech-stt-settings');
    return;
  }
  if (voiceRecorderModule.getIsRecording()) {
    voiceRecorderModule.stopRecording();
    return;
  }
  voiceRecorderModule.startRecording(
    null,
    uiModule.showToast,
    uiModule.showError,
    activeTarget
  );
}

function _readAloud() {
  if (!activeTarget) return;
  if (speakButton.classList.contains('unavailable')) {
    _openSpeechSettings('speech-tts-settings');
    return;
  }
  const manager = window.aiTTSManager;
  if (manager.isPlaying || manager._processing) {
    manager.stop();
    speakButton.classList.remove('active');
    return;
  }
  const text = _text(activeTarget).trim();
  if (!text) {
    uiModule.showToast('Nothing to read');
    return;
  }
  speakButton.classList.add('active');
  const reset = () => {
    speakButton.classList.remove('active', 'loading', 'playing');
    speakButton.innerHTML = SPEAKER_ICON;
    speakButton.style.color = '';
    _syncAvailability();
  };
  manager.enqueue(text, speakButton, reset);
}

export function init() {
  if (toolbar) return;
  toolbar = document.createElement('div');
  toolbar.className = 'speech-field-controls';
  toolbar.hidden = true;
  toolbar.setAttribute('role', 'toolbar');
  toolbar.setAttribute('aria-label', 'Speech controls');
  toolbar.innerHTML = `
    <button type="button" class="speech-field-btn speech-field-mic" aria-label="Dictate">${MIC_ICON}</button>
    <button type="button" class="speech-field-btn speech-field-speak" aria-label="Read aloud">${SPEAKER_ICON}</button>
  `;
  document.body.appendChild(toolbar);
  micButton = toolbar.querySelector('.speech-field-mic');
  speakButton = toolbar.querySelector('.speech-field-speak');
  toolbar.addEventListener('pointerdown', (event) => event.preventDefault());
  micButton.addEventListener('click', _startDictation);
  speakButton.addEventListener('click', _readAloud);

  document.addEventListener('focusin', (event) => _showFor(event.target));
  document.addEventListener('focusout', _hideSoon);
  document.addEventListener('selectionchange', _schedulePosition);
  window.addEventListener('resize', _schedulePosition);
  window.addEventListener('scroll', _schedulePosition, true);
  window.addEventListener('odysseus:recording-state', (event) => {
    const recording = !!event.detail?.recording;
    micButton.classList.toggle('active', recording);
    micButton.innerHTML = recording ? STOP_ICON : MIC_ICON;
    micButton.title = recording ? 'Stop dictation' : 'Dictate into this field';
    if (!recording) _syncAvailability();
  });
  window.addEventListener('odysseus:speech-settings-changed', _syncAvailability);

  setInterval(_syncAvailability, 5000);
}

export default { init };
