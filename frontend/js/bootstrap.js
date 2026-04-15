export async function ensurePartialsReady() {
  if (typeof window.loadFrontendPartials === 'function') {
    await window.loadFrontendPartials();
  }
}
