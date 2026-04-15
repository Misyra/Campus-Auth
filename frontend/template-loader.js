(function () {
  async function fetchInclude(el) {
    var src = el.getAttribute('data-include');
    if (!src) {
      return;
    }

    try {
      var res = await fetch(src, { cache: 'no-cache' });
      if (!res.ok) {
        throw new Error('HTTP ' + res.status);
      }
      el.innerHTML = await res.text();
      el.removeAttribute('data-include');
    } catch (err) {
      el.innerHTML = '<div class="include-error">模板加载失败: ' + src + '</div>';
      el.removeAttribute('data-include');
      console.error('[template-loader] failed:', src, err);
    }
  }

  async function includeRecursively(root) {
    if (!root) {
      return;
    }

    for (var i = 0; i < 12; i += 1) {
      var nodes = root.querySelectorAll('[data-include]');
      if (!nodes.length) {
        return;
      }
      var tasks = [];
      nodes.forEach(function (node) {
        tasks.push(fetchInclude(node));
      });
      await Promise.all(tasks);
    }
  }

  window.loadFrontendPartials = async function () {
    var appRoot = document.getElementById('app');
    await includeRecursively(appRoot);
  };
})();
