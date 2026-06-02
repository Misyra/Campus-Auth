export const statusMethods = {
  async fetchStatus() {
    try {
      const { data } = await this.$api.get('/api/status');
      this.status = data;
      if (this.fetchStatusFailCount > 0) {
        this.fetchStatusFailCount = 0;
        this.notify(true, '已重新连接到服务器');
      }
    } catch (error) {
      this.fetchStatusFailCount = (this.fetchStatusFailCount || 0) + 1;
      this.frontendLogger.warn('status', '获取状态失败', error);
      if (this.fetchStatusFailCount === 1) {
        this.notify(false, '无法连接到服务器，请检查后端是否已关闭');
      }
    }
  },
  async fetchLogs() {
    try {
      const { data } = await this.$api.get('/api/logs', { params: { limit: 250 } });
      // 按前端日志级别过滤（完整日志已在文件中）
      this.logs = data.filter(l => this._shouldShowLog(l.level));
      this.$nextTick(() => this.scrollToBottom());
    } catch (error) {
      this.frontendLogger.error('logs', '获取日志失败', error);
      this._recordInitError('加载日志失败');
    }
  },
};
