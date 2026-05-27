export const autostartMethods = {
  async fetchAutostart() {
    try {
      const { data } = await this.$api.get('/api/autostart/status');
      this.autostart = data;
    } catch (error) {
      this.frontendLogger.warn('autostart', '获取自启动状态失败', error);
      if (error?.response?.status === 404) {
        this.autostart = {
          platform: '-',
          enabled: false,
          method: '当前后端不支持',
          location: '',
        };
      }
    }
  },
  async _toggleAutostart(enable) {
    const action = enable ? 'enable' : 'disable';
    const label = enable ? '启用' : '关闭';
    this.busy.autostart = true;
    try {
      const { data } = await this.$api.post(`/api/autostart/${action}`);
      if (data.success) {
        this.frontendLogger.info('autostart', data.message);
        this.toastOnly(true, data.message);
      } else {
        this.frontendLogger.warn('autostart', `${label}自启动失败: ${data.message}`);
        this.notify(false, data.message);
      }
    } catch (error) {
      if (error?.response?.status === 404) {
        this.frontendLogger.warn('autostart', '后端不支持开机自启动');
        this.notify(false, '当前后端版本不支持开机自启动，请重启后端');
      } else {
        this.frontendLogger.error('autostart', `${label}自启动异常`, error);
        this.notify(false, `${label}自启动失败`);
      }
    } finally {
      await this.fetchAutostart();
      this.busy.autostart = false;
    }
  },
  async enableAutostart() { return this._toggleAutostart(true); },
  async disableAutostart() { return this._toggleAutostart(false); },
};
