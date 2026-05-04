export const statusMethods = {
  async fetchStatus() {
    try {
      const { data } = await this.$api.get('/api/status');
      this.status = data;
      this.fetchStatusFailCount = 0;
    } catch (error) {
      this.fetchStatusFailCount = (this.fetchStatusFailCount || 0) + 1;
      this.frontendLogger.warn('status', 'fetch status failed', error);
      if (this.fetchStatusFailCount >= 3) {
        this.notify(false, '无法连接到服务器，请检查后端是否已关闭');
        this.fetchStatusFailCount = 0;
      }
    }
  },
  async fetchLogs() {
    try {
      const { data } = await this.$api.get('/api/logs', { params: { limit: 250 } });
      // 按前端日志级别过滤（完整日志已在文件中）
      this.logs = data.filter(l => this._shouldShowLog(l.level));
      this.$nextTick(() => this.scrollLogToBottom());
    } catch (error) {
      this.frontendLogger.error('logs', 'failed to fetch logs', error);
    }
  },
};
