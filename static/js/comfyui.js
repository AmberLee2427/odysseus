let _panel = null;
let _iframe = null;
let _open = false;
let _comfyUrl = '';

function _setActive(active) {
  document.getElementById('tool-comfyui-btn')?.classList.toggle('active', active);
  document.getElementById('rail-comfyui')?.classList.toggle('active-section', active);
}

async function _resolveUrl() {
  if (_comfyUrl) return _comfyUrl;
  try {
    const response = await fetch('/api/comfyui/config', { credentials: 'same-origin' });
    if (response.ok) {
      const config = await response.json();
      if (config.url) _comfyUrl = config.url;
    }
  } catch (_) {}
  if (!_comfyUrl) {
    _comfyUrl = `${window.location.protocol}//${window.location.hostname}:8188`;
  }
  return _comfyUrl;
}

function _mount() {
  if (_panel) return _panel;
  _panel = document.createElement('section');
  _panel.id = 'comfyui-panel';
  _panel.className = 'comfyui-panel hidden';
  _panel.innerHTML = `
    <header class="comfyui-panel-header">
      <strong>ComfyUI</strong>
      <span id="comfyui-panel-url" class="comfyui-panel-url"></span>
      <button type="button" id="comfyui-reload" title="Reload ComfyUI">Reload</button>
      <button type="button" id="comfyui-new-tab" title="Open ComfyUI in a new tab">Open tab</button>
      <button type="button" id="comfyui-close" title="Close ComfyUI" aria-label="Close ComfyUI">&times;</button>
    </header>
    <div class="comfyui-frame-wrap">
      <iframe id="comfyui-frame" title="ComfyUI"></iframe>
    </div>
  `;
  document.body.appendChild(_panel);
  _iframe = _panel.querySelector('#comfyui-frame');
  _panel.querySelector('#comfyui-close')?.addEventListener('click', close);
  _panel.querySelector('#comfyui-reload')?.addEventListener('click', () => {
    if (_iframe?.src) _iframe.src = _iframe.src;
  });
  _panel.querySelector('#comfyui-new-tab')?.addEventListener('click', () => {
    const url = _comfyUrl || `${window.location.protocol}//${window.location.hostname}:8188`;
    window.open(url, '_blank', 'noopener,noreferrer');
  });
  return _panel;
}

export async function open() {
  const panel = _mount();
  const url = await _resolveUrl();
  panel.querySelector('#comfyui-panel-url').textContent = url;
  if (_iframe && !_iframe.src) _iframe.src = url;
  panel.classList.remove('hidden');
  _open = true;
  _setActive(true);
}

export function close() {
  if (!_panel) return;
  _panel.classList.add('hidden');
  _open = false;
  _setActive(false);
}

export function toggle() {
  return _open ? close() : open();
}

export function isOpen() {
  return _open;
}

export default { open, close, toggle, isOpen };
