import { LOG_SOURCES } from '../constants.js';

export const formatterMethods = {
  formatDuration(totalSeconds) {
    const sec = Number(totalSeconds || 0);
    const h = String(Math.floor(sec / 3600)).padStart(2, '0');
    const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
    const s = String(sec % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
  },
  formatTime(isoString) {
    if (!isoString) return '-';
    return isoString.replace('T', ' ').substring(0, 19);
  },
  formatLogTime(timestamp) {
    if (!timestamp) return '';
    return timestamp.substring(11, 19);
  },
  extractScreenshotUrl(message) {
    const text = String(message || '');
    const match = text.match(/截图[:：]\s*(\/(?:logs|debug|temp)\/\S+\.(?:png|jpg|jpeg|webp|gif))/i);
    if (!match) return '';
    const url = match[1];
    if (url.includes('..') || /[\x00-\x1f]/.test(url)) return '';
    return url;
  },
  stripScreenshotHint(message) {
    const text = String(message || '');
    return text.replace(/\s*[\[(]?\s*截图[:：]\s*\/(?:logs|debug|temp)\/\S+\.(?:png|jpg|jpeg|webp|gif)\s*[\])]?/gi, '').trim();
  },
  getLogClass(item) {
    const level = String(item?.level || '').toUpperCase();
    if (level === 'ERROR') return 'error';
    if (level === 'WARNING') return 'warning';
    return '';
  },
  getSourceLabel(source) {
    return LOG_SOURCES.find(s => s.value === source)?.label || source || '未知';
  },
};

/**
 * 格式化定时任务调度时间。
 * @param {{hour: number, minute: number}} schedule
 * @returns {string} 格式如 "08:30"
 */
export function formatScheduleTime(schedule) {
  if (!schedule) return '';
  const hour = String(schedule.hour ?? 0).padStart(2, '0');
  const minute = String(schedule.minute ?? 0).padStart(2, '0');
  return `${hour}:${minute}`;
}

/**
 * 格式化任务超时时间（秒 → 分钟）。
 * @param {number} seconds
 * @returns {string}
 */
export function formatTimeValue(seconds) {
  if (!seconds) return '-';
  if (seconds < 60) return `${seconds}秒`;
  return `${Math.round(seconds / 60)}分钟`;
}

/**
 * HEX 颜色转 RGB 对象。
 * @param {string} hex
 * @returns {{r: number, g: number, b: number} | null}
 */
export function hexToRgb(hex) {
  let h = (hex || '').replace('#', '');
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  const result = /^([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(h);
  return result ? {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16),
  } : null;
}

/**
 * 调整颜色亮度。
 * @param {string} hex - HEX 颜色值
 * @param {number} amount - 调整量（正数变亮，负数变暗）
 * @returns {string} 调整后的 HEX 颜色值
 */
export function adjustColor(hex, amount) {
  let h = hex.replace('#', '');
  // 展开 3 位简写（abc → aabbcc）
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  const num = parseInt(h, 16);
  const r = Math.max(0, Math.min(255, (num >> 16) + amount));
  const g = Math.max(0, Math.min(255, ((num >> 8) & 0x00FF) + amount));
  const b = Math.max(0, Math.min(255, (num & 0x0000FF) + amount));
  return `#${(1 << 24 | r << 16 | g << 8 | b).toString(16).slice(1)}`;
}
