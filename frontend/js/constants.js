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
    const jitter = Math.random() * 1000;
    const delay = RETRY_CONFIG.retryDelay * Math.pow(2, config.__retryCount - 1) + jitter;
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
  WS_BACKOFF_BASE: 1000,          // WebSocket 重连退避基础延迟（ms）
  WS_BACKOFF_MAX: 30000,          // WebSocket 重连退避上限（ms）
  WS_PING_INTERVAL: 30000,        // WebSocket 应用层 ping 间隔（ms）
};

export const LIMITS = {
  LOG_MAX_ENTRIES: 100,           // 前端日志最大条数
  FILE_UPLOAD_MAX: 5 * 1024 * 1024, // 文件上传最大大小（5MB）
  SCROLL_BOTTOM_THRESHOLD: 50,    // 判断滚动到底部的阈值（px）
  WS_LOG_BUFFER_MAX: 100,         // WS 断连期间前端日志缓冲上限
  WS_LOG_FLUSH_BATCH: 20,         // 单次 flush 最多发送的日志条数（背压）
};

// 日志级别选项
export const LOG_LEVELS = [
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' },
];

// 日志级别数值映射（数值越大级别越高）
export const LEVEL_VALUES = Object.fromEntries(LOG_LEVELS.map((l, i) => [l.value, i]));
// { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3 }

// 日志来源列表
export const LOG_SOURCES = [
  { value: "backend",  label: "backend" },
  { value: "frontend", label: "frontend" }
];


export const DEFAULT_CONFIG = {
  browser: {
    headless: true,
    timeout: 8,
    navigation_timeout: 8,
    login_timeout: 90,
    user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    low_resource_mode: false,
    disable_web_security: false,
    browser_args: "--disable-blink-features=AutomationControlled\n--disable-software-rasterizer\n--disable-extensions\n--disable-background-timer-throttling\n--disable-backgrounding-occluded-windows\n--disable-renderer-backgrounding\n--disable-features=TranslateUI,BlinkGenPropertyTrees\n--disable-ipc-flooding-protection\n--disable-hang-monitor\n--disable-popup-blocking",
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
    script_timeout: 60,
    bind_interface_name: '',
  },
  pause: {
    enabled: true,
    start_hour: 0,
    end_hour: 6,
  },
  logging: {
    level: "INFO",
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
  app_settings: {
    block_proxy: true,
    startup_action: "none",
    runtime_mode: "full",
    lightweight_tray: true,
    minimize_to_tray: true,
    auto_open_browser: false,
    proxy: "",
    app_port: 50721,
  },
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
  background_color: '',
  card_opacity: 0.45,
  card_blur: 12,
  border_intensity: 1.0,
  sidebar_opacity: 0.95,
  sidebar_color: '',
  sidebar_accent: '',
  backdrop_filter: false, // 毛玻璃效果
  accent_color: '#22d3ee',
  theme: 'light', // light | dark | auto
};

// 预设背景色（深色）
export const DARK_BG_COLORS = [
  { value: '#0f172a', label: '深空蓝' },
  { value: '#111827', label: '墨石黑' },
  { value: '#1a1a2e', label: '暗夜紫' },
  { value: '#16213e', label: '藏青' },
  { value: '#1b2838', label: 'Steam 暗' },
  { value: '#0d1117', label: 'GitHub 暗' },
];

// 预设背景色（浅色）
export const LIGHT_BG_COLORS = [
  { value: '#eef2f7', label: '默认灰白' },
  { value: '#f8fafc', label: '纯白' },
  { value: '#f1f5f9', label: '浅灰' },
  { value: '#e8edf5', label: '淡蓝灰' },
  { value: '#fef3c7', label: '暖黄' },
  { value: '#ecfdf5', label: '薄荷绿' },
];


// 自定义颜色默认结构（按类型分组，持久化到 localStorage 'appearance.custom_colors'）
export const DEFAULT_CUSTOM_COLORS = {
  accent: [],
  bg: [],
  sidebar: [],
  sidebar_accent: [],
};

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
};
