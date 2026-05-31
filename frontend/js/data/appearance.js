import { DEFAULT_APPEARANCE } from '../constants.js';

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

  return {
    appearance,
    randomWallpaperDialog: { visible: false, url: '', loading: false },
  };
}
