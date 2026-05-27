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
  async enableAutostart() {
    this.busy.autostart = true;
    try {
      const { data } = await this.$api.post('/api/autostart/enable');
      if (data.success) {
        this.frontendLogger.info('autostart', data.message);
        this.toastOnly(true, data.message);
      } else {
        this.frontendLogger.warn('autostart', '启用自启动失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      if (error?.response?.status === 404) {
        this.frontendLogger.warn('autostart', '后端不支持开机自启动');
        this.notify(false, '当前后端版本不支持开机自启动，请重启后端');
      } else {
        this.frontendLogger.error('autostart', '启用自启动异常', error);
        this.notify(false, '启用自启动失败');
      }
    } finally {
      await this.fetchAutostart();
      this.busy.autostart = false;
    }
  },
  async disableAutostart() {
    this.busy.autostart = true;
    try {
      const { data } = await this.$api.post('/api/autostart/disable');
      if (data.success) {
        this.frontendLogger.info('autostart', data.message);
        this.toastOnly(true, data.message);
      } else {
        this.frontendLogger.warn('autostart', '关闭自启动失败: ' + data.message);
        this.notify(false, data.message);
      }
    } catch (error) {
      if (error?.response?.status === 404) {
        this.frontendLogger.warn('autostart', '后端不支持开机自启动');
        this.notify(false, '当前后端版本不支持开机自启动，请重启后端');
      } else {
        this.frontendLogger.error('autostart', '关闭自启动异常', error);
        this.notify(false, '关闭自启动失败');
      }
    } finally {
      await this.fetchAutostart();
      this.busy.autostart = false;
    }
  },
};
