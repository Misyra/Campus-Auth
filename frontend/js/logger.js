import { LOG_LEVELS } from './constants.js';

// 日志级别数值映射（用于级别比较）
const _LEVEL_VALUES = Object.fromEntries(LOG_LEVELS.map((l, i) => [l.value, (i + 1) * 10]));

export function createFrontendLogger(initialLevel = 'INFO') {
  let currentLevel = String(initialLevel || 'INFO').toUpperCase();
  let _ws = null;

  const shouldLog = (level) => {
    const left = _LEVEL_VALUES[String(level || '').toUpperCase()] || _LEVEL_VALUES.INFO;
    const right = _LEVEL_VALUES[currentLevel] || _LEVEL_VALUES.INFO;
    return left >= right;
  };

  const format = (level, scope, message, meta) => {
    const stamp = new Date().toISOString();
    return [stamp, level, 'FRONTEND', scope, message, meta || ''];
  };

  const _sendToBackend = (level, scope, message, meta) => {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      try {
        _ws.send(JSON.stringify({
          type: 'frontend_log',
          data: { level, scope, message, meta: meta || '' },
        }));
      } catch (_) { /* ignore send errors */ }
    }
  };

  return {
    setWebSocket(ws) {
      _ws = ws;
    },
    setLevel(level) {
      const next = String(level || '').toUpperCase();
      currentLevel = _LEVEL_VALUES[next] ? next : 'INFO';
      console.info(...format('INFO', 'logger', `frontend log level => ${currentLevel}`));
    },
    debug(scope, message, meta) {
      if (shouldLog('DEBUG')) {
        console.debug(...format('DEBUG', scope, message, meta));
        _sendToBackend('DEBUG', scope, message, meta);
      }
    },
    info(scope, message, meta) {
      if (shouldLog('INFO')) {
        console.info(...format('INFO', scope, message, meta));
        _sendToBackend('INFO', scope, message, meta);
      }
    },
    warn(scope, message, meta) {
      if (shouldLog('WARNING')) {
        console.warn(...format('WARNING', scope, message, meta));
        _sendToBackend('WARNING', scope, message, meta);
      }
    },
    error(scope, message, meta) {
      if (shouldLog('ERROR')) {
        console.error(...format('ERROR', scope, message, meta));
        _sendToBackend('ERROR', scope, message, meta);
      }
    },
  };
}
