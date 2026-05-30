import { TIMING } from '../constants.js';

export const uiMethods = {
  setFrontendLogLevel(level) {
    this.frontendLogger.setLevel(level);
  },
  _showToast(success, message) {
    this.toast = { success, message, leaving: false };
    if (this._toastTimer) clearTimeout(this._toastTimer);
    if (this._toastLeavingTimer) clearTimeout(this._toastLeavingTimer);
    this._toastTimer = setTimeout(() => {
      this.toast.leaving = true;
      this._toastLeavingTimer = setTimeout(() => {
        this.toast.message = '';
        this.toast.leaving = false;
      }, TIMING.TOAST_LEAVE_DELAY);
    }, TIMING.TOAST_DURATION);
  },
  toastOnly(success, message) {
    this._showToast(success, message);
  },
  notify(success, message) {
    const entry = { success, message, time: new Date().toLocaleTimeString() };
    this.notifications.unshift(entry);
    if (this.notifications.length > TIMING.NOTIFICATION_MAX) this.notifications.length = TIMING.NOTIFICATION_MAX;
    this.unreadNotifications++;
    this._showToast(success, message);
  },
  nextWizardStep() {
    if (this.wizardStep < 4) {
      this.wizardStep++;
    }
  },
  skipWizard() {
    // 至少要有用户名和认证地址才能跳过
    if (!this.config.username || !this.config.auth_url) {
      if (!confirm('账号和认证地址尚未填写，跳过向导将无法使用自动认证。\n\n确定要跳过吗？')) return;
    }
    this.showWizard = false;
  },
  setSettingsTab(tabId) {
    this.currentSettingsTab = tabId;
  },
  addCustomVar() {
    // 确保 custom_variables 是对象
    if (!this.config.custom_variables || typeof this.config.custom_variables !== 'object') {
      this.config.custom_variables = {};
    }
    // 生成默认变量名
    let index = 1;
    let key = `var_${index}`;
    while (this.config.custom_variables.hasOwnProperty(key)) {
      index++;
      key = `var_${index}`;
    }
    this.config.custom_variables[key] = '';
  },
  removeCustomVar(key) {
    if (this.config.custom_variables && key in this.config.custom_variables) {
      delete this.config.custom_variables[key];
    }
  },
  updateCustomVarKey(oldKey, newKey) {
    if (!newKey || oldKey === newKey) return;
    newKey = newKey.trim();
    if (!newKey) return;
    // 验证新变量名格式
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(newKey)) {
      this.frontendLogger.warn('config', '自定义变量名格式无效: ' + newKey);
      this.toastOnly(false, '变量名必须以字母或下划线开头，只能包含字母、数字和下划线');
      // 恢复原值
      this.$nextTick(() => {
        const input = document.querySelector('.custom-var-item input[data-var-key="' + oldKey + '"]');
        if (input) input.value = oldKey;
      });
      return;
    }
    if (this.config.custom_variables.hasOwnProperty(newKey)) {
      this.frontendLogger.warn('config', '自定义变量名已存在: ' + newKey);
      this.toastOnly(false, '变量名已存在');
      return;
    }
    // 创建新键并复制值
    const newVars = {};
    for (const [k, v] of Object.entries(this.config.custom_variables)) {
      if (k === oldKey) {
        newVars[newKey] = v;
      } else {
        newVars[k] = v;
      }
    }
    this.config.custom_variables = newVars;
  },
  _isViewerAtBottom() {
    const logViewer = document.querySelector('.log-viewer');
    if (!logViewer || logViewer.scrollHeight === 0) return true;
    return logViewer.scrollTop + logViewer.clientHeight >= logViewer.scrollHeight - 50;
  },
  _appendLogs(entries) {
    const LOG_MAX_ENTRIES = 100;
    this.logs.push(...entries);
    if (this.logs.length > LOG_MAX_ENTRIES) {
      this.logs = this.logs.slice(-LOG_MAX_ENTRIES);
    }
    this.$nextTick(() => {
      if (this.autoScroll) {
        const logViewer = document.querySelector('.log-viewer');
        if (logViewer) logViewer.scrollTop = logViewer.scrollHeight;
      }
    });
  },
  scrollToBottom() {
    const logViewer = document.querySelector('.log-viewer');
    if (logViewer) {
      logViewer.scrollTo({ top: logViewer.scrollHeight, behavior: 'smooth' });
      this.newLogCount = 0;
    }
  },
  onLogScroll() {
    if (this._isViewerAtBottom()) this.newLogCount = 0;
  },
  openFullscreen(src) {
    this.fullscreenSrc = src;
  },
  closeFullscreen() {
    this.fullscreenSrc = '';
  },
  async quitApp() {
    if (!confirm('确定要退出应用吗？')) return;
    try {
      this.busy.monitor = true;
      await this.$api.post('/api/shutdown');
      // 尝试关闭窗口，浏览器可能拦截
      setTimeout(() => {
        window.close();
        // 如果窗口没关成（浏览器拦截），显示提示
        setTimeout(() => {
          document.body.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:16px;font-family:system-ui;color:#f1f5f9;background:#0f172a;">
              <svg viewBox="0 0 24 24" fill="none" stroke="#22d3ee" stroke-width="2" width="48" height="48">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22 4 12 14.01 9 11.01"/>
              </svg>
              <h2 style="margin:0;font-size:20px;">应用已退出</h2>
              <p style="margin:0;color:#94a3b8;font-size:14px;">后端已关闭，你可以关闭此标签页</p>
            </div>`;
        }, 500);
      }, 1000);
    } catch (error) {
      this.frontendLogger.error('app', '退出应用失败', error);
      this.notify(false, '退出失败，请手动关闭窗口');
    } finally {
      this.busy.monitor = false;
    }
  },
};
