import { TIMING, LIMITS } from '../constants.js';

export const uiMethods = {
  // 弹窗焦点陷阱：将焦点限制在指定容器内
  _trapFocus(container) {
    if (!container) return;
    const focusable = container.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length) focusable[0].focus();
    this._focusTrapHandler = (e) => {
      if (e.key === 'Escape') {
        this._releaseFocusTrap();
        return;
      }
      if (e.key !== 'Tab') return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', this._focusTrapHandler);
  },
  _releaseFocusTrap() {
    if (this._focusTrapHandler) {
      document.removeEventListener('keydown', this._focusTrapHandler);
      this._focusTrapHandler = null;
    }
  },
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
  // 导航到指定页面
  navigateTo(page) {
    this.currentPage = page;
    this.showMoreNav = false;
  },
  addCustomVar() {
    // 确保 custom_variables 是对象
    if (!this.config.custom_variables || typeof this.config.custom_variables !== 'object') {
      this.config.custom_variables = {};
    }
    // 生成默认变量名
    let index = 1;
    let key = `var_${index}`;
    while (Object.hasOwn(this.config.custom_variables, key)) {
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
    if (Object.hasOwn(this.config.custom_variables, newKey)) {
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
    const logViewer = this.$refs?.logViewer;
    if (!logViewer || logViewer.scrollHeight === 0) return true;
    return logViewer.scrollTop + logViewer.clientHeight >= logViewer.scrollHeight - LIMITS.SCROLL_BOTTOM_THRESHOLD;
  },
  _appendLogs(entries) {
    this.logs.push(...entries);
    if (this.logs.length > LIMITS.LOG_MAX_ENTRIES) {
      this.logs = this.logs.slice(-LIMITS.LOG_MAX_ENTRIES);
    }
    this.$nextTick(() => {
      if (this.autoScroll) {
        const logViewer = this.$refs?.logViewer;
        if (logViewer) logViewer.scrollTop = logViewer.scrollHeight;
      }
    });
  },
  scrollToBottom() {
    const logViewer = this.$refs?.logViewer;
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
      // 后端 shutdown 是异步的，WS 可能在 POST 响应返回前就断开
      // 必须在 POST 之前设置，否则 onclose 会触发无意义的重连
      this._wsDestroyed = true;
      if (this.ws) {
        this.ws.onclose = null;
        this.ws.onerror = null;
        this.ws.close();
      }
      await this.$api.post('/api/shutdown');
      // 尝试关闭窗口，浏览器可能拦截
      setTimeout(() => {
        window.close();
        // 如果窗口没关成（浏览器拦截），显示提示
        setTimeout(() => {
          const overlay = document.createElement('div');
          overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;position:fixed;inset:0;flex-direction:column;gap:16px;font-family:system-ui;color:#f1f5f9;background:#0f172a;z-index:9999;';
          overlay.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="#22d3ee" stroke-width="2" width="48" height="48">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <h2 style="margin:0;font-size:20px;">应用已退出</h2>
            <p style="margin:0;color:#94a3b8;font-size:14px;">后端已关闭，你可以关闭此标签页</p>`;
          document.body.appendChild(overlay);
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
