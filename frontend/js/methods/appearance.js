import { DEFAULT_APPEARANCE, ACCENT_COLORS, BG_COLORS } from '../constants.js';

export const appearanceMethods = {
  // 保存外观设置
  saveAppearance() {
    localStorage.setItem('appearance', JSON.stringify(this.appearance));
    this.applyAppearance();
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
    const wrapper = document.querySelector('.content-wrapper');
    if (wrapper) {
      const scale = (this.appearance.zoom || 100) / 100;
      wrapper.style.zoom = scale;
    }

    // 主题
    root.setAttribute('data-theme', this.appearance.theme);

    // 背景色
    if (this.appearance.background_color) {
      const bgRgb = this.hexToRgb(this.appearance.background_color);
      if (bgRgb) {
        root.style.setProperty('--bg-primary', this.appearance.background_color);
        // 根据背景色自动调整次要背景色
        root.style.setProperty('--bg-secondary', `rgb(${Math.min(bgRgb.r + 15, 255)}, ${Math.min(bgRgb.g + 15, 255)}, ${Math.min(bgRgb.b + 15, 255)})`);
      }
    }

    // 卡片透明度
    if (this.appearance.card_opacity != null) {
      const bgRgb = this.hexToRgb(this.appearance.background_color || '#0f172a');
      if (bgRgb) {
        root.style.setProperty('--bg-card', `rgba(${bgRgb.r}, ${bgRgb.g}, ${bgRgb.b}, ${this.appearance.card_opacity})`);
      }
    }

    // 边框可见度
    if (this.appearance.border_intensity != null) {
      root.style.setProperty('--border', `rgba(148, 163, 184, ${0.1 * this.appearance.border_intensity})`);
      root.style.setProperty('--border-hover', `rgba(148, 163, 184, ${0.2 * this.appearance.border_intensity})`);
      root.style.setProperty('--border-accent', `rgba(56, 189, 248, ${0.15 * this.appearance.border_intensity})`);
    }

    // 侧边栏透明度
    if (this.appearance.sidebar_opacity != null) {
      root.style.setProperty('--sidebar-opacity', this.appearance.sidebar_opacity);
    }

    // 侧边栏背景色：有自定义值直接用，否则从背景色加深推导
    const sidebarBase = this.appearance.sidebar_color || this.appearance.background_color || '#0f172a';
    const sidebarRgb = this.hexToRgb(sidebarBase);
    if (sidebarRgb) {
      if (this.appearance.sidebar_color) {
        // 用户自定义，直接使用
        root.style.setProperty('--sidebar-bg-1', `rgba(${sidebarRgb.r}, ${sidebarRgb.g}, ${sidebarRgb.b}, var(--sidebar-opacity, 0.95))`);
        root.style.setProperty('--sidebar-bg-2', `rgba(${sidebarRgb.r}, ${sidebarRgb.g}, ${sidebarRgb.b}, calc(var(--sidebar-opacity, 0.95) + 0.03))`);
      } else {
        // 从背景色加深推导
        const dr = Math.max(0, sidebarRgb.r - 10);
        const dg = Math.max(0, sidebarRgb.g - 10);
        const db = Math.max(0, sidebarRgb.b - 10);
        root.style.setProperty('--sidebar-bg-1', `rgba(${Math.min(sidebarRgb.r + 15, 255)}, ${Math.min(sidebarRgb.g + 15, 255)}, ${Math.min(sidebarRgb.b + 15, 255)}, var(--sidebar-opacity, 0.95))`);
        root.style.setProperty('--sidebar-bg-2', `rgba(${dr}, ${dg}, ${db}, calc(var(--sidebar-opacity, 0.95) + 0.03))`);
      }
    }

    // 侧边栏活跃项高亮色
    if (this.appearance.sidebar_accent) {
      root.style.setProperty('--sidebar-accent', this.appearance.sidebar_accent);
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
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';

    input.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      if (file.size > 5 * 1024 * 1024) {
        this.toastOnly(false, '图片大小不能超过 5MB');
        return;
      }

      try {
        // 上传到服务器
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
    };

    input.click();
  },

  // 清除背景图片
  async clearBackgroundImage() {
    if (this.appearance.background_filename) {
      try {
        await this.$api.delete(`/api/background/${this.appearance.background_filename}`);
      } catch {}
    }
    this.appearance.background_url = '';
    this.appearance.background_filename = '';
    this.applyAppearance();
  },

  // 获取预设主题色列表
  getAccentColors() {
    return ACCENT_COLORS;
  },
};
