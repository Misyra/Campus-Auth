import { LIMITS, TIMING } from '../constants.js';
import { extractApiError } from './utils.js';

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
      this.fetchLoginHistory(),
      this.loadScheduledTasks(),
      this.fetchShells(),
      this.fetchOcrStatus(),
      this.fetchLogLevels(),
      this.fetchBrowsers(),
    ]);
    const rejectedCount = initResults.filter(r => r.status === 'rejected').length;
    if (rejectedCount > 0) {
      this.frontendLogger.warn('app.init', `部分初始化失败: ${rejectedCount} 项`);
      this.notify(false, `⚠ 部分数据加载失败（${rejectedCount} 项），请刷新重试`);
    }
    this._initErrorCount = 0;
    this.isLoading = false;
    this.connectWebSocket();
    this._setupVisibilityChange();
    this.autoCheckUpdateOnStartup();
    this.timers.push(setInterval(() => {
        if (this._statusPolling) return;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
        this._statusPolling = true;
        this.fetchStatus()
          .catch(err => this.frontendLogger.warn('status_poll', err))
          .finally(() => { this._statusPolling = false; });
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
      const data = await this.$apiService.system.checkUpdate();
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
      const data = await this.$apiService.system.initStatus();
      this.showWizard = !data.agreed;
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
      const data = await this.$apiService.system.health();
      if (data?.version) {
        this.appVersion = data.version;
        if (data.python_version) this.pythonVersion = data.python_version;
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
      const data = await this.$apiService.system.checkUpdate();
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
      const data = await this.$apiService.system.agree();
      if (data.success) {
        this.showWizard = false;
        this.agreedToTerms = false;
        this.frontendLogger.info('lifecycle', '已同意协议');
      } else {
        this.frontendLogger.warn('lifecycle', '同意协议失败: ' + data.message);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      const msg = extractApiError(error, '操作失败');
      this.frontendLogger.error('lifecycle', '同意协议异常: ' + msg, error);
      this.toastOnly(false, msg);
    } finally {
      this.busy.save = false;
    }
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
      oldWs.onopen = null;
      oldWs.onmessage = null;
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
          if (typeof data.data === 'object' && data.data !== null) {
            this.status = data.data;
          } else {
            this.frontendLogger.warn('websocket', 'status 消息数据非对象: ' + typeof data.data);
          }
        } else if (data.type === 'log') {
          if (typeof data.data === 'object' && data.data !== null) {
            this._appendLogs([data.data]);
          } else {
            this.frontendLogger.warn('websocket', 'log 消息数据非对象: ' + typeof data.data);
          }
        } else if (data.type === 'pong') {
          // 心跳响应，无需处理
        } else {
          this.frontendLogger.warn('websocket', '未知消息类型: ' + data.type);
        }
      } catch (e) {
        this.frontendLogger.error('websocket', '消息解析错误', e);
      }
    };

    this.ws.onclose = () => {
      this.frontendLogger.setWebSocket(null);
      this.frontendLogger.warn('websocket', '连接已关闭');
      // 关闭时清理 ping 定时器，避免无意义的发送尝试
      if (this._wsPingTimer) {
        clearInterval(this._wsPingTimer);
        this.timers = this.timers.filter(t => t !== this._wsPingTimer);
        this._wsPingTimer = null;
      }
      if (this._wsDestroyed) return;
      if (this.wsRetryCount >= this.wsMaxRetries) {
        this.wsReconnecting = false;
        this.frontendLogger.error('websocket', '连接断开，重试次数已耗尽');
        this.notify(false, '与服务器的连接已断开，请刷新页面', 'network');
        return;
      }
      this.wsReconnecting = true;
      const delay = Math.min(TIMING.WS_BACKOFF_BASE * Math.pow(2, this.wsRetryCount), TIMING.WS_BACKOFF_MAX);
      this.wsRetryCount++;
      this._wsRetryTimer = setTimeout(() => {
        if (!this._wsDestroyed) this.connectWebSocket();
      }, delay);
    };

    this.ws.onerror = () => {
      this.frontendLogger.error('websocket', '连接错误');
      // 不调用 this.ws.close()，浏览器会自动关闭并触发 onclose
    };

    // 应用层 ping/pong，防止校园网代理 60s 无流量切断连接
    // 清理旧的 ping timer，防止重连时累积
    if (this._wsPingTimer) {
      clearInterval(this._wsPingTimer);
      this.timers = this.timers.filter(t => t !== this._wsPingTimer);
    }
    this._wsPingTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, TIMING.WS_PING_INTERVAL);
    this.timers.push(this._wsPingTimer);
  },
  _setupVisibilityChange() {
    // 监听页面可见性变化，切回页面时主动重连
    // 已知限制：无防抖，快速 Alt+Tab 会绕过 wsMaxRetries 限制。
    // 实际无影响：localhost 通信开销极小，connectWebSocket 会先清理旧连接再创建新连接，
    // 不会堆积。重置 wsRetryCount 是故意设计 — 页面恢复可见时给新的重连机会。
    this._visibilityHandler = () => {
      if (document.visibilityState === 'visible' && this.ws?.readyState !== WebSocket.OPEN) {
        this.wsRetryCount = 0;
        this.frontendLogger.info('websocket', '页面恢复可见，尝试重连');
        this.connectWebSocket();
      }
    };
    document.addEventListener('visibilitychange', this._visibilityHandler);
  },
  async fetchStatus() {
    try {
      const data = await this.$apiService.monitor.fetchStatus();
      this.status = data;
      if (this.fetchStatusFailCount > 0) {
        this.fetchStatusFailCount = 0;
        this.notify(true, '已重新连接到服务器', 'network');
      }
    } catch (error) {
      this.fetchStatusFailCount = (this.fetchStatusFailCount || 0) + 1;
      this.frontendLogger.warn('status', '获取状态失败', error);
      if (this.fetchStatusFailCount === 1) {
        this.notify(false, '无法连接到服务器，请检查后端是否已关闭', 'network');
      }
    }
  },
  async fetchLogs() {
    try {
      const data = await this.$apiService.system.fetchLogs(LIMITS.LOG_MAX_ENTRIES);
      this.logs = data;
      this.$nextTick(() => this.scrollToBottom());
    } catch (error) {
      this.frontendLogger.error('logs', '获取日志失败', error);
      this._recordInitError('加载日志失败');
    }
  },
};
