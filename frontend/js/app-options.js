import { api, DEFAULT_CONFIG, SETTINGS_TABS } from './constants.js';
import { createFrontendLogger } from './logger.js';
import { actionMethods } from './methods/actions.js';
import { autostartMethods } from './methods/autostart.js';
import { configMethods } from './methods/config.js';
import { formatterMethods } from './methods/formatters.js';
import { lifecycleMethods } from './methods/lifecycle.js';
import { profileMethods } from './methods/profiles.js';
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
      defaultPortalUrls: DEFAULT_CONFIG.portal_check_urls,
      frontendLogger: createFrontendLogger('INFO'),
      isLoading: true,
      status: {
        monitoring: false,
        network_check_count: 0,
        login_attempt_count: 0,
        last_check_time: null,
        runtime_seconds: 0,
        network_connected: false,
        status_detail: '已停止',
        network_state: 'unknown',
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
        detect: false,
        editorDetect: false,
        debug: false,
        backup: false,
        uninstall: false,
      },
      backups: [],
      toast: {
        success: true,
        message: '',
        leaving: false,
      },
      timers: [],
      _wsDestroyed: false,
      _wsRetryTimer: null,
      _dangerTimer: null,
      _repoDisclaimerTimer: null,
      _toastTimer: null,
      newLogCount: 0,
      fetchStatusFailCount: 0,
      wsReconnecting: false,
      wsRetryCount: 0,
      wsMaxRetries: 5,
      notifications: [],
      unreadNotifications: 0,
      showNotifications: false,
      logFilter: { level: '', search: '' },
      autoScroll: true,
      tasks: [],
      activeTaskId: 'default',
      editingTask: null,
      jsonError: '',
      savedConfigSnapshot: '',
      dangerConfirm: null,
      dangerCountdown: 0,
      debugSession: {
        running: false,
        task_id: null,
        current_step: 0,
        total_steps: 0,
        steps: [],
        results: [],
        screenshot_url: null,
      },
      debugLoading: false,
      pureMode: false,
      profiles: {},
      activeProfileId: 'default',
      autoSwitch: true,
      editingProfile: null,
      detectResult: null,
      editorDetectResult: null,
      fullscreenSrc: '',
      updateInfo: null,
      updateLoading: false,
      repoImport: {
        visible: false,
        url: 'https://github.com/Misyra/campus-auth-tasks/blob/master/index.json',
        source: 'github',
        loading: false,
        error: '',
        tasks: [],
        searchQuery: '',
        disclaimer: null,
        disclaimerCountdown: 0,
      },
      uninstall: {
        visible: false,
        scanning: false,
        items: [],
        results: null,
      },
    };
  },
  computed: {
    activeTask() {
      return this.tasks.find(t => t.id === this.activeTaskId) || null;
    },
    pageTitle() {
      const titles = {
        dashboard: '仪表盘',
        settings: '设置',
        tasks: '任务管理',
        profiles: '配置方案',
        'profile-edit': this.editingProfile?.id ? '编辑方案' : '新建方案',
        about: '关于',
      };
      return titles[this.currentPage] || '仪表盘';
    },
    canProceed() {
      if (this.wizardStep === 1) {
        return this.config.username && this.config.password && this.config.auth_url;
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
      // 首次检测中（network_state 为 unknown）显示为检测中状态
      if (this.status.network_state === 'unknown') return 'checking';
      if (this.status.network_connected === false) return 'disconnected';
      return 'connected';
    },
    networkStatusText() {
      if (!this.status.monitoring) return '已停止';
      return this.status.status_detail || '正在启动监控';
    },
    portalCheckEnabled: {
      get() {
        return !!(this.config.portal_check_urls && this.config.portal_check_urls.trim());
      },
      set(val) {
        this.config.portal_check_urls = val ? (this.config.portal_check_urls || this.defaultPortalUrls) : '';
      },
    },
    filteredRepoTasks() {
      const q = this.repoImport.searchQuery.trim().toLowerCase();
      if (!q) return this.repoImport.tasks;
      return this.repoImport.tasks.filter(t => {
        const name = (t.name || '').toLowerCase();
        const desc = (t.description || '').toLowerCase();
        const tags = (t.tags || []).join(' ').toLowerCase();
        const author = (t.author || '').toLowerCase();
        return name.includes(q) || desc.includes(q) || tags.includes(q) || author.includes(q);
      });
    },
    uninstallCheckedCount() {
      return this.uninstall.items.filter(it => it.exists && it.checked).length;
    },
  },
  watch: {
    currentPage() {
      // 页面切换时清理待处理的危险确认对话框，避免 Promise 永久挂起
      if (this.dangerConfirm) {
        this.dangerConfirm.resolve(false);
        this.dangerConfirm = null;
        this.dangerCountdown = 0;
        if (this._dangerTimer) {
          clearInterval(this._dangerTimer);
          this._dangerTimer = null;
        }
      }
    },
  },
  mounted() {
    document.getElementById('app').style.display = '';
    this.$api = api;
    this.init();
  },
  beforeUnmount() {
    this._wsDestroyed = true;
    if (this._wsRetryTimer) {
      clearTimeout(this._wsRetryTimer);
    }
    if (this._dangerTimer) {
      clearInterval(this._dangerTimer);
    }
    if (this._repoDisclaimerTimer) {
      clearInterval(this._repoDisclaimerTimer);
    }
    if (this._toastTimer) {
      clearTimeout(this._toastTimer);
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
    ...profileMethods,
  },
};
