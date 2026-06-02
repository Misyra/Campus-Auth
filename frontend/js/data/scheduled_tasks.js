// 定时任务相关数据
export function scheduledTasksData() {
  return {
    scheduledTasks: [],
    scheduledTaskForm: {
      id: '',
      name: '',
      description: '',
      type: 'script',
      target_id: '',
      command: '',
      shell_path: '',
      enabled: true,
      schedule: {
        hour: 8,
        minute: 0,
      },
      timeout: 60,
    },
    scheduledTaskHistory: [],
    showScheduledTaskModal: false,
    editingScheduledTask: null,
    scheduledTaskFormLoading: false,
    scheduledTaskHistoryLoading: false,
    selectedScheduledTaskId: null,
  };
}
