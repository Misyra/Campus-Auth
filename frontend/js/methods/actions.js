import { extractApiError } from './utils.js';

export const actionMethods = {
  async openUninstall() {
    this.uninstall.visible = true;
    this.uninstall.scanning = true;
    this.openModal('.uninstall-overlay');
    this.uninstall.results = null;
    this.uninstall.items = [];
    try {
      const data = await this.$apiService.uninstall.detect();
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
    this.closeModal();
    this.uninstall.visible = false;
    this.uninstall.results = null;
  },
  async confirmUninstall() {
    const keys = this.uninstall.items.filter(it => it.exists && it.checked).map(it => it.key);
    if (keys.length === 0) return;
    if (!confirm(`确定要清理以下 ${keys.length} 个项目吗？此操作不可撤销。`)) return;
    this.busy.uninstall = true;
    try {
      const data = await this.$apiService.uninstall.perform(keys);
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
      this.frontendLogger.info('monitor', `${this.status.monitoring ? 'stop' : 'start'} monitor`);
      const data = await (this.status.monitoring ? this.$apiService.monitor.stop() : this.$apiService.monitor.start());
      this.frontendLogger.info('monitor', '监控状态切换: ' + data.message);
      this.toastOnly(data.success, data.message);
      await this.fetchStatus();
    } catch (error) {
      const msg = extractApiError(error, '操作失败');
      this.frontendLogger.error('monitor', '切换监控失败', msg);
      this.notify(false, msg, 'monitor');
    } finally {
      this.busy.monitor = false;
    }
  },
  async manualLogin() {
    if (this.busy.loginCooldown) return;
    this.busy.action = true;
    this.busy.login = true;
    try {
      this.frontendLogger.info('action', '手动登录请求');
      // B5 修复：后端 dispatch 超时 = max(login_timeout, 60) + 10s，前端多留 15s 缓冲
      const loginTimeout = this.config.browser.login_timeout || 90;
      const loginTimeoutMs = (Math.max(loginTimeout, 60) + 25) * 1000;
      const data = await this.$apiService.actions.login(loginTimeoutMs);
      this.notify(data.success, this.stripScreenshotHint(data.message), 'login');
      // 登录完成后刷新登录历史
      this.fetchLoginHistory();
    } catch (error) {
      const msg = extractApiError(error, '手动登录失败');
      this.frontendLogger.error('action', '手动登录失败', msg);
      this.notify(false, this.stripScreenshotHint(msg), 'login');
    } finally {
      this.busy.login = false;
      // 3 秒防抖：API 返回后继续锁定按钮，防止短时间内重复点击
      this.busy.loginCooldown = true;
      if (this._loginCooldownTimer) clearTimeout(this._loginCooldownTimer);
      this._loginCooldownTimer = setTimeout(() => { this.busy.loginCooldown = false; }, 3000);
      this.busy.action = false;
    }
  },
  async cancelLogin() {
    try {
      this.frontendLogger.info('action', '取消登录请求');
      const data = await this.$apiService.actions.cancelLogin();
      this.toastOnly(data.success, data.message);
    } catch (error) {
      const msg = extractApiError(error, '取消登录失败');
      this.frontendLogger.error('action', '取消登录失败', msg);
      this.toastOnly(false, msg);
    }
  },
  async testNetwork() {
    this.busy.action = true;
    try {
      this.frontendLogger.info('action', '手动网络测试');
      const data = await this.$apiService.actions.testNetwork();
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
      const data = await this.$apiService.history.fetch(30);
      this.loginHistory = data;
    } catch (error) {
      this.frontendLogger.error('history', '获取登录历史失败', error);
    }
  },
  async clearLoginHistory() {
    if (!this.loginHistory.length) return;
    if (!confirm(`确定要清空所有 ${this.loginHistory.length} 条登录记录吗？此操作不可撤销。`)) return;
    try {
      const data = await this.$apiService.history.clear();
      this.loginHistory = [];
      this.toastOnly(data.success, data.message);
    } catch (error) {
      const msg = extractApiError(error, '清空登录历史失败');
      this.frontendLogger.error('history', '清空登录历史失败', msg);
      this.toastOnly(false, msg);
    }
  },
};
