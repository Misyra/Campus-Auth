import { appOptions } from './js/app-options.js';
import { ensurePartialsReady } from './js/bootstrap.js';
import { ToggleSwitch } from './js/components.js';
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
    if (appearance.zoom) {
      document.querySelector('.content-wrapper')?.style.setProperty('zoom', appearance.zoom / 100);
    }
    if (appearance.theme) {
      root.setAttribute('data-theme', appearance.theme);
    }
    if (appearance.backdrop_filter === false) {
      body.classList.add('no-backdrop-filter');
    }
    if (appearance.background_color) {
      root.style.setProperty('--bg-primary', appearance.background_color);
    }
    if (appearance.card_opacity != null) {
      const bgHex = appearance.background_color || '#0f172a';
      const num = parseInt(bgHex.replace('#', ''), 16);
      const r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255;
      root.style.setProperty('--bg-card', `rgba(${r}, ${g}, ${b}, ${appearance.card_opacity})`);
      // 提前设置卡片毛玻璃 blur，避免页面切换时延迟渲染
      if (appearance.backdrop_filter !== false && appearance.card_opacity > 0) {
        root.style.setProperty('--card-blur', `blur(${Math.round(appearance.card_opacity * 20)}px)`);
      } else {
        root.style.setProperty('--card-blur', 'none');
      }
    }
    if (appearance.sidebar_opacity != null) {
      root.style.setProperty('--sidebar-opacity', appearance.sidebar_opacity);
    }
    if (appearance.sidebar_accent) {
      root.style.setProperty('--sidebar-accent', appearance.sidebar_accent);
    }
    if (appearance.sidebar_color) {
      const num = parseInt(appearance.sidebar_color.replace('#', ''), 16);
      const r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255;
      root.style.setProperty('--sidebar-bg-1', `rgba(${r}, ${g}, ${b}, var(--sidebar-opacity, 0.95))`);
      root.style.setProperty('--sidebar-bg-2', `rgba(${r}, ${g}, ${b}, calc(var(--sidebar-opacity, 0.95) + 0.03))`);
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

  // 注册图标组件
  for (const [name, component] of Object.entries(ICONS)) {
    app.component(name, component);
  }

  app.mount('#app');
}

bootstrapApp();
