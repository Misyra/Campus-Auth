import { DEFAULT_APPEARANCE, ACCENT_COLORS } from '../constants.js';

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
      root.style.setProperty('--bg-image', `url(${this.appearance.background_url})`);
      root.style.setProperty('--bg-blur', `blur(${this.appearance.background_blur}px)`);
      root.style.setProperty('--bg-opacity', this.appearance.background_opacity);
      root.classList.add('has-custom-bg');
    } else {
      root.classList.remove('has-custom-bg');
      root.style.removeProperty('--bg-image');
      root.style.removeProperty('--bg-blur');
      root.style.removeProperty('--bg-opacity');
    }

    // 主题色
    if (this.appearance.accent_color) {
      root.style.setProperty('--accent', this.appearance.accent_color);
      root.style.setProperty('--accent-hover', this.adjustColor(this.appearance.accent_color, -20));
    }

    // 字体大小
    if (this.appearance.font_size) {
      root.style.setProperty('--font-size-base', `${this.appearance.font_size}px`);
    }

    // 主题
    root.setAttribute('data-theme', this.appearance.theme);

    // 动态渐变背景
    if (this.appearance.animate_gradient) {
      body.classList.add('animate-gradient');
    } else {
      body.classList.remove('animate-gradient');
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

  // 选择背景图片
  selectBackgroundImage() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;

      // 限制文件大小（5MB）
      if (file.size > 5 * 1024 * 1024) {
        this.toastOnly(false, '图片大小不能超过 5MB');
        return;
      }

      const reader = new FileReader();
      reader.onload = (event) => {
        this.appearance.background_url = event.target.result;
        this.applyAppearance();
      };
      reader.readAsDataURL(file);
    };
    input.click();
  },

  // 清除背景图片
  clearBackgroundImage() {
    this.appearance.background_url = '';
    this.applyAppearance();
  },

  // 获取预设主题色列表
  getAccentColors() {
    return ACCENT_COLORS;
  },
};
