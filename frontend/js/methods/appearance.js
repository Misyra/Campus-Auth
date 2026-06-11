import { DEFAULT_APPEARANCE, ACCENT_COLORS, BG_COLORS, LIMITS } from '../constants.js';
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
    localStorage.removeItem('appearance');
    this.applyAppearance();
    this.toastOnly(true, '已恢复默认外观');
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
      root.style.setProperty('--accent-hover', this.adjustColor(this.appearance.accent_color, -20));
    }

    // 页面缩放 — 只缩放内容区域，顶栏和侧边栏不受影响
    const wrapper = document.querySelector('.content-wrapper'); // 无 ref 可用，保留 querySelector
    if (wrapper) {
      const scale = (this.appearance.zoom || 100) / 100;
      wrapper.style.zoom = scale;
    }

    // 主题
    root.setAttribute('data-theme', this.appearance.theme);

    const isLight = this.appearance.theme === 'light';
    const _p = (k, v) => root.style.setProperty(k, v);

    // 背景色
    if (isLight) {
      _p('--bg-primary', '#eef2f7');
      _p('--bg-secondary', '#e4e9f0');
    } else if (this.appearance.background_color) {
      const bgRgb = this.hexToRgb(this.appearance.background_color);
      if (bgRgb) {
        _p('--bg-primary', this.appearance.background_color);
        _p('--bg-secondary', `rgb(${Math.min(bgRgb.r + 15, 255)}, ${Math.min(bgRgb.g + 15, 255)}, ${Math.min(bgRgb.b + 15, 255)})`);
      }
    }

    // 卡片透明度 — 毛玻璃 blur 跟随透明度联动
    const co = this.appearance.card_opacity;
    if (this.appearance.backdrop_filter) {
      // 透明度 0 → 完全关闭 blur，透明度 1 → 最强 blur
      _p('--card-blur', co > 0 ? `blur(${Math.round(co * 20)}px)` : 'none');
    } else {
      _p('--card-blur', 'none');
    }

    if (isLight) {
      _p('--bg-card', `rgba(255, 255, 255, ${co})`);
    } else {
      const cardRgb = this.hexToRgb(this.appearance.background_color || '#0f172a');
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
      const sidebarRgb = this.hexToRgb(this.appearance.sidebar_color);
      if (sidebarRgb) {
        _p('--sidebar-bg-1', `rgba(${sidebarRgb.r}, ${sidebarRgb.g}, ${sidebarRgb.b}, var(--sidebar-opacity))`);
        _p('--sidebar-bg-2', `rgba(${sidebarRgb.r}, ${sidebarRgb.g}, ${sidebarRgb.b}, calc(var(--sidebar-opacity) + 0.03))`);
      }
    } else if (isLight) {
      _p('--sidebar-bg-1', 'rgba(241, 245, 249, var(--sidebar-opacity))');
      _p('--sidebar-bg-2', 'rgba(226, 232, 240, calc(var(--sidebar-opacity) + 0.03))');
    } else {
      // 深色主题从背景色推导
      const bgRgb = this.hexToRgb(this.appearance.background_color || '#0f172a');
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

  // 颜色调整辅助函数
  adjustColor(hex, amount) {
    const num = parseInt(hex.replace('#', ''), 16);
    const r = Math.max(0, Math.min(255, (num >> 16) + amount));
    const g = Math.max(0, Math.min(255, ((num >> 8) & 0x00FF) + amount));
    const b = Math.max(0, Math.min(255, (num & 0x0000FF) + amount));
    return `#${(1 << 24 | r << 16 | g << 8 | b).toString(16).slice(1)}`;
  },

  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? {
      r: parseInt(result[1], 16),
      g: parseInt(result[2], 16),
      b: parseInt(result[3], 16),
    } : null;
  },

  getBgColors() {
    return BG_COLORS;
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

      this.appearance.background_url = data.url;
      this.appearance.background_filename = data.filename;
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
    this.$nextTick(() => {
      const overlay = document.querySelector('.random-wallpaper-overlay');
      if (overlay) this._trapFocus(overlay);
    });
  },

  // 关闭随机壁纸对话框
  closeRandomWallpaperDialog() {
    this._releaseFocusTrap();
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
      this.appearance.background_url = data.url;
      this.appearance.background_filename = data.filename;
      this.appearance.wallpaper_api_url = url;
      this.randomWallpaperDialog.visible = false;
      this.applyAppearance();
      this.toastOnly(true, '已设置随机壁纸');
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

  // 获取预设主题色列表
  getAccentColors() {
    return ACCENT_COLORS;
  },
};
