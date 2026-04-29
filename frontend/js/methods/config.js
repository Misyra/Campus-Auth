import { DEFAULT_CONFIG } from '../constants.js';

export const configMethods = {
  async fetchConfig() {
    try {
      const { data } = await this.$api.get('/api/config');
      this.config = {
        ...DEFAULT_CONFIG,
        ...data,
        auth_url: data.auth_url || DEFAULT_CONFIG.auth_url,
        browser_extra_headers_json: data.browser_extra_headers_json || '',
      };
      this.setFrontendLogLevel(this.config.frontend_log_level || 'INFO');
      this.frontendLogger.info('config', 'config loaded');
    } catch (error) {
      this.frontendLogger.error('config', 'failed to fetch config', error);
    }
  },
  async saveConfig() {
    this.busy.save = true;
    try {
      const payload = { ...this.config };
      if (payload.carrier !== '自定义') {
        payload.carrier_custom = '';
      }
      const { data } = await this.$api.put('/api/config', payload);
      this.setFrontendLogLevel(this.config.frontend_log_level || 'INFO');
      this.notify(data.success, data.message);
      if (data.success) {
        this.savedConfigSnapshot = JSON.stringify(this.config);
      }
    } catch (error) {
      const msg = error?.response?.data?.detail || '保存失败';
      this.frontendLogger.error('config', 'save config failed', error);
      this.notify(false, msg);
    } finally {
      this.busy.save = false;
    }
  },
  resetConfig() {
    if (!confirm('确定要恢复默认设置吗？当前修改将丢失。')) return;
    this.config = { ...DEFAULT_CONFIG };
    this.notify(true, '已恢复默认设置，请点击保存以生效');
  },
};
