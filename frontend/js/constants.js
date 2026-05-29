export const api = window.axios.create({
  timeout: 10000,
});

export const LOG_LEVELS = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
};

export const BROWSER_ARGS_DEFAULT = "--disable-blink-features=AutomationControlled\n--disable-software-rasterizer\n--disable-extensions\n--disable-background-timer-throttling\n--disable-backgrounding-occluded-windows\n--disable-renderer-backgrounding\n--disable-features=TranslateUI,BlinkGenPropertyTrees\n--disable-ipc-flooding-protection\n--disable-hang-monitor\n--disable-popup-blocking";

// 浏览器与监控参数的共享默认值（DEFAULT_CONFIG 和 DEFAULT_PROFILE_SETTINGS 共用）
const _SHARED_DEFAULTS = {
  carrier: "无",
  carrier_custom: "",
  check_interval_seconds: 300,
  auto_start: false,
  headless: true,
  browser_timeout: 8,
  browser_navigation_timeout: 15,
  login_timeout: 60,
  max_retries: 3,
  retry_interval: 5,
  browser_low_resource_mode: false,
  browser_disable_web_security: false,
  browser_extra_headers_json: "",
  browser_args: BROWSER_ARGS_DEFAULT,
  stealth_mode: false,
  stealth_custom_script: "",
  pause_enabled: true,
  pause_start_hour: 0,
  pause_end_hour: 6,
  network_targets: "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443",
  http_targets: "https://www.baidu.com,https://www.qq.com",
  enable_local_check: true,
  enable_tcp_check: true,
  enable_http_check: true,
  check_auth_url: true,
  auth_url_targets: "",
  custom_variables: {},
};

export const DEFAULT_CONFIG = {
  ..._SHARED_DEFAULTS,
  username: "",
  password: "",
  use_global_credentials: true,
  auth_url: "",
  active_task: "",
  browser_user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
  portal_check_urls: "http://captive.apple.com/hotspot-detect.html|Success\nhttp://www.msftconnecttest.com/connecttest.txt|Microsoft Connect Test\nhttp://detectportal.firefox.com/success.txt|success",
  backend_log_level: "INFO",
  frontend_log_level: "INFO",
  access_log: false,
  minimize_to_tray: true,
  auto_open_browser: false,
  login_then_exit: false,
  log_retention_days: 7,
  proxy: "",
  block_proxy: true,
  browser_locale: "zh-CN",
  browser_timezone: "Asia/Shanghai",
  browser_viewport_width: 1280,
  browser_viewport_height: 720,
  network_check_timeout: 2,
  app_port: 50721,
};

export const SETTINGS_TABS = [
  { id: 'account', label: '账号设置', hint: '账号、密码与认证地址' },
  { id: 'monitor', label: '网络与监控', hint: '检测策略、重试与代理' },
  { id: 'system', label: '系统与日志', hint: '日志、自启动与配置备份' },
  { id: 'browser', label: '浏览器设置', hint: '请求头、图片与浏览器参数' },
  { id: 'tasks', label: '任务设置', hint: '活动任务与模板入口' },
];

export const DEFAULT_PROFILE_SETTINGS = {
  ..._SHARED_DEFAULTS,
  name: '',
  match_gateway_ip: '',
  match_ssid: '',
  username: '',
  password: '',
  use_global_credentials: true,
  use_global_advanced: true,
  use_global_auth_url: true,
  use_global_task: true,
  auth_url: '',
  active_task: '',
  browser_user_agent: '',
};
