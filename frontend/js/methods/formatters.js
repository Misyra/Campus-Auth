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
    const source = String(item?.source || 'monitor');
    return `[${level}] [${source}]`;
  },
  extractScreenshotUrl(message) {
    const text = String(message || '');
    const match = text.match(/截图[:：]\s*(\/debug\/[\w./-]+\.(?:png|jpg|jpeg|webp|gif))/i);
    return match ? match[1] : '';
  },
  stripScreenshotHint(message) {
    const text = String(message || '');
    return text.replace(/\s*[\[(]?\s*截图[:：]\s*\/debug\/[\w./-]+\.(?:png|jpg|jpeg|webp|gif)\s*[\])]?/gi, '').trim();
  },
  getLogClass(message) {
    const text = this.stripScreenshotHint(message);
    if (text.includes('错误') || text.includes('✗') || text.includes('EXCEPTION')) return 'error';
    if (text.includes('异常') || text.includes('警告') || text.includes('失败')) return 'warning';
    if (text.includes('成功') || text.includes('✓')) return 'success';
    return '';
  },
};
