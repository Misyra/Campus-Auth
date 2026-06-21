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
    custom_variables: { ...src.custom_variables },
    block_proxy: src.block_proxy,
    shell_path: src.shell_path,
    minimize_to_tray: src.minimize_to_tray,
    lightweight_tray: src.lightweight_tray,
    startup_action: src.startup_action,
    autostart_lightweight: src.autostart_lightweight,
    auto_open_browser: src.auto_open_browser,
    proxy: src.proxy,
    app_port: src.app_port,
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
    // 日志级别配置
    logLevels: {
      global_level: 'INFO',
      source_levels: {},
    },
    // 并发锁（防止重复请求）
    _autostartInFlight: false,
  };
}
