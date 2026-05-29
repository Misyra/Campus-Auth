import { appOptions } from './js/app-options.js';
import { ensurePartialsReady } from './js/bootstrap.js';
import {
  GlassCard,
  FormGroup,
  ToggleSwitch,
  StatusDot,
  LoadingSpinner,
  EmptyState,
} from './js/components.js';

const { createApp } = window.Vue;

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
  app.component('glass-card', GlassCard);
  app.component('form-group', FormGroup);
  app.component('toggle-switch', ToggleSwitch);
  app.component('status-dot', StatusDot);
  app.component('loading-spinner', LoadingSpinner);
  app.component('empty-state', EmptyState);

  app.mount('#app');
}

bootstrapApp();
