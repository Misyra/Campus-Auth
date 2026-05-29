import { api, SETTINGS_TABS } from './constants.js';
import { createFrontendLogger } from './logger.js';
import { actionMethods } from './methods/actions.js';
import { autostartMethods } from './methods/autostart.js';
import { configMethods } from './methods/config.js';
import { formatterMethods } from './methods/formatters.js';
import { lifecycleMethods } from './methods/lifecycle.js';
import { profileMethods } from './methods/profiles.js';
import { scriptMethods } from './methods/scripts.js';
import { statusMethods } from './methods/status.js';
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

      // 全局共享状态
      settingsTabs: SETTINGS_TABS,
      frontendLogger: createFrontendLogger('INFO'),
      appVersion: 'unknown',
    };
  },
  computed: {
    activeTask() {
      return this.tasks.find(t => t.id === this.activeTaskId) || null;
    },
    browserTasks() {
      return this.tasks.filter(t => t.type !== 'script');
    },
    pageTitle() {
      const titles = {
        dashboard: '仪表盘',
        settings: '设置',
        tasks: '任务管理',
        scripts: 'Python 脚本',
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
      return this._configDirty;
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
    config: {
      handler() {
        if (!this.savedConfigSnapshot) {
          this._configDirty = false;
          return;
        }
        this._configDirty = JSON.stringify(this.config) !== this.savedConfigSnapshot;
      },
      deep: true,
    },
    currentPage(newPage) {
      if (this.dangerConfirm) {
        this.dangerConfirm.resolve(false);
        this.dangerConfirm = null;
        this.dangerCountdown = 0;
        if (this._dangerTimer) {
          clearInterval(this._dangerTimer);
          this._dangerTimer = null;
        }
      }
      if (newPage === 'dashboard' && this.autoScroll) {
        this.$nextTick(() => this.scrollToBottom());
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
    if (this._wsRetryTimer) clearTimeout(this._wsRetryTimer);
    if (this._dangerTimer) clearInterval(this._dangerTimer);
    if (this._repoDisclaimerTimer) clearInterval(this._repoDisclaimerTimer);
    if (this._toastTimer) clearTimeout(this._toastTimer);
    if (this._toastLeavingTimer) clearTimeout(this._toastLeavingTimer);
    this.timers.forEach((t) => clearInterval(t));
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
    ...profileMethods,
  },
};
