export const actionMethods = {
  async toggleMonitor() {
    this.busy.monitor = true;
    try {
      const url = this.status.monitoring ? '/api/monitor/stop' : '/api/monitor/start';
      this.frontendLogger.info('monitor', `request ${url}`);
      const { data } = await this.$api.post(url);
      this.notify(data.success, data.message);
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
      const { data } = await this.$api.post('/api/actions/login');
      this.notify(data.success, data.message);
    } catch (error) {
      const msg = error?.response?.data?.detail || '手动登录失败';
      this.frontendLogger.error('action', 'manual login failed', msg);
      this.notify(false, msg);
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
    } catch (error) {
      const msg = error?.response?.data?.detail || '网络测试失败';
      this.frontendLogger.error('action', 'network test failed', msg);
      this.notify(false, msg);
    } finally {
      this.busy.action = false;
    }
  },
};
