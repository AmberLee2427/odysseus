const els = {
  baseUrl: document.getElementById('baseUrl'),
  token: document.getElementById('token'),
  pageSummary: document.getElementById('pageSummary'),
  screenshots: document.getElementById('screenshots'),
  instruction: document.getElementById('instruction'),
  status: document.getElementById('status'),
  save: document.getElementById('save'),
  test: document.getElementById('test'),
  summarize: document.getElementById('summarize'),
  screenshot: document.getElementById('screenshot')
};

function show(value, isError = false) {
  els.status.classList.toggle('error', isError);
  els.status.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
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
    screenshots: els.screenshots.checked
  };
}

async function load() {
  try {
    const settings = await send('settings:get');
    els.baseUrl.value = settings.baseUrl || '';
    els.token.value = settings.token || '';
    els.pageSummary.checked = settings.pageSummary !== false;
    els.screenshots.checked = settings.screenshots !== false;
    show('Ready.');
  } catch (error) {
    show(error.message, true);
  }
}

els.save.addEventListener('click', async () => {
  try {
    const settings = await send('settings:set', { settings: formSettings() });
    show({ saved: true, baseUrl: settings.baseUrl, pageSummary: settings.pageSummary, screenshots: settings.screenshots });
  } catch (error) {
    show(error.message, true);
  }
});

els.test.addEventListener('click', async () => {
  try {
    await send('settings:set', { settings: formSettings() });
    show(await send('ping'));
  } catch (error) {
    show(error.message, true);
  }
});

els.summarize.addEventListener('click', async () => {
  try {
    await send('settings:set', { settings: formSettings() });
    const result = await send('summarize', { instruction: els.instruction.value });
    show(result.summary || result);
  } catch (error) {
    show(error.message, true);
  }
});

els.screenshot.addEventListener('click', async () => {
  try {
    await send('settings:set', { settings: formSettings() });
    show(await send('screenshot'));
  } catch (error) {
    show(error.message, true);
  }
});

load();
