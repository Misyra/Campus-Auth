import { extractApiError } from '../methods/utils.js';

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

export const coreTaskMethods = {
  async fetchTasks() {
    try {
      const { data } = await this.$api.get('/api/tasks');
      this.tasks = data;
    } catch (error) {
      this.frontendLogger.error('tasks', '获取任务列表失败', error);
      if (!this._initErrorShown) {
        this._initErrorShown = true;
        this.notify(false, '加载任务列表失败');
      }
    }
  },
  async fetchActiveTask() {
    try {
      const { data } = await this.$api.get('/api/tasks/active');
      this.activeTaskId = data.task_id;
    } catch (error) {
      this.frontendLogger.error('tasks', '获取活动任务失败', error);
      if (!this._initErrorShown) {
        this._initErrorShown = true;
        this.notify(false, '加载活动任务失败');
      }
    }
  },
  async setActiveTask(taskId) {
    try {
      this.frontendLogger.info('tasks', `设置活动任务: ${taskId}`);
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
  async saveTask() {
    if (!this.editingTask || !this.editingTask.id) {
      this.frontendLogger.warn('tasks', '保存任务被拒绝: 空 ID');
      this.toastOnly(false, '请输入任务ID');
      return;
    }
    if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(this.editingTask.id)) {
      this.frontendLogger.warn('tasks', '保存任务被拒绝: ID 格式无效');
      this.toastOnly(false, '任务ID必须以字母开头，且只能包含字母、数字和下划线');
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
      this.frontendLogger.info('tasks', `保存任务: ${this.editingTask.id}`);
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
      this.frontendLogger.error('tasks', '保存任务失败', error);
      this.notify(false, extractApiError(error, '保存失败'));
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
          await this.setActiveTask('default');
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
};
