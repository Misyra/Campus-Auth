const DANGEROUS_STEP_TYPES = new Set(['eval', 'custom_js']);
const TRUSTED_SOURCES = new Set(['builtin', 'signed']);

function detectDangerousSteps(config) {
  const source = config.source || '';
  if (TRUSTED_SOURCES.has(source)) return [];
  const steps = config.steps || [];
  const warnings = [];
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const type = step.type || '';
    if (DANGEROUS_STEP_TYPES.has(type)) {
      const desc = step.description || step.id || `步骤 ${i + 1}`;
      const code = step.script || step.code || step.value || step.extra?.code || step.extra?.script || '';
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
        this.notify(true, '活动任务已设置');
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
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
        };
        this.jsonError = '';
      } catch (error) {
        this.notify(false, '加载任务失败');
      }
    } else {
      this.editingTask = {
        id: '',
        name: '',
        description: '',
        url: 'http://172.29.0.2',
        json: '',
      };
      this.jsonError = '';
    }
  },
  async loadTemplate(templateId) {
    try {
      const { data } = await this.$api.get(`/api/tasks/${templateId}`);
      if (this.editingTask) {
        this.editingTask.json = JSON.stringify(data, null, 2);
        this.jsonError = '';
      }
    } catch (error) {
      this.notify(false, '加载模板失败');
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
      this.notify(false, 'JSON 格式错误，无法格式化');
    }
  },
  async saveTask() {
    if (!this.editingTask || !this.editingTask.id) {
      this.notify(false, '请输入任务ID');
      return;
    }
    let config;
    try {
      config = JSON.parse(this.editingTask.json);
    } catch (e) {
      this.jsonError = e.message;
      this.notify(false, 'JSON 格式错误: ' + e.message);
      return;
    }
    config.name = this.editingTask.name || config.name;
    config.description = this.editingTask.description || config.description;
    config.url = this.editingTask.url || config.url;

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
        this.notify(true, data.message || '任务保存成功');
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
      this.dangerConfirm = { dangers, resolve };
    });
  },
  confirmDanger(allow) {
    if (this.dangerConfirm) {
      this.dangerConfirm.resolve(allow);
      this.dangerConfirm = null;
    }
  },
  async deleteTask(taskId) {
    if (!confirm('确定要删除这个任务吗？')) return;
    try {
      const { data } = await this.$api.delete(`/api/tasks/${taskId}`);
      if (data.success) {
        this.notify(true, '任务删除成功');
        await this.fetchTasks();
        if (this.activeTaskId === taskId) {
          this.activeTaskId = 'default';
        }
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, '删除任务失败');
    }
  },
  async duplicateTask(taskId) {
    try {
      const { data } = await this.$api.get(`/api/tasks/${taskId}`);
      const newId = taskId + '_copy';
      this.editingTask = {
        id: newId,
        name: data.name + ' (副本)',
        description: data.description,
        url: data.url,
        json: JSON.stringify(data, null, 2),
      };
      this.jsonError = '';
    } catch (error) {
      this.notify(false, '复制任务失败');
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
      this.notify(true, '任务已导出');
    }).catch(() => {
      this.notify(false, '导出失败');
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
          };
          this.jsonError = '';
          // 显示来源信息
          const source = data.source || 'api';
          const sourceLabel = source === 'builtin' ? '内置' : source === 'signed' ? '已签名' : '外部导入';
          this.notify(true, `已导入任务配置（来源：${sourceLabel}），请检查后保存`);
        } catch {
          this.notify(false, '文件不是有效的 JSON');
        }
      };
      reader.readAsText(file);
    };
    input.click();
  },
};
