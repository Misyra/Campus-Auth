import { DEFAULT_CONFIG } from '../constants.js';

// 深拷贝嵌套配置
function cloneConfig(src) {
  return {
    browser: { ...src.browser },
    monitor: { ...src.monitor },
    pause: { ...src.pause },
    logging: { ...src.logging },
    retry: { ...src.retry },
    credentials: { ...src.credentials },
    active_task: src.active_task,
    app_settings: { ...src.app_settings, custom_variables: { ...src.app_settings.custom_variables } },
  };
}

// 配置相关数据
export function configData() {
  return {
    config: cloneConfig(DEFAULT_CONFIG),
    defaultUrlCheckUrls: DEFAULT_CONFIG.monitor.url_check_urls,
    dangerConfirm: null,
    dangerCountdown: 0,
    availableShells: [],
    defaultShell: '',
    // OCR 依赖管理
    ocrStatus: { installed: false, size_mb: 0 },
    // 并发锁（防止重复请求）
    _autostartInFlight: false,
  };
}
