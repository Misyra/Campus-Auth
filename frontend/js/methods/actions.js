export const actionMethods = {
  async openUninstall() {
    this.uninstall.visible = true;
    this.uninstall.scanning = true;
    this.uninstall.results = null;
    this.uninstall.items = [];
    try {
      const { data } = await this.$api.get('/api/uninstall/detect');
      this.uninstall.items = data.map(it => ({ ...it, checked: it.exists }));
    } catch (error) {
      const msg = error?.response?.data?.detail || '检测失败';
      this.toastOnly(false, msg);
      this.uninstall.visible = false;
    } finally {
      this.uninstall.scanning = false;
    }
  },
  closeUninstall() {
    this.uninstall.visible = false;
    this.uninstall.results = null;
  },
  async confirmUninstall() {
    const keys = this.uninstall.items.filter(it => it.exists && it.checked).map(it => it.key);
    if (keys.length === 0) return;
    if (!confirm(`确定要清理以下 ${keys.length} 个项目吗？此操作不可撤销。`)) return;
    this.busy.uninstall = true;
    try {
      const { data } = await this.$api.post('/api/uninstall', { keys });
      this.uninstall.results = data.results || [];
      this.toastOnly(data.success, data.success ? '清理完成' : '部分项目清理失败');
    } catch (error) {
      const msg = error?.response?.data?.detail || '卸载失败';
      this.toastOnly(false, msg);
    } finally {
      this.busy.uninstall = false;
    }
  },
  async toggleMonitor() {
    this.busy.monitor = true;
    try {
      const url = this.status.monitoring ? '/api/monitor/stop' : '/api/monitor/start';
      this.frontendLogger.info('monitor', `request ${url}`);
      const { data } = await this.$api.post(url);
      this.frontendLogger.info('monitor', 'monitor toggled: ' + data.message);
      this.toastOnly(data.success, data.message);
      await this.fetchStatus();
    } catch (error) {
      const msg = error?.response?.data?.detail || '操作失败';
      this.frontendLogger.error('monitor', 'toggle monitor failed', msg);
      this.notify(false, msg);
    } finally {
      this.busy.monitor = false;
    }
  },
  async manualLogin() {
    this.busy.action = true;
    try {
      this.frontendLogger.info('action', 'manual login requested');
      const loginTimeoutMs = (this.config.login_timeout || 120) * 1000;
      const { data } = await this.$api.post('/api/actions/login', null, { timeout: loginTimeoutMs });
      this.notify(data.success, this.stripScreenshotHint(data.message));
    } catch (error) {
      const msg = error?.response?.data?.detail || '手动登录失败';
      this.frontendLogger.error('action', 'manual login failed', msg);
      this.notify(false, this.stripScreenshotHint(msg));
    } finally {
      this.busy.action = false;
    }
  },
  async testNetwork() {
    this.busy.action = true;
    try {
      this.frontendLogger.info('action', 'network test requested');
      const { data } = await this.$api.post('/api/actions/test-network');
      // 网络测试结果只显示 toast，不记录通知历史
      this.toastOnly(data.success, data.message);
    } catch (error) {
      const msg = error?.response?.data?.detail || '网络测试失败';
      this.frontendLogger.error('action', 'network test failed', msg);
      this.toastOnly(false, msg);
    } finally {
      this.busy.action = false;
    }
  },
};
