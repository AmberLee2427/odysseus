// Project registry UI helpers. This stays frontend-only: the backend registry
// owns persistence and project identifiers.

import uiModule from './ui.js';

const API_BASE = window.location.origin;

let projects = [];
let selectedProjectId = null;
let projectsInitialized = false;

function _projectId(project) {
  return project && String(project.project_id || project.id || '');
}

function _normalizeProjectList(payload) {
  const raw = Array.isArray(payload) ? payload
    : Array.isArray(payload?.projects) ? payload.projects
    : Array.isArray(payload?.items) ? payload.items
    : [];
  const seen = new Set();
  const out = [];
  for (const project of raw) {
    const id = _projectId(project);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ ...project, project_id: id });
  }
  return out;
}

function _safeText(value, fallback = '') {
  const text = value == null ? '' : String(value);
  return text.trim() || fallback;
}

async function _jsonOrThrow(res) {
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const message = data?.detail || data?.error || `HTTP ${res.status}`;
    throw new Error(message);
  }
  return data;
}

export async function listProjects({ silent = true } = {}) {
  try {
    const res = await fetch(`${API_BASE}/api/projects`, { credentials: 'same-origin' });
    projects = _normalizeProjectList(await _jsonOrThrow(res));
    renderProjectSidebar();
    document.dispatchEvent(new CustomEvent('odysseus:projects-loaded', { detail: { projects } }));
    return projects;
  } catch (error) {
    projects = [];
    renderProjectSidebar({ error: silent ? '' : error.message });
    if (!silent) uiModule.showError(`Failed to load projects: ${error.message}`);
    return projects;
  }
}

export async function getProject(projectId) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}`, { credentials: 'same-origin' });
  const data = await _jsonOrThrow(res);
  const project = data?.project || data;
  return project ? { ...project, project_id: _projectId(project) } : null;
}

export async function createProject(payload) {
  const res = await fetch(`${API_BASE}/api/projects`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await _jsonOrThrow(res);
  const project = data?.project || data;
  await listProjects();
  return project ? { ...project, project_id: _projectId(project) } : null;
}

export async function updateProject(projectId, payload) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await _jsonOrThrow(res);
  const project = data?.project || data;
  await listProjects();
  return project ? { ...project, project_id: _projectId(project) } : null;
}

export async function listProjectWorktrees(projectId) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}/worktrees`, { credentials: 'same-origin' });
  return _jsonOrThrow(res);
}

export async function createProjectWorktree(projectId, payload) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}/worktrees`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return _jsonOrThrow(res);
}

export async function removeProjectWorktree(projectId, path) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}/worktrees`, {
    method: 'DELETE',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  return _jsonOrThrow(res);
}

export function getProjectsSnapshot() {
  return projects.slice();
}

export function getSelectedProjectId() {
  return selectedProjectId;
}

export function getProjectForSession(session) {
  const sidProject = session?.project_id || session?.projectId;
  if (!sidProject) return null;
  return projects.find(project => _projectId(project) === String(sidProject)) || null;
}

function _renderEmptyProjectState(container, message) {
  container.innerHTML = '';
  const empty = document.createElement('div');
  empty.className = 'project-sidebar-empty';
  empty.textContent = message;
  container.appendChild(empty);
}

export function renderProjectSidebar({ error = '' } = {}) {
  const section = document.getElementById('projects-section');
  const list = document.getElementById('project-list');
  if (!section || !list) return;

  section.classList.remove('hidden');
  if (error) {
    _renderEmptyProjectState(list, error);
    return;
  }
  if (!projects.length) {
    _renderEmptyProjectState(list, 'No projects yet');
    return;
  }

  const frag = document.createDocumentFragment();
  projects.forEach(project => {
    const id = _projectId(project);
    // Match Chats exactly: a sidebar list row is a div, not a button. Global
    // button styling is intentionally colorful in some themes, which made
    // project rows look like top-level controls instead of nested entries.
    const row = document.createElement('div');
    row.setAttribute('role', 'button');
    row.setAttribute('tabindex', '-1');
    row.className = 'list-item project-list-item';
    row.dataset.projectId = id;
    if (selectedProjectId === id) row.classList.add('active');
    row.title = _safeText(project.root_path || project.rootPath || project.name, 'Open project');
    row.innerHTML = '<span class="session-icon"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg></span><span class="grow"></span>';
    row.querySelector('.grow').textContent = _safeText(project.name, 'Untitled project');
    const open = async () => {
      await openProjectDashboard(id);
      const sidebar = document.getElementById('sidebar');
      const backdrop = document.getElementById('sidebar-backdrop');
      if (sidebar) {
        sidebar.classList.add('hidden');
        if (backdrop) backdrop.classList.remove('visible');
        if (window.syncRailSide) window.syncRailSide();
      }
    };
    row.addEventListener('click', open);
    row.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      open();
    });
    frag.appendChild(row);
  });

  list.innerHTML = '';
  list.appendChild(frag);
}

function _projectSessions(project, sessions) {
  const id = _projectId(project);
  return (sessions || []).filter(session => String(session?.project_id || session?.projectId || '') === id);
}

const BOARD_DEFAULT = {
  version: 1,
  cards: [],
};

const CARD_COLOURS = ['paper', 'peach', 'lilac', 'mint', 'sky', 'sun'];
const DEFAULT_CARD_COLOURS = { chat: 'sky', note: 'sun', task: 'mint', document: 'lilac' };

function _defaultCardColour(type) {
  try {
    const saved = JSON.parse(localStorage.getItem('odysseus-project-board-colours') || '{}');
    return (CARD_COLOURS.includes(saved[type]) || /^#[0-9a-f]{6}$/i.test(saved[type] || '')) ? saved[type] : (DEFAULT_CARD_COLOURS[type] || 'paper');
  } catch (_) { return DEFAULT_CARD_COLOURS[type] || 'paper'; }
}

function _boardFor(project) {
  const mirror = project?.mirror && typeof project.mirror === 'object' ? project.mirror : {};
  const board = mirror.board && typeof mirror.board === 'object' ? mirror.board : {};
  return { ...BOARD_DEFAULT, ...board, cards: Array.isArray(board.cards) ? board.cards : [] };
}

function _cardKey(type, id) { return `${type}:${id}`; }

function _escapeText(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
}

function _renderAnnotationMarkdown(value) {
  let html = _escapeText(value || '');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/\n/g, '<br>');
  return html;
}

function _artifactFor(card, artifacts) {
  return artifacts.find(item => item.key === card.artifact_key) || null;
}

async function _loadBoardArtifacts(sessions) {
  const chats = (sessions || []).map(session => ({
    key: _cardKey('chat', session.id), type: 'chat', id: session.id,
    title: _safeText(session.name, 'Untitled chat'), preview: 'Conversation', project_id: session.project_id || null, data: session,
  }));
  const load = async (url, field, type, map) => {
    try {
      const res = await fetch(`${API_BASE}${url}`, { credentials: 'same-origin' });
      const data = await _jsonOrThrow(res);
      return (Array.isArray(data?.[field]) ? data[field] : []).map(item => ({
        key: _cardKey(type, item.id), type, id: item.id, project_id: item.project_id || null, ...map(item), data: item,
      }));
    } catch (_) { return []; }
  };
  const [notes, tasks, documents] = await Promise.all([
    load('/api/notes', 'notes', 'note', note => ({
      title: _safeText(note.title, 'Untitled note'),
      preview: _safeText(note.content || note.items, 'Note'),
    })),
    load('/api/tasks', 'tasks', 'task', task => ({
      title: _safeText(task.name, 'Untitled task'),
      preview: _safeText(task.status, 'Task'),
    })),
    load('/api/documents/library?limit=50', 'documents', 'document', doc => ({
      title: _safeText(doc.title, 'Untitled document'),
      preview: _safeText(doc.preview, doc.language || 'Document'),
    })),
  ]);
  return [...chats, ...notes, ...tasks, ...documents];
}

function _cardIcon(type) {
  return ({ chat: '◌', note: '✦', task: '✓', document: '▤' })[type] || '•';
}

function _createBoardCard(card, artifact, board, persist, editAnnotation) {
  const node = document.createElement('article');
  node.className = `project-board-card project-board-card--${card.colour || 'paper'}`;
  if (/^#[0-9a-f]{6}$/i.test(card.colour || '')) node.style.setProperty('--card-bg', `color-mix(in srgb, ${card.colour} 38%, var(--panel))`);
  node.dataset.cardId = card.id;
  node.style.setProperty('--board-x', `${card.x ?? 90}px`);
  node.style.setProperty('--board-y', `${card.y ?? 80}px`);
  node.style.setProperty('--board-w', `${card.w ?? 230}px`);
  node.style.setProperty('--board-h', `${card.h ?? 160}px`);
  node.style.setProperty('--board-rotation', `${card.rotation ?? 0}deg`);
  node.style.zIndex = String(card.z || 1);
  const annotation = card.type === 'annotation';
  if (annotation) {
    node.classList.add('project-board-annotation');
    node.classList.toggle('annotation-transparent', card.transparent !== false);
    node.classList.toggle('annotation-shadow', !!card.shadow);
    node.style.setProperty('--annotation-colour', card.background_colour || '#f9d85d');
    node.style.setProperty('--annotation-text-colour', card.text_colour || 'var(--fg)');
  }
  const title = annotation ? '' : (artifact?.title || card.title || 'Missing artifact');
  const preview = annotation ? _safeText(card.text, 'Double-click to write a note.') : (artifact?.preview || 'This source artifact is no longer available.');
  node.innerHTML = `
    <div class="project-board-card-bar" title="Drag card">
      <span class="project-board-type">${annotation ? '' : `${_cardIcon(card.type)} ${_escapeText(card.type || 'note')}`}</span>
      <button type="button" class="project-board-card-menu" aria-label="Card menu">•••</button>
    </div>
    <div class="project-board-card-body">
      ${annotation ? `<div class="project-annotation-text">${card.markdown ? _renderAnnotationMarkdown(card.text) : _escapeText(preview)}</div>` : `<h3>${_escapeText(title)}</h3><p>${_escapeText(preview)}</p>`}
    </div>
    <div class="project-board-card-options hidden" aria-label="Card options">
      <span>Colour</span><div class="project-board-colours"></div>
      <button type="button" class="project-board-remove" title="Remove from board" aria-label="Remove from board"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="m19 6-1 14H6L5 6m3 0V4h8v2m-6 4v6m4-6v6"/></svg> Remove from board</button>
    </div>
    ${annotation ? '<button type="button" class="project-board-trash" aria-label="Remove from board" title="Remove from board"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="m19 6-1 14H6L5 6m3 0V4h8v2m-6 4v6m4-6v6"/></svg></button>' : ''}
    <span class="project-board-rotate" title="Rotate"></span><span class="project-board-resize" title="Resize"></span>`;
  const bringForward = () => {
    card.z = Math.max(0, ...board.cards.map(other => Number(other.z) || 0)) + 1;
    node.style.zIndex = String(card.z);
  };
  node.addEventListener('pointerdown', bringForward);
  const options = node.querySelector('.project-board-card-options');
  const closeOptions = () => options.classList.add('hidden');
  const colourPicker = node.querySelector('.project-board-colours');
  CARD_COLOURS.forEach(colour => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = `project-board-colour project-board-colour--${colour}`;
    button.title = colour; button.setAttribute('aria-label', `Use ${colour}`);
    button.addEventListener('pointerdown', event => event.stopPropagation());
    button.addEventListener('click', event => {
      event.stopPropagation();
      card.colour = colour;
      node.className = `project-board-card project-board-card--${colour}`;
      closeOptions(); persist();
    });
    colourPicker.appendChild(button);
  });
  node.querySelector('.project-board-card-menu').addEventListener('pointerdown', event => event.stopPropagation());
  node.querySelector('.project-board-card-menu').addEventListener('click', event => {
    event.stopPropagation(); options.classList.toggle('hidden');
  });
  const remove = event => {
    event.stopPropagation();
      board.cards = board.cards.filter(other => other.id !== card.id);
      node.remove(); persist(); return;
  };
  node.querySelector('.project-board-remove').addEventListener('pointerdown', event => event.stopPropagation());
  node.querySelector('.project-board-remove').addEventListener('click', remove);
  node.querySelector('.project-board-trash')?.addEventListener('pointerdown', event => event.stopPropagation());
  node.querySelector('.project-board-trash')?.addEventListener('click', remove);
  const beginGesture = (handle, mode) => {
    handle.addEventListener('pointerdown', event => {
      event.preventDefault(); event.stopPropagation(); bringForward();
      const startX = event.clientX, startY = event.clientY;
      const start = { x: card.x ?? 90, y: card.y ?? 80, w: card.w ?? 230, h: card.h ?? 160, rotation: card.rotation ?? 0 };
      handle.setPointerCapture(event.pointerId);
      const move = moveEvent => {
        const dx = moveEvent.clientX - startX, dy = moveEvent.clientY - startY;
        if (mode === 'drag') { card.x = Math.max(0, start.x + dx); card.y = Math.max(0, start.y + dy); }
        if (mode === 'resize') { card.w = Math.max(160, start.w + dx); card.h = Math.max(110, start.h + dy); }
        if (mode === 'rotate') { card.rotation = Math.round((start.rotation + dx / 2) / 5) * 5; }
        node.style.setProperty('--board-x', `${card.x}px`); node.style.setProperty('--board-y', `${card.y}px`);
        node.style.setProperty('--board-w', `${card.w}px`); node.style.setProperty('--board-h', `${card.h}px`);
        node.style.setProperty('--board-rotation', `${card.rotation}deg`);
      };
      const end = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', end); try { handle.releasePointerCapture(event.pointerId); } catch (_) {} persist(); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', end, { once: true });
      window.addEventListener('pointercancel', end, { once: true });
    });
  };
  beginGesture(node.querySelector('.project-board-card-bar'), 'drag');
  beginGesture(node.querySelector('.project-board-resize'), 'resize');
  beginGesture(node.querySelector('.project-board-rotate'), 'rotate');
  node.addEventListener('dblclick', () => {
    if (annotation) { editAnnotation?.(card); return; }
    const artifactId = artifact?.id;
    if (card.type === 'chat' && artifactId) window.sessionModule?.selectSession?.(artifactId);
    if (card.type === 'note' && artifactId) window.notesModule?.openNote?.(artifactId);
    if (card.type === 'task' && artifactId) window.tasksModule?.openTasks?.(artifactId);
    if (card.type === 'document' && artifactId) window.documentModule?.loadDocument?.(artifactId);
  });
  return node;
}

function _mountProjectBoard(shell, project, sessions) {
  const host = shell.querySelector('.project-board');
  const world = document.createElement('div');
  world.className = 'project-board-world';
  const empty = host.querySelector('.project-board-empty');
  if (empty) world.appendChild(empty);
  host.replaceChildren(world);
  const board = _boardFor(project);
  let zoom = Math.min(1.5, Math.max(0.2, Number(board.zoom) || 1));
  let artifacts = [];
  let saveTimer = null;
  const persist = () => {
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(async () => {
      try {
        const updated = await updateProject(_projectId(project), { mirror: { ...(project.mirror || {}), board } });
        project.mirror = updated?.mirror || { ...(project.mirror || {}), board };
      } catch (error) { uiModule.showError(`Could not save board: ${error.message}`); }
    }, 450);
  };
  const render = () => {
    world.querySelectorAll('.project-board-card').forEach(node => node.remove());
    const bounds = board.cards.reduce((size, card) => ({
      width: Math.max(size.width, (card.x || 0) + (card.w || 230) + 420),
      height: Math.max(size.height, (card.y || 0) + (card.h || 160) + 360),
    }), { width: 2200, height: 1400 });
    world.style.width = `${bounds.width}px`;
    world.style.height = `${bounds.height}px`;
    world.style.zoom = String(zoom);
    board.cards.forEach(card => world.appendChild(_createBoardCard(card, _artifactFor(card, artifacts), board, persist, editAnnotation)));
    world.querySelector('.project-board-empty')?.classList.toggle('hidden', board.cards.length > 0);
  };
  const editAnnotation = card => {
    const overlay = document.createElement('div');
    overlay.className = 'project-annotation-editor';
    const backlinkOptions = ['<option value="">No backlink</option>', ...artifacts.filter(a => a.type !== 'annotation').map(a => `<option value="${_escapeText(a.key)}">${_escapeText(a.type)} — ${_escapeText(a.title)}</option>`)].join('');
    overlay.innerHTML = `<form class="project-annotation-form"><h3>Edit annotation</h3><label>Text<textarea name="text" rows="5" maxlength="4000"></textarea></label><label>Tags <input name="tags" placeholder="research, question"></label><label>Linked artifact<select name="backlink">${backlinkOptions}</select></label><div class="project-annotation-colours"><label>Background<input type="color" name="background_colour"></label><label>Text colour<input type="color" name="text_colour"></label></div><label class="project-annotation-context"><input type="checkbox" name="transparent"> Transparent background</label><label class="project-annotation-context"><input type="checkbox" name="shadow"> Drop shadow</label><label class="project-annotation-context"><input type="checkbox" name="markdown"> Render Markdown</label><label class="project-annotation-context"><input type="checkbox" name="include_context"> Include in agent context</label><div class="project-form-actions"><button type="button" class="project-secondary-btn" data-cancel>Cancel</button><button class="project-primary-btn">Save annotation</button></div></form>`;
    const form = overlay.querySelector('form');
    form.elements.text.value = card.text || '';
    form.elements.tags.value = (card.tags || []).join(', ');
    form.elements.backlink.value = card.backlink || '';
    form.elements.include_context.checked = !!card.include_context;
    form.elements.background_colour.value = /^#[0-9a-f]{6}$/i.test(card.background_colour || '') ? card.background_colour : '#f9d85d';
    form.elements.text_colour.value = /^#[0-9a-f]{6}$/i.test(card.text_colour || '') ? card.text_colour : '#f5f0ff';
    form.elements.transparent.checked = card.transparent !== false;
    form.elements.shadow.checked = !!card.shadow;
    form.elements.markdown.checked = !!card.markdown;
    form.querySelector('[data-cancel]').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', event => { if (event.target === overlay) overlay.remove(); });
    form.addEventListener('submit', event => {
      event.preventDefault();
      card.title = ''; card.text = form.elements.text.value.trim();
      card.tags = form.elements.tags.value.split(',').map(v => v.trim().replace(/^#/, '')).filter(Boolean);
      card.backlink = form.elements.backlink.value || null; card.include_context = form.elements.include_context.checked;
      card.background_colour = form.elements.background_colour.value; card.text_colour = form.elements.text_colour.value;
      card.transparent = form.elements.transparent.checked; card.shadow = form.elements.shadow.checked; card.markdown = form.elements.markdown.checked;
      overlay.remove(); render(); persist();
    });
    document.body.appendChild(overlay);
  };
  const zoomReadout = shell.querySelector('[data-board-zoom-reset]');
  const applyZoom = (next) => {
    zoom = Math.min(1.5, Math.max(0.2, Math.round(next * 10) / 10));
    board.zoom = zoom;
    zoomReadout.textContent = `${Math.round(zoom * 100)}%`;
    render(); persist();
  };
  shell.querySelector('[data-board-zoom-out]').addEventListener('click', () => applyZoom(zoom - 0.1));
  shell.querySelector('[data-board-zoom-in]').addEventListener('click', () => applyZoom(zoom + 0.1));
  zoomReadout.addEventListener('click', () => applyZoom(1));
  const addArtifact = async artifact => {
    if (board.cards.some(card => card.artifact_key === artifact.key)) { uiModule.showToast('That is already on this board.'); return; }
    try {
      const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId(project))}/artifacts/${encodeURIComponent(artifact.type)}/${encodeURIComponent(artifact.id)}`, {
        method: 'POST', credentials: 'same-origin',
      });
      await _jsonOrThrow(res);
      artifact.project_id = _projectId(project);
    } catch (error) {
      uiModule.showError(`Could not assign artifact to this project: ${error.message}`);
      return;
    }
    const index = board.cards.length;
    const cardId = window.crypto?.randomUUID?.() || `card-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    board.cards.push({ id: cardId, artifact_key: artifact.key, type: artifact.type, x: 70 + (index % 4) * 55, y: 70 + (index % 3) * 45, w: 230, h: 160, rotation: 0, colour: _defaultCardColour(artifact.type), z: index + 1 });
    render(); persist();
  };
  const addAnnotation = () => {
    const index = board.cards.length;
    const id = window.crypto?.randomUUID?.() || `annotation-${Date.now()}`;
    const card = { id, type: 'annotation', title: '', text: '', tags: [], backlink: null, include_context: false, transparent: true, shadow: false, markdown: true, text_colour: '#f5f0ff', background_colour: '#f9d85d', x: 100 + (index % 4) * 50, y: 100 + (index % 3) * 42, w: 260, h: 180, rotation: 0, z: index + 1 };
    board.cards.push(card); render(); editAnnotation(card);
  };
  shell.querySelector('[data-board-add]').addEventListener('click', () => {
    const tray = shell.querySelector('.project-board-tray');
    tray.classList.toggle('hidden');
    if (!tray.classList.contains('hidden')) {
      const list = tray.querySelector('.project-board-picker-list');
      list.innerHTML = '<button type="button" class="project-board-new-annotation">✎ New annotation</button>' + (artifacts.length ? '' : '<div class="project-board-picker-empty">Loading your things…</div>');
      list.querySelector('.project-board-new-annotation').addEventListener('click', () => { addAnnotation(); tray.classList.add('hidden'); });
      const available = artifacts.filter(artifact => (!artifact.project_id || artifact.project_id === _projectId(project)) && !board.cards.some(card => card.artifact_key === artifact.key));
      if (!available.length) {
        list.innerHTML = '<div class="project-board-picker-empty">Everything available is already on this board, or belongs to another project.</div>';
      }
      available.forEach(artifact => {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'project-board-picker-item';
        button.innerHTML = `<span>${_cardIcon(artifact.type)}</span><span><b>${_escapeText(artifact.title)}</b><small>${_escapeText(artifact.type)}</small></span>`;
        button.addEventListener('click', async () => { await addArtifact(artifact); tray.classList.add('hidden'); }); list.appendChild(button);
      });
    }
  });
  render();
  _loadBoardArtifacts(sessions).then(async loaded => {
    artifacts = loaded;
    // Boards created before canonical artifact metadata existed still become
    // real project context the first time they are opened.
    await Promise.all(board.cards.map(async card => {
      const artifact = _artifactFor(card, artifacts);
      if (!artifact || artifact.project_id === _projectId(project)) return;
      try {
        const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId(project))}/artifacts/${encodeURIComponent(artifact.type)}/${encodeURIComponent(artifact.id)}`, { method: 'POST', credentials: 'same-origin' });
        await _jsonOrThrow(res); artifact.project_id = _projectId(project);
      } catch (_) { /* leave legacy card visible; a later explicit add can retry */ }
    }));
    render();
  });
}

function _appendReadout(parent, label, value) {
  const row = document.createElement('div');
  row.className = 'project-readout-row';
  const key = document.createElement('span');
  key.className = 'project-readout-label';
  key.textContent = label;
  const val = document.createElement('span');
  val.className = 'project-readout-value';
  val.textContent = _safeText(value, 'Not set');
  row.append(key, val);
  parent.appendChild(row);
}

function _worktreeLabel(worktree) {
  const bits = [worktree.branch || (worktree.detached ? 'detached' : 'worktree')];
  if (worktree.path) bits.push(worktree.path);
  return bits.join(' - ');
}

function _renderWorktreeRows(list, projectId, rootPath, worktrees, refresh) {
  list.innerHTML = '';
  if (!worktrees.length) {
    const empty = document.createElement('div');
    empty.className = 'project-card-empty';
    empty.textContent = 'No extra worktrees attached yet.';
    list.appendChild(empty);
    return;
  }
  worktrees.forEach(worktree => {
    const row = document.createElement('div');
    row.className = 'project-worktree-row';
    const label = document.createElement('span');
    label.textContent = _worktreeLabel(worktree);
    row.appendChild(label);
    if (worktree.path && worktree.path !== rootPath) {
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'project-secondary-btn';
      remove.textContent = 'Remove';
      remove.addEventListener('click', async () => {
        remove.disabled = true;
        try {
          await removeProjectWorktree(projectId, worktree.path);
          uiModule.showToast('Worktree removed');
          await refresh();
        } catch (error) {
          uiModule.showError(`Failed to remove worktree: ${error.message}`);
        } finally {
          remove.disabled = false;
        }
      });
      row.appendChild(remove);
    }
    list.appendChild(row);
  });
}

function _renderBranchOptions(select, branches) {
  select.innerHTML = '<option value="">Default branch/HEAD</option>';
  branches.forEach(branch => {
    const opt = document.createElement('option');
    opt.value = branch;
    opt.textContent = branch;
    select.appendChild(opt);
  });
}

function _mountWorktreePanel(card, projectId) {
  card.innerHTML = `
    <h3>Worktrees</h3>
    <p class="project-card-meta">Loading Git worktrees...</p>
    <div class="project-worktree-list"></div>
    <form class="project-form project-worktree-form">
      <label>Path<input name="path" autocomplete="off" placeholder="../my-project-feature" required></label>
      <label>Existing branch<select name="branch"></select></label>
      <label>Or new branch<input name="new_branch" autocomplete="off" placeholder="feature/my-run"></label>
      <div class="project-form-actions">
        <button type="submit" class="project-primary-btn">Create worktree</button>
      </div>
    </form>
  `;
  const meta = card.querySelector('.project-card-meta');
  const list = card.querySelector('.project-worktree-list');
  const form = card.querySelector('.project-worktree-form');
  const branchSelect = form.elements.branch;

  const refresh = async () => {
    try {
      const data = await listProjectWorktrees(projectId);
      const worktrees = Array.isArray(data?.worktrees) ? data.worktrees : [];
      const branches = Array.isArray(data?.branches) ? data.branches : [];
      const rootPath = data?.root_path || '';
      meta.textContent = rootPath ? `Root: ${rootPath}` : 'Git worktrees attached to this project.';
      _renderBranchOptions(branchSelect, branches);
      _renderWorktreeRows(list, projectId, rootPath, worktrees, refresh);
    } catch (error) {
      meta.textContent = error.message;
      list.innerHTML = '';
    }
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = {
      path: form.elements.path.value.trim(),
      branch: form.elements.branch.value.trim() || null,
      new_branch: form.elements.new_branch.value.trim() || null,
    };
    if (!payload.path) return;
    if (payload.new_branch) payload.branch = payload.branch || null;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      await createProjectWorktree(projectId, payload);
      form.reset();
      uiModule.showToast('Worktree created');
      await refresh();
    } catch (error) {
      uiModule.showError(`Failed to create worktree: ${error.message}`);
    } finally {
      button.disabled = false;
    }
  });

  refresh();
}

function _makeProjectForm(project, onSave) {
  const form = document.createElement('form');
  form.className = 'project-form';
  form.innerHTML = `
    <label>Project name<input name="name" autocomplete="off" required></label>
    <label>Description<textarea name="description" rows="3"></textarea></label>
    <label>Root path<input name="root_path" autocomplete="off" placeholder="/home/amber/Code/my-project"></label>
    <div class="project-form-actions">
      <button type="submit" class="project-primary-btn">Save project</button>
    </div>
  `;
  form.elements.name.value = project?.name || '';
  form.elements.description.value = project?.description || '';
  form.elements.root_path.value = project?.root_path || project?.rootPath || '';
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = {
      name: form.elements.name.value.trim(),
      description: form.elements.description.value.trim(),
      root_path: form.elements.root_path.value.trim(),
    };
    if (!payload.name) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      await onSave(payload);
      uiModule.showToast('Project saved');
    } catch (error) {
      uiModule.showError(`Failed to save project: ${error.message}`);
    } finally {
      button.disabled = false;
    }
  });
  return form;
}

export function showNewProjectDashboard() {
  selectedProjectId = null;
  const box = document.getElementById('chat-history');
  if (!box) return;
  box.innerHTML = '';
  const shell = document.createElement('section');
  shell.className = 'project-dashboard';
  shell.innerHTML = `
    <div class="project-dashboard-header">
      <div>
        <div class="project-kicker">Projects</div>
        <h2>Create project</h2>
        <p>Give Odysseus a stable project home. Chats and worktrees can attach here once the backend wiring exposes them.</p>
      </div>
    </div>
  `;
  shell.appendChild(_makeProjectForm(null, async (payload) => {
    const project = await createProject(payload);
    if (project) await openProjectDashboard(_projectId(project));
  }));
  box.appendChild(shell);
  _setProjectMode(true);
  renderProjectSidebar();
}

export async function openProjectDashboard(projectId, opts = {}) {
  let project = projects.find(p => _projectId(p) === String(projectId));
  if (!project && projectId) {
    try { project = await getProject(projectId); } catch (_) {}
  }
  if (!project) {
    uiModule.showError('Project not found');
    return;
  }
  selectedProjectId = _projectId(project);
  const sessions = opts.sessions || window.sessionModule?.getSessions?.() || [];
  renderProjectDashboard(project, sessions);
  renderProjectSidebar();
}

export function renderProjectDashboard(project, sessions = []) {
  const box = document.getElementById('chat-history');
  if (!box) return;
  const id = _projectId(project);
  const chats = _projectSessions(project, sessions);
  box.innerHTML = '';

  const shell = document.createElement('section');
  shell.className = 'project-dashboard';
  shell.dataset.projectId = id;
  shell.innerHTML = `
    <div class="project-dashboard-header">
      <div>
        <div class="project-kicker">Project board</div>
        <h2></h2>
        <p></p>
      </div>
      <div class="project-header-actions">
        <button type="button" class="project-board-zoom-btn" data-board-zoom-out aria-label="Zoom out" title="Zoom out">−</button>
        <button type="button" class="project-board-zoom-readout" data-board-zoom-reset title="Reset zoom">100%</button>
        <button type="button" class="project-board-zoom-btn" data-board-zoom-in aria-label="Zoom in" title="Zoom in">+</button>
        <button type="button" class="project-board-add-btn" data-project-chat aria-label="New project chat" title="New project chat">+</button>
        <button type="button" class="project-board-add-btn project-board-agent-btn" data-project-agent aria-label="New project agent" title="New project agent">&#xE795;</button>
        <button type="button" class="project-board-add-btn" data-board-add aria-label="Add existing artifact" title="Add existing artifact">☌</button>
      </div>
      <div class="project-edit-panel hidden"></div>
    </div>
    <div class="project-board-wrap">
      <div class="project-board" aria-label="Project board">
        <div class="project-board-empty"><span>✦</span><strong>Make this project yours.</strong><p>Add chats, notes, tasks, and documents, then arrange them into a little constellation.</p></div>
      </div>
      <aside class="project-board-tray hidden">
        <div class="project-board-tray-title">Add to board</div>
        <div class="project-board-picker-list"></div>
      </aside>
    </div>
    <div class="project-underboard">
      <div class="project-readout"></div>
      <div class="project-grid">
        <article class="project-card">
          <h3>Chats</h3>
          <p class="project-card-meta"></p>
          <div class="project-chat-links"></div>
        </article>
        <article class="project-card">
          <h3>Worktrees</h3>
          <p>Loading Git worktrees...</p>
        </article>
      </div>
    </div>
  `;
  shell.querySelector('h2').textContent = _safeText(project.name, 'Untitled project');
  shell.querySelector('.project-dashboard-header p').textContent = _safeText(project.description, 'No description yet.');

  const readout = shell.querySelector('.project-readout');
  _appendReadout(readout, 'Root path', project.root_path || project.rootPath);
  _appendReadout(readout, 'Project ID', id);

  const chatMeta = shell.querySelector('.project-card-meta');
  chatMeta.textContent = chats.length
    ? `${chats.length} chat${chats.length === 1 ? '' : 's'} linked to this project.`
    : 'No linked chats yet.';
  const links = shell.querySelector('.project-chat-links');
  chats.slice(0, 8).forEach(session => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'project-chat-link';
    btn.textContent = _safeText(session.name, 'Untitled chat');
    btn.addEventListener('click', () => window.sessionModule?.selectSession?.(session.id));
    links.appendChild(btn);
  });
  if (!links.children.length) {
    const empty = document.createElement('div');
    empty.className = 'project-card-empty';
    empty.textContent = 'Project chats will nest here once sessions include project_id.';
    links.appendChild(empty);
  }

  _mountProjectBoard(shell, project, sessions);
  requestAnimationFrame(() => {
    shell.querySelector('.project-board')?.scrollTo({ left: 0, top: 0 });
    box.scrollTo({ top: 0 });
  });

  const startProjectChat = (agent) => {
    const current = window.sessionModule?.getSessions?.().find(s => s.id === window.sessionModule?.getCurrentSessionId?.());
    if (!current?.endpoint_url || !current?.model) {
      uiModule.showError('Choose a model in a chat first, then create a project chat.'); return;
    }
    window.sessionModule?.createDirectChat?.(current.endpoint_url, current.model, current.endpoint_id, id);
    if (agent) document.getElementById('mode-agent-btn')?.click();
  };
  shell.querySelector('[data-project-chat]').addEventListener('click', () => startProjectChat(false));
  shell.querySelector('[data-project-agent]').addEventListener('click', () => startProjectChat(true));

  _mountWorktreePanel(shell.querySelector('.project-grid .project-card:nth-child(2)'), id);

  const editPanel = shell.querySelector('.project-edit-panel');
  editPanel.appendChild(_makeProjectForm(project, async (payload) => {
    const updated = await updateProject(id, payload);
    if (updated) renderProjectDashboard(updated, window.sessionModule?.getSessions?.() || sessions);
  }));
  shell.querySelector('.project-dashboard-header > div:first-child').title = 'Double-click to edit project details';
  shell.querySelector('.project-dashboard-header > div:first-child').addEventListener('dblclick', () => {
    editPanel.classList.toggle('hidden');
  });

  box.appendChild(shell);
  _setProjectMode(true);
}

export function clearProjectMode() {
  selectedProjectId = null;
  _setProjectMode(false);
  renderProjectSidebar();
}

function _setProjectMode(active) {
  document.body.classList.toggle('project-dashboard-active', !!active);
  const meta = document.getElementById('current-meta');
  if (meta && active) meta.textContent = 'Projects';
}

export function initProjects() {
  // projects.js is also an independent module entry in index.html. Keep this
  // idempotent: an older cached app.js may not call this at all, while a fresh
  // app.js imports and calls it during normal startup.
  if (projectsInitialized) return;
  projectsInitialized = true;
  document.getElementById('project-new-btn')?.addEventListener('click', (event) => {
    event.stopPropagation();
    showNewProjectDashboard();
  });
  renderProjectSidebar();
}

function _bootstrapProjects() {
  initProjects();
  // Do not rely on app.js for the first registry fetch. This makes the Project
  // sidebar resilient to a stale app shell during a service-worker rollout.
  listProjects({ silent: true }).catch(error => console.warn('loadProjects error:', error));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _bootstrapProjects, { once: true });
} else {
  _bootstrapProjects();
}

export default {
  initProjects,
  listProjects,
  getProject,
  createProject,
  updateProject,
  listProjectWorktrees,
  createProjectWorktree,
  removeProjectWorktree,
  getProjectsSnapshot,
  getSelectedProjectId,
  getProjectForSession,
  openProjectDashboard,
  showNewProjectDashboard,
  renderProjectDashboard,
  renderProjectSidebar,
  clearProjectMode,
};
