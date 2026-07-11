import { DEFAULT_CONFIG } from '../constants.js';

// 深拷贝嵌套配置
function cloneConfig(src) {
  const m = src.monitor;
  return {
    browser: { ...src.browser },
    monitor: {
      ...m,
      ping_targets: [...m.ping_targets],
      test_urls: [...m.test_urls],
      url_check_urls: [...m.url_check_urls],
      auth_url_targets: [...m.auth_url_targets],
    },
    pause: { ...src.pause },
    logging: { ...src.logging },
    retry: { ...src.retry },
    credentials: { ...src.credentials },
    active_task: src.active_task,
    app_settings: { ...src.app_settings },
  };
}

// 配置相关数据
export function configData() {
  return {
    config: cloneConfig(DEFAULT_CONFIG),
    // 密码掩码回显：后端 has_password 标记，前端展示 •••••• 占位
    passwordSaved: false,
    // inline edit 模式：是否处于密码编辑态
    editingPassword: false,
    defaultUrlCheckUrls: [...DEFAULT_CONFIG.monitor.url_check_urls],
    dangerConfirm: null,
    dangerCountdown: 0,
    availableShells: [],
    defaultShell: '',
    // OCR 依赖管理
    ocrStatus: { installed: false, size_mb: 0 },
    // 并发锁（防止重复请求）
    _autostartInFlight: false,
    // 用于 configDirty computed 的快照（响应式，使 dirty 指示器及时更新）
    _lastSavedConfig: null,
  };
}
