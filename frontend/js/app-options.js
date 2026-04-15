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
      status: {
        monitoring: false,
        network_check_count: 0,
        login_attempt_count: 0,
        last_check_time: null,
        runtime_seconds: 0,
      },
      logs: [],
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
      },
      timers: [],
      tasks: [],
      activeTaskId: 'default',
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
    this.$api = api;
    this.init();
  },
  beforeUnmount() {
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
