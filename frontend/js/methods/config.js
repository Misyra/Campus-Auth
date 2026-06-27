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

  // 配置变更时调用（统一 1 秒防抖）
  onConfigChange() {
    if (!this._isConfigLoaded) return;
    this._debounceSave(1000);
  },

  async fetchConfig(updateSnapshot = false) {
    try {
      const data = await this.$apiService.config.fetch();
      this.config = {
        browser: { ...DEFAULT_CONFIG.browser, ...(data.browser || {}) },
        monitor: { ...DEFAULT_CONFIG.monitor, ...(data.monitor || {}) },
        pause: { ...DEFAULT_CONFIG.pause, ...(data.pause || {}) },
        logging: { ...DEFAULT_CONFIG.logging, ...(data.logging || {}) },
        retry: { ...DEFAULT_CONFIG.retry, ...(data.retry || {}) },
        credentials: {
          username: data.username ?? '',
          password: data.password ?? '',
          auth_url: data.auth_url ?? '',
          isp: data.isp ?? '',
          carrier_custom: data.carrier_custom ?? '',
        },
        active_task: data.active_task ?? '',
        app_settings: { ...DEFAULT_CONFIG.app_settings, ...(data.app_settings || {}) },
      };
      this._passwordChanged = false;
      this._credentialsChanged = false;
      // 同步浏览器选择状态
      if (data.browser?.browser_channel) {
        this.selectedBrowser = data.browser.browser_channel;
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
  // 前端校验配置
  _validateConfig() {
    const warnings = [];
    const url = this.config.credentials.auth_url;
    if (url && !/^https?:\/\//.test(url)) {
      warnings.push('认证地址必须以 http:// 或 https:// 开头');
    }
    const port = this.config.app_settings.app_port;
    if (port && (port < 1 || port > 65535)) {
      warnings.push('端口范围必须在 1-65535 之间');
    }
    return warnings;
  },

  // 检查网络检测方式数量
  _getActiveCheckCount() {
    let count = 0;
    if (this.config.monitor.enable_tcp_check) count++;
    if (this.config.monitor.enable_http_check) count++;
    if (this.config.monitor.url_check_urls && this.config.monitor.url_check_urls.length > 0) count++;
    return count;
  },

  // 切换网络检测方式前检查
  onCheckToggle(field, value) {
    // 如果是关闭操作，检查是否是最后一种检测方式
    if (!value && this._getActiveCheckCount() === 0) {
      this.toastOnly(false, '至少需要保留一种网络检测方式');
      // 恢复为开启状态
      this.$nextTick(() => {
        if (field === 'tcp') this.config.monitor.enable_tcp_check = true;
        if (field === 'http') this.config.monitor.enable_http_check = true;
        if (field === 'url') {
          this.config.monitor.url_check_urls = this.defaultUrlCheckUrls?.length
            ? [...this.defaultUrlCheckUrls]
            : ['http://captive.apple.com/hotspot-detect.html|Success'];
        }
      });
      return;
    }
    this.onConfigChange();
  },

  async saveConfig() {
    // 脏值检测
    const current = JSON.stringify(this.config);
    if (this._lastSavedConfig && current === this._lastSavedConfig) {
      return;
    }

    // 前端校验（仅警告，不阻塞保存）
    const warnings = this._validateConfig();
    if (warnings.length > 0) {
      this.frontendLogger.warn('config', warnings.join('；'));
    }

    // 警告级提示（不阻塞保存）
    if (!this.config.credentials.auth_url) {
      this.frontendLogger.warn('config', '认证地址为空，自动认证将无法工作');
    }
    if (!this.config.credentials.username) {
      this.frontendLogger.warn('config', '账号为空，自动认证将无法工作');
    }
    if (!this.config.monitor.enable_tcp_check && !this.config.monitor.enable_http_check && !(this.config.monitor.url_check_urls && this.config.monitor.url_check_urls.length)) {
      this.frontendLogger.warn('config', '未启用任何网络检测方式，自动认证可能无法正常工作');
    }

    // 取消上一次请求
    if (this._saveAbortController) {
      this._saveAbortController.abort();
    }
    this._saveAbortController = new AbortController();

    const controller = this._saveAbortController;
    this.busy.save = true;
    this.saveFailed = false;
    try {
      const c = this.config;
      const payload = {
        browser: c.browser,
        monitor: c.monitor,
        pause: c.pause,
        logging: c.logging,
        retry: c.retry,
        app_settings: c.app_settings,
        active_task: c.active_task || '',
      };
      // 凭据：仅发送变更项
      if (this._passwordChanged) {
        payload.password = c.credentials.password || '';
      }
      if (this._credentialsChanged) {
        payload.username = c.credentials.username || '';
        payload.auth_url = c.credentials.auth_url || '';
        payload.isp = c.credentials.isp || '';
        payload.carrier_custom = c.credentials.carrier_custom || '';
      }

      const data = await this.$apiService.config.patch(payload, {
        signal: this._saveAbortController.signal,
      });
      if (data.success) {
        this._lastSavedConfig = current;
        this._credentialsChanged = false;
        this.frontendLogger.info('config', '配置保存成功');

        // 用后端规范化值刷新 config 并重置 savedConfigSnapshot
        await this.fetchConfig(true);
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
      if (this._saveAbortController === controller) {
        this.busy.save = false;
      }
    }
  },
  async resetConfig() {
    if (!confirm('确定要恢复默认设置吗？当前修改将丢失。')) return;
    try {
      const data = await this.$apiService.config.fetchDefaults();
      // 保留 credentials（凭据不重置）
      this.config = {
        browser: { ...data.browser },
        monitor: { ...data.monitor },
        pause: { ...data.pause },
        logging: { ...data.logging },
        retry: { ...data.retry },
        app_settings: { ...data.app_settings },
        credentials: { ...this.config.credentials },
        active_task: '',
      };
      this._lastSavedConfig = null;
      this.frontendLogger.info('config', '已恢复默认设置');
      this.saveConfig();
    } catch (error) {
      this.frontendLogger.error('config', '获取默认配置失败', error);
      this.toastOnly(false, '获取默认配置失败');
    }
  },
  onShellFileSelected(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    this.config.app_settings.shell_path = file.path || file.name;
    e.target.value = '';
  },
  async fetchShells() {
    try {
      const data = await this.$apiService.autostart.fetchShells();
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
      const data = await this.$apiService.config.fetchStealthScript();
      this.config.browser.stealth_custom_script = data.script || '';
      this.frontendLogger.info('config', '已加载默认反检测脚本');
    } catch (error) {
      this.frontendLogger.warn('config', '获取默认反检测脚本失败', error);
    }
  },
  // ── OCR 依赖管理 ──
  async fetchOcrStatus() {
    try {
      const data = await this.$apiService.ocr.fetchStatus();
      this.ocrStatus = data;
    } catch {
      this.ocrStatus = { installed: false, size_mb: 0 };
    }
  },
  async _toggleOcr(action) {
    const isInstall = action === 'install';
    const confirmText = isInstall
      ? '确定要安装 OCR 依赖吗？\nddddocr + onnxruntime 约占用 ~120MB 磁盘空间。'
      : '确定要卸载 OCR 依赖吗？\n卸载后 OCR 验证码识别步骤将无法使用。';
    if (!confirm(confirmText)) return;
    this.busy.ocr = true;
    try {
      const data = await (action === 'install' ? this.$apiService.ocr.install() : this.$apiService.ocr.uninstall());
      if (data.success) {
        this.frontendLogger.info('ocr', data.message);
        this.notify(true, data.message + '，需重启程序后生效', 'install');
        await this.fetchOcrStatus();
      } else {
        this.frontendLogger.warn('ocr', `${isInstall ? '安装' : '卸载'}失败: ${data.message}`);
        this.notify(false, data.message, 'install');
      }
    } catch (error) {
      const fallback = isInstall ? '安装失败' : '卸载失败';
      const label = isInstall ? '安装' : '卸载';
      const msg = extractApiError(error, fallback);
      this.frontendLogger.error('ocr', `${label}异常: ${msg}`, error);
      this.notify(false, msg, 'install');
    } finally {
      this.busy.ocr = false;
    }
  },
  async installOcr() { return this._toggleOcr('install'); },
  async uninstallOcr() { return this._toggleOcr('uninstall'); },
  // ── 开机自启动管理 ──
  async fetchAutostart() {
    if (this._autostartInFlight) return;
    this._autostartInFlight = true;
    try {
      const data = await this.$apiService.autostart.fetchStatus();
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
      const data = await this.$apiService.autostart.toggle(enable);
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
      const data = await this.$apiService.autostart.setMode(lightweight);
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
      const data = await this.$apiService.config.fetchLogLevels();
      // 统一更新到 config.logging，不再使用独立的 logLevels
      if (data.global_level) {
        this.config.logging.level = data.global_level;
      }
      if (data.source_levels) {
        this.config.logging.source_levels = data.source_levels;
      }
    } catch (error) {
      this.frontendLogger.warn('config', '获取日志级别配置失败', error);
    }
  },
  async setSourceLevel(source, level) {
    try {
      const data = await this.$apiService.config.setSourceLevel(source, level);
      if (data.success) {
        if (source === 'global') {
          this.config.logging.level = level;
        } else {
          if (!this.config.logging.source_levels) {
            this.config.logging.source_levels = {};
          }
          this.config.logging.source_levels[source] = level;
        }
        this.frontendLogger.info('config', `日志级别已设置: ${source} -> ${level}`);
        this.toastOnly(true, data.message);
      } else {
        this.frontendLogger.warn('config', '设置日志级别被拒绝: ' + data.message);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      const msg = extractApiError(error, '设置失败');
      this.frontendLogger.error('config', `设置日志级别失败: ${msg}`, error);
      this.toastOnly(false, msg);
    }
  },
};
