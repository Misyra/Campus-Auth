export const uiMethods = {
  setFrontendLogLevel(level) {
    this.frontendLogger.setLevel(level);
  },
  notify(success, message) {
    this.toast = { success, message };
    setTimeout(() => {
      this.toast.message = '';
    }, 3000);
  },
  nextWizardStep() {
    if (this.wizardStep < 4) {
      this.wizardStep++;
    }
  },
  skipWizard() {
    this.showWizard = false;
  },
  setSettingsTab(tabId) {
    this.currentSettingsTab = tabId;
  },
  async quitApp() {
    if (!confirm('确定要退出应用吗？')) return;
    try {
      this.busy.monitor = true;
      await this.$api.post('/api/shutdown');
      this.notify(true, '应用正在关闭...');
      setTimeout(() => {
        window.close();
      }, 1500);
    } catch (error) {
      this.notify(false, '退出失败，请手动关闭窗口');
      window.close();
    } finally {
      this.busy.monitor = false;
    }
  },
};
