import { extractApiError, safeApiCall } from './utils.js';
import { formatScheduleTime, formatTimeValue } from './formatters.js';

// 定时任务相关方法
export const scheduledTasksMethods = {
  // 加载定时任务列表
  async loadScheduledTasks() {
    try {
      const { data } = await this.$api.get('/api/scheduled-tasks');
      this.scheduledTasks = data;
    } catch (e) {
      this.frontendLogger.error('scheduled_tasks', '加载定时任务失败', e);
    }
  },

  // 打开创建定时任务对话框
  openCreateScheduledTask() {
    this.editingScheduledTask = null;
    this.scheduledTaskForm = {
      name: '',
      description: '',
      type: 'script',
      target_id: '',
      enabled: true,
      schedule: {
        hour: 8,
        minute: 0,
      },
      timeout: 60,
    };
    this.showScheduledTaskModal = true;
  },

  // 打开编辑定时任务对话框
  openEditScheduledTask(task) {
    this.editingScheduledTask = task.id;
    this.scheduledTaskForm = {
      name: task.name || '',
      description: task.description || '',
      type: task.type || 'script',
      target_id: task.target_id || '',
      enabled: task.enabled !== false,
      schedule: {
        hour: task.schedule?.hour ?? 8,
        minute: task.schedule?.minute ?? 0,
      },
      timeout: task.timeout || 60,
    };
    this.showScheduledTaskModal = true;
  },

  // 关闭定时任务对话框
  closeScheduledTaskModal() {
    this.showScheduledTaskModal = false;
    this.editingScheduledTask = null;
  },

  // 保存定时任务
  async saveScheduledTask() {
    const form = this.scheduledTaskForm;

    // 验证
    if (!form.name.trim()) {
      this.toastOnly(false, '请输入任务名称');
      return;
    }

    if (!form.target_id) {
      this.toastOnly(false, '请选择目标任务');
      return;
    }

    this.scheduledTaskFormLoading = true;

    try {
      const url = this.editingScheduledTask
        ? `/api/scheduled-tasks/${this.editingScheduledTask}`
        : '/api/scheduled-tasks';

      const { data: result } = this.editingScheduledTask
        ? await this.$api.put(url, form)
        : await this.$api.post(url, form);

      this.toastOnly(result.success, result.message);

      if (result.success) {
        this.closeScheduledTaskModal();
        await this.loadScheduledTasks();
      }
    } catch (e) {
      const msg = extractApiError(e, '保存失败');
      this.toastOnly(false, msg);
    } finally {
      this.scheduledTaskFormLoading = false;
    }
  },

  // 删除定时任务
  async deleteScheduledTask(taskId) {
    if (!confirm('确定要删除这个定时任务吗？')) return;
    const resp = await safeApiCall.call(this, () => this.$api.delete(`/api/scheduled-tasks/${taskId}`), '删除失败');
    if (!resp) return;
    const result = resp.data;
    this.toastOnly(result.success, result.message);
    if (result.success) {
      await this.loadScheduledTasks();
    }
  },

  // 切换定时任务启用状态
  async toggleScheduledTask(taskId) {
    const resp = await safeApiCall.call(this, () => this.$api.post(`/api/scheduled-tasks/${taskId}/toggle`), '操作失败');
    if (!resp) return;
    const result = resp.data;
    this.toastOnly(result.success, result.message);
    if (result.success) {
      await this.loadScheduledTasks();
    }
  },

  // 手动执行定时任务
  async runScheduledTask(taskId) {
    const resp = await safeApiCall.call(this, () => this.$api.post(`/api/scheduled-tasks/${taskId}/run`), '执行失败');
    if (!resp) return;
    const result = resp.data;
    this.toastOnly(result.success, result.message);
    await this.loadScheduledTasks();
  },

  // 加载执行历史
  async loadScheduledTaskHistory(taskId) {
    this.selectedScheduledTaskId = taskId;
    this.scheduledTaskHistoryLoading = true;

    try {
      const { data } = await this.$api.get(`/api/scheduled-tasks/${taskId}/history`);
      this.scheduledTaskHistory = data;
    } catch (e) {
      this.frontendLogger.error('scheduled_tasks', '加载执行历史失败', e);
      this.scheduledTaskHistory = [];
    } finally {
      this.scheduledTaskHistoryLoading = false;
    }
  },

  // 关闭历史对话框
  closeScheduledTaskHistory() {
    this.selectedScheduledTaskId = null;
    this.scheduledTaskHistory = [];
  },

  // 格式化任务类型
  formatTaskType(type) {
    const types = {
      script: '自定义脚本',
      browser: '浏览器任务',
    };
    return types[type] || type;
  },

  // 处理时间变化
  onTimeChange(event) {
    const value = event.target.value;
    if (value) {
      const [hour, minute] = value.split(':').map(Number);
      this.scheduledTaskForm.schedule.hour = hour;
      this.scheduledTaskForm.schedule.minute = minute;
    }
  },
};
