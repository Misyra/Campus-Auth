import { appOptions } from './js/app-options.js';
import { ensurePartialsReady } from './js/bootstrap.js';
import { CustomSelect, ToggleSwitch } from './js/components.js';
import { ICONS } from './js/icons.js';

const { createApp } = window.Vue;

// Vue 挂载前先应用外观设置，避免刷新后背景图闪烁或失效
function applyAppearanceEarly() {
  try {
    const saved = localStorage.getItem('appearance');
    if (!saved) return;
    const appearance = JSON.parse(saved);
    const root = document.documentElement;
    const body = document.body;

    if (appearance.background_url) {
      body.style.setProperty('--bg-image', `url(${appearance.background_url})`);
      body.style.setProperty('--bg-blur', `blur(${appearance.background_blur || 10}px)`);
      body.style.setProperty('--bg-opacity', appearance.background_opacity || 0.3);
      body.classList.add('has-custom-bg');
    }

    if (appearance.accent_color) {
      root.style.setProperty('--accent', appearance.accent_color);
    }
    // zoom 在 mounted() 中由 applyAppearance() 统一处理，此处不设置（Vue 挂载前 .content-wrapper 可能不存在）
    if (appearance.theme) {
      root.setAttribute('data-theme', appearance.theme);
    }
    if (appearance.backdrop_filter === false) {
      body.classList.add('no-backdrop-filter');
    }
    if (appearance.background_color) {
      root.style.setProperty('--bg-primary', appearance.background_color);
    }
    if (appearance.sidebar_opacity != null) {
      root.style.setProperty('--sidebar-opacity', appearance.sidebar_opacity);
    }
    if (appearance.sidebar_accent) {
      root.style.setProperty('--sidebar-accent', appearance.sidebar_accent);
    }
  } catch {
    // 外观设置应用失败（localStorage 不可用或数据损坏），忽略
  }
}
applyAppearanceEarly();

// 性能检测：帧率低于 30fps 时禁用毛玻璃效果
function detectPerformance() {
  let frameCount = 0;
  let lastTime = performance.now();
  const CHECK_DURATION = 2000; // 检测 2 秒

  function measure() {
    frameCount++;
    const now = performance.now();
    const elapsed = now - lastTime;

    if (elapsed >= CHECK_DURATION) {
      const fps = Math.round((frameCount * 1000) / elapsed);
      if (fps < 30) {
        document.documentElement.classList.add('no-backdrop-filter');
        console.log(`[性能检测] 帧率 ${fps}fps < 30fps，已禁用毛玻璃效果`);
      }
      return; // 检测完成，停止测量
    }
    requestAnimationFrame(measure);
  }

  requestAnimationFrame(measure);
}

// 页面加载 5 秒后开始检测，留出加载时间
setTimeout(detectPerformance, 5000);

async function bootstrapApp() {
  await ensurePartialsReady();

  const app = createApp(appOptions);

  // 注册全局组件
  app.component('toggle-switch', ToggleSwitch);
  app.component('custom-select', CustomSelect);

  // 注册图标组件
  for (const [name, component] of Object.entries(ICONS)) {
    app.component(name, component);
  }

  app.mount('#app');
}

bootstrapApp();
