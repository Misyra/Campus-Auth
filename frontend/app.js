const { createApp } = Vue;

const api = axios.create({
  timeout: 10000,
});

const LOG_LEVELS = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
};

function createFrontendLogger(initialLevel = 'INFO') {
  let currentLevel = String(initialLevel || 'INFO').toUpperCase();

  const shouldLog = (level) => {
    const left = LOG_LEVELS[String(level || '').toUpperCase()] || LOG_LEVELS.INFO;
    const right = LOG_LEVELS[currentLevel] || LOG_LEVELS.INFO;
    return left >= right;
  };

  const format = (level, scope, message, meta) => {
    const stamp = new Date().toISOString();
    return [stamp, level, 'FRONTEND', scope, message, meta || ''];
  };

  return {
    setLevel(level) {
      const next = String(level || '').toUpperCase();
      currentLevel = LOG_LEVELS[next] ? next : 'INFO';
      console.info(...format('INFO', 'logger', `frontend log level => ${currentLevel}`));
    },
    debug(scope, message, meta) {
      if (shouldLog('DEBUG')) console.debug(...format('DEBUG', scope, message, meta));
    },
    info(scope, message, meta) {
      if (shouldLog('INFO')) console.info(...format('INFO', scope, message, meta));
    },
    warn(scope, message, meta) {
      if (shouldLog('WARNING')) console.warn(...format('WARNING', scope, message, meta));
    },
    error(scope, message, meta) {
      if (shouldLog('ERROR')) console.error(...format('ERROR', scope, message, meta));
    },
  };
}

createApp({
  data() {
    return {
      currentPage: 'dashboard',
      ws: null,
      showWizard: false,
      wizardStep: 1,
      config: {
        username: "",
        password: "",
        carrier: "无",
        check_interval_minutes: 5,
        auto_start: false,
        headless: false,
        pause_enabled: true,
        pause_start_hour: 0,
        pause_end_hour: 6,
        network_targets: "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443",
        backend_log_level: "INFO",
        frontend_log_level: "INFO",
        access_log: false,
        minimize_to_tray: false,
      },
      frontendLogger: createFrontendLogger("INFO"),
      status: {
        monitoring: false,
        network_check_count: 0,
        login_attempt_count: 0,
        last_check_time: null,
        runtime_seconds: 0,
      },
      logs: [],
      autostart: {
        platform: "-",
        enabled: false,
        method: "-",
        location: "",
      },
      busy: {
        save: false,
        monitor: false,
        action: false,
        autostart: false,
      },
      toast: {
        success: true,
        message: "",
      },
      timers: [],
      tasks: [],
      activeTaskId: "default",
      editingTask: null,
    };
  },
  computed: {
    pageTitle() {
      const titles = {
        dashboard: '仪表盘',
        settings: '设置',
        tasks: '任务管理',
        about: '关于',
      };
      return titles[this.currentPage] || '仪表盘';
    },
    canProceed() {
      if (this.wizardStep === 1) {
        return this.config.username && this.config.password;
      }
      return true;
    },
  },
  mounted() {
    this.init();
  },
  beforeUnmount() {
    this.timers.forEach((t) => clearInterval(t));
    if (this.ws) {
      this.ws.close();
    }
  },
  methods: {
    setFrontendLogLevel(level) {
      this.frontendLogger.setLevel(level);
    },
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
        const { data } = await api.get("/api/init-status");
        this.showWizard = !data.initialized;
      } catch {
        this.showWizard = false;
      }
    },
    nextWizardStep() {
      if (this.wizardStep < 4) {
        this.wizardStep++;
      }
    },
    skipWizard() {
      this.showWizard = false;
    },
    async finishWizard() {
      this.busy.save = true;
      try {
        const { data } = await api.put("/api/config", this.config);
        if (data.success) {
          this.showWizard = false;
          this.notify(true, "配置完成！");
        } else {
          this.notify(false, data.message);
        }
      } catch (error) {
        const msg = error?.response?.data?.detail || "保存失败";
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
          this.notify(false, "与服务器的连接已断开，请刷新页面");
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
    notify(success, message) {
      this.toast = { success, message };
      setTimeout(() => {
        this.toast.message = "";
      }, 3000);
    },
    formatDuration(totalSeconds) {
      const sec = Number(totalSeconds || 0);
      const h = String(Math.floor(sec / 3600)).padStart(2, "0");
      const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
      const s = String(sec % 60).padStart(2, "0");
      return `${h}:${m}:${s}`;
    },
    formatTime(isoString) {
      if (!isoString) return '-';
      return isoString.replace('T', ' ').substring(0, 19);
    },
    formatLogTime(timestamp) {
      if (!timestamp) return '';
      return timestamp.substring(11, 19);
    },
    formatLogMeta(item) {
      const level = String(item?.level || 'INFO').toUpperCase();
      const source = String(item?.source || 'monitor');
      return `[${level}] [${source}]`;
    },
    extractScreenshotUrl(message) {
      const text = String(message || '');
      const match = text.match(/截图[:：]\s*(\/debug\/[^\s]+)/i);
      return match ? match[1] : '';
    },
    stripScreenshotHint(message) {
      const text = String(message || '');
      return text.replace(/\s*截图[:：]\s*\/debug\/[^\s]+/gi, '').trim();
    },
    getLogClass(message) {
      const text = this.stripScreenshotHint(message);
      if (text.includes('错误') || text.includes('✗') || text.includes('EXCEPTION')) return 'error';
      if (text.includes('异常') || text.includes('警告') || text.includes('失败')) return 'warning';
      if (text.includes('成功') || text.includes('✓')) return 'success';
      return '';
    },
    async fetchConfig() {
      try {
        const { data } = await api.get("/api/config");
        this.config = data;
        this.setFrontendLogLevel(this.config.frontend_log_level || 'INFO');
        this.frontendLogger.info('config', 'config loaded');
      } catch (error) {
        this.frontendLogger.error('config', 'failed to fetch config', error);
      }
    },
    async fetchStatus() {
      try {
        const { data } = await api.get("/api/status");
        this.status = data;
        this.fetchStatusFailCount = 0;
      } catch (error) {
        this.fetchStatusFailCount = (this.fetchStatusFailCount || 0) + 1;
        this.frontendLogger.warn('status', 'fetch status failed', error);
        if (this.fetchStatusFailCount >= 3) {
          this.notify(false, "无法连接到服务器，请检查后端是否已关闭");
          this.fetchStatusFailCount = 0;
        }
      }
    },
    async fetchLogs() {
      try {
        const { data } = await api.get("/api/logs", { params: { limit: 250 } });
        this.logs = data;
      } catch (error) {
        this.frontendLogger.error('logs', 'failed to fetch logs', error);
      }
    },
    async fetchAutostart() {
      try {
        const { data } = await api.get("/api/autostart/status");
        this.autostart = data;
      } catch (error) {
        this.frontendLogger.warn('autostart', 'fetch autostart failed', error);
        if (error?.response?.status === 404) {
          this.autostart = {
            platform: "-",
            enabled: false,
            method: "当前后端不支持",
            location: "",
          };
        }
      }
    },
    async saveConfig() {
      this.busy.save = true;
      try {
        const { data } = await api.put("/api/config", this.config);
        this.setFrontendLogLevel(this.config.frontend_log_level || 'INFO');
        this.notify(data.success, data.message);
      } catch (error) {
        const msg = error?.response?.data?.detail || "保存失败";
        this.frontendLogger.error('config', 'save config failed', error);
        this.notify(false, msg);
      } finally {
        this.busy.save = false;
      }
    },
    async toggleMonitor() {
      this.busy.monitor = true;
      try {
        const url = this.status.monitoring ? "/api/monitor/stop" : "/api/monitor/start";
        this.frontendLogger.info('monitor', `request ${url}`);
        const { data } = await api.post(url);
        this.notify(data.success, data.message);
        await this.fetchStatus();
      } catch {
        this.frontendLogger.error('monitor', 'toggle monitor failed');
        this.notify(false, "操作失败");
      } finally {
        this.busy.monitor = false;
      }
    },
    async manualLogin() {
      this.busy.action = true;
      try {
        this.frontendLogger.info('action', 'manual login requested');
        const { data } = await api.post("/api/actions/login");
        this.notify(data.success, data.message);
      } catch {
        this.frontendLogger.error('action', 'manual login failed');
        this.notify(false, "手动登录失败");
      } finally {
        this.busy.action = false;
      }
    },
    async testNetwork() {
      this.busy.action = true;
      try {
        this.frontendLogger.info('action', 'network test requested');
        const { data } = await api.post("/api/actions/test-network");
        this.notify(data.success, data.message);
      } catch {
        this.frontendLogger.error('action', 'network test failed');
        this.notify(false, "网络测试失败");
      } finally {
        this.busy.action = false;
      }
    },
    async enableAutostart() {
      this.busy.autostart = true;
      try {
        const { data } = await api.post("/api/autostart/enable");
        this.notify(data.success, data.message);
      } catch (error) {
        if (error?.response?.status === 404) {
          this.notify(false, "当前后端版本不支持开机自启动，请重启后端");
        } else {
          this.notify(false, "启用自启动失败");
        }
      } finally {
        await this.fetchAutostart();
        this.busy.autostart = false;
      }
    },
    async disableAutostart() {
      this.busy.autostart = true;
      try {
        const { data } = await api.post("/api/autostart/disable");
        this.notify(data.success, data.message);
      } catch (error) {
        if (error?.response?.status === 404) {
          this.notify(false, "当前后端版本不支持开机自启动，请重启后端");
        } else {
          this.notify(false, "关闭自启动失败");
        }
      } finally {
        await this.fetchAutostart();
        this.busy.autostart = false;
      }
    },
    async fetchTasks() {
      try {
        const { data } = await api.get("/api/tasks");
        this.tasks = data;
      } catch (error) {
        this.frontendLogger.error('tasks', 'failed to fetch tasks', error);
      }
    },
    async fetchActiveTask() {
      try {
        const { data } = await api.get("/api/tasks/active");
        this.activeTaskId = data.task_id;
      } catch (error) {
        this.frontendLogger.error('tasks', 'failed to fetch active task', error);
      }
    },
    async setActiveTask(taskId) {
      try {
        this.frontendLogger.info('tasks', `set active task: ${taskId}`);
        const { data } = await api.post(`/api/tasks/active/${taskId}`);
        if (data.success) {
          this.activeTaskId = taskId;
          this.notify(true, "活动任务已设置");
        } else {
          this.notify(false, data.message);
        }
      } catch (error) {
        this.notify(false, "设置活动任务失败");
      }
    },
    async showTaskEditor(taskId) {
      if (taskId) {
        try {
          const { data } = await api.get(`/api/tasks/${taskId}`);
          this.editingTask = {
            id: taskId,
            name: data.name,
            description: data.description,
            url: data.url,
            json: JSON.stringify(data, null, 2),
          };
        } catch (error) {
          this.notify(false, "加载任务失败");
        }
      } else {
        this.editingTask = {
          id: "",
          name: "",
          description: "",
          url: "http://172.29.0.2",
          json: "",
        };
      }
    },
    async loadTemplate(templateId) {
      try {
        const { data } = await api.get(`/api/tasks/${templateId}`);
        if (this.editingTask) {
          this.editingTask.json = JSON.stringify(data, null, 2);
        }
      } catch (error) {
        this.notify(false, "加载模板失败");
      }
    },
    async saveTask() {
      if (!this.editingTask || !this.editingTask.id) {
        this.notify(false, "请输入任务ID");
        return;
      }
      try {
        this.frontendLogger.info('tasks', `save task: ${this.editingTask.id}`);
        const config = JSON.parse(this.editingTask.json);
        config.name = this.editingTask.name || config.name;
        config.description = this.editingTask.description || config.description;
        config.url = this.editingTask.url || config.url;

        
        const { data } = await api.put(`/api/tasks/${this.editingTask.id}`, config);
        if (data.success) {
          this.notify(true, "任务保存成功");
          this.editingTask = null;
          await this.fetchTasks();
        } else {
          this.notify(false, data.message);
        }
      } catch (error) {
        this.frontendLogger.error('tasks', 'save task failed', error);
        this.notify(false, error.message || "保存失败");
      }
    },
    async deleteTask(taskId) {
      if (!confirm("确定要删除这个任务吗？")) return;
      try {
        const { data } = await api.delete(`/api/tasks/${taskId}`);
        if (data.success) {
          this.notify(true, "任务删除成功");
          await this.fetchTasks();
          if (this.activeTaskId === taskId) {
            this.activeTaskId = "default";
          }
        } else {
          this.notify(false, data.message);
        }
      } catch (error) {
        this.notify(false, "删除任务失败");
      }
    },
    async quitApp() {
      if (!confirm("确定要退出应用吗？")) return;
      try {
        this.busy.monitor = true;
        await api.post("/api/shutdown");
        this.notify(true, "应用正在关闭...");
        setTimeout(() => {
          window.close();
        }, 1500);
      } catch (error) {
        this.notify(false, "退出失败，请手动关闭窗口");
        window.close();
      } finally {
        this.busy.monitor = false;
      }
    },
  },
}).mount("#app");
