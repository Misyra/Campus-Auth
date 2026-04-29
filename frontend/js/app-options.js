import { api, DEFAULT_CONFIG, SETTINGS_TABS } from './constants.js';
import { createFrontendLogger } from './logger.js';
import { actionMethods } from './methods/actions.js';
import { autostartMethods } from './methods/autostart.js';
import { configMethods } from './methods/config.js';
import { formatterMethods } from './methods/formatters.js';
import { lifecycleMethods } from './methods/lifecycle.js';
import { statusMethods } from './methods/status.js';
import { taskMethods } from './methods/tasks.js';
import { uiMethods } from './methods/ui.js';

export const appOptions = {
  data() {
    return {
      currentPage: 'dashboard',
      ws: null,
      showWizard: false,
      wizardStep: 1,
      currentSettingsTab: 'account',
      settingsTabs: SETTINGS_TABS,
      config: { ...DEFAULT_CONFIG },
      frontendLogger: createFrontendLogger('INFO'),
      isLoading: true,
      status: {
        monitoring: false,
        network_check_count: 0,
        login_attempt_count: 0,
        last_check_time: null,
        runtime_seconds: 0,
      },
      logs: [],
      appVersion: 'unknown',
      autostart: {
        platform: '-',
        enabled: false,
        method: '-',
        location: '',
      },
      busy: {
        save: false,
        monitor: false,
        action: false,
        autostart: false,
      },
      toast: {
        success: true,
        message: '',
        leaving: false,
      },
      timers: [],
      _wsDestroyed: false,
      _wsRetryTimer: null,
      _newLogCount: 0,
      wsReconnecting: false,
      wsRetryAttempt: 0,
      notifications: [],
      unreadNotifications: 0,
      showNotifications: false,
      logFilter: { level: '', search: '' },
      tasks: [],
      activeTaskId: 'default',
      editingTask: null,
      jsonError: '',
      savedConfigSnapshot: '',
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
      if (this.wizardStep === 2 && this.config.carrier === '自定义') {
        return !!(this.config.carrier_custom && this.config.carrier_custom.trim());
      }
      return true;
    },
    configDirty() {
      if (!this.savedConfigSnapshot) return false;
      return JSON.stringify(this.config) !== this.savedConfigSnapshot;
    },
    filteredLogs() {
      let result = this.logs;
      if (this.logFilter.level) {
        result = result.filter(l => l.level === this.logFilter.level);
      }
      if (this.logFilter.search) {
        const q = this.logFilter.search.toLowerCase();
        result = result.filter(l => l.message.toLowerCase().includes(q));
      }
      return result;
    },
    networkStatus() {
      if (!this.status.monitoring) return 'idle';
      if (this.status.login_attempt_count > 0) return 'disconnected';
      return 'connected';
    },
  },
  mounted() {
    this.$api = api;
    this.init();
  },
  beforeUnmount() {
    this._wsDestroyed = true;
    if (this._wsRetryTimer) {
      clearTimeout(this._wsRetryTimer);
    }
    this.timers.forEach((t) => clearInterval(t));
    if (this.ws) {
      this.ws.close();
    }
  },
  methods: {
    ...uiMethods,
    ...formatterMethods,
    ...lifecycleMethods,
    ...configMethods,
    ...statusMethods,
    ...actionMethods,
    ...autostartMethods,
    ...taskMethods,
  },
};
