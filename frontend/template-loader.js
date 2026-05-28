(function () {
  const MAX_INCLUDE_DEPTH = 12;

  async function fetchInclude(el) {
    const src = el.getAttribute('data-include');
    if (!src) return;

    try {
      const res = await fetch(src, { cache: 'no-cache' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      el.innerHTML = await res.text();
      el.removeAttribute('data-include');
    } catch (err) {
      el.innerHTML = '<div class="include-error">模板加载失败: ' + src + '</div>';
      el.removeAttribute('data-include');
      console.error('[template-loader] failed:', src, err);
    }
  }

  async function includeRecursively(root) {
    if (!root) return;

    for (let i = 0; i < MAX_INCLUDE_DEPTH; i += 1) {
      const nodes = root.querySelectorAll('[data-include]');
      if (!nodes.length) return;
      await Promise.all(Array.from(nodes, node => fetchInclude(node)));
    }
  }

  window.loadFrontendPartials = async function () {
    const appRoot = document.getElementById('app');
    await includeRecursively(appRoot);
  };
})();
