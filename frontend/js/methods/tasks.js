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
    }
  },
  async loadTemplate(templateId) {
    try {
      const { data } = await this.$api.get(`/api/tasks/${templateId}`);
      if (this.editingTask) {
        this.editingTask.json = JSON.stringify(data, null, 2);
      }
    } catch (error) {
      this.notify(false, '加载模板失败');
    }
  },
  async saveTask() {
    if (!this.editingTask || !this.editingTask.id) {
      this.notify(false, '请输入任务ID');
      return;
    }
    try {
      this.frontendLogger.info('tasks', `save task: ${this.editingTask.id}`);
      const config = JSON.parse(this.editingTask.json);
      config.name = this.editingTask.name || config.name;
      config.description = this.editingTask.description || config.description;
      config.url = this.editingTask.url || config.url;

      const { data } = await this.$api.put(`/api/tasks/${this.editingTask.id}`, config);
      if (data.success) {
        this.notify(true, '任务保存成功');
        this.editingTask = null;
        await this.fetchTasks();
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('tasks', 'save task failed', error);
      this.notify(false, error.message || '保存失败');
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
};
