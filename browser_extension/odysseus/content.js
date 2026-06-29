(() => {
  const MAX_PAGE_TEXT = 60000;
  const MAX_SELECTED_TEXT = 20000;
  const MAX_EDITOR_TEXT = 120000;

  function cleanText(value) {
    return String(value || '')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
  }

  function visibleText() {
    const clone = document.body ? document.body.cloneNode(true) : null;
    if (!clone) return '';
    clone.querySelectorAll('script,style,noscript,svg,canvas,iframe').forEach((node) => node.remove());
    return cleanText(clone.innerText || clone.textContent || '').slice(0, MAX_PAGE_TEXT);
  }

  function projectIdFromUrl() {
    const match = location.pathname.match(/\/project\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function textFromActiveElement() {
    const active = document.activeElement;
    if (!active || typeof active.value !== 'string') return null;
    const start = typeof active.selectionStart === 'number' ? active.selectionStart : null;
    const end = typeof active.selectionEnd === 'number' ? active.selectionEnd : null;
    return {
      text: active.value,
      selectedText: start !== null && end !== null ? active.value.slice(start, end) : '',
      selection: start !== null && end !== null ? { start, end } : null,
    };
  }

  function codeMirrorView() {
    const cmContent = document.querySelector('.cm-content');
    return cmContent && cmContent.cmView && cmContent.cmView.view ? cmContent.cmView.view : null;
  }

  function textFromCodeMirror() {
    const view = codeMirrorView();
    if (!view || !view.state || !view.state.doc) return null;
    const doc = view.state.doc;
    const text = typeof doc.toString === 'function' ? doc.toString() : '';
    const range = view.state.selection && view.state.selection.main;
    const selectedText = range && range.from !== range.to ? doc.sliceString(range.from, range.to) : '';
    return {
      text,
      selectedText,
      selection: range ? { start: range.from, end: range.to } : null,
    };
  }

  function textFromVisibleCodeMirrorLines() {
    const lines = Array.from(document.querySelectorAll('.cm-line, .CodeMirror-line'));
    if (!lines.length) return null;
    return {
      text: cleanText(lines.map((line) => line.textContent || '').join('\n')),
      selectedText: '',
      selection: null,
      warning: 'Only visible editor lines were available from the Overleaf tab.',
    };
  }

  function currentFileName() {
    const selectors = [
      '.file-tree .selected .entity-name',
      '.file-tree .selected',
      '.ide-file-tree .selected',
      '.editor-tabs .active',
      '.tab.active',
      '[aria-selected="true"]',
    ];
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const text = cleanText(node && node.textContent);
      if (text && /\.(tex|bib|sty|cls|md|txt)$/i.test(text)) return text.slice(0, 200);
    }
    const title = cleanText(document.title);
    const titleMatch = title.match(/([^/\\|]+?\.(?:tex|bib|sty|cls|md|txt))/i);
    return titleMatch ? titleMatch[1].slice(0, 200) : '';
  }

  function projectTitle() {
    const selectors = [
      '.project-name',
      '.ide-project-name',
      '[data-testid="project-name"]',
      'header h1',
    ];
    for (const selector of selectors) {
      const text = cleanText(document.querySelector(selector) && document.querySelector(selector).textContent);
      if (text) return text.slice(0, 300);
    }
    return cleanText(document.title.replace(/- Overleaf.*$/i, '')).slice(0, 300);
  }

  function overleafContext() {
    if (!/\.overleaf\.com$/.test(location.hostname) || !projectIdFromUrl()) return null;
    const selection = cleanText(window.getSelection ? window.getSelection() : '');
    const sources = [
      ['codemirror', textFromCodeMirror],
      ['active-element', textFromActiveElement],
      ['visible-lines', textFromVisibleCodeMirrorLines],
    ];
    let found = null;
    let editorKind = '';
    for (const [kind, source] of sources) {
      try {
        found = source();
      } catch {
        found = null;
      }
      if (found && (found.text || found.selectedText)) {
        editorKind = kind;
        break;
      }
    }
    found = found || { text: '', selectedText: '', selection: null };
    return {
      project_id: projectIdFromUrl(),
      project_title: projectTitle(),
      file_name: currentFileName(),
      editor_kind: editorKind || 'unknown',
      title: document.title || '',
      url: location.href,
      selected_text: cleanText(found.selectedText || selection).slice(0, MAX_SELECTED_TEXT),
      text: cleanText(found.text || '').slice(0, MAX_EDITOR_TEXT),
      selection: found.selection || null,
      warning: found.warning || '',
    };
  }

  const selection = String(window.getSelection ? window.getSelection() : '').trim();
  return {
    title: document.title || '',
    url: location.href,
    selected_text: selection.slice(0, 20000),
    text: visibleText(),
    html_excerpt: (document.documentElement && document.documentElement.outerHTML || '').slice(0, 20000),
    overleaf: overleafContext(),
  };
})();
