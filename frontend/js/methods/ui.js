export const uiMethods = {
  setFrontendLogLevel(level) {
    this.frontendLogger.setLevel(level);
  },
  notify(success, message) {
    // 记录通知历史
    const entry = { success, message, time: new Date().toLocaleTimeString() };
    this.notifications.unshift(entry);
    if (this.notifications.length > 30) this.notifications.length = 30;
    this.unreadNotifications++;

    // Toast 带淡出动画
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
      this.notify(false, '变量名必须以字母或下划线开头，只能包含字母、数字和下划线');
      // 恢复原值
      this.$nextTick(() => {
        const input = document.querySelector('.custom-var-item input[var-key="' + oldKey + '"]');
        if (input) input.value = oldKey;
      });
      return;
    }
    if (this.config.custom_variables.hasOwnProperty(newKey)) {
      this.notify(false, '变量名已存在');
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
  scrollLogToBottom() {
    // 智能滚动：仅在用户已经在底部时自动滚动
    const logViewer = document.querySelector('.log-viewer');
    if (!logViewer) return;
    const isAtBottom = logViewer.scrollTop + logViewer.clientHeight >= logViewer.scrollHeight - 60;
    if (isAtBottom) {
      logViewer.scrollTop = logViewer.scrollHeight;
      this._newLogCount = 0;
    } else {
      this._newLogCount = (this._newLogCount || 0) + 1;
    }
  },
  scrollToBottom() {
    // 手动点击"新消息"按钮时滚动
    const logViewer = document.querySelector('.log-viewer');
    if (logViewer) {
      logViewer.scrollTop = logViewer.scrollHeight;
      this._newLogCount = 0;
    }
  },
  async quitApp() {
    if (!confirm('确定要退出应用吗？')) return;
    try {
      this.busy.monitor = true;
      await this.$api.post('/api/shutdown');
      this.notify(true, '应用正在关闭...');
      setTimeout(() => {
        window.close();
      }, 1500);
    } catch (error) {
      this.notify(false, '退出失败，请手动关闭窗口');
      window.close();
    } finally {
      this.busy.monitor = false;
    }
  },
};
