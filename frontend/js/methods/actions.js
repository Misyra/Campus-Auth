import { extractApiError } from './utils.js';

export const actionMethods = {
  async openUninstall() {
    this.uninstall.visible = true;
    this.uninstall.scanning = true;
    this.$nextTick(() => {
      const overlay = document.querySelector('.uninstall-overlay');
      if (overlay) this._trapFocus(overlay);
    });
    this.uninstall.results = null;
    this.uninstall.items = [];
    try {
      const { data } = await this.$api.get('/api/uninstall/detect');
      this.uninstall.items = data.map(it => ({ ...it, checked: it.exists }));
    } catch (error) {
      const msg = extractApiError(error, '检测失败');
      this.toastOnly(false, msg);
      this.uninstall.visible = false;
    } finally {
      this.uninstall.scanning = false;
    }
  },
  closeUninstall() {
    this._releaseFocusTrap();
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
      const msg = extractApiError(error, '卸载失败');
      this.toastOnly(false, msg);
    } finally {
      this.busy.uninstall = false;
    }
  },
  async toggleMonitor() {
    this.busy.monitor = true;
    try {
      const url = this.status.monitoring ? '/api/monitor/stop' : '/api/monitor/start';
      this.frontendLogger.info('monitor', `POST ${url}`);
      const { data } = await this.$api.post(url);
      this.frontendLogger.info('monitor', '监控状态切换: ' + data.message);
      this.toastOnly(data.success, data.message);
      await this.fetchStatus();
    } catch (error) {
      const msg = extractApiError(error, '操作失败');
      this.frontendLogger.error('monitor', '切换监控失败', msg);
      this.notify(false, msg);
    } finally {
      this.busy.monitor = false;
    }
  },
  async manualLogin() {
    this.busy.action = true;
    try {
      this.frontendLogger.info('action', '手动登录请求');
      const loginTimeoutMs = (this.config.login_timeout || 120) * 1000;
      const { data } = await this.$api.post('/api/actions/login', null, { timeout: loginTimeoutMs });
      this.notify(data.success, this.stripScreenshotHint(data.message));
    } catch (error) {
      const msg = extractApiError(error, '手动登录失败');
      this.frontendLogger.error('action', '手动登录失败', msg);
      this.notify(false, this.stripScreenshotHint(msg));
    } finally {
      this.busy.action = false;
    }
  },
  async testNetwork() {
    this.busy.action = true;
    try {
      this.frontendLogger.info('action', '手动网络测试');
      const { data } = await this.$api.post('/api/actions/test-network');
      // 网络测试结果只显示 toast，不记录通知历史
      this.toastOnly(data.success, data.message);
    } catch (error) {
      const msg = extractApiError(error, '网络测试失败');
      this.frontendLogger.error('action', '网络测试失败', msg);
      this.toastOnly(false, msg);
    } finally {
      this.busy.action = false;
    }
  },
  async fetchLoginHistory() {
    try {
      const { data } = await this.$api.get('/api/login-history', { params: { limit: 30 } });
      this.loginHistory = data;
    } catch (error) {
      this.frontendLogger.error('history', '获取登录历史失败', error);
    }
  },
  async clearLoginHistory() {
    if (!this.loginHistory.length) return;
    if (!confirm(`确定要清空所有 ${this.loginHistory.length} 条登录记录吗？此操作不可撤销。`)) return;
    try {
      const { data } = await this.$api.delete('/api/login-history');
      this.loginHistory = [];
      this.toastOnly(data.success, data.message);
    } catch (error) {
      const msg = extractApiError(error, '清空登录历史失败');
      this.frontendLogger.error('history', '清空登录历史失败', msg);
      this.toastOnly(false, msg);
    }
  },
};
