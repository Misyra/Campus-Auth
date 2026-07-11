import { LOG_LEVELS, LEVEL_VALUES, LIMITS } from './constants.js';


export function createFrontendLogger(initialLevel = 'INFO') {
  let currentLevel = String(initialLevel || 'INFO').toUpperCase();
  let _ws = null;
  // WS 断连期间的日志缓冲，重连成功后 flush
  const _logBuffer = [];

  const shouldLog = (level) => {
    const left = LEVEL_VALUES[String(level || '').toUpperCase()] ?? LEVEL_VALUES.INFO;
    const right = LEVEL_VALUES[currentLevel] ?? LEVEL_VALUES.INFO;
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
    } else {
      // WS 不可用时缓冲日志，重连后批量补发；超限丢弃最旧
      _logBuffer.push({ level, scope, message, meta: meta || '' });
      if (_logBuffer.length > LIMITS.WS_LOG_BUFFER_MAX) {
        _logBuffer.shift();
      }
    }
  };

  const _flushBuffer = () => {
    if (!_ws || _ws.readyState !== WebSocket.OPEN || _logBuffer.length === 0) return;
    const batch = _logBuffer.splice(0, LIMITS.WS_LOG_FLUSH_BATCH);
    let sent = 0;
    try {
      for (const msg of batch) {
        _ws.send(JSON.stringify({
          type: 'frontend_log',
          data: { level: msg.level, scope: msg.scope, message: msg.message, meta: msg.meta },
        }));
        sent++;
      }
    } catch (_) {
      _logBuffer.unshift(...batch.slice(sent));
    }
    // 剩余消息在下次 setWebSocket 时继续 flush
  };

  return {
    setWebSocket(ws) {
      _ws = ws;
      _flushBuffer();
    },
    setLevel(level) {
      const next = String(level || '').toUpperCase();
      currentLevel = (LEVEL_VALUES[next] ?? -1) >= 0 ? next : 'INFO';
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
