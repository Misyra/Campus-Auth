import { LOG_SOURCES } from '../constants.js';

// 日志文件查看器方法
export const logFileMethods = {
  async fetchLogFileGroups() {
    try {
      const { data } = await this.$api.get('/api/logfiles/list');
      this.logFileGroups = data;
      if (data.length && !this.logViewer.date) {
        this.logViewer.date = data[0].date;
        this.logViewer.file = data[0].files[0]?.name || 'app.log';
        await this.fetchLogFileContent();
      }
    } catch (error) {
      this.frontendLogger.error('logfiles', '获取日志文件列表失败', error);
    }
  },
  async refreshLogFiles() {
    this.logFileGroups = [];
    this.logViewer.date = '';
    this.logViewer.lines = [];
    await this.fetchLogFileGroups();
  },
  async selectLogFileDate(date) {
    this.logViewer.date = date;
    const group = this.logFileGroups.find(g => g.date === date);
    this.logViewer.file = group?.files[0]?.name || 'app.log';
    await this.fetchLogFileContent();
  },
  async fetchLogFileContent() {
    if (!this.logViewer.file) return;
    this.logViewer.loading = true;
    try {
      const params = {
        file: this.logViewer.file,
        limit: 5000,
      };
      if (this.logViewer.level) params.level = this.logViewer.level;
      if (this.logViewer.source) params.source = this.logViewer.source;
      if (this.logViewer.search) params.search = this.logViewer.search;
      const { data } = await this.$api.get('/api/logfiles/content', { params });
      this.logViewer.lines = data.lines;
      this.logViewer.totalLines = data.total_lines;
      this.$nextTick(() => {
        const viewer = this.$refs?.logFileViewer;
        if (viewer) viewer.scrollTop = viewer.scrollHeight;
      });
    } catch (error) {
      this.frontendLogger.error('logfiles', '获取日志内容失败', error);
      this.logViewer.lines = [];
    } finally {
      this.logViewer.loading = false;
    }
  },
  getLogFileClass(level) {
    const l = String(level || '').toUpperCase();
    if (l === 'ERROR' || l === 'CRITICAL') return 'error';
    if (l === 'WARNING') return 'warning';
    if (l === 'DEBUG') return 'debug';
    return '';
  },
  getSourceLabel(source) {
    return LOG_SOURCES[source]?.label || (source ? source.toUpperCase().slice(0, 3) : '未知');
  },
};
