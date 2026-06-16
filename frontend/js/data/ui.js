// UI 状态相关数据
export function uiData() {
  return {
    currentPage: 'dashboard',
    showMoreNav: false,
    showWizard: false,
    wizardStep: 1,
    agreedToTerms: false,
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
    availableBrowsers: [],
    selectedBrowser: 'playwright',
    browserLoading: false,
    saveFailed: false,
  };
}
