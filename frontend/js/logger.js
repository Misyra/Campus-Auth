import { LOG_LEVELS } from './constants.js';

export function createFrontendLogger(initialLevel = 'INFO') {
  let currentLevel = String(initialLevel || 'INFO').toUpperCase();

  const shouldLog = (level) => {
    const left = LOG_LEVELS[String(level || '').toUpperCase()] || LOG_LEVELS.INFO;
    const right = LOG_LEVELS[currentLevel] || LOG_LEVELS.INFO;
    return left >= right;
  };

  const format = (level, scope, message, meta) => {
    const stamp = new Date().toISOString();
    return [stamp, level, 'FRONTEND', scope, message, meta || ''];
  };

  return {
    setLevel(level) {
      const next = String(level || '').toUpperCase();
      currentLevel = LOG_LEVELS[next] ? next : 'INFO';
      console.info(...format('INFO', 'logger', `frontend log level => ${currentLevel}`));
    },
    debug(scope, message, meta) {
      if (shouldLog('DEBUG')) console.debug(...format('DEBUG', scope, message, meta));
    },
    info(scope, message, meta) {
      if (shouldLog('INFO')) console.info(...format('INFO', scope, message, meta));
    },
    warn(scope, message, meta) {
      if (shouldLog('WARNING')) console.warn(...format('WARNING', scope, message, meta));
    },
    error(scope, message, meta) {
      if (shouldLog('ERROR')) console.error(...format('ERROR', scope, message, meta));
    },
  };
}
