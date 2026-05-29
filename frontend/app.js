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
