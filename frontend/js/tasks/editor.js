import { extractApiError } from '../methods/utils.js';

export const editorTaskMethods = {
  async showTaskEditor(taskId) {
    if (taskId) {
      try {
        const { data } = await this.$api.get(`/api/tasks/${taskId}`);
        // 脚本任务跳转到脚本编辑器
        if (data.type === 'script') {
          this.showScriptEditor(taskId);
          this.currentPage = 'scripts';
          return;
        }
        this.editingTaskType = 'browser';
        const displayData = data.raw_json || data;
        this.editingTask = {
          id: taskId,
          name: data.name,
          description: data.description,
          url: data.url,
          json: JSON.stringify(displayData, null, 2),
          _isNew: false,
        };
        this.jsonError = '';
      } catch (error) {
        this.frontendLogger.error('tasks', '加载任务失败: ' + taskId, error);
        this.toastOnly(false, '加载任务失败');
      }
    } else {
      this.editingTaskType = 'browser';
      this.editingTask = {
        id: '',
        name: '',
        description: '',
        url: '',
        json: '',
        _isNew: true,
      };
      this.jsonError = '';
    }
  },
  async loadTemplate(templateId) {
    if (!this.editingTask) return;
    try {
      const { data } = await this.$api.get(`/api/tasks/${templateId}`);
      this.editingTask.json = JSON.stringify(data, null, 2);
      this.jsonError = '';
    } catch (error) {
      this.frontendLogger.error('tasks', '加载模板失败: ' + templateId, error);
      this.toastOnly(false, '加载模板失败');
    }
  },
  validateJson() {
    if (!this.editingTask || !this.editingTask.json.trim()) {
      this.jsonError = '';
      return;
    }
    try {
      JSON.parse(this.editingTask.json);
      this.jsonError = '';
    } catch (e) {
      this.jsonError = e.message;
    }
  },
  formatJson() {
    if (!this.editingTask) return;
    try {
      const parsed = JSON.parse(this.editingTask.json);
      this.editingTask.json = JSON.stringify(parsed, null, 2);
      this.jsonError = '';
    } catch (e) {
      this.frontendLogger.warn('tasks', 'JSON 格式化失败: ' + e.message);
      this.toastOnly(false, 'JSON 格式错误，无法格式化');
    }
  },
  _cancelDangerConfirm(reason) {
    this._releaseFocusTrap();
    if (this._dangerTimer) {
      clearInterval(this._dangerTimer);
      this._dangerTimer = null;
    }
    if (this._dangerResolve) {
      this._dangerResolve(false);
      this._dangerResolve = null;
    }
    this.dangerConfirm = null;
    this.dangerCountdown = 0;
  },
  showDangerConfirm(dangers) {
    return new Promise((resolve) => {
      // 清理旧状态，避免泄漏
      this._cancelDangerConfirm('reenter');
      // resolve 存储到非响应式属性，避免 Vue 代理函数对象
      this._dangerResolve = resolve;
      this.dangerConfirm = { dangers };
      this.dangerCountdown = 3;
      this.$nextTick(() => {
        const overlay = document.querySelector('.danger-overlay');
        if (overlay) this._trapFocus(overlay);
      });
      const timer = setInterval(() => {
        this.dangerCountdown--;
        if (this.dangerCountdown <= 0) {
          clearInterval(timer);
        }
      }, 1000);
      this._dangerTimer = timer;
    });
  },
  confirmDanger(allow) {
    this._releaseFocusTrap();
    if (this._dangerTimer) {
      clearInterval(this._dangerTimer);
      this._dangerTimer = null;
    }
    if (this._dangerResolve) {
      this._dangerResolve(allow);
      this._dangerResolve = null;
    }
    this.dangerConfirm = null;
    this.dangerCountdown = 0;
  },
  async duplicateTask(taskId) {
    try {
      const { data } = await this.$api.get(`/api/tasks/${taskId}`);
      const baseId = taskId.replace(/_copy(_\d+)?$/, '');
      const existingIds = new Set((this.tasks || []).map(t => t.id));
      let newId = baseId + '_copy';
      let counter = 2;
      while (existingIds.has(newId)) {
        newId = baseId + '_copy_' + counter;
        counter++;
      }
      const baseName = data.name.replace(/\s*\(副本\)(\s*\d+)?$/, '');
      const suffix = counter > 2 ? ` (副本${counter - 1})` : ' (副本)';
      this.editingTask = {
        id: newId,
        name: baseName + suffix,
        description: data.description,
        url: data.url,
        json: JSON.stringify(data, null, 2),
        _isNew: true,
      };
      this.jsonError = '';
    } catch (error) {
      this.frontendLogger.error('tasks', '复制任务失败: ' + taskId, error);
      this.toastOnly(false, '复制任务失败');
    }
  },
  async exportTask(taskId) {
    try {
      const { data } = await this.$api.get(`/api/tasks/${taskId}`);
      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${taskId}.json`;
      a.click();
      URL.revokeObjectURL(url);
      this.frontendLogger.info('tasks', '任务已导出');
    } catch (error) {
      this.frontendLogger.error('tasks', '导出任务失败: ' + taskId, error);
      this.toastOnly(false, '导出失败');
    }
  },
  importTask() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const data = JSON.parse(ev.target.result);
          let id = file.name.replace(/\.json$/, '').replace(/[^A-Za-z0-9_]/g, '_');
          // 确保 ID 以字母开头（HTML ID 规范）
          if (/^[0-9]/.test(id)) {
            id = 'task_' + id;
          }
          this.editingTask = {
            id: id,
            name: data.name || '',
            description: data.description || '',
            url: data.url || '',
            json: JSON.stringify(data, null, 2),
            _isNew: true,
          };
          this.jsonError = '';
          this.currentPage = 'tasks';
          this.frontendLogger.info('tasks', '已导入任务配置，请检查后保存');
        } catch (e) {
          this.frontendLogger.warn('tasks', '导入失败: 文件不是有效 JSON: ' + e.message);
          this.toastOnly(false, '文件不是有效的 JSON');
        }
        input.value = '';
        input.onchange = null;
      };
      reader.readAsText(file);
    };
    input.click();
  },

  async fetchPureMode() {
    try {
      const { data } = await this.$api.get('/api/pure-mode');
      this.pureMode = data.enabled;
    } catch {
      // 纯净模式查询失败，保持默认值
    }
  },

  async togglePureMode() {
    // 防止快速点击导致竞态
    if (this._pureModeLoading) return;
    this._pureModeLoading = true;
    // v-model 已同步更新 pureMode，此处调用 API 持久化到后端
    try {
      const { data } = await this.$api.post('/api/pure-mode');
      // 以后端返回值为准，确保前后端状态一致
      this.pureMode = data.enabled;
      this.frontendLogger.info('tasks', `纯净模式已${data.enabled ? '开启' : '关闭'}`);
      this.toastOnly(true, `纯净模式已${data.enabled ? '开启' : '关闭'}`);
    } catch (error) {
      // API 失败，回滚 UI 状态
      this.pureMode = !this.pureMode;
      this.frontendLogger.error('tasks', '切换纯净模式失败', error);
      this.toastOnly(false, '切换纯净模式失败');
    } finally {
      this._pureModeLoading = false;
    }
  },

  // ==================== 仓库导入 ====================

  selectRepoSource(source) {
    this.repoImport.source = source;
    if (source === 'github') {
      this.repoImport.url = 'https://github.com/Misyra/campus-auth-tasks/blob/master/index.json';
    } else if (source === 'gitee') {
      this.repoImport.url = 'https://raw.giteeusercontent.com/Misyra/campus-auth-tasks/raw/master/index.gitee.json';
    }
    // 'custom' 保留当前 URL 不动
  },

  _resetRepoImport() {
    this.repoImport.error = '';
    this.repoImport.tasks = [];
    this.repoImport.searchQuery = '';
    this.repoImport.loading = false;
    this.repoImport.disclaimer = null;
  },

  showRepoImport() {
    this.repoImport.visible = true;
    this._resetRepoImport();
    this.$nextTick(() => {
      const overlay = document.querySelector('.repo-overlay');
      if (overlay) this._trapFocus(overlay);
    });
  },

  closeRepoImport() {
    this._releaseFocusTrap();
    this.repoImport.visible = false;
    this._resetRepoImport();
  },

  async fetchRepoIndex() {
    const url = this.repoImport.url.trim();
    if (!url) {
      this.repoImport.error = '请输入索引地址';
      return;
    }
    this.repoImport.loading = true;
    this.repoImport.error = '';
    this.repoImport.tasks = [];
    this.repoImport.searchQuery = '';
    try {
      const { data } = await this.$api.get(`/api/repo/fetch?url=${encodeURIComponent(url)}`);
      if (!Array.isArray(data) || data.length === 0) {
        this.repoImport.error = '索引为空或格式不正确';
        return;
      }
      this.repoImport.tasks = data;
    } catch (e) {
      const msg = extractApiError(e, '加载失败，请检查地址是否正确');
      this.repoImport.error = msg;
      this.frontendLogger.error('tasks', '获取远程索引失败', msg);
      this.toastOnly(false, `获取远程索引失败: ${msg}`);
    } finally {
      this.repoImport.loading = false;
    }
  },

  async confirmRepoImport(task) {
    if (this._repoDisclaimerTimer) {
      clearInterval(this._repoDisclaimerTimer);
      this._repoDisclaimerTimer = null;
    }
    this.repoImport.disclaimer = task;
    this.repoImport.disclaimerCountdown = 3;
    this.$nextTick(() => {
      const modal = document.querySelector('.repo-disclaimer-modal');
      if (modal) this._trapFocus(modal);
    });
    const timer = setInterval(() => {
      this.repoImport.disclaimerCountdown--;
      if (this.repoImport.disclaimerCountdown <= 0) {
        clearInterval(timer);
        this.repoImport.disclaimerCountdown = 0;
      }
    }, 1000);
    this._repoDisclaimerTimer = timer;
  },

  cancelRepoDisclaimer() {
    this._releaseFocusTrap();
    if (this._repoDisclaimerTimer) {
      clearInterval(this._repoDisclaimerTimer);
      this._repoDisclaimerTimer = null;
    }
    this.repoImport.disclaimer = null;
    this.repoImport.disclaimerCountdown = 0;
  },

  async acceptRepoDisclaimer() {
    this._releaseFocusTrap();
    if (this._repoDisclaimerTimer) {
      clearInterval(this._repoDisclaimerTimer);
      this._repoDisclaimerTimer = null;
    }
    const task = this.repoImport.disclaimer;
    this.repoImport.disclaimer = null;
    if (!task) return;

    try {
      const { data } = await this.$api.get(`/api/repo/task?url=${encodeURIComponent(task.url)}`);
      const id = (task.id || data.name || 'imported').replace(/[^A-Za-z0-9_]/g, '_');
      this.editingTask = {
        id: id,
        name: data.name || task.name || '',
        description: data.description || task.description || '',
        url: data.url || '',
        json: JSON.stringify(data, null, 2),
        _isNew: true,
      };
      this.jsonError = '';
      this.closeRepoImport();
      this.currentPage = 'tasks';
      this.frontendLogger.info('tasks', `已从仓库导入: ${task.name}`);
      this.toastOnly(true, `已导入「${task.name}」，请在右侧编辑器内确认后保存`);
    } catch (e) {
      const msg = extractApiError(e, '下载任务失败');
      this.frontendLogger.error('tasks', '远程任务下载失败', msg);
      this.toastOnly(false, `远程任务下载失败: ${msg}`);
    }
  },
};
