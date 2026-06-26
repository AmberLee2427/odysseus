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
  els.status.classList.toggle('pending', false);
  els.status.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function showPending(message) {
  els.status.classList.remove('error');
  els.status.classList.add('pending');
  els.status.textContent = message;
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
  await withBusy(els.save, 'Saving...', async () => {
    try {
      showPending('Saving extension settings...');
      const settings = await send('settings:set', { settings: formSettings() });
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
      show(await send('ping'));
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
      showPending('Sending page text to Odysseus...');
      const result = await send('summarize', { instruction: els.instruction.value });
      show(result.summary || result);
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
