import { DEFAULT_CONFIG } from '../constants.js';

// 配置相关数据
export function configData() {
  return {
    config: { ...DEFAULT_CONFIG },
    defaultPortalUrls: DEFAULT_CONFIG.portal_check_urls,
    savedConfigSnapshot: '',
    dangerConfirm: null,
    dangerCountdown: 0,
  };
}
