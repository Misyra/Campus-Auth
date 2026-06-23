// 状态相关数据
export function statusData() {
  return {
    _initErrorCount: 0, // 初始化错误计数（避免多模块竞态）
    _statusPolling: false, // 状态轮询锁
    status: {
      monitoring: false,
      network_check_count: 0,
      login_attempt_count: 0,
      last_check_time: null,
      runtime_seconds: 0,
      network_connected: false,
      status_detail: '已停止',
      network_state: 'unknown',
    },
    autostart: {
      platform: '-',
      enabled: false,
      method: '-',
      location: '',
      lightweight: true,
    },
    busy: {
      save: false,
      monitor: false,
      action: false,
      login: false,
      loginCooldown: false,
      autostart: false,
      detect: false,
      editorDetect: false,
      debug: false,
      uninstall: false,
      ocr: false,
    },
  };
}
