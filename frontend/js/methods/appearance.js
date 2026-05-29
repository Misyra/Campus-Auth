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

        // 删除旧背景
        if (this.appearance.background_filename) {
          this.$api.delete(`/api/background/${this.appearance.background_filename}`).catch(() => {});
        }

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
