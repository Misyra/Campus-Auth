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
      install: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
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
    const labels = { login: '登录', monitor: '监控', network: '网络', update: '更新', security: '安全', install: '安装' };
    return labels[category] || '';
  },
  // 通知下拉菜单：切换 + 点击外部关闭
  toggleNotifications() {
    this.showNotifications = !this.showNotifications;
    if (this.showNotifications) {
      this.unreadNotifications = 0;
      document.addEventListener('mousedown', this._onNotifyOutsideClick);
    } else {
      document.removeEventListener('mousedown', this._onNotifyOutsideClick);
    }
  },
  _onNotifyOutsideClick(e) {
    const wrapper = document.querySelector('.notification-wrapper');
    if (wrapper && !wrapper.contains(e.target)) {
      this.showNotifications = false;
      document.removeEventListener('mousedown', this._onNotifyOutsideClick);
    }
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
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      this.availableBrowsers = data.browsers;
      // 只在已有选择时同步，向导模式下默认不选择
      if (this.selectedBrowser) {
        this.selectedBrowser = data.current;
        this.config.browser.browser_channel = data.current;
      }
    } catch (error) {
      console.error('获取浏览器列表失败:', error);
    } finally {
      this.browserLoading = false;
    }
  },
  // 选择浏览器
  selectBrowser(channel) {
    this.selectedBrowser = channel;
    this.config.browser.browser_channel = channel;
    this.onConfigChange();
  },
  // 辅助方法：获取浏览器信息
  getBrowser(channel) {
    return this.availableBrowsers.find(b => b.channel === channel) || { channel, installed: false };
  },
  // 辅助方法：获取浏览器图标
  getBrowserIcon(channel) {
    const browser = this.availableBrowsers.find(b => b.channel === channel);
    return browser ? browser.icon : '';
  },
  // 辅助方法：检查浏览器是否已安装
  isBrowserInstalled(channel) {
    const browser = this.availableBrowsers.find(b => b.channel === channel);
    return browser ? browser.installed : false;
  },
  // 辅助方法：获取其他浏览器（排除 Playwright）
  getOtherBrowsers() {
    return this.availableBrowsers.filter(b => b.channel !== 'playwright');
  },
  // 浏览器选择共享 partial 辅助：返回当前活跃的浏览器 channel
  getActiveBrowserChannel() {
    // wizard 模式用 selectedBrowser，settings 模式用 config.browser.browser_channel
    return this.selectedBrowser || this.config.browser.browser_channel;
  },
  // 浏览器选择共享 partial 辅助：自定义路径输入处理
  onBrowserCustomPathInput() {
    // settings 模式下需要触发配置保存
    if (this.onConfigChange) {
      this.onConfigChange();
    }
  },
  // 处理浏览器点击
  handleBrowserClick(browser) {
    if (browser.installed) {
      // Firefox 兼容性警告
      if (browser.channel === 'firefox') {
        if (!confirm('Firefox 可能不支持部分功能（如反检测模式、自定义浏览器参数等）。\n\n建议使用 Chromium 内核浏览器（Playwright Chromium、Edge、Chrome）。\n\n确定要使用 Firefox 吗？')) {
          return;
        }
      }
      this.selectBrowser(browser.channel);
    } else if (browser.channel === 'custom') {
      // 自定义浏览器始终 installed=true，但代码上仍保持独立分支
      // 选中并聚焦到路径输入框
      this.selectBrowser(browser.channel);
      this.$nextTick(() => {
        const input = document.querySelector('[data-custom-browser-path]');
        if (input) input.focus();
      });
    } else if (browser.channel === 'playwright') {
      // Playwright Chromium 未安装，提示自动下载
      if (confirm('Playwright Chromium 未安装。\n\n是否自动下载？（约 150MB）')) {
        this.installPlaywrightChromium();
      }
    } else {
      // 其他浏览器未安装，弹窗提示跳转官网
      const downloadUrls = {
        msedge: 'https://www.microsoft.com/edge',
        chrome: 'https://www.google.com/chrome/',
        firefox: 'https://www.firefox.com/',
      };
      const url = downloadUrls[browser.channel] || 'https://playwright.dev/docs/browsers';
      if (confirm(`${browser.name} 未安装。\n\n是否跳转到官网下载？`)) {
        window.open(url, '_blank');
      }
    }
  },
  // 安装 Playwright Chromium（后台下载，不阻塞 UI）
  installPlaywrightChromium() {
    this.playwrightDownloading = true;
    this.notify(true, 'Playwright Chromium 下载已开始，你可以继续配置其他选项', 'install');
    this.frontendLogger.info('browser', '开始下载 Playwright Chromium');
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 分钟超时
    fetch('/api/browsers/install-playwright', {
      method: 'POST',
      signal: controller.signal,
    })
      .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
      .then(data => {
        if (data.success) {
          this.frontendLogger.info('browser', 'Playwright Chromium 安装成功');
          this.notify(true, 'Playwright Chromium 安装完成！', 'install');
          this.fetchBrowsers();
        } else {
          this.frontendLogger.error('browser', '安装失败: ' + data.message);
          this.notify(false, '安装失败: ' + data.message, 'install');
        }
      })
      .catch(error => {
        if (error.name === 'AbortError') {
          this.frontendLogger.error('browser', '安装超时（超过 10 分钟）');
          this.notify(false, '安装超时，请检查网络后重试', 'install');
        } else {
          this.frontendLogger.error('browser', '安装请求失败', error);
          this.notify(false, '安装请求失败，请查看日志', 'install');
        }
      })
      .finally(() => {
        clearTimeout(timeoutId);
        this.playwrightDownloading = false;
      });
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
    if (!this.config.app_settings.custom_variables || typeof this.config.app_settings.custom_variables !== 'object') {
      this.config.app_settings.custom_variables = {};
    }
    // 生成默认变量名
    let index = 1;
    let key = `var_${index}`;
    while (Object.hasOwn(this.config.app_settings.custom_variables, key)) {
      index++;
      key = `var_${index}`;
    }
    this.config.app_settings.custom_variables[key] = '';
    this.onConfigChange();
  },
  removeCustomVar(key) {
    if (this.config.app_settings.custom_variables && key in this.config.app_settings.custom_variables) {
      const newVars = { ...this.config.app_settings.custom_variables };
      delete newVars[key];
      this.config.app_settings.custom_variables = newVars;
      this.onConfigChange();
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
        const input = document.querySelector('.custom-var-item input[data-var-key="' + CSS.escape(oldKey) + '"]');
        if (input) input.value = oldKey;
      });
      return;
    }
    if (Object.hasOwn(this.config.app_settings.custom_variables, newKey)) {
      this.frontendLogger.warn('config', '自定义变量名已存在: ' + newKey);
      this.toastOnly(false, '变量名已存在');
      return;
    }
    // 创建新键并复制值
    const newVars = {};
    for (const [k, v] of Object.entries(this.config.app_settings.custom_variables)) {
      if (k === oldKey) {
        newVars[newKey] = v;
      } else {
        newVars[k] = v;
      }
    }
    this.config.app_settings.custom_variables = newVars;
    this.onConfigChange();
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
      await this.$apiService.system.shutdown();
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
