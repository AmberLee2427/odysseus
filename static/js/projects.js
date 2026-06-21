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
      if (window.innerWidth < 768 && sidebar) {
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
        <div class="project-kicker">Project</div>
        <h2></h2>
        <p></p>
      </div>
      <button type="button" class="project-secondary-btn" id="project-edit-toggle">Edit</button>
    </div>
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
    <div class="project-edit-panel hidden"></div>
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

  _mountWorktreePanel(shell.querySelector('.project-grid .project-card:nth-child(2)'), id);

  const editPanel = shell.querySelector('.project-edit-panel');
  editPanel.appendChild(_makeProjectForm(project, async (payload) => {
    const updated = await updateProject(id, payload);
    if (updated) renderProjectDashboard(updated, window.sessionModule?.getSessions?.() || sessions);
  }));
  shell.querySelector('#project-edit-toggle').addEventListener('click', () => {
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
  document.getElementById('rail-projects')?.addEventListener('click', () => {
    const sidebar = document.getElementById('sidebar');
    const section = document.getElementById('projects-section');
    if (sidebar) sidebar.classList.remove('hidden');
    if (section) {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
      section.classList.remove('collapsed');
    }
    if (window.syncRailSide) window.syncRailSide();
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
