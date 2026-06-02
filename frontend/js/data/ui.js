// UI 状态相关数据
export function uiData() {
  return {
    currentPage: 'dashboard',
    showMoreNav: false,
    showWizard: false,
    wizardStep: 1,
    currentSettingsTab: 'account',
    isLoading: true,
    fullscreenSrc: '',
    updateInfo: null,
    updateLoading: false,
    toast: {
      success: true,
      message: '',
      leaving: false,
    },
    notifications: [],
    unreadNotifications: 0,
    showNotifications: false,
  };
}
