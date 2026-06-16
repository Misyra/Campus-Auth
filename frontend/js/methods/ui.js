import { TIMING, LIMITS } from '../constants.js';

export const uiMethods = {
  // 弹窗焦点陷阱：将焦点限制在指定容器内
  _trapFocus(container) {
    this._releaseFocusTrap(); // 清理旧监听器，防止连续打开弹窗时泄漏
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
  // 统一弹窗管理：打开弹窗时自动设置焦点陷阱
  openModal(overlaySelector) {
    this.$nextTick(() => {
      const overlay = document.querySelector(overlaySelector);
      if (overlay) this._trapFocus(overlay);
    });
  },
  // 统一弹窗管理：关闭弹窗时自动释放焦点陷阱
  closeModal() {
    this._releaseFocusTrap();
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
  // 通知分类图标（内联 SVG）
  _notifyCategoryIcon(category) {
    const icons = {
      login: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
      monitor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
      network: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
      update: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
      security: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    };
    return icons[category] || '';
  },
  _formatNotifyTime() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    return `${now.getMonth() + 1}/${now.getDate()} ${h}:${m}:${s}`;
  },
  _notifyCategoryLabel(category) {
    const labels = { login: '登录', monitor: '监控', network: '网络', update: '更新', security: '安全' };
    return labels[category] || '';
  },
  notify(success, message, category, action) {
    const entry = {
      success,
      message,
      time: this._formatNotifyTime(),
      category: category || '',
      icon: this._notifyCategoryIcon(category),
      label: this._notifyCategoryLabel(category),
      action: action || null,
    };
    this.notifications.unshift(entry);
    if (this.notifications.length > TIMING.NOTIFICATION_MAX) this.notifications.length = TIMING.NOTIFICATION_MAX;
    this.unreadNotifications++;
    this._showToast(success, message);
  },
  // 获取可用浏览器列表
  async fetchBrowsers() {
    this.browserLoading = true;
    try {
      const response = await fetch('/api/browsers');
      const data = await response.json();
      this.availableBrowsers = data.browsers;
      this.selectedBrowser = data.current;
    } catch (error) {
      console.error('获取浏览器列表失败:', error);
    } finally {
      this.browserLoading = false;
    }
  },
  // 选择浏览器
  selectBrowser(channel) {
    this.selectedBrowser = channel;
    this.config.browser_channel = channel;
  },
  nextWizardStep() {
    // 第 1 步需要同意协议
    if (this.wizardStep === 1 && !this.agreedToTerms) {
      this.toastOnly(false, '请先阅读并同意使用协议');
      return;
    }
    // 第 2 步验证账号信息
    if (this.wizardStep === 2) {
      if (!this.config.username) {
        this.toastOnly(false, '请输入账号');
        return;
      }
      if (!this.config.password) {
        this.toastOnly(false, '请输入密码');
        return;
      }
      if (this.config.password.length < 2) {
        this.toastOnly(false, '密码长度不能少于2位');
        return;
      }
      if (!this.config.auth_url) {
        this.toastOnly(false, '请输入认证地址');
        return;
      }
      if (!/^https?:\/\//i.test(this.config.auth_url)) {
        this.toastOnly(false, '认证地址必须以 http:// 或 https:// 开头');
        return;
      }
      if (this.config.carrier === '自定义' && (!this.config.carrier_custom || !this.config.carrier_custom.trim())) {
        this.toastOnly(false, '请输入自定义运营商关键字');
        return;
      }
    }
    // 步骤 4：浏览器选择（无需验证，直接进入下一步）
    if (this.wizardStep === 4) {
      this.config.browser_channel = this.selectedBrowser;
    }
    if (this.wizardStep < 5) {
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
  // 编辑器关闭确认
  closeEditor() {
    if (this.editingTask && !confirm('当前有未保存的修改，确定要关闭吗？')) return;
    this.editingTask = null;
    this.jsonError = '';
  },
  // 清空日志确认
  clearLogs() {
    if (!this.logs.length) return;
    if (!confirm(`确定要清空当前 ${this.logs.length} 条日志显示吗？\n（后端日志文件不受影响）`)) return;
    this.logs = [];
    this.newLogCount = 0;
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
    // P1-FE-5: 用 requestAnimationFrame 节流，避免每次 scroll 事件都执行
    if (this._logScrollRaf) return;
    this._logScrollRaf = requestAnimationFrame(() => {
      this._logScrollRaf = null;
      if (this._isViewerAtBottom()) this.newLogCount = 0;
    });
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
      // 显示退出提示页面
      this._showExitOverlay();
    } catch (error) {
      this.frontendLogger.error('app', '退出应用失败', error);
      this._showExitOverlay();
    } finally {
      this.busy.monitor = false;
    }
  },
  _showExitOverlay() {
    const overlay = document.createElement('div');
    overlay.className = 'exit-overlay';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('width', '48');
    svg.setAttribute('height', '48');
    svg.innerHTML = '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>';
    const h2 = document.createElement('h2');
    h2.textContent = '已安全退出';
    const p = document.createElement('p');
    p.textContent = '后端服务已关闭';
    const btn = document.createElement('button');
    btn.className = 'btn btn-primary';
    btn.textContent = '关闭页面';
    btn.addEventListener('click', () => window.close());
    overlay.append(svg, h2, p, btn);
    document.body.appendChild(overlay);
  },
};
