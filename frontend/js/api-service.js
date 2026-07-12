/**
 * API 服务层 — 集中管理路径、请求参数和响应解包。
 *
 * 约定：
 * - 所有写操作返回 ApiResponse: { success, message, data? }
 * - GET 操作直接返回响应数据
 * - 异常统一向上抛出，由调用方 catch 处理
 */
import { api } from './constants.js';

export const apiService = {
  // ── 配置 ──
  config: {
    fetch: () => api.get('/api/config').then(r => r.data),
    save: (payload, opts) => api.put('/api/config', payload, opts).then(r => r.data),
    patch: (payload, opts) => api.patch('/api/config', payload, opts).then(r => r.data),
    fetchDefaults: () => api.get('/api/config/defaults').then(r => r.data),
    fetchLogLevels: () => api.get('/api/config/log-levels').then(r => r.data),
    setLogLevel: (level) => api.put('/api/config/log-level', { level }).then(r => r.data),
    fetchStealthScript: () => api.get('/api/config/default-stealth-script').then(r => r.data),
  },

  // ── 监控与操作 ──
  monitor: {
    fetchStatus: () => api.get('/api/status').then(r => r.data),
    start: () => api.post('/api/monitor/start').then(r => r.data),
    stop: () => api.post('/api/monitor/stop').then(r => r.data),
    fetchInterfaces: () => api.get('/api/network/interfaces').then(r => r.data),
  },

  // ── 登录操作 ──
  actions: {
    login: (timeoutMs) => api.post('/api/actions/login', null, { timeout: timeoutMs }).then(r => r.data),
    cancelLogin: () => api.post('/api/actions/cancel-login').then(r => r.data),
    testNetwork: () => api.post('/api/actions/test-network', null, { timeout: 5000 }).then(r => r.data),
  },

  // ── 系统 ──
  system: {
    health: () => api.get('/api/health').then(r => r.data),
    initStatus: () => api.get('/api/init-status').then(r => r.data),
    checkUpdate: () => api.get('/api/check-update').then(r => r.data),
    agree: () => api.post('/api/agree').then(r => r.data),
    shutdown: () => api.post('/api/shutdown').then(r => r.data),
    fetchLogs: (limit) => api.get('/api/logs', { params: { limit } }).then(r => r.data),
  },

  // ── 方案 ──
  profiles: {
    list: () => api.get('/api/profiles').then(r => r.data),
    get: (id) => api.get(`/api/profiles/${id}`).then(r => r.data),
    save: (id, payload) => api.put(`/api/profiles/${id}`, payload).then(r => r.data),
    delete: (id) => api.delete(`/api/profiles/${id}`).then(r => r.data),
    setActive: (id) => api.post(`/api/profiles/active/${id}`).then(r => r.data),
    detect: () => api.post('/api/profiles/detect').then(r => r.data),
    toggleAutoSwitch: (enabled) => api.post('/api/profiles/auto-switch', { enabled }).then(r => r.data),
  },

  // ── 自启动 ──
  autostart: {
    fetchStatus: () => api.get('/api/autostart/status').then(r => r.data),
    toggle: (enable) => api.post(`/api/autostart/${enable ? 'enable' : 'disable'}`).then(r => r.data),
    setMode: (runtime_mode) => api.post('/api/autostart/mode', { runtime_mode }).then(r => r.data),
  },

  // ── OCR ──
  ocr: {
    fetchStatus: () => api.get('/api/ocr/status').then(r => r.data),
    install: () => api.post('/api/ocr/install').then(r => r.data),
    uninstall: () => api.post('/api/ocr/uninstall').then(r => r.data),
  },

  // ── 历史 ──
  history: {
    fetch: (limit) => api.get('/api/login-history', { params: { limit } }).then(r => r.data),
    clear: () => api.delete('/api/login-history').then(r => r.data),
  },

  // ── 卸载 ──
  uninstall: {
    detect: () => api.get('/api/uninstall/detect').then(r => r.data),
    perform: (keys) => api.post('/api/uninstall', { keys }).then(r => r.data),
  },

  // ── 浏览器 ──
  browsers: {
    fetch: () => api.get('/api/browsers').then(r => r.data),
    installPlaywright: (opts) => api.post('/api/browsers/install-playwright', null, opts).then(r => r.data),
  },

  // ── 调试 ──
  debug: {
    start: (taskId) => api.post('/api/debug/start', { task_id: taskId }).then(r => r.data),
    next: () => api.post('/api/debug/next').then(r => r.data),
    runAll: () => api.post('/api/debug/run-all').then(r => r.data),
    stop: () => api.post('/api/debug/stop').then(r => r.data),
  },
};
