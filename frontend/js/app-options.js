import { api, SETTINGS_TABS } from './constants.js';
import { createFrontendLogger } from './logger.js';
import { actionMethods } from './methods/actions.js';
import { appearanceMethods } from './methods/appearance.js';
import { autostartMethods } from './methods/autostart.js';
import { configMethods } from './methods/config.js';
import { dragMethods } from './methods/drag.js';
import { formatterMethods } from './methods/formatters.js';
import { lifecycleMethods } from './methods/lifecycle.js';
import { profileMethods } from './methods/profiles.js';
import { scheduledTasksMethods } from './methods/scheduled_tasks.js';
import { scriptMethods } from './methods/scripts.js';

import { statusMethods } from './methods/status.js';
import { taskMethods } from './tasks/index.js';
import { uiMethods } from './methods/ui.js';
import { logFileMethods } from './methods/logfiles.js';

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
import { logFileData } from './data/logfiles.js';
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
      ...logFileData(),
      ...scheduledTasksData(),

      // 全局共享状态
      settingsTabs: SETTINGS_TABS,
      carrierOptions: [
        { value: '无', label: '无' },
        { value: '移动', label: '移动' },
        { value: '联通', label: '联通' },
        { value: '电信', label: '电信' },
        { value: '自定义', label: '自定义' },
      ],
      loginActionOptions: [
        { value: false, label: '保持监控（推荐）' },
        { value: true, label: '退出程序' },
      ],
      logLevelOptions: [
        { value: '', label: '全部级别' },
        { value: 'INFO', label: 'INFO' },
        { value: 'WARNING', label: 'WARNING' },
        { value: 'ERROR', label: 'ERROR' },
        { value: 'CRITICAL', label: 'CRITICAL' },
        { value: 'DEBUG', label: 'DEBUG' },
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
    logFileOptions() {
      return this.currentLogFiles.map(f => ({
        value: f.name,
        label: f.name + ' (' + this.formatFileSize(f.size) + ')',
      }));
    },
    pageTitle() {
      const titles = {
        dashboard: '仪表盘',
        settings: '设置',
        tasks: '任务管理',
        scripts: '自定义脚本',
        scheduled_tasks: '定时任务',
        profiles: '配置方案',
        'profile-edit': this.editingProfile?.id ? '编辑方案' : '新建方案',
        appearance: '外观设置',
        logs: '日志查看器',
        about: '关于',
      };
      return titles[this.currentPage] || '仪表盘';
    },
    canProceed() {
      if (this.wizardStep === 1) {
        return this.agreedToTerms;
      }
      if (this.wizardStep === 2) {
        if (this.config.carrier === '自定义') {
          return this.config.username && this.config.password && this.config.auth_url && !!(this.config.carrier_custom && this.config.carrier_custom.trim());
        }
        return this.config.username && this.config.password && this.config.auth_url;
      }
      return true;
    },
    configDirty() {
      return this._configDirty;
    },
    filteredLogs() {
      const { level, source, search } = this.logFilter;
      const q = search ? search.toLowerCase() : '';
      return this.logs.filter(l =>
        (!level || l.level === level) &&
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
        return !!(this.config.url_check_urls && this.config.url_check_urls.trim());
      },
      set(val) {
        this.config.url_check_urls = val ? (this.config.url_check_urls || this.defaultUrlCheckUrls) : '';
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
    currentLogFiles() {
      const group = this.logFileGroups.find(g => g.date === this.logViewer.date);
      return group?.files || [];
    },
    shellPathMode: {
      get() {
        if (!this.config.shell_path) return this._shellCustomMode ? '__custom__' : '';
        if (this.availableShells.some(s => s.path === this.config.shell_path)) return this.config.shell_path;
        return '__custom__';
      },
      set(val) {
        this._shellCustomMode = (val === '__custom__');
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
    config: {
      handler() {
        if (this._configDirtyTimer) clearTimeout(this._configDirtyTimer);
        this._configDirtyTimer = setTimeout(() => {
          if (!this.savedConfigSnapshot) {
            this._configDirty = false;
            return;
          }
          this._configDirty = JSON.stringify(this.config) !== this.savedConfigSnapshot;
        }, 150);
      },
      deep: true,
    },
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
        this._releaseFocusTrap();
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
      if (newPage === 'logs' && !this.logFileGroups.length) {
        this.fetchLogFileGroups();
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
    if (this._logScrollRaf) cancelAnimationFrame(this._logScrollRaf);
    if (this._configDirtyTimer) clearTimeout(this._configDirtyTimer);
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
    ...statusMethods,
    ...actionMethods,
    ...autostartMethods,
    ...taskMethods,
    ...scriptMethods,
    ...scheduledTasksMethods,
    ...profileMethods,
    ...appearanceMethods,

    ...dragMethods,
    ...logFileMethods,
  },
};
