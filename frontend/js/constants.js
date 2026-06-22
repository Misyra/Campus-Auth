export const api = window.axios.create({
  timeout: 10000,
});

// 请求重试配置
const RETRY_CONFIG = {
  maxRetries: 2,
  retryDelay: 1000,
  retryableStatuses: [408, 429, 500, 502, 503, 504],
};

// 响应拦截器：对网络错误和 5xx 状态码自动重试（仅幂等方法）
const RETRYABLE_METHODS = ['GET', 'HEAD', 'OPTIONS'];
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;
    if (!config || config.__retryCount >= RETRY_CONFIG.maxRetries) {
      return Promise.reject(error);
    }

    // 仅允许幂等方法自动重试
    if (!RETRYABLE_METHODS.includes(config.method?.toUpperCase())) {
      return Promise.reject(error);
    }

    const status = error?.response?.status;
    const isCanceled = error.code === 'ERR_CANCELED' || error.name === 'CanceledError';
    const isNetworkError = !error.response && !isCanceled;
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

// 日志级别选项
export const LOG_LEVELS = [
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' },
  { value: 'CRITICAL', label: 'CRITICAL' },
];

// 日志级别数值映射（数值越大级别越高）
export const LEVEL_VALUES = Object.fromEntries(LOG_LEVELS.map((l, i) => [l.value, i]));
// { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 }

// 日志来源列表
export const LOG_SOURCES = [
  { value: 'backend', label: 'backend', color: '#4fc3f7' },
  { value: 'network', label: 'network', color: '#81c784' },
  { value: 'task', label: 'task', color: '#fff176' },
  { value: 'frontend', label: 'frontend', color: '#ce93d8' },
  { value: 'debug', label: 'debug', color: '#ffab91' },
];

export const BROWSER_ARGS_DEFAULT = "--disable-blink-features=AutomationControlled\n--disable-software-rasterizer\n--disable-extensions\n--disable-background-timer-throttling\n--disable-backgrounding-occluded-windows\n--disable-renderer-backgrounding\n--disable-features=TranslateUI,BlinkGenPropertyTrees\n--disable-ipc-flooding-protection\n--disable-hang-monitor\n--disable-popup-blocking";

export const DEFAULT_CONFIG = {
  browser: {
    headless: true,
    timeout: 8,
    navigation_timeout: 15,
    login_timeout: 90,
    user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    low_resource_mode: false,
    disable_web_security: false,
    extra_headers_json: "",
    browser_args: BROWSER_ARGS_DEFAULT,
    stealth_mode: false,
    stealth_custom_script: "",
    locale: "zh-CN",
    timezone_id: "Asia/Shanghai",
    viewport_width: 1280,
    viewport_height: 720,
    pure_mode: true,
    browser_channel: "msedge",
    browser_custom_path: "",
    custom_browser_engine: "auto",
  },
  monitor: {
    check_interval_seconds: 300,
    network_check_timeout: 2,
    ping_targets: ["8.8.8.8:53", "114.114.114.114:53", "www.baidu.com:443"],
    enable_tcp_check: false,
    enable_http_check: false,
    enable_local_check: true,
    test_urls: [
      "https://connect.rom.miui.com/generate_204",
      "https://connectivitycheck.platform.hicloud.com/generate_204",
    ],
    check_auth_url: false,
    auth_url_targets: [],
    url_check_urls: [
      "http://captive.apple.com/hotspot-detect.html|Success",
      "http://www.msftconnecttest.com/connecttest.txt|Microsoft Connect Test",
      "http://detectportal.firefox.com/success.txt|success",
    ],
  },
  pause: {
    enabled: true,
    start_hour: 0,
    end_hour: 6,
  },
  logging: {
    level: "INFO",
    frontend_level: "INFO",
    log_retention_days: 7,
    access_log: false,
  },
  retry: {
    max_retries: 3,
    retry_interval: 5,
  },
  credentials: {
    username: "",
    password: "",
    auth_url: "",
    isp: "",
    carrier_custom: "",
  },
  active_task: "",
  custom_variables: {},
  block_proxy: true,
  shell_path: "",
  minimize_to_tray: true,
  lightweight_tray: true,
  startup_action: "none",
  autostart_lightweight: true,
  auto_open_browser: false,
  proxy: "",
  app_port: 50721,
};

export const SETTINGS_TABS = [
  { id: 'account', label: '账号设置', hint: '账号、密码与认证地址' },
  { id: 'monitor', label: '网络与监控', hint: '检测策略、重试与代理' },
  { id: 'system', label: '系统与日志', hint: '日志、自启动与启动行为' },
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
  card_blur: 12,
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
  name: '',
  match_gateway_ip: '',
  match_ssid: '',
  username: '',
  password: '',
  auth_url: '',
  active_task: '',
  carrier: "无",
  carrier_custom: "",
  check_interval_seconds: 300,
  browser_channel: "msedge",
  browser_custom_path: "",
  headless: true,
  browser_timeout: 8,
  browser_navigation_timeout: 15,
  login_timeout: 90,
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
