import { LOG_LEVELS, TIMING } from '../constants.js';

export const lifecycleMethods = {
  // 封装初始化错误计数，达到阈值后静默（避免多模块竞态读写 _initErrorCount）
  _recordInitError(msg) {
    if (this._initErrorCount < 2) {
      this._initErrorCount++;
      this.notify(false, msg);
    }
  },
  async init() {
    this.frontendLogger.info('app.init', '开始初始化');
    this.isLoading = true;
    const initResults = await Promise.allSettled([
      this.fetchConfig(true),
      this.fetchStatus(),
      this.fetchLogs(),
      this.fetchAppVersion(),
      this.fetchAutostart(),
      this.checkInitStatus(),
      this.fetchTasks(),
      this.fetchScripts(),
      this.fetchActiveTask(),
      this.fetchProfiles(),
      this.fetchPureMode(),
      this.fetchBackups(),
      this.fetchLoginHistory(),
      this.loadScheduledTasks(),
      this.fetchShells(),
    ]);
    const rejectedCount = initResults.filter(r => r.status === 'rejected').length;
    if (rejectedCount > 0) {
      this.frontendLogger.warn('app.init', `部分初始化失败: ${rejectedCount} 项`);
    }
    this._initErrorCount = 0;
    this.isLoading = false;
    this.connectWebSocket();
    this.autoCheckUpdateOnStartup();
    this.timers.push(setInterval(() => {
        if (this._statusPolling) return;
        this._statusPolling = true;
        this.fetchStatus().finally(() => { this._statusPolling = false; });
    }, TIMING.STATUS_POLL_INTERVAL));  // 30s fallback, WS 实时推送
    this.timers.push(setInterval(() => this.fetchAutostart(), TIMING.AUTOSTART_POLL_INTERVAL));
    this.frontendLogger.info('app.init', '初始化完成');
  },
  async _waitWebSocketReady(timeoutMs = TIMING.WS_READY_TIMEOUT) {
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

      this.notify(true, message, 'update', { label: '前往下载', page: 'about' });
      const wsReady = await this._waitWebSocketReady();
      const logMessage = `${message}，请前往“关于”页面下载`;
      this.frontendLogger.warn('update', logMessage);
      if (!wsReady) {
        // 二次读取 readyState，补偿 T1→T2 期间 WS 可能已连接的竞态
        if (this.ws?.readyState === WebSocket.OPEN) return;
        this._appendLogs([{
          timestamp: new Date().toISOString(),
          level: 'WARNING',
          source: 'frontend',
          message: `[update] ${logMessage}`,
        }]);
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
        this.notify(false, '密码解密失败，请在设置页面重新输入密码', 'security');
      }
    } catch (error) {
      // 网络错误（无 response）时保持 showWizard 不变
      // 服务端明确返回错误时才抑制向导
      if (error?.response?.status) {
        this.showWizard = false;
      }
      this.frontendLogger.warn('init', '检查初始化状态失败', error);
    }
  },
  async fetchAppVersion() {
    try {
      const { data } = await this.$api.get('/api/health');
      if (data?.version) {
        this.appVersion = data.version;
        return;
      }
    } catch {
      // health 接口不可用，继续尝试 openapi 回退
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), TIMING.OPENAPI_TIMEOUT);
      let openapiResp;
      try {
        openapiResp = await fetch('/openapi.json', { cache: 'no-cache', signal: controller.signal });
      } finally {
        clearTimeout(timeoutId);
      }
      if (openapiResp.ok) {
        const schema = await openapiResp.json();
        this.appVersion = schema?.info?.version || 'unknown';
        return;
      }
    } catch {
      // openapi 回退也不可用，版本设为 unknown
    }

    this.appVersion = 'unknown';
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
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      const msg = error?.response?.data?.detail || '保存失败';
      this.frontendLogger.error('lifecycle', '向导保存异常: ' + msg, error);
      this.toastOnly(false, msg);
    } finally {
      this.busy.save = false;
    }
  },
  _shouldShowLog(level) {
    // 根据前端日志级别过滤 WebSocket 日志显示
    // 完整日志始终写入文件，前端仅按级别展示
    const frontendLevel = (this.config.frontend_log_level || 'INFO').toUpperCase();
    const levels = LOG_LEVELS;
    const msgLevel = levels[String(level || '').toUpperCase()] ?? 20;
    const minLevel = levels[frontendLevel] ?? 30;
    return msgLevel >= minLevel;
  },
  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/logs`;

    clearTimeout(this._wsRetryTimer);

    if (this.ws) {
      // 清理旧回调，防止快速重连时旧 onclose 切断新连接
      const oldWs = this.ws;
      if (this.frontendLogger) {
        this.frontendLogger.setWebSocket(null);
      }
      oldWs.onclose = null;
      oldWs.onerror = null;
      oldWs.close();
    }

    this.ws = new WebSocket(wsUrl);
    this.frontendLogger.info('websocket', `正在连接 ${wsUrl}`);

    this.ws.onopen = () => {
      this.wsRetryCount = 0;
      this.wsReconnecting = false;
      this.frontendLogger.setWebSocket(this.ws);
      this.frontendLogger.info('websocket', '已连接');

      // 重连后重新获取状态，补偿断连期间可能错过的更新
      if (this._wsWasConnected) {
        this.fetchStatus();
        this.fetchLoginHistory();
      }
      this._wsWasConnected = true;
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'status') {
          this.status = { ...this.status, ...data.data };
        } else if (data.type === 'log') {
          if (this._shouldShowLog(data.data.level)) {
            this._appendLogs([data.data]);
          }
        }
      } catch (e) {
        this.frontendLogger.error('websocket', '消息解析错误', e);
      }
    };

    this.ws.onclose = () => {
      this.frontendLogger.setWebSocket(null);
      this.frontendLogger.warn('websocket', '连接已关闭');
      if (this._wsDestroyed) return;
      if (this.wsRetryCount >= this.wsMaxRetries) {
        this.wsReconnecting = false;
        this.frontendLogger.error('websocket', '连接断开，重试次数已耗尽');
        this.notify(false, '与服务器的连接已断开，请刷新页面', 'network');
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
      this.frontendLogger.error('websocket', '连接错误');
      // 不调用 this.ws.close()，浏览器会自动关闭并触发 onclose
    };
  },
};
