import { DEFAULT_APPEARANCE } from '../constants.js';

// 外观设置数据
export function appearanceData() {
  // 从 localStorage 加载保存的外观设置
  const saved = localStorage.getItem('appearance');
  const appearance = saved ? { ...DEFAULT_APPEARANCE, ...JSON.parse(saved) } : { ...DEFAULT_APPEARANCE };

  return {
    appearance,
  };
}
