import { makeWindowDraggable } from './windowDrag.js';
import * as Modals from './modalManager.js';

let _panel = null;
let _terminal = null;
let _fitAddon = null;
let _socket = null;
let _httpSession = null;
let _httpPolling = false;
let _open = false;
let _libraryPromise = null;
let _panelObserver = null;
let _themeObserver = null;

function _setSessionDot(active) {
  ['tool-terminal-btn', 'rail-terminal'].forEach(id => {
    document.getElementById(id)?.classList.toggle('terminal-session-active', active);
  });
}

export async function syncSessionIndicator() {
  try {
    const response = await fetch('/api/terminal/session', {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) return;
    _setSessionDot(!!(await response.json()).active);
  } catch (_) {}
}

function _loadLibrary() {
  if (!_libraryPromise) {
    _libraryPromise = Promise.all([
      import('https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/+esm'),
      import('https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/+esm'),
    ]).then(([xterm, fit]) => ({ Terminal: xterm.Terminal, FitAddon: fit.FitAddon }));
  }
  return _libraryPromise;
}

function _setActive(active) {
  document.getElementById('tool-terminal-btn')?.classList.toggle('active', active);
  document.getElementById('rail-terminal')?.classList.toggle('active-section', active);
}

function _setStatus(text, state = '') {
  const status = _panel?.querySelector('#terminal-status');
  if (!status) return;
  status.textContent = text;
  status.dataset.state = state;
}

function _terminalTheme() {
  const styles = getComputedStyle(document.documentElement);
  const value = (name, fallback) => styles.getPropertyValue(name).trim() || fallback;
  return {
    background: value('--bg', '#0b0d10'),
    foreground: value('--fg', '#d8dee9'),
    cursor: value('--accent', value('--red', '#e06c75')),
    selectionBackground: value('--border', '#3b4252'),
  };
}

function _applyTerminalTheme() {
  if (_terminal) _terminal.options.theme = _terminalTheme();
}

function _send(payload) {
  if (_socket?.readyState === WebSocket.OPEN) {
    _socket.send(JSON.stringify(payload));
    return;
  }
  if (!_httpSession) return;
  const action = payload.type === 'resize' ? 'resize' : 'input';
  fetch(`/api/terminal/session/${_httpSession}/${action}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

function _fit() {
  if (!_fitAddon || !_terminal || !_open) return;
  try {
    _fitAddon.fit();
    _send({ type: 'resize', cols: _terminal.cols, rows: _terminal.rows });
  } catch (_) {}
}

function _connect() {
  _closeTransport(false);
  _terminal?.reset();
  _terminal?.writeln('\x1b[90mConnecting to the Odysseus container...\x1b[0m');
  _setStatus('connecting', 'connecting');
  _connectHttp(true);
}

async function _connectHttp(forceNew = false) {
  _setStatus('connecting through proxy', 'connecting');
  try {
    const response = await fetch(`/api/terminal/session${forceNew ? '?new=1' : ''}`, {
      method: 'POST',
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const session = await response.json();
    _httpSession = session.id;
    _setSessionDot(true);
    _setStatus(session.reused ? 'reconnected' : 'connected', 'connected');
    _fit();
    _terminal?.focus();
    _pollHttp();
  } catch (error) {
    _setStatus('connection error', 'error');
    _terminal?.writeln(`\r\n\x1b[31mTerminal connection failed: ${error.message}\x1b[0m`);
  }
}

async function _pollHttp() {
  if (_httpPolling || !_httpSession) return;
  _httpPolling = true;
  try {
    while (_httpSession && _open) {
      const response = await fetch(`/api/terminal/session/${_httpSession}/output`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = new Uint8Array(await response.arrayBuffer());
      if (data.length) _terminal?.write(data);
      if (response.headers.get('X-Terminal-Closed') === '1') {
        _setStatus('shell exited', 'error');
        _setSessionDot(false);
        break;
      }
      await new Promise(resolve => setTimeout(resolve, data.length ? 20 : 160));
    }
  } catch (error) {
    if (_httpSession) _setStatus('connection error', 'error');
  } finally {
    _httpPolling = false;
  }
}

function _closeTransport(terminate = false) {
  if (_socket) {
    _socket.onclose = null;
    _socket.close();
    _socket = null;
  }
  if (_httpSession) {
    const session = _httpSession;
    _httpSession = null;
    if (terminate) {
      fetch(`/api/terminal/session/${session}`, {
        method: 'DELETE',
        credentials: 'same-origin',
        keepalive: true,
      }).then(() => _setSessionDot(false)).catch(() => {});
    }
  }
}

async function _mount() {
  if (_panel) return _panel;
  const { Terminal, FitAddon } = await _loadLibrary();
  _panel = document.createElement('div');
  _panel.id = 'terminal-modal';
  _panel.className = 'modal hidden';
  _panel.innerHTML = `
    <div class="modal-content terminal-modal-content">
      <header class="modal-header">
        <div class="terminal-title-group">
          <h4>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3"/><line x1="13" y1="15" x2="17" y2="15"/></svg>
            Terminal
          </h4>
          <span class="terminal-scope">container &middot; /app</span>
        </div>
        <div class="terminal-header-actions">
          <span id="terminal-status" class="terminal-status">disconnected</span>
          <button type="button" id="terminal-new" class="terminal-header-btn" title="Close this shell and start a new one">New shell</button>
          <button type="button" id="terminal-close" class="modal-close" title="Close Terminal" aria-label="Close Terminal">&times;</button>
        </div>
      </header>
      <div id="terminal-screen" class="terminal-screen"></div>
    </div>
  `;
  document.body.appendChild(_panel);

  _terminal = new Terminal({
    cursorBlink: true,
    fontFamily: '"JetBrains Mono", "SFMono-Regular", Consolas, monospace',
    fontSize: 13,
    scrollback: 5000,
    theme: _terminalTheme(),
  });
  _fitAddon = new FitAddon();
  _terminal.loadAddon(_fitAddon);
  _terminal.open(_panel.querySelector('#terminal-screen'));
  _terminal.onData(data => _send({ type: 'input', data }));

  _panel.querySelector('#terminal-close')?.addEventListener('click', close);
  _panel.querySelector('#terminal-new')?.addEventListener('click', _connect);
  const content = _panel.querySelector('.modal-content');
  const header = _panel.querySelector('.modal-header');
  makeWindowDraggable(_panel, {
    content,
    header,
    minWidth: 360,
    minHeight: 240,
    resizeStorageKey: 'winsize-terminal-modal',
  });
  Modals.register('terminal-modal', {
    railBtnId: 'rail-terminal',
    sidebarBtnId: 'tool-terminal-btn',
    label: 'Terminal',
    icon: 'M3 4h18v16H3zM7 9l3 3-3 3M13 15h4',
    closeFn: _destroy,
    restoreFn: () => {
      _open = true;
      _setActive(true);
      requestAnimationFrame(_fit);
      _pollHttp();
      _terminal?.focus();
    },
  });
  Modals.injectMinimizeButton(_panel, 'terminal-modal');
  _panelObserver = new MutationObserver(() => {
    const minimized = _panel?.classList.contains('modal-minimized');
    const hidden = _panel?.classList.contains('hidden');
    _open = !minimized && !hidden;
    _setActive(_open);
  });
  _panelObserver.observe(_panel, { attributes: true, attributeFilter: ['class'] });
  _themeObserver = new MutationObserver(_applyTerminalTheme);
  _themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
  _themeObserver.observe(document.body, { attributes: true, attributeFilter: ['class', 'style'] });
  new ResizeObserver(() => requestAnimationFrame(_fit))
    .observe(_panel.querySelector('#terminal-screen'));
  return _panel;
}

export async function open() {
  try {
    const panel = await _mount();
    panel.classList.remove('hidden');
    panel.style.display = 'flex';
    _open = true;
    _setActive(true);
    if (!_httpSession) _connectHttp();
    requestAnimationFrame(_fit);
    _terminal?.focus();
  } catch (error) {
    console.error('Failed to load terminal renderer:', error);
    window.alert("Terminal renderer could not load. Check this browser's internet connection and try again.");
  }
}

export function close() {
  if (Modals.isRegistered('terminal-modal')) {
    Modals.close('terminal-modal');
    return;
  }
  _destroy();
}

function _destroy() {
  if (!_panel) return;
  _open = false;
  _setActive(false);
  _closeTransport(false);
  _panelObserver?.disconnect();
  _themeObserver?.disconnect();
  _panelObserver = null;
  _themeObserver = null;
  _panel.remove();
  _panel = null;
  _terminal = null;
  _fitAddon = null;
}

export function toggle() {
  if (Modals.toggle('terminal-modal')) {
    _open = true;
    return;
  }
  if (_open) {
    Modals.minimize('terminal-modal');
    _open = false;
    _setActive(false);
    return;
  }
  return open();
}

export function isOpen() {
  return _open;
}

export default { open, close, toggle, isOpen };

syncSessionIndicator();
window.addEventListener('focus', syncSessionIndicator);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) syncSessionIndicator();
});
