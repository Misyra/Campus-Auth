export const uiMethods = {
  setFrontendLogLevel(level) {
    this.frontendLogger.setLevel(level);
  },
  toastOnly(success, message) {
    // 仅显示 Toast，不记录到通知历史（用于非关键信息如网络测试结果）
    this.toast = { success, message, leaving: false };
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this.toast.leaving = true;
      setTimeout(() => {
        this.toast.message = '';
        this.toast.leaving = false;
      }, 300);
    }, 3000);
  },
  notify(success, message) {
    // 记录通知历史 + Toast（用于重要事件）
    const entry = { success, message, time: new Date().toLocaleTimeString() };
    this.notifications.unshift(entry);
    if (this.notifications.length > 30) this.notifications.length = 30;
    this.unreadNotifications++;

    this.toast = { success, message, leaving: false };
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this.toast.leaving = true;
      setTimeout(() => {
        this.toast.message = '';
        this.toast.leaving = false;
      }, 300);
    }, 3000);
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
    if (this.config.custom_variables && this.config.custom_variables.hasOwnProperty(key)) {
      const newVars = { ...this.config.custom_variables };
      delete newVars[key];
      this.config.custom_variables = newVars;
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
        const input = document.querySelector('.custom-var-item input[var-key="' + oldKey + '"]');
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
    if (!logViewer) return true;
    return logViewer.scrollTop + logViewer.clientHeight >= logViewer.scrollHeight - 5;
  },
  scrollLogToBottom(wasAtBottom) {
    // 智能滚动：仅在用户本来就在底部时自动滚动
    // wasAtBottom 在内容追加前捕获，避免新内容撑高 scrollHeight 导致误判
    const logViewer = document.querySelector('.log-viewer');
    if (!logViewer) return;
    if (!this.autoScroll) {
      this.newLogCount = (this.newLogCount || 0) + 1;
      return;
    }
    if (wasAtBottom === undefined) {
      wasAtBottom = logViewer.scrollTop + logViewer.clientHeight >= logViewer.scrollHeight - 5;
    }
    if (wasAtBottom) {
      logViewer.scrollTop = logViewer.scrollHeight;
      this.newLogCount = 0;
    } else {
      this.newLogCount = (this.newLogCount || 0) + 1;
    }
  },
  scrollToBottom() {
    // 手动点击"新消息"按钮时滚动
    const logViewer = document.querySelector('.log-viewer');
    if (logViewer) {
      logViewer.scrollTop = logViewer.scrollHeight;
      this.newLogCount = 0;
    }
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
