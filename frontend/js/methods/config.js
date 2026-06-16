import { DEFAULT_CONFIG } from '../constants.js';
import { extractApiError } from './utils.js';

export const configMethods = {
  // 自动保存相关属性
  _isConfigLoaded: false,
  _lastSavedConfig: null,
  _saveConfigTimer: null,
  _saveAbortController: null,

  // 防抖保存
  _debounceSave(delay = 500) {
    if (this._saveConfigTimer) clearTimeout(this._saveConfigTimer);
    this._saveConfigTimer = setTimeout(() => {
      this.saveConfig();
    }, delay);
  },

  // 配置变更时调用
  onConfigChange(field, value, type = 'toggle') {
    if (!this._isConfigLoaded) return;
    const delay = type === 'input' ? 1000 : 500;
    this._debounceSave(delay);
  },

  async fetchConfig(updateSnapshot = false) {
    try {
      const { data } = await this.$api.get('/api/config');
      this.config = {
        ...DEFAULT_CONFIG,
        ...data,
        browser_extra_headers_json: data.browser_extra_headers_json || '',
      };
      // 同步浏览器选择状态
      if (data.browser_channel) {
        this.selectedBrowser = data.browser_channel;
      }
      if (updateSnapshot) {
        this._lastSavedConfig = JSON.stringify(this.config);
      }
      this.frontendLogger.info('config', '配置已加载');

      // 首次加载完成后启用自动保存
      if (!this._isConfigLoaded) {
        this.$nextTick(() => {
          this._isConfigLoaded = true;
        });
      }
    } catch (error) {
      this.frontendLogger.error('config', '获取配置失败', error);
      this._recordInitError('加载配置失败');
    }
  },
  async saveConfig() {
    // 脏值检测
    const current = JSON.stringify(this.config);
    if (this._lastSavedConfig && current === this._lastSavedConfig) {
      return;
    }

    // 关键字段检查（自动保存时跳过确认弹窗）
    if (!this.config.auth_url) {
      this.frontendLogger.warn('config', '认证地址为空，自动认证将无法工作');
    }
    if (!this.config.username) {
      this.frontendLogger.warn('config', '账号为空，自动认证将无法工作');
    }
    if (!this.config.enable_tcp_check && !this.config.enable_http_check && !(this.config.url_check_urls && this.config.url_check_urls.trim())) {
      this.toastOnly(false, '至少需要启用一种网络检测方式（TCP / HTTP / 网址响应）');
      return;
    }

    // 取消上一次请求
    if (this._saveAbortController) {
      this._saveAbortController.abort();
    }
    this._saveAbortController = new AbortController();

    this.busy.save = true;
    this.saveFailed = false;
    try {
      const payload = { ...this.config };
      if (payload.carrier !== '自定义') {
        payload.carrier_custom = '';
      }
      const { data } = await this.$api.put('/api/config', payload, {
        signal: this._saveAbortController.signal,
      });
      if (data.success) {
        this._lastSavedConfig = current;
        this.frontendLogger.info('config', '配置保存成功');
        // 用后端规范化值刷新 config 并重置 savedConfigSnapshot
        await this.fetchConfig(true);
        await this.fetchProfiles();
      } else {
        this.frontendLogger.warn('config', '保存配置被拒绝: ' + data.message);
        this.toastOnly(false, data.message);
        this.saveFailed = true;
      }
    } catch (error) {
      if (error.name === 'AbortError') return;  // 被取消，忽略
      const msg = extractApiError(error, '保存失败');
      this.frontendLogger.error('config', '保存配置失败', error);
      this.toastOnly(false, msg);
      this.saveFailed = true;
    } finally {
      this.busy.save = false;
    }
  },
  resetConfig() {
    if (!confirm('确定要恢复默认设置吗？当前修改将丢失。')) return;
    this.config = structuredClone(DEFAULT_CONFIG);
    this._lastSavedConfig = null;  // 重置快照，configDirty 会自动检测到变更
    this.frontendLogger.info('config', '已恢复默认设置');
  },
  onShellFileSelected(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    this.config.shell_path = file.path || file.name;
    e.target.value = '';
  },
  async fetchShells() {
    try {
      const { data } = await this.$api.get('/api/shells');
      this.availableShells = data.shells || [];
      this.defaultShell = data.default || '';
    } catch (error) {
      this.frontendLogger.warn('config', '获取 Shell 列表失败', error);
      this.availableShells = [];
      this.defaultShell = '';
    }
  },
  async loadDefaultStealthScript() {
    try {
      const { data } = await this.$api.get('/api/config/default-stealth-script');
      this.config.stealth_custom_script = data.script || '';
      this.frontendLogger.info('config', '已加载默认反检测脚本');
    } catch (error) {
      this.frontendLogger.warn('config', '获取默认反检测脚本失败', error);
    }
  },
  // ── OCR 依赖管理 ──
  async fetchOcrStatus() {
    try {
      const { data } = await this.$api.get('/api/ocr/status');
      this.ocrStatus = data;
    } catch {
      this.ocrStatus = { installed: false, size_mb: 0 };
    }
  },
  async installOcr() {
    if (!confirm('确定要安装 OCR 依赖吗？\nddddocr + onnxruntime 约占用 ~120MB 磁盘空间。')) return;
    this.busy.ocr = true;
    try {
      const { data } = await this.$api.post('/api/ocr/install');
      if (data.success) {
        this.frontendLogger.info('ocr', data.message);
        this.notify(true, data.message + '，需重启程序后生效', 'install');
        await this.fetchOcrStatus();
      } else {
        this.frontendLogger.warn('ocr', '安装失败: ' + data.message);
        this.notify(false, data.message, 'install');
      }
    } catch (error) {
      const msg = extractApiError(error, '安装失败');
      this.frontendLogger.error('ocr', '安装异常: ' + msg, error);
      this.notify(false, msg, 'install');
    } finally {
      this.busy.ocr = false;
    }
  },
  async uninstallOcr() {
    if (!confirm('确定要卸载 OCR 依赖吗？\n卸载后 OCR 验证码识别步骤将无法使用。')) return;
    this.busy.ocr = true;
    try {
      const { data } = await this.$api.post('/api/ocr/uninstall');
      if (data.success) {
        this.frontendLogger.info('ocr', data.message);
        this.notify(true, data.message + '，需重启程序后生效', 'install');
        await this.fetchOcrStatus();
      } else {
        this.frontendLogger.warn('ocr', '卸载失败: ' + data.message);
        this.notify(false, data.message, 'install');
      }
    } catch (error) {
      const msg = extractApiError(error, '卸载失败');
      this.frontendLogger.error('ocr', '卸载异常: ' + msg, error);
      this.notify(false, msg, 'install');
    } finally {
      this.busy.ocr = false;
    }
  },
  // ── 开机自启动管理 ──
  async fetchAutostart() {
    if (this._autostartInFlight) return;
    this._autostartInFlight = true;
    try {
      const { data } = await this.$api.get('/api/autostart/status');
      this.autostart = data;
    } catch (error) {
      this.frontendLogger.warn('autostart', '获取自启动状态失败', error);
      if (error?.response?.status === 404) {
        this.autostart = {
          platform: '-',
          enabled: false,
          method: '当前后端不支持',
          location: '',
        };
      }
    } finally {
      this._autostartInFlight = false;
    }
  },
  async _toggleAutostart(enable) {
    const action = enable ? 'enable' : 'disable';
    const label = enable ? '启用' : '关闭';
    this.busy.autostart = true;
    try {
      const { data } = await this.$api.post(`/api/autostart/${action}`);
      if (data.success) {
        this.frontendLogger.info('autostart', data.message);
        this.toastOnly(true, data.message);
      } else {
        this.frontendLogger.warn('autostart', `${label}自启动失败: ${data.message}`);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      if (error?.response?.status === 404) {
        this.frontendLogger.warn('autostart', '后端不支持开机自启动');
        this.toastOnly(false, '当前后端版本不支持开机自启动，请重启后端');
      } else {
        this.frontendLogger.error('autostart', `${label}自启动异常`, error);
        this.toastOnly(false, `${label}自启动失败`);
      }
    } finally {
      await this.fetchAutostart();
      this.busy.autostart = false;
    }
  },
  async enableAutostart() { return this._toggleAutostart(true); },
  async disableAutostart() { return this._toggleAutostart(false); },
  async setAutostartMode(lightweight) {
    try {
      const { data } = await this.$api.post('/api/autostart/mode', { lightweight });
      if (data.success) {
        this.frontendLogger.info('autostart', data.message);
        this.toastOnly(true, data.message);
      } else {
        this.frontendLogger.warn('autostart', `切换自启动模式失败: ${data.message}`);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('autostart', '切换自启动模式异常', error);
      this.toastOnly(false, '切换自启动模式失败');
    }
  },
  // ── 日志级别管理 ──
  async fetchLogLevels() {
    try {
      const { data } = await this.$api.get('/api/config/log-levels');
      this.logLevels = data;
    } catch (error) {
      this.frontendLogger.warn('config', '获取日志级别配置失败', error);
    }
  },
  async setSourceLevel(source, level) {
    try {
      await this.$api.put('/api/config/source-level', { source, level });
      this.logLevels.source_levels[source] = level;
      this.frontendLogger.info('config', `已设置 ${source} 级别为 ${level}`);
      this.toastOnly(true, `已设置 ${source} 级别为 ${level}`);
    } catch (error) {
      const msg = extractApiError(error, '设置失败');
      this.frontendLogger.error('config', `设置日志级别失败: ${msg}`, error);
      this.toastOnly(false, msg);
    }
  },
};
