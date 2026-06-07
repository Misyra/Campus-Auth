// 调试会话相关数据
export function debugData() {
  return {
    debugSession: {
      running: false,
      task_id: null,
      current_step: 0,
      total_steps: 0,
      steps: [],
      results: [],
      screenshot_url: null,
    },
    debugLoading: false,
    pureMode: false,
    _pureModeLoading: false,
  };
}
