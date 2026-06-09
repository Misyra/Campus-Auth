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
  formatLogMeta(item) {
    const level = String(item?.level || 'INFO').toUpperCase();
    const source = String(item?.source || 'backend');
    return `[${level}] [${source}]`;
  },
  getSourceLabel(source) {
    return LOG_SOURCES[source]?.label || source || '未知';
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
    if (level === 'ERROR' || level === 'CRITICAL') return 'error';
    if (level === 'WARNING') return 'warning';
    if (level === 'SUCCESS') return 'success';
    // 成功消息没有专门的 level，保留关键词匹配作为补充
    // 注意：不匹配英文 "success"，避免 success=False 等误判
    const text = this.stripScreenshotHint(item?.message || item || '');
    if (text.includes('成功') || text.includes('✓')) return 'success';
    return '';
  },
};
