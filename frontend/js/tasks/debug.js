import { extractApiError } from '../methods/utils.js';

export const debugTaskMethods = {
  async startDebug(taskId) {
    this.debugLoading = true;
    try {
      const data = await this.$apiService.debug.start(taskId);
      this.debugSession = data;
      // P1-FE-6: 构建 Map 加速步骤结果查询
      this._resultByIndex = new Map((data.results || []).map(r => [r.step_index, r]));
      this.frontendLogger.info('debug', `开始调试任务 ${taskId}`);
      this.openModal('.debug-overlay');
    } catch (error) {
      const msg = extractApiError(error, '启动调试失败');
      this.frontendLogger.error('debug', '启动调试失败: ' + msg);
      this.toastOnly(false, msg);
    } finally {
      this.debugLoading = false;
    }
  },

  async _debugAction(apiCall, errorMsg) {
    this.busy.debug = true;
    try {
      const data = await apiCall();
      this.debugSession = data;
      // P1-FE-6: 构建 Map 加速步骤结果查询
      this._resultByIndex = new Map((data.results || []).map(r => [r.step_index, r]));
    } catch (error) {
      const msg = extractApiError(error, errorMsg);
      this.frontendLogger.error('debug', errorMsg + ': ' + msg);
      this.toastOnly(false, msg);
    } finally {
      this.busy.debug = false;
    }
  },

  debugNextStep() {
    return this._debugAction(() => this.$apiService.debug.next(), '执行步骤失败');
  },

  debugRunAll() {
    return this._debugAction(() => this.$apiService.debug.runAll(), '执行全部失败');
  },

  async debugStop() {
    this.closeModal();
    try {
      const data = await this.$apiService.debug.stop();
      this.frontendLogger.info('debug', '调试已停止');
      this.toastOnly(true, data.message || '调试已停止');
    } catch (error) {
      this.frontendLogger.error('debug', '停止调试失败', error);
      this.toastOnly(false, '停止调试失败');
    } finally {
      // 无论 API 成功失败都重置本地状态（调试会话已不可用）
      this.debugSession = {
        running: false, task_id: null, current_step: 0,
        total_steps: 0, steps: [], results: [], screenshot_url: null,
      };
      this._resultByIndex = new Map();
    }
  },

  getDebugStepResult(index) {
    // P1-FE-6: 用 Map O(1) 查询替代 Array.find O(n)
    return this._resultByIndex?.get(index) || null;
  },

  getDebugStepStatus(index) {
    const result = this.getDebugStepResult(index);
    if (result) return result.success ? 'success' : 'failed';
    if (index === this.debugSession.current_step) return 'current';
    return 'pending';
  },
};
