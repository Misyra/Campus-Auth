export const api = window.axios.create({
  timeout: 10000,
});

export const LOG_LEVELS = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
};

export const DEFAULT_BROWSER_USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

export const DEFAULT_CONFIG = {
  username: "",
  password: "",
  auth_url: "http://172.29.0.2",
  carrier: "无",
  carrier_custom: "",
  check_interval_minutes: 5,
  auto_start: false,
  headless: false,
  browser_timeout: 8000,
  browser_user_agent: DEFAULT_BROWSER_USER_AGENT,
  browser_low_resource_mode: false,
  browser_disable_web_security: false,
  browser_extra_headers_json: "",
  pause_enabled: true,
  pause_start_hour: 0,
  pause_end_hour: 6,
  network_targets: "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443",
  backend_log_level: "INFO",
  frontend_log_level: "INFO",
  access_log: false,
  minimize_to_tray: false,
  custom_variables: {},
};

export const SETTINGS_TABS = [
  { id: 'account', label: '账号设置', hint: '账号、密码与认证地址' },
  { id: 'system', label: '系统设置', hint: '监控、日志与行为控制' },
  { id: 'browser', label: '浏览器设置', hint: '请求头、图片与浏览器参数' },
  { id: 'tasks', label: '任务设置', hint: '活动任务与模板入口' },
];
