import { extractApiError } from '../methods/utils.js';

export const debugTaskMethods = {
  async startDebug(taskId) {
    this.debugLoading = true;
    try {
      const { data } = await this.$api.post('/api/debug/start', { task_id: taskId });
      this.debugSession = data;
      this.frontendLogger.info('debug', `开始调试任务 ${taskId}`);
    } catch (error) {
      const msg = extractApiError(error, '启动调试失败');
      this.frontendLogger.error('debug', '启动调试失败: ' + msg);
      this.notify(false, msg);
    } finally {
      this.debugLoading = false;
    }
  },

  async _debugAction(endpoint, errorMsg) {
    this.busy.debug = true;
    try {
      const { data } = await this.$api.post(endpoint);
      this.debugSession = data;
    } catch (error) {
      const msg = extractApiError(error, errorMsg);
      this.frontendLogger.error('debug', errorMsg + ': ' + msg);
      this.notify(false, msg);
    } finally {
      this.busy.debug = false;
    }
  },

  debugNextStep() {
    return this._debugAction('/api/debug/next', '执行步骤失败');
  },

  debugRunAll() {
    return this._debugAction('/api/debug/run-all', '执行全部失败');
  },

  async debugStop() {
    try {
      const { data } = await this.$api.post('/api/debug/stop');
      this.debugSession = {
        running: false, task_id: null, current_step: 0,
        total_steps: 0, steps: [], results: [], screenshot_url: null,
      };
      this.frontendLogger.info('debug', '调试已停止');
      this.notify(true, data.message || '调试已停止');
    } catch (error) {
      this.frontendLogger.error('debug', '停止调试失败', error);
      this.notify(false, '停止调试失败');
    }
  },

  getDebugStepResult(index) {
    return this.debugSession.results.find(r => r.step_index === index) || null;
  },

  getDebugStepStatus(index) {
    const result = this.getDebugStepResult(index);
    if (result) return result.success ? 'success' : 'failed';
    if (index === this.debugSession.current_step) return 'current';
    return 'pending';
  },
};
