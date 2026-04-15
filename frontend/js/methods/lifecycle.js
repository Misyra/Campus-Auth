export const lifecycleMethods = {
  async init() {
    this.frontendLogger.info('app.init', 'start init');
    await Promise.all([
      this.fetchConfig(),
      this.fetchStatus(),
      this.fetchLogs(),
      this.fetchAutostart(),
      this.checkInitStatus(),
      this.fetchTasks(),
      this.fetchActiveTask(),
    ]);
    this.connectWebSocket();
    this.timers.push(setInterval(this.fetchStatus, 4000));
    this.timers.push(setInterval(this.fetchAutostart, 12000));
    this.frontendLogger.info('app.init', 'init finished');
  },
  async checkInitStatus() {
    try {
      const { data } = await this.$api.get('/api/init-status');
      this.showWizard = !data.initialized;
    } catch {
      this.showWizard = false;
    }
  },
  async finishWizard() {
    this.busy.save = true;
    try {
      const { data } = await this.$api.put('/api/config', this.config);
      if (data.success) {
        this.showWizard = false;
        this.notify(true, '配置完成！');
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
  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/logs`;

    if (this.ws) {
      this.ws.close();
    }

    this.ws = new WebSocket(wsUrl);
    this.frontendLogger.info('websocket', `connecting ${wsUrl}`);
    this.wsRetryCount = this.wsRetryCount || 0;
    this.wsMaxRetries = 5;

    this.ws.onopen = () => {
      this.wsRetryCount = 0;
      this.frontendLogger.info('websocket', 'connected');
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'log') {
          this.logs.push(data.data);
          if (this.logs.length > 300) {
            this.logs = this.logs.slice(-300);
          }
        }
      } catch (e) {
        this.frontendLogger.error('websocket', 'message parse error', e);
      }
    };

    this.ws.onclose = () => {
      this.frontendLogger.warn('websocket', 'connection closed');
      if (this.wsRetryCount >= this.wsMaxRetries) {
        this.notify(false, '与服务器的连接已断开，请刷新页面');
        return;
      }
      const delay = Math.min(1000 * Math.pow(2, this.wsRetryCount), 30000);
      this.wsRetryCount++;
      setTimeout(() => {
        this.connectWebSocket();
      }, delay);
    };

    this.ws.onerror = () => {
      this.frontendLogger.error('websocket', 'connection error');
      this.ws.close();
    };
  },
};
