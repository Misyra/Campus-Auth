// 任务相关数据
export function taskData() {
  return {
    tasks: [],
    activeTaskId: 'default',
    editingTask: null,
    editingTaskType: 'browser', // 'browser' | 'script'
    jsonError: '',
  };
}
