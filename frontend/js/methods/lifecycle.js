export const lifecycleMethods = {
  async init() {
    this.frontendLogger.info('app.init', 'start init');
    this.isLoading = true;
    await Promise.all([
      this.fetchConfig(true),
      this.fetchStatus(),
      this.fetchLogs(),
      this.fetchAppVersion(),
      this.fetchAutostart(),
      this.checkInitStatus(),
      this.fetchTasks(),
      this.fetchActiveTask(),
      this.fetchProfiles(),
      this.fetchSafeMode(),
      this.fetchBackups(),
    ]);
    this.isLoading = false;
    this.connectWebSocket();
    this.autoCheckUpdateOnStartup();
    this.timers.push(setInterval(() => this.fetchStatus(), 30000));  // 30s fallback, WS 实时推送
    this.timers.push(setInterval(() => this.fetchAutostart(), 12000));
    this.frontendLogger.info('app.init', 'init finished');
  },
  async _waitWebSocketReady(timeoutMs = 2000) {
    if (!this.ws) return false;
    if (this.ws.readyState === WebSocket.OPEN) return true;
    if (this.ws.readyState === WebSocket.CLOSING || this.ws.readyState === WebSocket.CLOSED) {
      return false;
    }

    return new Promise((resolve) => {
      let done = false;
      const ws = this.ws;

      const cleanup = (result) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('close', onClose);
        resolve(result);
      };

      const onOpen = () => cleanup(true);
      const onClose = () => cleanup(false);
      const timer = setTimeout(() => cleanup(ws.readyState === WebSocket.OPEN), timeoutMs);

      ws.addEventListener('open', onOpen, { once: true });
      ws.addEventListener('close', onClose, { once: true });
    });
  },
  async autoCheckUpdateOnStartup() {
    try {
      const { data } = await this.$api.get('/api/check-update');
      this.updateInfo = data;
      if (!data?.has_update) return;

      const latest = data.latest ? `v${data.latest}` : '新版本';
      const current = data.current ? `（当前 v${data.current}）` : '';
      const message = `发现新版本 ${latest}${current}`;

      this.notify(true, message);
      const wsReady = await this._waitWebSocketReady();
      const logMessage = `${message}，请前往“关于”页面下载`;
      this.frontendLogger.warn('update', logMessage);
      if (!wsReady) {
        const wasAtBottom = this._isViewerAtBottom();
        this.logs.push({
          timestamp: new Date().toISOString(),
          level: 'WARNING',
          source: 'frontend',
          message: `[update] ${logMessage}`,
        });
        if (this.logs.length > 300) {
          this.logs = this.logs.slice(-300);
        }
        this.$nextTick(() => this.scrollLogToBottom(wasAtBottom));
      }
    } catch (error) {
      this.frontendLogger.debug('update', '启动自动检查更新失败', error);
    }
  },
  async checkInitStatus() {
    try {
      const { data } = await this.$api.get('/api/init-status');
      this.showWizard = !data.initialized;
      if (data.password_decryption_failed) {
        this.frontendLogger.error('init', '密码解密失败，请在设置页面重新输入密码');
        this.notify(false, '密码解密失败，请在设置页面重新输入密码');
      }
    } catch {
      this.showWizard = false;
    }
  },
  async fetchAppVersion() {
    try {
      const { data } = await this.$api.get('/api/health');
      if (data?.version) {
        this.appVersion = data.version;
        return;
      }

      const openapiResp = await fetch('/openapi.json', { cache: 'no-cache' });
      if (openapiResp.ok) {
        const schema = await openapiResp.json();
        this.appVersion = schema?.info?.version || 'unknown';
        return;
      }

      this.appVersion = 'unknown';
    } catch {
      try {
        const openapiResp = await fetch('/openapi.json', { cache: 'no-cache' });
        if (openapiResp.ok) {
          const schema = await openapiResp.json();
          this.appVersion = schema?.info?.version || 'unknown';
          return;
        }
      } catch {
        // ignore fallback fetch error
      }
      this.appVersion = 'unknown';
    }
  },
  async checkUpdate() {
    this.updateLoading = true;
    this.updateInfo = null;
    try {
      const { data } = await this.$api.get('/api/check-update');
      this.updateInfo = data;
    } catch {
      this.updateInfo = { error: '检查更新失败，请检查网络连接' };
    } finally {
      this.updateLoading = false;
    }
  },
  async finishWizard() {
    this.busy.save = true;
    try {
      const { data } = await this.$api.put('/api/config', this.config);
      if (data.success) {
        this.showWizard = false;
        // 从 API 重新加载配置以获取服务端规范化后的值，确保快照一致
        await this.fetchConfig(true);
        this.frontendLogger.info('lifecycle', '配置完成');
      } else {
        this.frontendLogger.warn('lifecycle', '向导保存失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      const msg = error?.response?.data?.detail || '保存失败';
      this.frontendLogger.error('lifecycle', '向导保存异常: ' + msg, error);
      this.notify(false, msg);
    } finally {
      this.busy.save = false;
    }
  },
  _shouldShowLog(level) {
    // 根据前端日志级别过滤 WebSocket 日志显示
    // 完整日志始终写入文件，前端仅按级别展示
    const frontendLevel = (this.config.frontend_log_level || 'INFO').toUpperCase();
    const levels = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 };
    const msgLevel = levels[String(level || '').toUpperCase()] ?? 1;
    const minLevel = levels[frontendLevel] ?? 2;
    return msgLevel >= minLevel;
  },
  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/logs`;

    clearTimeout(this._wsRetryTimer);

    if (this.ws) {
      this.ws.close();
    }

    this.ws = new WebSocket(wsUrl);
    this.frontendLogger.info('websocket', `connecting ${wsUrl}`);

    this.ws.onopen = () => {
      this.wsRetryCount = 0;
      this.wsReconnecting = false;
      this.frontendLogger.setWebSocket(this.ws);
      this.frontendLogger.info('websocket', 'connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'status') {
          this.status = { ...this.status, ...data.data };
        } else if (data.type === 'log') {
          if (this._shouldShowLog(data.data.level)) {
            const wasAtBottom = this._isViewerAtBottom();
            this.logs.push(data.data);
            if (this.logs.length > 300) {
              this.logs = this.logs.slice(-300);
            }
            this.$nextTick(() => this.scrollLogToBottom(wasAtBottom));
          }
        } else if (data.type === 'log_batch') {
          if (Array.isArray(data.data)) {
            const filtered = data.data.filter(d => this._shouldShowLog(d.level));
            const wasAtBottom = this._isViewerAtBottom();
            this.logs.push(...filtered);
            if (this.logs.length > 300) {
              this.logs = this.logs.slice(-300);
            }
            this.$nextTick(() => this.scrollLogToBottom(wasAtBottom));
          }
        }
      } catch (e) {
        this.frontendLogger.error('websocket', 'message parse error', e);
      }
    };

    this.ws.onclose = () => {
      this.frontendLogger.setWebSocket(null);
      this.frontendLogger.warn('websocket', 'connection closed');
      if (this._wsDestroyed) return;
      if (this.wsRetryCount >= this.wsMaxRetries) {
        this.wsReconnecting = false;
        this.frontendLogger.error('websocket', '连接断开，重试次数已耗尽');
        this.notify(false, '与服务器的连接已断开，请刷新页面');
        return;
      }
      this.wsReconnecting = true;
      const delay = Math.min(1000 * Math.pow(2, this.wsRetryCount), 30000);
      this.wsRetryCount++;
      this._wsRetryTimer = setTimeout(() => {
        if (!this._wsDestroyed) this.connectWebSocket();
      }, delay);
    };

    this.ws.onerror = () => {
      this.frontendLogger.error('websocket', 'connection error');
      this.ws.close();
    };
  },
};
