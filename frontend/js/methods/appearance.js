import { DEFAULT_APPEARANCE, DEFAULT_CUSTOM_COLORS, ACCENT_COLORS, DARK_BG_COLORS, LIGHT_BG_COLORS, LIMITS } from '../constants.js';
import { hexToRgb, adjustColor } from './formatters.js';
import { pickFile } from './utils.js';

export const appearanceMethods = {
  // 保存外观设置
  saveAppearance() {
    // 持久化和 applyAppearance 由 app-options.js 中的 watcher 统一负责（100ms 防抖）
    this.toastOnly(true, '外观设置已保存');
  },

  // 重置外观设置
  resetAppearance() {
    if (!confirm('确定要恢复默认外观设置吗？')) return;
    this.appearance = { ...DEFAULT_APPEARANCE };
    this.customColors = { ...DEFAULT_CUSTOM_COLORS };
    localStorage.removeItem('appearance');
    localStorage.removeItem('appearance.custom_colors');
    this.applyAppearance();
    this.toastOnly(true, '已恢复默认外观');
  },

  // 新增自定义颜色（picker 选色后调用）
  addCustomColor(type, hex) {
    if (!hex || !DEFAULT_CUSTOM_COLORS.hasOwnProperty(type)) return;
    hex = hex.toLowerCase();
    // 去重：系统预设或已存在的自定义色不重复加入
    const systemColors = type === 'accent' ? ACCENT_COLORS : type === 'bg' ? [...DARK_BG_COLORS, ...LIGHT_BG_COLORS] : [];
    if (systemColors.some(c => c.value.toLowerCase() === hex)) return;
    if (this.customColors[type].some(c => c.toLowerCase() === hex)) return;
    this.customColors[type].push(hex);
    localStorage.setItem('appearance.custom_colors', JSON.stringify(this.customColors));
  },

  // 删除自定义颜色（长按或右键触发）
  removeCustomColor(type, hex) {
    if (!DEFAULT_CUSTOM_COLORS.hasOwnProperty(type)) return;
    const idx = this.customColors[type].findIndex(c => c.toLowerCase() === hex.toLowerCase());
    if (idx === -1) return;
    this.customColors[type].splice(idx, 1);
    localStorage.setItem('appearance.custom_colors', JSON.stringify(this.customColors));
    // 若该色正被使用，回退到默认色
    const defaultKey = type === 'accent' ? 'accent_color'
      : type === 'bg' ? 'background_color'
      : type === 'sidebar' ? 'sidebar_color'
      : 'sidebar_accent';
    if ((this.appearance[defaultKey] || '').toLowerCase() === hex.toLowerCase()) {
      this.appearance[defaultKey] = DEFAULT_APPEARANCE[defaultKey];
    }
  },

  // 重置单张分区卡（cardKey: 'background' | 'theme' | 'card' | 'sidebar'）
  resetCard(cardKey) {
    const fields = {
      background: ['background_url', 'background_filename', 'wallpaper_api_url', 'background_blur', 'background_opacity', 'backdrop_filter', 'card_blur'],
      theme: ['theme', 'accent_color', 'background_color'],
      card: ['card_opacity', 'border_intensity'],
      sidebar: ['sidebar_opacity', 'sidebar_color', 'sidebar_accent'],
    }[cardKey];
    if (!fields) return;
    // 先捕获待删除文件名（重置后会丢失）
    const filenameToDelete = cardKey === 'background' ? this.appearance.background_filename : '';
    fields.forEach(f => {
      this.appearance[f] = DEFAULT_APPEARANCE[f];
    });
    // 背景卡重置时清理已上传文件（可能已不存在，静默失败）
    if (filenameToDelete) {
      this.$api.delete(`/api/background/${filenameToDelete}`).catch(() => {});
    }
    this.applyAppearance();
    this.toastOnly(true, '已恢复默认');
  },

  // 判断分区卡是否有项偏离默认
  cardDirty(cardKey) {
    const fields = {
      background: ['background_url', 'background_blur', 'background_opacity', 'backdrop_filter', 'card_blur'],
      theme: ['theme', 'accent_color', 'background_color'],
      card: ['card_opacity', 'border_intensity'],
      sidebar: ['sidebar_opacity', 'sidebar_color', 'sidebar_accent'],
    }[cardKey] || [];
    return fields.some(f => this.appearance[f] !== DEFAULT_APPEARANCE[f]);
  },

  // 触发自定义色 picker（hidden input click）
  pickCustomColor(type) {
    const input = document.querySelector(`input[data-color-picker="${type}"]`);
    if (input) input.click();
  },

  // picker onchange：选色后加入自定义列表并设为当前值
  onCustomColorPicked(type, event) {
    const hex = event.target.value;
    this.addCustomColor(type, hex);
    const fieldMap = {
      accent: 'accent_color',
      bg: 'background_color',
      sidebar: 'sidebar_color',
      sidebar_accent: 'sidebar_accent',
    };
    this.appearance[fieldMap[type]] = hex;
    event.target.value = '#000000'; // 重置 picker
  },

  // 长按/右键删除自定义色
  onColorLongPress(type, hex, event) {
    event.preventDefault();
    if (confirm(`删除自定义颜色 ${hex}？`)) {
      this.removeCustomColor(type, hex);
    }
  },

  // 移动端长按触发（touchstart 启动 600ms 计时器）
  startLongPress(type, hex, event) {
    // 同步阻止默认行为（防止长按文本选择/上下文菜单）
    event.preventDefault();
    let timer = setTimeout(() => {
      this.onColorLongPress(type, hex, event);
    }, 600);
    // 触摸结束或移动时取消
    const cancel = () => {
      clearTimeout(timer);
      event.target.removeEventListener('touchend', cancel);
      event.target.removeEventListener('touchmove', cancel);
    };
    event.target.addEventListener('touchend', cancel);
    event.target.addEventListener('touchmove', cancel);
  },

  // 获取合并后的颜色列表（系统预设 + 自定义，bg 类型按主题切换）
  getColorList(type) {
    let systemColors;
    if (type === 'bg') {
      const effectiveTheme = this.getEffectiveTheme();
      systemColors = effectiveTheme === 'dark' ? DARK_BG_COLORS : LIGHT_BG_COLORS;
    } else {
      systemColors = type === 'accent' ? ACCENT_COLORS : [];
    }
    const custom = (this.customColors[type] || []).map(hex => ({ value: hex, label: hex, custom: true }));
    return [...systemColors, ...custom];
  },

  // 获取当前生效的主题（解析 auto）
  getEffectiveTheme() {
    const themeMode = this.appearance.theme || 'light';
    if (themeMode === 'auto') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return themeMode;
  },

  // 恢复当前主题的默认背景色
  resetThemeBackground() {
    this.appearance.background_color = '';
    this.applyAppearance();
    this.toastOnly(true, '已恢复默认背景色');
  },

  // 应用外观设置到页面
  applyAppearance() {
    const root = document.documentElement;
    const body = document.body;

    // 背景图片
    if (this.appearance.background_url) {
      body.style.setProperty('--bg-image', `url(${this.appearance.background_url})`);
      body.style.setProperty('--bg-blur', `blur(${this.appearance.background_blur}px)`);
      body.style.setProperty('--bg-opacity', this.appearance.background_opacity);
      body.classList.add('has-custom-bg');
    } else {
      body.classList.remove('has-custom-bg');
      body.style.removeProperty('--bg-image');
      body.style.removeProperty('--bg-blur');
      body.style.removeProperty('--bg-opacity');
    }

    // 毛玻璃效果
    if (this.appearance.backdrop_filter) {
      body.classList.remove('no-backdrop-filter');
    } else {
      body.classList.add('no-backdrop-filter');
    }

    // 主题色
    if (this.appearance.accent_color) {
      root.style.setProperty('--accent', this.appearance.accent_color);
      root.style.setProperty('--accent-hover', adjustColor(this.appearance.accent_color, -20));
      const accentRgb = hexToRgb(this.appearance.accent_color);
      if (accentRgb) {
        root.style.setProperty('--accent-rgb', `${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}`);
      }
    }

    // 主题
    const themeMode = this.appearance.theme || 'light';
    let effectiveTheme = themeMode;
    if (themeMode === 'auto') {
      effectiveTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    root.setAttribute('data-theme', effectiveTheme);

    const isLight = effectiveTheme === 'light';
    const _p = (k, v) => root.style.setProperty(k, v);

    // 背景色
    if (isLight) {
      if (this.appearance.background_color) {
        const bgRgb = hexToRgb(this.appearance.background_color);
        if (bgRgb) {
          _p('--bg-primary', this.appearance.background_color);
          _p('--bg-secondary', `rgb(${Math.min(bgRgb.r + 15, 255)}, ${Math.min(bgRgb.g + 15, 255)}, ${Math.min(bgRgb.b + 15, 255)})`);
        }
      } else {
        _p('--bg-primary', '#eef2f7');
        _p('--bg-secondary', '#e4e9f0');
      }
    } else if (this.appearance.background_color) {
      const bgRgb = hexToRgb(this.appearance.background_color);
      if (bgRgb) {
        _p('--bg-primary', this.appearance.background_color);
        _p('--bg-secondary', `rgb(${Math.min(bgRgb.r + 15, 255)}, ${Math.min(bgRgb.g + 15, 255)}, ${Math.min(bgRgb.b + 15, 255)})`);
      }
    } else {
      _p('--bg-primary', '#0f172a');
      _p('--bg-secondary', '#1e293b');
    }

    // 卡片透明度与毛玻璃模糊
    const co = this.appearance.card_opacity;
    const blurPx = this.appearance.card_blur ?? 12;
    if (this.appearance.backdrop_filter && blurPx > 0) {
      _p('--card-blur', `blur(${blurPx}px)`);
    } else {
      _p('--card-blur', 'none');
    }

    if (isLight) {
      _p('--bg-card', `rgba(255, 255, 255, ${co})`);
    } else {
      const cardRgb = hexToRgb(this.appearance.background_color || '#0f172a');
      if (cardRgb) {
        _p('--bg-card', `rgba(${cardRgb.r}, ${cardRgb.g}, ${cardRgb.b}, ${co})`);
      }
    }

    // 边框可见度
    const bi = this.appearance.border_intensity;
    if (isLight) {
      _p('--border', `rgba(100, 116, 139, ${0.12 * bi})`);
      _p('--border-hover', `rgba(100, 116, 139, ${0.22 * bi})`);
      _p('--border-accent', `rgba(56, 189, 248, ${0.15 * bi})`);
    } else {
      _p('--border', `rgba(148, 163, 184, ${0.1 * bi})`);
      _p('--border-hover', `rgba(148, 163, 184, ${0.2 * bi})`);
      _p('--border-accent', `rgba(56, 189, 248, ${0.15 * bi})`);
    }

    // 侧边栏透明度
    _p('--sidebar-opacity', this.appearance.sidebar_opacity);

    // 侧边栏背景色
    if (this.appearance.sidebar_color) {
      // 用户自定义颜色
      const sidebarRgb = hexToRgb(this.appearance.sidebar_color);
      if (sidebarRgb) {
        _p('--sidebar-bg-1', `rgba(${sidebarRgb.r}, ${sidebarRgb.g}, ${sidebarRgb.b}, var(--sidebar-opacity))`);
        _p('--sidebar-bg-2', `rgba(${sidebarRgb.r}, ${sidebarRgb.g}, ${sidebarRgb.b}, calc(var(--sidebar-opacity) + 0.03))`);
      }
    } else if (isLight) {
      _p('--sidebar-bg-1', 'rgba(241, 245, 249, var(--sidebar-opacity))');
      _p('--sidebar-bg-2', 'rgba(226, 232, 240, calc(var(--sidebar-opacity) + 0.03))');
    } else {
      // 深色主题从背景色推导
      const bgRgb = hexToRgb(this.appearance.background_color || '#0f172a');
      if (bgRgb) {
        _p('--sidebar-bg-1', `rgba(${Math.min(bgRgb.r + 15, 255)}, ${Math.min(bgRgb.g + 15, 255)}, ${Math.min(bgRgb.b + 15, 255)}, var(--sidebar-opacity))`);
        _p('--sidebar-bg-2', `rgba(${Math.max(bgRgb.r - 10, 0)}, ${Math.max(bgRgb.g - 10, 0)}, ${Math.max(bgRgb.b - 10, 0)}, calc(var(--sidebar-opacity) + 0.03))`);
      }
    }

    // 侧边栏活跃项高亮色
    if (this.appearance.sidebar_accent) {
      _p('--sidebar-accent', this.appearance.sidebar_accent);
    } else {
      root.style.removeProperty('--sidebar-accent');
    }
  },

  // 选择背景图片（上传到服务器）
  async selectBackgroundImage() {
    const file = await pickFile('image/*');
    if (!file) return;

    if (file.size > LIMITS.FILE_UPLOAD_MAX) {
      this.toastOnly(false, '图片大小不能超过 5MB');
      return;
    }

    try {
      const formData = new FormData();
      formData.append('file', file);

      const { data } = await this.$api.post('/api/background/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      // ApiResponse 信封：{ success, message, data: { filename, url } }
      this.appearance.background_url = data.data.url;
      this.appearance.background_filename = data.data.filename;
      this.applyAppearance();
      this.toastOnly(true, '背景图片已设置');
    } catch (err) {
      console.error('上传背景图片失败:', err);
      this.toastOnly(false, '上传失败: ' + (err.response?.data?.detail || err.message));
    }
  },

  // 打开随机壁纸对话框
  openRandomWallpaperDialog() {
    this.randomWallpaperDialog.url = this.appearance.wallpaper_api_url || 'https://t.alcy.cc/pc';
    this.randomWallpaperDialog.loading = false;
    this.randomWallpaperDialog.visible = true;
    this.openModal('.random-wallpaper-overlay');
  },

  // 关闭随机壁纸对话框
  closeRandomWallpaperDialog() {
    this.closeModal();
    this.randomWallpaperDialog.visible = false;
  },

  // 确认设置随机壁纸
  async confirmRandomWallpaper() {
    const url = this.randomWallpaperDialog.url.trim();
    if (!url) {
      this.toastOnly(false, '请输入壁纸 URL');
      return;
    }
    try {
      new URL(url);
    } catch {
      this.toastOnly(false, 'URL 格式不正确');
      return;
    }
    this.randomWallpaperDialog.loading = true;
    try {
      // 调用后端接口，下载远程图片保存到本地
      const { data } = await this.$api.post('/api/background/fetch-url', { url });
      // ApiResponse 信封：{ success, message, data: { filename, url } }
      this.appearance.background_url = data.data.url;
      this.appearance.background_filename = data.data.filename;
      this.appearance.wallpaper_api_url = url;
      this.randomWallpaperDialog.visible = false;
      this.applyAppearance();
      this.toastOnly(true, '已下载并设置为背景');
    } catch (err) {
      this.toastOnly(false, err.response?.data?.detail || '获取壁纸失败');
    } finally {
      this.randomWallpaperDialog.loading = false;
    }
  },

  // 清除背景图片
  async clearBackgroundImage() {
    if (this.appearance.background_filename) {
      try {
        await this.$api.delete(`/api/background/${this.appearance.background_filename}`);
      } catch {
        // 删除旧背景图失败（可能已不存在），继续清理本地引用
      }
    }
    this.appearance.background_url = '';
    this.appearance.background_filename = '';
    this.appearance.wallpaper_api_url = '';
    this.applyAppearance();
  },

  // 打开背景图放大预览
  openBgLightbox() {
    this.bgLightbox.visible = true;
  },

  // 关闭背景图放大预览
  closeBgLightbox() {
    this.bgLightbox.visible = false;
  },
};
