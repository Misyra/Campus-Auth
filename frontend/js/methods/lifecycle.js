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
    this.timers.push(setInterval(this.fetchStatus, 30000));  // 30s fallback, WS 实时推送
    this.timers.push(setInterval(this.fetchAutostart, 12000));
    this.frontendLogger.info('app.init', 'init finished');
  },
  async checkInitStatus() {
    try {
      const { data } = await this.$api.get('/api/init-status');
      this.showWizard = !data.initialized;
      if (data.password_decryption_failed) {
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
        this.notify(false, data.message);
      }
    } catch (error) {
      const msg = error?.response?.data?.detail || '保存失败';
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
      this.frontendLogger.info('websocket', 'connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'status') {
          this.status = { ...this.status, ...data.data };
        } else if (data.type === 'log') {
          // 按前端日志级别过滤显示（完整日志已写入文件）
          if (this._shouldShowLog(data.data.level)) {
            this.logs.push(data.data);
            if (this.logs.length > 300) {
              this.logs = this.logs.slice(-300);
            }
            this.$nextTick(() => this.scrollLogToBottom());
          }
        } else if (data.type === 'log_batch') {
          if (Array.isArray(data.data)) {
            const filtered = data.data.filter(d => this._shouldShowLog(d.level));
            this.logs.push(...filtered);
            if (this.logs.length > 300) {
              this.logs = this.logs.slice(-300);
            }
            this.$nextTick(() => this.scrollLogToBottom());
          }
        }
      } catch (e) {
        this.frontendLogger.error('websocket', 'message parse error', e);
      }
    };

    this.ws.onclose = () => {
      this.frontendLogger.warn('websocket', 'connection closed');
      if (this._wsDestroyed) return;
      if (this.wsRetryCount >= this.wsMaxRetries) {
        this.wsReconnecting = false;
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
