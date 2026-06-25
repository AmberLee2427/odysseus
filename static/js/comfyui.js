let _panel = null;
let _open = false;
let _publicUrl = '';
let _selectedAppId = 'krea2-text';
const APP_BACKGROUND_STORAGE_KEY = 'odysseus.comfyui.appBackgrounds.v1';

const COMFY_APPS = [
  {
    id: 'krea2-text',
    name: 'Krea 2',
    subtitle: 'Fast local text-to-image',
    foundation: 'Krea 2',
    useCase: 'Photoreal, anime, style studies, fast prompt iteration.',
    workflow: 'image_krea2_turbo_t2i.json',
    status: 'Ready',
    statusTone: 'info',
    fields: ['prompt', 'aspect ratio', 'megapixels', 'seed', 'refine prompt', 'LoRA toggle'],
    example: '',
    note: 'Uses the working Krea 2 Turbo text-to-image workflow recovered from ComfyUI history.',
  },
  {
    id: 'ideogram4-layout',
    name: 'Ideogram 4',
    subtitle: 'Text, posters, layout',
    foundation: 'Ideogram 4',
    useCase: 'Typography-heavy images and composed layouts.',
    workflow: 'ideogram4.json',
    status: 'Box editor later',
    statusTone: 'info',
    fields: ['prompt', 'style', 'background', 'aspect ratio', 'layout boxes'],
    example: 'https://storage.googleapis.com/ideogram-static/website/images/a1012359f02f1a7a.webp',
    note: 'Useful, but more annoying because layout boxes need a drawing UI.',
  },
  {
    id: 'upscale-utility',
    name: 'Image Upscaler',
    subtitle: 'Utility app',
    foundation: 'Workflow-backed utility',
    useCase: 'Upscale or enhance an image already in the Gallery.',
    workflow: 'upscale_4x.json',
    status: 'Needs mapping',
    statusTone: 'muted',
    fields: ['image', 'scale', 'strength'],
    example: '',
    note: 'Good utility card once image-input wiring is in place.',
  },
];

function _escape(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
}

function _setText(selector, text) {
  const el = _panel?.querySelector(selector);
  if (el) el.textContent = text;
}

async function _fetchJson(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) {}
  if (!response.ok) {
    throw new Error((data && (data.detail || data.error || data.message)) || text || response.statusText);
  }
  return data;
}

async function _loadConfig() {
  try {
    const config = await _fetchJson('/api/comfyui/backend/config');
    _publicUrl = config.public_url || '';
  } catch (_) {
    _publicUrl = '';
  }
}

function _queueLabel(status) {
  if (!status?.ok) return 'offline';
  return `${status.queue_running || 0} running · ${status.queue_pending || 0} pending`;
}

async function refreshStatus() {
  if (!_panel) return;
  _setText('#comfyui-status-value', 'checking…');
  _setText('#comfyui-queue-value', 'checking…');
  try {
    const status = await _fetchJson('/api/comfyui/status');
    _setText('#comfyui-status-value', status.ok ? 'online' : 'offline');
    _setText('#comfyui-queue-value', _queueLabel(status));
  } catch (error) {
    _setText('#comfyui-status-value', 'offline');
    _setText('#comfyui-queue-value', 'unknown');
  }
}

function _imageCard(image) {
  const prompt = image.prompt || image.filename || 'ComfyUI output';
  const model = image.model || 'ComfyUI';
  return `
    <div class="gallery-card comfyui-image-card">
      <img src="${_escape(image.url)}" alt="${_escape(prompt)}" loading="lazy">
      <div class="gallery-card-info">
        <div class="gallery-card-prompt">${_escape(prompt)}</div>
        <div class="gallery-card-meta"><span class="gallery-card-model">${_escape(model)}</span></div>
      </div>
    </div>
  `;
}

async function refreshImages() {
  if (!_panel) return;
  const grid = _panel.querySelector('#comfyui-images');
  if (!grid) return;
  grid.innerHTML = '<div class="comfyui-empty">Loading…</div>';
  try {
    const gallery = await _fetchJson('/api/gallery/library?tag=comfyui&sort=recent&limit=24');
    const galleryItems = Array.isArray(gallery?.items) ? gallery.items : [];
    if (galleryItems.length) {
      grid.innerHTML = galleryItems.map(_imageCard).join('');
      _setText('#comfyui-output-count', `${galleryItems.length} from Gallery`);
      return;
    }

    const live = await _fetchJson('/api/comfyui/images?max_items=75&limit=24');
    const liveItems = Array.isArray(live?.images) ? live.images : [];
    if (liveItems.length) {
      grid.innerHTML = liveItems.map(_imageCard).join('');
      _setText('#comfyui-output-count', `${liveItems.length} live`);
      return;
    }

    grid.innerHTML = '<div class="comfyui-empty">No ComfyUI images in Gallery yet. Try Sync.</div>';
    _setText('#comfyui-output-count', '0');
  } catch (error) {
    grid.innerHTML = `<div class="comfyui-empty">Could not load images: ${_escape(error.message)}</div>`;
  }
}

function _appById(id) {
  return COMFY_APPS.find((app) => app.id === id) || COMFY_APPS[0];
}

function _appStatus(app) {
  return `<span class="comfyui-app-status comfyui-app-status-${_escape(app.statusTone || 'muted')}">${_escape(app.status)}</span>`;
}

function _storedAppBackgrounds() {
  try {
    const raw = localStorage.getItem(APP_BACKGROUND_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_) {
    return {};
  }
}

function _appBackground(app) {
  return _storedAppBackgrounds()[app.id] || app.example || '';
}

function _appCard(app) {
  const selected = app.id === _selectedAppId ? ' selected' : '';
  const background = _appBackground(app);
  return `
    <button type="button" class="gallery-card comfyui-app-card${selected}" data-app-id="${_escape(app.id)}">
      <div class="comfyui-app-thumb ${background ? '' : 'comfyui-app-thumb-empty'}">
        ${background ? `<img src="${_escape(background)}" alt="" loading="lazy">` : '<span>✦</span>'}
      </div>
      <div class="gallery-card-info">
        <div class="gallery-card-prompt">${_escape(app.name)}</div>
        <div class="gallery-card-meta"><span>${_escape(app.subtitle)}</span></div>
        <div class="comfyui-app-card-footer">
          ${_appStatus(app)}
        </div>
      </div>
    </button>
  `;
}

export function getApps() {
  return COMFY_APPS.map((app) => ({ ...app }));
}

export function getAppBackground(appId) {
  const app = _appById(appId);
  return _appBackground(app);
}

export function setAppBackground(appId, url) {
  const backgrounds = _storedAppBackgrounds();
  const clean = String(url || '').trim();
  if (clean) backgrounds[appId] = clean;
  else delete backgrounds[appId];
  try {
    localStorage.setItem(APP_BACKGROUND_STORAGE_KEY, JSON.stringify(backgrounds));
  } catch (_) {}
  renderApps();
}

function _randomSeed() {
  return Math.floor(Math.random() * 9007199254740991);
}

function _kreaFormHtml() {
  return `
    <form id="comfyui-krea-form" class="comfyui-app-form">
      <label class="comfyui-field comfyui-field-wide">
        <span>Prompt</span>
        <textarea id="comfyui-krea-prompt" rows="4">A cinematic photograph of a small observatory on a windswept hill under a luminous spiral galaxy, warm window light, crisp night air, realistic detail</textarea>
      </label>
      <div class="comfyui-form-grid">
        <label class="comfyui-field">
          <span>Aspect ratio</span>
          <select id="comfyui-krea-aspect" class="comfyui-select">
            <option>1:1 (Square)</option>
            <option>2:3 (Portrait Photo)</option>
            <option>3:2 (Photo)</option>
            <option>3:4 (Portrait Standard)</option>
            <option>4:3 (Standard)</option>
            <option>9:16 (Portrait Widescreen)</option>
            <option>16:9 (Widescreen)</option>
            <option>21:9 (Ultrawide)</option>
          </select>
        </label>
        <label class="comfyui-field">
          <span>Megapixels</span>
          <input id="comfyui-krea-megapixels" type="number" min="0.1" max="16" step="0.1" value="1">
        </label>
        <label class="comfyui-field">
          <span>Seed</span>
          <input id="comfyui-krea-seed" type="number" min="0" step="1" value="${_randomSeed()}">
        </label>
        <label class="comfyui-field">
          <span>Steps</span>
          <input id="comfyui-krea-steps" type="number" min="1" max="40" step="1" value="8">
        </label>
      </div>
      <div class="comfyui-check-row">
        <label><input id="comfyui-krea-refine" type="checkbox" checked> Refine prompt</label>
        <label><input id="comfyui-krea-lora" type="checkbox"> Enable LoRA</label>
      </div>
      <div class="comfyui-actions">
        <button type="submit" class="gallery-select-btn" id="comfyui-krea-submit">Generate</button>
        <button type="button" class="gallery-select-btn" id="comfyui-krea-random-seed">Random seed</button>
        <span id="comfyui-submit-status" class="comfyui-muted"></span>
      </div>
    </form>
  `;
}

function _readKreaForm() {
  const prompt = _panel?.querySelector('#comfyui-krea-prompt')?.value?.trim();
  if (!prompt) throw new Error('Prompt is required.');
  const seed = Number.parseInt(_panel?.querySelector('#comfyui-krea-seed')?.value || '', 10);
  const steps = Number.parseInt(_panel?.querySelector('#comfyui-krea-steps')?.value || '8', 10);
  const megapixels = Number.parseFloat(_panel?.querySelector('#comfyui-krea-megapixels')?.value || '1');
  return {
    prompt,
    aspectRatio: _panel?.querySelector('#comfyui-krea-aspect')?.value || '1:1 (Square)',
    megapixels: Number.isFinite(megapixels) ? megapixels : 1,
    seed: Number.isFinite(seed) ? seed : _randomSeed(),
    steps: Number.isFinite(steps) ? steps : 8,
    refine: Boolean(_panel?.querySelector('#comfyui-krea-refine')?.checked),
    lora: Boolean(_panel?.querySelector('#comfyui-krea-lora')?.checked),
  };
}

function _applyKreaForm(workflow, values) {
  const next = JSON.parse(JSON.stringify(workflow));
  next['30:19'].inputs.value = values.prompt;
  next['49'].inputs.aspect_ratio = values.aspectRatio;
  next['49'].inputs.megapixels = values.megapixels;
  next['30:3'].inputs.seed = values.seed;
  next['30:3'].inputs.steps = values.steps;
  next['30:24'].inputs.value = values.refine;
  next['30:23'].inputs.value = values.lora;
  next['29'].inputs.filename_prefix = 'Odysseus_Krea2';
  return next;
}

async function submitKrea(event) {
  event?.preventDefault();
  _setText('#comfyui-submit-status', 'Preparing workflow…');
  try {
    const values = _readKreaForm();
    const data = await _fetchJson('/api/comfyui/workflows/image_krea2_turbo_t2i.json');
    const payload = _applyKreaForm(data.workflow, values);
    _setText('#comfyui-submit-status', 'Submitting…');
    const result = await _fetchJson('/api/comfyui/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    _setText('#comfyui-submit-status', `Queued ${result.prompt_id || ''}`.trim());
    await refreshStatus();
  } catch (error) {
    _setText('#comfyui-submit-status', `Submit failed: ${error.message}`);
  }
}

function renderApps() {
  if (!_panel) return;
  const grid = _panel.querySelector('#comfyui-apps');
  if (grid) grid.innerHTML = COMFY_APPS.map(_appCard).join('');
  renderSelectedApp();
}

function renderSelectedApp() {
  if (!_panel) return;
  const app = _appById(_selectedAppId);
  const detail = _panel.querySelector('#comfyui-app-detail');
  if (!detail) return;
  const isKrea = app.id === 'krea2-text';
  detail.innerHTML = `
    <div class="comfyui-section-title">
      <h2>${_escape(app.name)}</h2>
      ${_appStatus(app)}
    </div>
    ${isKrea ? _kreaFormHtml() : `
      <p class="comfyui-app-desc">${_escape(app.useCase)}</p>
      <div class="comfyui-actions">
        <button type="button" class="gallery-select-btn" id="comfyui-open-app-settings">Configure in Gallery Settings</button>
        <button type="button" class="gallery-select-btn" id="comfyui-open-full-from-app">Open full ComfyUI</button>
        <span id="comfyui-submit-status" class="comfyui-muted">Configure this app before generating.</span>
      </div>
    `}
  `;
  _panel.querySelector('#comfyui-krea-form')?.addEventListener('submit', submitKrea);
  _panel.querySelector('#comfyui-krea-random-seed')?.addEventListener('click', () => {
    const seed = _panel.querySelector('#comfyui-krea-seed');
    if (seed) seed.value = String(_randomSeed());
  });
  _panel.querySelector('#comfyui-open-app-settings')?.addEventListener('click', () => {
    document.querySelector('#gallery-modal .gallery-tab[data-tab="settings"]')?.click();
    document.getElementById('gallery-comfy-apps-settings')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  _panel.querySelector('#comfyui-open-full-from-app')?.addEventListener('click', () => {
    const url = _publicUrl || `${window.location.protocol}//${window.location.hostname}:8188`;
    window.open(url, '_blank', 'noopener,noreferrer');
  });
}

async function syncGallery() {
  _setText('#comfyui-sync-status', 'Syncing…');
  try {
    const result = await _fetchJson('/api/gallery/sync-comfyui', { method: 'POST' });
    _setText('#comfyui-sync-status', `${result.imported || 0} imported · ${result.duplicates || 0} duplicates`);
    await refreshImages();
  } catch (error) {
    _setText('#comfyui-sync-status', `Sync failed: ${error.message}`);
  }
}

export function mountInto(container) {
  if (!container) return null;
  if (_panel && _panel.parentElement === container) return _panel;
  if (_panel && _panel.parentElement) _panel.remove();
  _panel = document.createElement('section');
  _panel.id = 'comfyui-panel';
  _panel.className = 'comfyui-panel';
  _panel.innerHTML = `
    <div class="gallery-toolbar comfyui-toolbar">
      <div class="comfyui-status-pill"><span>Status</span><strong id="comfyui-status-value">checking…</strong></div>
      <div class="comfyui-status-pill"><span>Queue</span><strong id="comfyui-queue-value">checking…</strong></div>
      <span class="gallery-toolbar-break" aria-hidden="true"></span>
      <button type="button" class="gallery-select-btn gallery-toolbar-action" id="comfyui-refresh">Refresh</button>
      <button type="button" class="gallery-select-btn gallery-toolbar-action" id="comfyui-gallery-sync">Sync</button>
      <button type="button" class="gallery-select-btn gallery-toolbar-action" id="comfyui-new-tab">Open full</button>
      <span id="comfyui-sync-status" class="comfyui-muted"></span>
    </div>
    <div class="comfyui-native-wrap">
      <section class="admin-card comfyui-submit-section">
        <div class="comfyui-section-title">
          <h2>Apps</h2>
          <span>Workflow-backed image tools</span>
        </div>
        <div id="comfyui-apps" class="comfyui-app-grid"></div>
        <div id="comfyui-app-detail" class="comfyui-app-detail"></div>
      </section>
      <section class="admin-card comfyui-grid-section">
        <div class="comfyui-section-title">
          <h2>Recent ComfyUI images</h2>
          <span id="comfyui-output-count"></span>
        </div>
        <div id="comfyui-images" class="gallery-grid comfyui-images"></div>
      </section>
    </div>
  `;
  container.replaceChildren(_panel);
  _panel.querySelector('#comfyui-refresh')?.addEventListener('click', () => {
    refreshStatus();
    refreshImages();
  });
  _panel.querySelector('#comfyui-gallery-sync')?.addEventListener('click', syncGallery);
  _panel.addEventListener('click', (event) => {
    const card = event.target.closest?.('.comfyui-app-card');
    if (!card) return;
    _selectedAppId = card.dataset.appId || _selectedAppId;
    renderApps();
  });
  _panel.querySelector('#comfyui-new-tab')?.addEventListener('click', () => {
    const url = _publicUrl || `${window.location.protocol}//${window.location.hostname}:8188`;
    window.open(url, '_blank', 'noopener,noreferrer');
  });
  return _panel;
}

export async function refresh() {
  if (!_panel) return;
  _open = true;
  await _loadConfig();
  renderApps();
  await Promise.all([refreshStatus(), refreshImages()]);
}

export async function open() {
  const gallery = await import('./gallery.js');
  gallery.openGallery({ tab: 'comfyui' });
}

export function close() {
  _open = false;
}

export function toggle() {
  return open();
}

export function isOpen() {
  return _open;
}

export default {
  mountInto,
  refresh,
  open,
  close,
  toggle,
  isOpen,
  getApps,
  getAppBackground,
  setAppBackground,
};
