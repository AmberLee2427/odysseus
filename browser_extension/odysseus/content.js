(() => {
  function visibleText() {
    const clone = document.body ? document.body.cloneNode(true) : null;
    if (!clone) return '';
    clone.querySelectorAll('script,style,noscript,svg,canvas,iframe').forEach((node) => node.remove());
    return (clone.innerText || clone.textContent || '')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/[ \t]{2,}/g, ' ')
      .trim()
      .slice(0, 60000);
  }

  const selection = String(window.getSelection ? window.getSelection() : '').trim();
  return {
    title: document.title || '',
    url: location.href,
    selected_text: selection.slice(0, 20000),
    text: visibleText(),
    html_excerpt: (document.documentElement && document.documentElement.outerHTML || '').slice(0, 20000)
  };
})();
