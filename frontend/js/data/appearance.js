import { DEFAULT_APPEARANCE, DEFAULT_CUSTOM_COLORS } from '../constants.js';

// 外观设置数据
export function appearanceData() {
  // 从 localStorage 加载保存的外观设置
  const saved = localStorage.getItem('appearance');
  let appearance = { ...DEFAULT_APPEARANCE };
  if (saved) {
    try {
      appearance = { ...DEFAULT_APPEARANCE, ...JSON.parse(saved) };
    } catch (e) {
      console.warn('外观设置解析失败，使用默认值:', e);
      localStorage.removeItem('appearance');
    }
  }

  // 从 localStorage 加载自定义颜色
  const savedColors = localStorage.getItem('appearance.custom_colors');
  let customColors = { ...DEFAULT_CUSTOM_COLORS };
  if (savedColors) {
    try {
      customColors = { ...DEFAULT_CUSTOM_COLORS, ...JSON.parse(savedColors) };
    } catch (e) {
      console.warn('自定义颜色解析失败，使用默认值:', e);
      localStorage.removeItem('appearance.custom_colors');
    }
  }

  return {
    appearance,
    customColors,
    randomWallpaperDialog: { visible: false, url: '', loading: false },
    bgLightbox: { visible: false },
  };
}
