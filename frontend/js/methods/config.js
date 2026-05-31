import { DEFAULT_CONFIG } from '../constants.js';
import { extractApiError } from './utils.js';

export const configMethods = {
  async fetchConfig(updateSnapshot = false) {
    try {
      const { data } = await this.$api.get('/api/config');
      this.config = {
        ...DEFAULT_CONFIG,
        ...data,
        browser_extra_headers_json: data.browser_extra_headers_json || '',
      };
      this.setFrontendLogLevel(this.config.frontend_log_level || 'INFO');
      if (updateSnapshot) {
        this._configDirty = false;
        this.savedConfigSnapshot = JSON.stringify(this.config);
      }
      this.frontendLogger.info('config', '配置已加载');
    } catch (error) {
      this.frontendLogger.error('config', '获取配置失败', error);
      if (this._initErrorCount < 2) {
        this._initErrorCount++;
        this.notify(false, '加载配置失败');
      }
    }
  },
  async saveConfig() {
    // 关键字段检查
    if (!this.config.auth_url && !confirm('认证地址为空，自动认证将无法工作。\n\n确定要继续保存吗？')) {
      return;
    }
    if (!this.config.username && !confirm('账号为空，自动认证将无法工作。\n\n确定要继续保存吗？')) {
      return;
    }
    const passwordIsMasked = this.config.password && this.config.password.startsWith('•');
    if (!passwordIsMasked && !this.config.password && !confirm('密码为空，自动认证将无法工作。\n\n确定要继续保存吗？')) {
      return;
    }
    if (!this.config.enable_tcp_check && !this.config.enable_http_check && !(this.config.portal_check_urls && this.config.portal_check_urls.trim())) {
      this.notify(false, '至少需要启用一种网络检测方式（TCP / HTTP / Captive Portal）');
      return;
    }

    this.busy.save = true;
    try {
      const payload = { ...this.config };
      if (payload.carrier !== '自定义') {
        payload.carrier_custom = '';
      }
      const { data } = await this.$api.put('/api/config', payload);
      this.setFrontendLogLevel(this.config.frontend_log_level || 'INFO');
      if (data.success) {
        this.frontendLogger.info('config', data.message || '配置保存成功');
        this._configDirty = false;
        this.savedConfigSnapshot = JSON.stringify(this.config);
        await this.fetchProfiles();
      } else {
        this.frontendLogger.warn('config', '保存配置被拒绝: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      const msg = extractApiError(error, '保存失败');
      this.frontendLogger.error('config', '保存配置失败', error);
      this.notify(false, msg);
    } finally {
      this.busy.save = false;
    }
  },
  resetConfig() {
    if (!confirm('确定要恢复默认设置吗？当前修改将丢失。')) return;
    this.config = structuredClone(DEFAULT_CONFIG);
    this._configDirty = true;
    this.frontendLogger.info('config', '已恢复默认设置，请点击保存以生效');
  },
  async fetchBackups() {
    try {
      const { data } = await this.$api.get('/api/backup/list');
      this.backups = data;
    } catch {
      // 备份列表获取失败，初始化为空数组
      this.backups = [];
    }
  },
  async createBackup() {
    this.busy.backup = true;
    try {
      const { data } = await this.$api.post('/api/backup/create');
      if (data.success) {
        this.frontendLogger.info('backup', '备份创建成功: ' + data.message);
        this.notify(true, data.message);
        await this.fetchBackups();
      } else {
        this.frontendLogger.warn('backup', '备份创建失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      const msg = extractApiError(error, '创建备份失败');
      this.frontendLogger.error('backup', '备份创建异常: ' + msg, error);
      this.notify(false, msg);
    } finally {
      this.busy.backup = false;
    }
  },
  async restoreBackup(filename) {
    if (!confirm(`确定要从 ${filename} 恢复配置吗？当前配置将被覆盖。`)) return;
    await this.createBackup();
    try {
      const { data } = await this.$api.post(`/api/backup/restore/${filename}`);
      if (data.success) {
        this.frontendLogger.info('backup', '备份恢复成功: ' + filename);
        this.notify(true, data.message);
        await this.fetchConfig(true);
        await this.fetchProfiles();
        await this.fetchBackups();
      } else {
        this.frontendLogger.warn('backup', '备份恢复失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      const msg = extractApiError(error, '恢复备份失败');
      this.frontendLogger.error('backup', '备份恢复异常: ' + msg, error);
      this.notify(false, msg);
    }
  },
  exportBackup(filename) {
    // 直接触发浏览器下载
    const url = `${window.location.origin}/api/backup/download/${filename}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    this.frontendLogger.info('config', `导出备份: ${filename}`);
  },
  async deleteBackup(filename) {
    if (!confirm(`确定要删除备份 ${filename} 吗？`)) return;
    try {
      const { data } = await this.$api.delete(`/api/backup/${filename}`);
      if (data.success) {
        this.frontendLogger.info('backup', '备份删除成功: ' + filename);
        this.toastOnly(true, data.message);
        await this.fetchBackups();
      } else {
        this.frontendLogger.warn('backup', '备份删除失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      const msg = extractApiError(error, '删除备份失败');
      this.frontendLogger.error('backup', '备份删除异常: ' + msg, error);
      this.notify(false, msg);
    }
  },
};
