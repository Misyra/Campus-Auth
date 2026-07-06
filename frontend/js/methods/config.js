import { DEFAULT_CONFIG } from '../constants.js';
import { extractApiError } from './utils.js';

// 凭据字段映射：前端嵌套 config.credentials.* ↔ 后端平铺字段
// 新增凭据字段只需在此处登记，fetchConfig/saveConfig 自动同步
const CREDENTIAL_FIELDS = ['username', 'password', 'auth_url', 'isp', 'carrier_custom'];

export const configMethods = {
  async fetchConfig(updateSnapshot = false) {
    try {
      const data = await this.$apiService.config.fetch();
      this.config = {
        browser: { ...DEFAULT_CONFIG.browser, ...(data.browser || {}) },
        monitor: { ...DEFAULT_CONFIG.monitor, ...(data.monitor || {}) },
        pause: { ...DEFAULT_CONFIG.pause, ...(data.pause || {}) },
        logging: { ...DEFAULT_CONFIG.logging, ...(data.logging || {}) },
        retry: { ...DEFAULT_CONFIG.retry, ...(data.retry || {}) },
        credentials: Object.fromEntries(
          CREDENTIAL_FIELDS.map(f => [f, data[f] ?? ''])
        ),
        active_task: data.active_task ?? '',
        app_settings: { ...DEFAULT_CONFIG.app_settings, ...(data.app_settings || {}) },
      };
      // 同步浏览器选择状态
      if (data.browser?.browser_channel) {
        this.selectedBrowser = data.browser.browser_channel;
      }
      // 密码掩码回显：记录后端是否已保存密码
      this.passwordSaved = !!data.has_password;
      this.editingPassword = false;
      if (updateSnapshot) {
        this._lastSavedConfig = JSON.stringify(this.config);
      }
      this.frontendLogger.info('config', '配置已加载');
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

  // 确保至少保留一种网络检测方式
  _ensureAtLeastOneCheckMethod() {
    const { enable_tcp_check, enable_http_check, url_check_urls } = this.config.monitor;
    if (!enable_tcp_check && !enable_http_check && !(url_check_urls && url_check_urls.length)) {
      this.toastOnly(false, '至少需要保留一种网络检测方式');
      this.$nextTick(() => {
        this.config.monitor.enable_tcp_check = true;
      });
    }
  },

  // 密码字段聚焦：已保存密码时进入编辑态（清空掩码占位）
  onPasswordFocus() {
    if (this.passwordSaved) {
      this.editingPassword = true;
    }
  },
  // 密码字段失焦：未输入内容则恢复掩码显示
  onPasswordBlur() {
    if (!this.config.credentials.password) {
      this.editingPassword = false;
    }
  },

  async saveConfig() {
    // 脏值检测
    if (this._lastSavedConfig && JSON.stringify(this.config) === this._lastSavedConfig) {
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

    // 单调递增序号用于 finally 排重（比 AbortController 引用比较更可靠）
    this._saveSeq = (this._saveSeq || 0) + 1;
    const currentSeq = this._saveSeq;

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
      // 记录本次是否提交了明文密码（用于成功后更新 passwordSaved 标记）
      const submittedPassword = !!c.credentials.password;
      const payload = {
        browser: c.browser,
        monitor: c.monitor,
        pause: c.pause,
        logging: c.logging,
        retry: c.retry,
        app_settings: c.app_settings,
        active_task: c.active_task || '',
      };
      // 凭据字段：username/auth_url/isp/carrier_custom 空串表示清空
      ['username', 'auth_url', 'isp', 'carrier_custom'].forEach(f => {
        payload[f] = c.credentials[f] ?? '';
      });
      // 密码字段：未编辑时传 null（不修改），编辑态传实际值（空串表示清空）
      if (this.passwordSaved && !this.editingPassword) {
        payload.password = null;  // 未修改密码
      } else {
        payload.password = c.credentials.password || '';  // 编辑态：空串清空，有值则加密
      }

      const data = await this.$apiService.config.patch(payload, {
        signal: controller.signal,
      });
      if (data.success) {
        // 若本次提交了明文密码，标记密码已保存（驱动掩码回显）
        if (submittedPassword) {
          this.passwordSaved = true;
        }
        // 密码已加密存储到服务端，前端清空明文显示并退出编辑态
        // （与服务端 GET /api/config 始终返回空串的行为一致）
        this.config.credentials.password = '';
        this.editingPassword = false;
        // 重建快照（password 已清空，与当前状态一致）
        this._lastSavedConfig = JSON.stringify(this.config);
        this.frontendLogger.info('config', '配置保存成功');
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
      // 仅当没有更新的 saveConfig 调用时才恢复按钮状态
      if (this._saveSeq === currentSeq) {
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
          runtime_mode: 'full',
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
  async setAutostartMode(runtimeMode) {
    try {
      const data = await this.$apiService.autostart.setMode(runtimeMode);
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
      if (data.level) {
        this.config.logging.level = data.level;
      }

    } catch (error) {
      this.frontendLogger.warn('config', '获取日志级别配置失败', error);
    }
  },
  async setLogLevel(level) {
    try {
      const data = await this.$apiService.config.setLogLevel(level);
      if (data.success) {
        this.config.logging.level = level;
        this.frontendLogger.setLevel(level);
        this.frontendLogger.info('config', `日志级别已设置: ${level}`);
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
