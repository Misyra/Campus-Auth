const DANGEROUS_STEP_TYPES = new Set(['eval', 'custom_js']);

function detectDangerousSteps(config) {
  const steps = config.steps || [];
  const warnings = [];
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const type = step.type || '';
    if (DANGEROUS_STEP_TYPES.has(type)) {
      const desc = step.description || step.id || `步骤 ${i + 1}`;
      const code = step.script || step.extra?.script || '';
      warnings.push({
        stepIndex: i + 1,
        stepType: type,
        description: desc,
        code: String(code).slice(0, 2000),
      });
    }
  }
  return warnings;
}

export const taskMethods = {
  async fetchTasks() {
    try {
      const { data } = await this.$api.get('/api/tasks');
      this.tasks = data;
    } catch (error) {
      this.frontendLogger.error('tasks', 'failed to fetch tasks', error);
    }
  },
  async fetchActiveTask() {
    try {
      const { data } = await this.$api.get('/api/tasks/active');
      this.activeTaskId = data.task_id;
    } catch (error) {
      this.frontendLogger.error('tasks', 'failed to fetch active task', error);
    }
  },
  async setActiveTask(taskId) {
    try {
      this.frontendLogger.info('tasks', `set active task: ${taskId}`);
      const { data } = await this.$api.post(`/api/tasks/active/${taskId}`);
      if (data.success) {
        this.activeTaskId = taskId;
        this.frontendLogger.info('tasks', `活动任务已设置: ${taskId}`);
      } else {
        this.frontendLogger.warn('tasks', '设置活动任务失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('tasks', '设置活动任务异常', error);
      this.notify(false, '设置活动任务失败');
    }
  },
  async showTaskEditor(taskId) {
    if (taskId) {
      try {
        const { data } = await this.$api.get(`/api/tasks/${taskId}`);
        this.editingTask = {
          id: taskId,
          name: data.name,
          description: data.description,
          url: data.url,
          json: JSON.stringify(data, null, 2),
          _isNew: false,
        };
        this.jsonError = '';
      } catch (error) {
        this.frontendLogger.error('tasks', '加载任务失败: ' + taskId, error);
        this.toastOnly(false, '加载任务失败');
      }
    } else {
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
  async saveTask() {
    if (!this.editingTask || !this.editingTask.id) {
      this.frontendLogger.warn('tasks', '保存任务被拒绝: 空 ID');
      this.toastOnly(false, '请输入任务ID');
      return;
    }
    let config;
    try {
      config = JSON.parse(this.editingTask.json);
    } catch (e) {
      this.jsonError = e.message;
      this.frontendLogger.warn('tasks', '保存任务被拒绝: JSON 无效: ' + e.message);
      this.toastOnly(false, 'JSON 格式错误: ' + e.message);
      return;
    }
    config.name = this.editingTask.name || config.name;
    config.description = this.editingTask.description || config.description;
    config.url = this.editingTask.url || config.url || '{{LOGIN_URL}}';

    // 清理已废弃字段
    delete config.version;
    delete config.source;

    // 客户端检测危险步骤
    const dangers = detectDangerousSteps(config);
    if (dangers.length > 0) {
      const confirmed = await this.showDangerConfirm(dangers);
      if (!confirmed) return;
    }

    try {
      this.frontendLogger.info('tasks', `save task: ${this.editingTask.id}`);
      const { data } = await this.$api.put(`/api/tasks/${this.editingTask.id}`, config);
      if (data.success) {
        this.frontendLogger.info('tasks', data.message || '任务保存成功');
        this.editingTask = null;
        this.jsonError = '';
        await this.fetchTasks();
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('tasks', 'save task failed', error);
      this.notify(false, error?.response?.data?.detail || error.message || '保存失败');
    }
  },
  showDangerConfirm(dangers) {
    return new Promise((resolve) => {
      if (this._dangerTimer) {
        clearInterval(this._dangerTimer);
        this._dangerTimer = null;
      }
      this.dangerConfirm = { dangers, resolve };
      this.dangerCountdown = 5;
      const timer = setInterval(() => {
        this.dangerCountdown--;
        if (this.dangerCountdown <= 0) {
          clearInterval(timer);
          this.dangerCountdown = 0;
        }
      }, 1000);
      this._dangerTimer = timer;
    });
  },
  confirmDanger(allow) {
    if (this._dangerTimer) {
      clearInterval(this._dangerTimer);
      this._dangerTimer = null;
    }
    if (this.dangerConfirm) {
      this.dangerConfirm.resolve(allow);
      this.dangerConfirm = null;
      this.dangerCountdown = 0;
    }
  },
  async deleteTask(taskId) {
    if (!confirm('确定要删除这个任务吗？')) return;
    try {
      const { data } = await this.$api.delete(`/api/tasks/${taskId}`);
      if (data.success) {
        this.frontendLogger.info('tasks', '任务删除成功: ' + taskId);
        this.toastOnly(true, '任务已删除');
        await this.fetchTasks();
        if (this.activeTaskId === taskId) {
          this.activeTaskId = 'default';
        }
      } else {
        this.frontendLogger.warn('tasks', '删除任务失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('tasks', '删除任务异常', error);
      this.notify(false, '删除任务失败');
    }
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
  exportTask(taskId) {
    this.$api.get(`/api/tasks/${taskId}`).then(({ data }) => {
      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${taskId}.json`;
      a.click();
      URL.revokeObjectURL(url);
      this.frontendLogger.info('tasks', '任务已导出');
    }).catch((error) => {
      this.frontendLogger.error('tasks', '导出任务失败: ' + taskId, error);
      this.toastOnly(false, '导出失败');
    });
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
          const id = file.name.replace(/\.json$/, '').replace(/[^A-Za-z0-9_]/g, '_');
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
      };
      reader.readAsText(file);
    };
    input.click();
  },

  async fetchSafeMode() {
    try {
      const { data } = await this.$api.get('/api/safe-mode');
      this.safeMode = data.enabled;
    } catch { /* ignore */ }
  },

  async toggleSafeMode() {
    try {
      const { data } = await this.$api.post('/api/safe-mode');
      this.safeMode = data.enabled;
      this.frontendLogger.info('tasks', `纯净模式已${data.enabled ? '开启' : '关闭'}`);
      this.toastOnly(true, `纯净模式已${data.enabled ? '开启' : '关闭'}`);
    } catch (error) {
      this.safeMode = !this.safeMode;
      this.frontendLogger.error('tasks', '切换纯净模式失败', error);
      this.toastOnly(false, '切换纯净模式失败');
    }
  },

  async startDebug(taskId) {
    this.debugLoading = true;
    try {
      const { data } = await this.$api.post('/api/debug/start', { task_id: taskId });
      this.debugSession = data;
      this.frontendLogger.info('debug', `started for task ${taskId}`);
    } catch (error) {
      const msg = error?.response?.data?.detail || '启动调试失败';
      this.frontendLogger.error('debug', '启动调试失败: ' + msg);
      this.notify(false, msg);
    } finally {
      this.debugLoading = false;
    }
  },

  async debugNextStep() {
    this.busy.debug = true;
    try {
      const { data } = await this.$api.post('/api/debug/next');
      this.debugSession = data;
    } catch (error) {
      const msg = error?.response?.data?.detail || '执行步骤失败';
      this.frontendLogger.error('debug', '执行步骤失败: ' + msg);
      this.notify(false, msg);
    } finally {
      this.busy.debug = false;
    }
  },

  async debugRunAll() {
    this.busy.debug = true;
    try {
      const { data } = await this.$api.post('/api/debug/run-all');
      this.debugSession = data;
    } catch (error) {
      const msg = error?.response?.data?.detail || '执行失败';
      this.frontendLogger.error('debug', '执行全部失败: ' + msg);
      this.notify(false, msg);
    } finally {
      this.busy.debug = false;
    }
  },

  async debugStop() {
    try {
      const { data } = await this.$api.post('/api/debug/stop');
      this.debugSession = {
        running: false, task_id: null, current_step: 0,
        total_steps: 0, steps: [], results: [], screenshot_url: null,
      };
      this.frontendLogger.info('debug', '调试已停止');
      this.notify(true, data.message || '调试已停止');
    } catch (error) {
      this.frontendLogger.error('debug', '停止调试失败', error);
      this.notify(false, '停止调试失败');
    }
  },

  getDebugStepResult(index) {
    return this.debugSession.results.find(r => r.step_index === index) || null;
  },

  getDebugStepStatus(index) {
    const result = this.getDebugStepResult(index);
    if (result) return result.success ? 'success' : 'failed';
    if (index === this.debugSession.current_step) return 'current';
    return 'pending';
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

  showRepoImport() {
    this.repoImport.visible = true;
    this.repoImport.error = '';
    this.repoImport.tasks = [];
    this.repoImport.searchQuery = '';
    this.repoImport.loading = false;
    this.repoImport.disclaimer = null;
  },

  closeRepoImport() {
    this.repoImport.visible = false;
    this.repoImport.tasks = [];
    this.repoImport.searchQuery = '';
    this.repoImport.error = '';
    this.repoImport.disclaimer = null;
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
      const msg = e?.response?.data?.detail || '加载失败，请检查地址是否正确';
      this.repoImport.error = msg;
      this.frontendLogger.error('tasks', '获取远程索引失败', msg);
      this.notify(false, `获取远程索引失败: ${msg}`);
    } finally {
      this.repoImport.loading = false;
    }
  },

  async confirmRepoImport(task) {
    this.repoImport.disclaimer = task;
    this.repoImport.disclaimerCountdown = 3;
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
    if (this._repoDisclaimerTimer) {
      clearInterval(this._repoDisclaimerTimer);
      this._repoDisclaimerTimer = null;
    }
    this.repoImport.disclaimer = null;
    this.repoImport.disclaimerCountdown = 0;
  },

  async acceptRepoDisclaimer() {
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
      this.notify(true, `已导入「${task.name}」，请在右侧编辑器内确认后保存`);
    } catch (e) {
      const msg = e?.response?.data?.detail || '下载任务失败';
      this.frontendLogger.error('tasks', '远程任务下载失败', msg);
      this.notify(false, `远程任务下载失败: ${msg}`);
    }
  },
};
