const DEFAULT_SETTINGS = {
  baseUrl: '',
  token: '',
  pageSummary: true,
  screenshots: true
};

function trimBaseUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '');
}

async function getSettings() {
  const stored = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  return { ...DEFAULT_SETTINGS, ...stored, baseUrl: trimBaseUrl(stored.baseUrl) };
}

async function odysseusFetch(path, options = {}) {
  const settings = await getSettings();
  if (!settings.baseUrl || !settings.token) {
    throw new Error('Set an Odysseus URL and browser token first.');
  }
  const response = await fetch(`${settings.baseUrl}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
      'Authorization': `Bearer ${settings.token}`,
      ...(options.headers || {})
    }
  });
  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: text.slice(0, 500) };
    }
  }
  if (!response.ok) {
    const detail = data && (data.detail || data.error);
    throw new Error(detail || `Odysseus returned HTTP ${response.status}`);
  }
  return data;
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs && tabs[0];
  if (!tab || !tab.id) throw new Error('No active tab.');
  return tab;
}

async function extractPage(tabId) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    files: ['content.js']
  });
  return result;
}

async function summarizeCurrentTab(instruction) {
  const settings = await getSettings();
  if (!settings.pageSummary) throw new Error('Page summary capability is off.');
  const tab = await activeTab();
  const page = await extractPage(tab.id);
  return odysseusFetch('/api/browser/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page, instruction: instruction || '' })
  });
}

async function saveScreenshot() {
  const settings = await getSettings();
  if (!settings.screenshots) throw new Error('Screenshot capability is off.');
  const tab = await activeTab();
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  return odysseusFetch('/api/browser/captures/screenshot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: tab.title || '',
      url: tab.url || '',
      data_url: dataUrl
    })
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (!message || !message.type) throw new Error('Unknown request.');
    if (message.type === 'settings:get') return getSettings();
    if (message.type === 'settings:set') {
      const next = {
        baseUrl: trimBaseUrl(message.settings && message.settings.baseUrl),
        token: String((message.settings && message.settings.token) || '').trim(),
        pageSummary: !!(message.settings && message.settings.pageSummary),
        screenshots: !!(message.settings && message.settings.screenshots)
      };
      await chrome.storage.sync.set(next);
      return next;
    }
    if (message.type === 'ping') return odysseusFetch('/api/browser/ping');
    if (message.type === 'summarize') return summarizeCurrentTab(message.instruction || '');
    if (message.type === 'screenshot') return saveScreenshot();
    throw new Error(`Unknown request: ${message.type}`);
  })()
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
  return true;
});
