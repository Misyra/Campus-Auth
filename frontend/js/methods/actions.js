export const actionMethods = {
  async toggleMonitor() {
    this.busy.monitor = true;
    try {
      const url = this.status.monitoring ? '/api/monitor/stop' : '/api/monitor/start';
      this.frontendLogger.info('monitor', `request ${url}`);
      const { data } = await this.$api.post(url);
      this.notify(data.success, data.message);
      await this.fetchStatus();
    } catch {
      this.frontendLogger.error('monitor', 'toggle monitor failed');
      this.notify(false, '操作失败');
    } finally {
      this.busy.monitor = false;
    }
  },
  async manualLogin() {
    this.busy.action = true;
    try {
      this.frontendLogger.info('action', 'manual login requested');
      const { data } = await this.$api.post('/api/actions/login');
      this.notify(data.success, data.message);
    } catch {
      this.frontendLogger.error('action', 'manual login failed');
      this.notify(false, '手动登录失败');
    } finally {
      this.busy.action = false;
    }
  },
  async testNetwork() {
    this.busy.action = true;
    try {
      this.frontendLogger.info('action', 'network test requested');
      const { data } = await this.$api.post('/api/actions/test-network');
      this.notify(data.success, data.message);
    } catch {
      this.frontendLogger.error('action', 'network test failed');
      this.notify(false, '网络测试失败');
    } finally {
      this.busy.action = false;
    }
  },
};
