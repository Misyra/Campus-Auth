import { DEFAULT_CONFIG } from '../constants.js';

// 配置相关数据
export function configData() {
  return {
    config: { ...DEFAULT_CONFIG },
    defaultUrlCheckUrls: DEFAULT_CONFIG.url_check_urls,
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
