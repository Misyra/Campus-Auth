export const api = window.axios.create({
  timeout: 10000,
});

// 请求重试配置
const RETRY_CONFIG = {
  maxRetries: 2,
  retryDelay: 1000,
  retryableStatuses: [408, 429, 500, 502, 503, 504],
};

// 响应拦截器：对网络错误和 5xx 状态码自动重试
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;
    if (!config || config.__retryCount >= RETRY_CONFIG.maxRetries) {
      return Promise.reject(error);
    }
    const status = error?.response?.status;
    const isNetworkError = !error.response;
    const isRetryable = isNetworkError || RETRY_CONFIG.retryableStatuses.includes(status);
    if (!isRetryable) return Promise.reject(error);

    config.__retryCount = (config.__retryCount || 0) + 1;
    const delay = RETRY_CONFIG.retryDelay * Math.pow(2, config.__retryCount - 1);
    await new Promise(r => setTimeout(r, delay));
    return api(config);
  }
);

export const TIMING = {
  STATUS_POLL_INTERVAL: 30000,    // 状态轮询间隔（ms）
  AUTOSTART_POLL_INTERVAL: 60000, // 自启动轮询间隔（ms）
  TOAST_DURATION: 3000,           // Toast 显示时长（ms）
  TOAST_LEAVE_DELAY: 300,         // Toast 离场动画时长（ms）
  NOTIFICATION_MAX: 30,           // 通知最大条数
  WS_READY_TIMEOUT: 2000,         // WebSocket 就绪等待超时（ms）
  OPENAPI_TIMEOUT: 5000,          // OpenAPI 请求超时（ms）
  DRAG_SWAP_COOLDOWN: 120,        // 拖拽交换冷却时间（ms）
};

export const LIMITS = {
  LOG_MAX_ENTRIES: 100,           // 前端日志最大条数
  FILE_UPLOAD_MAX: 5 * 1024 * 1024, // 文件上传最大大小（5MB）
  SCROLL_BOTTOM_THRESHOLD: 50,    // 判断滚动到底部的阈值（px）
};

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
  check_interval_milliseconds: 0,
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
  shell_path: "",
};

export const SETTINGS_TABS = [
  { id: 'account', label: '账号设置', hint: '账号、密码与认证地址' },
  { id: 'monitor', label: '网络与监控', hint: '检测策略、重试与代理' },
  { id: 'system', label: '系统与日志', hint: '日志、自启动与配置备份' },
  { id: 'browser', label: '浏览器设置', hint: '请求头、图片与浏览器参数' },
  { id: 'tasks', label: '任务设置', hint: '活动任务与模板入口' },
];

// 外观设置默认值
export const DEFAULT_APPEARANCE = {
  background_url: '',
  background_filename: '',
  wallpaper_api_url: '',
  background_blur: 10,
  background_opacity: 0.3,
  background_color: '#0f172a',
  card_opacity: 0.45,
  border_intensity: 1.0,
  sidebar_opacity: 0.95,
  sidebar_color: '',
  sidebar_accent: '',
  backdrop_filter: false, // 毛玻璃效果
  accent_color: '#22d3ee',
  zoom: 100,
  theme: 'dark', // dark | light
};

// 预设背景色
export const BG_COLORS = [
  { value: '#0f172a', label: '深空蓝' },
  { value: '#111827', label: '墨石黑' },
  { value: '#1a1a2e', label: '暗夜紫' },
  { value: '#16213e', label: '藏青' },
  { value: '#1b2838', label: 'Steam 暗' },
  { value: '#0d1117', label: 'GitHub 暗' },
];

// 预设主题色
export const ACCENT_COLORS = [
  { value: '#22d3ee', label: '青色' },
  { value: '#3b82f6', label: '蓝色' },
  { value: '#8b5cf6', label: '紫色' },
  { value: '#ec4899', label: '粉色' },
  { value: '#f59e0b', label: '橙色' },
  { value: '#10b981', label: '绿色' },
  { value: '#ef4444', label: '红色' },
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
