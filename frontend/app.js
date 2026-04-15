import { appOptions } from './js/app-options.js';
import { ensurePartialsReady } from './js/bootstrap.js';

const { createApp } = window.Vue;

async function bootstrapApp() {
  await ensurePartialsReady();
  createApp(appOptions).mount('#app');
}

bootstrapApp();
