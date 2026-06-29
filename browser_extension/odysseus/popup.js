const els = {
  baseUrl: document.getElementById('baseUrl'),
  token: document.getElementById('token'),
  pageSummary: document.getElementById('pageSummary'),
  screenshots: document.getElementById('screenshots'),
  instruction: document.getElementById('instruction'),
  targetSession: document.getElementById('targetSession'),
  status: document.getElementById('status'),
  save: document.getElementById('save'),
  test: document.getElementById('test'),
  summarize: document.getElementById('summarize'),
  screenshot: document.getElementById('screenshot')
};

function show(value, isError = false) {
  els.status.classList.toggle('error', isError);
  els.status.classList.toggle('pending', false);
  els.status.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function showPending(message) {
  els.status.classList.remove('error');
  els.status.classList.add('pending');
  els.status.textContent = message;
}

function showSummaryResult(result) {
  if (result && result.saved && result.session_url) {
    const baseUrl = els.baseUrl.value.trim().replace(/\/+$/, '');
    const url = `${baseUrl}${result.session_url}`;
    const verb = result.appended ? 'Added to Odysseus chat' : 'Saved to Odysseus chat';
    show(`${verb}:\n${result.session_name || result.title || 'Browser summary'}\n${url}`);
    return;
  }
  show((result && result.summary) || result);
}

function setThemeVar(name, value) {
  if (typeof value === 'string' && value.trim()) {
    document.documentElement.style.setProperty(name, value.trim());
  }
}

function applyTheme(theme) {
  const colors = theme && theme.colors;
  if (!colors) return;
  setThemeVar('--ody-bg', colors.bg);
  setThemeVar('--ody-fg', colors.fg);
  setThemeVar('--ody-panel', colors.panel);
  setThemeVar('--ody-border', colors.border);
  setThemeVar('--ody-accent', colors.red || colors.accent);
}

async function refreshTheme() {
  try {
    const data = await send('theme');
    applyTheme(data.theme);
  } catch {
    // The popup has a local fallback theme until the extension is configured.
  }
}

async function withBusy(button, label, task) {
  const original = button.textContent;
  const controls = [els.save, els.test, els.summarize, els.screenshot];
  controls.forEach((control) => { control.disabled = true; });
  button.textContent = label;
  document.body.classList.add('busy');
  try {
    return await task();
  } finally {
    button.textContent = original;
    controls.forEach((control) => { control.disabled = false; });
    document.body.classList.remove('busy');
  }
}

function send(type, payload = {}) {
  return chrome.runtime.sendMessage({ type, ...payload }).then((response) => {
    if (!response || !response.ok) throw new Error((response && response.error) || 'Request failed.');
    return response.data;
  });
}

function formSettings() {
  return {
    baseUrl: els.baseUrl.value,
    token: els.token.value,
    pageSummary: els.pageSummary.checked,
    screenshots: els.screenshots.checked,
    targetSessionId: els.targetSession.value
  };
}

function renderSessions(sessions, selectedId) {
  const current = selectedId || els.targetSession.value || '';
  els.targetSession.innerHTML = '<option value="">New browser summary chat</option>';
  (sessions || []).forEach((session) => {
    const option = document.createElement('option');
    option.value = session.id;
    option.textContent = session.name || session.id;
    els.targetSession.appendChild(option);
  });
  els.targetSession.value = Array.from(els.targetSession.options).some((option) => option.value === current) ? current : '';
}

async function refreshSessions(selectedId = '') {
  try {
    const data = await send('sessions');
    renderSessions(data.sessions || [], selectedId);
  } catch {
    renderSessions([], selectedId);
  }
}

async function load() {
  try {
    const settings = await send('settings:get');
    els.baseUrl.value = settings.baseUrl || '';
    els.token.value = settings.token || '';
    els.pageSummary.checked = settings.pageSummary !== false;
    els.screenshots.checked = settings.screenshots !== false;
    renderSessions([], settings.targetSessionId || '');
    if (settings.baseUrl && settings.token) {
      await refreshTheme();
      await refreshSessions(settings.targetSessionId || '');
    }
    show('Ready.');
  } catch (error) {
    show(error.message, true);
  }
}

els.save.addEventListener('click', async () => {
  await withBusy(els.save, 'Saving...', async () => {
    try {
      showPending('Saving extension settings...');
      const settings = await send('settings:set', { settings: formSettings() });
      await refreshTheme();
      await refreshSessions(settings.targetSessionId || '');
      show({ saved: true, baseUrl: settings.baseUrl, pageSummary: settings.pageSummary, screenshots: settings.screenshots });
    } catch (error) {
      show(error.message, true);
    }
  });
});

els.test.addEventListener('click', async () => {
  await withBusy(els.test, 'Testing...', async () => {
    try {
      showPending('Testing Odysseus connection...');
      await send('settings:set', { settings: formSettings() });
      showPending('Waiting for Odysseus...');
      const ping = await send('ping');
      await refreshTheme();
      await refreshSessions(els.targetSession.value);
      show(ping);
    } catch (error) {
      show(error.message, true);
    }
  });
});

els.summarize.addEventListener('click', async () => {
  await withBusy(els.summarize, 'Summarizing...', async () => {
    try {
      showPending('Reading the active tab...');
      await send('settings:set', { settings: formSettings() });
      showPending('Saving browser summary to Odysseus...');
      const result = await send('summarize', { instruction: els.instruction.value });
      showSummaryResult(result);
    } catch (error) {
      show(error.message, true);
    }
  });
});

els.screenshot.addEventListener('click', async () => {
  await withBusy(els.screenshot, 'Saving...', async () => {
    try {
      showPending('Capturing visible tab...');
      await send('settings:set', { settings: formSettings() });
      showPending('Saving screenshot to Odysseus...');
      show(await send('screenshot'));
    } catch (error) {
      show(error.message, true);
    }
  });
});

load();
