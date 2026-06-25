import { api, SETTINGS_TABS, LOG_LEVELS, LEVEL_VALUES } from './constants.js';
import { createFrontendLogger } from './logger.js';
import { actionMethods } from './methods/actions.js';
import { appearanceMethods } from './methods/appearance.js';
import { configMethods } from './methods/config.js';
import { dragMethods } from './methods/drag.js';
import { formatterMethods } from './methods/formatters.js';
import { lifecycleMethods } from './methods/lifecycle.js';
import { profileMethods } from './methods/profiles.js';
import { scheduledTasksMethods } from './methods/scheduled_tasks.js';
import { scriptMethods } from './methods/scripts.js';

import { taskMethods } from './tasks/index.js';
import { uiMethods } from './methods/ui.js';


// 按功能域拆分的数据模块
import { dashboardData } from './data/dashboard.js';
import { configData } from './data/config.js';
import { taskData } from './data/tasks.js';
import { scriptData } from './data/scripts.js';
import { debugData } from './data/debug.js';
import { profileData } from './data/profiles.js';
import { repoData } from './data/repo.js';
import { uninstallData } from './data/uninstall.js';
import { uiData } from './data/ui.js';
import { websocketData } from './data/websocket.js';
import { timerData } from './data/timers.js';
import { statusData } from './data/status.js';
import { appearanceData } from './data/appearance.js';
import { scheduledTasksData } from './data/scheduled_tasks.js';

export const appOptions = {
  data() {
    return {
      // 各功能域数据
      ...dashboardData(),
      ...configData(),
      ...taskData(),
      ...scriptData(),
      ...debugData(),
      ...profileData(),
      ...repoData(),
      ...uninstallData(),
      ...uiData(),
      ...websocketData(),
      ...timerData(),
      ...statusData(),
      ...appearanceData(),
      ...scheduledTasksData(),

      // 全局共享状态
      settingsTabs: SETTINGS_TABS,
      carrierOptions: [
        { value: '', label: '无' },
        { value: '移动', label: '移动' },
        { value: '联通', label: '联通' },
        { value: '电信', label: '电信' },
        { value: '自定义', label: '自定义' },
      ],
      loginActionOptions: [
        { value: 'none', label: '不自动执行' },
        { value: 'monitor', label: '启动后开始监控（推荐）' },
        { value: 'login_once', label: '自动登录，成功后退出' },
      ],
      logSourceOptions: [
        { value: '', label: '全部来源' },
        { value: 'backend', label: 'BAK' },
        { value: 'network', label: 'NET' },
        { value: 'task', label: 'TSK' },
        { value: 'frontend', label: 'FRT' },
        { value: 'debug', label: 'DBG' },
      ],
      scheduledTaskTypeOptions: [
        { value: 'script', label: '自定义脚本' },
        { value: 'browser', label: '浏览器任务' },
      ],
      frontendLogger: createFrontendLogger('INFO'),
      appVersion: 'unknown',
      pythonVersion: '',
      shellCustomMode: false,
    };
  },
  computed: {
    activeTask() {
      return this.tasks.find(t => t.id === this.activeTaskId) || null;
    },
    browserTasks() {
      return this.tasks.filter(t => t.type !== 'script');
    },
    taskOptions() {
      return [
        { value: '', label: '默认任务' },
        ...this.tasks.map(t => ({ value: t.id, label: t.name || t.id })),
      ];
    },
    scriptTargetOptions() {
      return [
        { value: '', label: '请选择...' },
        ...this.scripts.map(s => ({
          value: s.id,
          label: s.name + (s.binary_path ? ' (' + this.getBinaryName(s.binary_path) + ')' : ''),
        })),
      ];
    },
    browserTargetOptions() {
      return [
        { value: '', label: '请选择...' },
        ...this.browserTasks.map(t => ({ value: t.id, label: t.name })),
      ];
    },
    pageTitle() {
      const titles = {
        dashboard: '仪表盘',
        settings: '设置',
        tasks: '任务管理',
        scripts: '自定义脚本',
        scheduled_tasks: '定时任务',
        profiles: '配置方案',
        'profile-edit': this.editingProfile?.id ? '编辑配置方案' : '新建配置方案',
        appearance: '外观设置',
        about: '关于',
      };
      return titles[this.currentPage] || '仪表盘';
    },
    configDirty() {
      return this._lastSavedConfig !== null && JSON.stringify(this.config) !== this._lastSavedConfig;
    },
    filteredLogs() {
      const { level, source, search } = this.logFilter;
      const q = search ? search.toLowerCase() : '';
      const minLevel = LEVEL_VALUES[level] ?? 0;
      return this.logs.filter(l =>
        (!level || (LEVEL_VALUES[l.level] ?? 0) >= minLevel) &&
        (!source || l.source === source) &&
        (!q || l.message.toLowerCase().includes(q))
      );
    },
    networkStatus() {
      if (!this.status.monitoring) return 'idle';
      if (this.status.network_state === 'unknown') return 'checking';
      if (this.status.network_connected === false) return 'disconnected';
      return 'connected';
    },
    networkStatusText() {
      if (!this.status.monitoring) return '已停止';
      return this.status.status_detail || '正在启动监控';
    },
    urlCheckEnabled: {
      get() {
        return !!(this.config.monitor.url_check_urls && this.config.monitor.url_check_urls.length);
      },
      set(val) {
        if (val) {
          if (!this.config.monitor.url_check_urls.length) {
            this.config.monitor.url_check_urls = this.defaultUrlCheckUrls.length
              ? [...this.defaultUrlCheckUrls]
              : [''];
          }
        } else {
          this.config.monitor.url_check_urls = [];
        }
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
    shellPathMode: {
      get() {
        if (this.shellCustomMode) return '__custom__';
        if (!this.config.shell_path) return '';
        if (this.availableShells.some(s => s.path === this.config.shell_path)) return this.config.shell_path;
        return '__custom__';
      },
      set(val) {
        this.shellCustomMode = (val === '__custom__');
        if (val !== '__custom__') this.config.shell_path = val;
      },
    },
    shellPathOptions() {
      return [
        { value: '', label: '自动检测（推荐）' },
        ...this.availableShells.map(s => ({ value: s.path, label: s.name + ' - ' + s.description })),
        { value: '__custom__', label: '自定义路径...' },
      ];
    },
    logLevelOptions() {
      return LOG_LEVELS;
    },
    autostartModeOptions() {
      return [
        { value: true, label: '轻量模式（推荐）' },
        { value: false, label: '完整模式' },
      ];
    },
    startupActionHint() {
      const hints = {
        none: '程序启动后不自动执行任何操作，需手动启动监控',
        monitor: '程序启动后自动开始网络监控，断网时自动重连',
        login_once: '启动后尝试登录一次，成功后自动退出。适用于开机自启动场景',
      };
      return hints[this.config.startup_action] || hints.none;
    },
    startupActionLabel() {
      const opt = this.loginActionOptions.find(o => o.value === this.config.startup_action);
      return opt ? opt.label.replace('（推荐）', '') : '不自动执行';
    },
    binaryOptions() {
      return [
        { value: '', label: '选择执行程序...' },
        ...this.availableBinaries.map(b => ({ value: b.path, label: b.name })),
        { value: '__custom_python__', label: 'Python (自定义环境)' },
        { value: '__custom__', label: '自定义路径...' },
      ];
    },
  },
  watch: {
    appearance: {
      handler() {
        // 防抖：避免频繁操作 DOM 导致卡顿
        if (this._appearanceTimer) clearTimeout(this._appearanceTimer);
        this._appearanceTimer = setTimeout(() => {
          this.applyAppearance();
          localStorage.setItem('appearance', JSON.stringify(this.appearance));
        }, 100);
      },
      deep: true,
    },
    currentPage(newPage) {
      if (this._dangerResolve) {
        this.closeModal();
        this._dangerResolve(false);
        this._dangerResolve = null;
        this.dangerConfirm = null;
        this.dangerCountdown = 0;
        if (this._dangerTimer) {
          clearInterval(this._dangerTimer);
          this._dangerTimer = null;
        }
      }
      if (newPage === 'dashboard' && this.autoScroll) {
        this.$nextTick(() => {
          const logViewer = this.$refs?.logViewer;
          if (logViewer) logViewer.scrollTop = logViewer.scrollHeight;
        });
      }
    },
  },
  mounted() {
    document.getElementById('app').style.display = '';
    this.$api = api;
    this.init();
    // 应用保存的外观设置
    this.applyAppearance();
  },
  beforeUnmount() {
    this._wsDestroyed = true;
    if (this._wsRetryTimer) clearTimeout(this._wsRetryTimer);
    if (this._dangerTimer) clearInterval(this._dangerTimer);
    if (this._repoDisclaimerTimer) clearInterval(this._repoDisclaimerTimer);
    if (this._toastTimer) clearTimeout(this._toastTimer);
    if (this._toastLeavingTimer) clearTimeout(this._toastLeavingTimer);
    if (this._appearanceTimer) clearTimeout(this._appearanceTimer);
    if (this._saveConfigTimer) clearTimeout(this._saveConfigTimer);
    if (this._saveAbortController) this._saveAbortController.abort();
    if (this._logScrollRaf) cancelAnimationFrame(this._logScrollRaf);
    document.removeEventListener('mousedown', this._onNotifyOutsideClick);
    this.timers.forEach((t) => clearInterval(t));
    if (this._visibilityHandler) {
      document.removeEventListener('visibilitychange', this._visibilityHandler);
    }
    if (this.ws) this.ws.close();
  },
  methods: {
    ...uiMethods,
    ...formatterMethods,
    ...lifecycleMethods,
    ...configMethods,
    ...actionMethods,
    ...taskMethods,
    ...scriptMethods,
    ...scheduledTasksMethods,
    ...profileMethods,
    ...appearanceMethods,

    ...dragMethods,
  },
};
