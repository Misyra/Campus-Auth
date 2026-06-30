// 定时器相关数据
export function timerData() {
  return {
    timers: [],
    _dangerTimer: null,
    _repoDisclaimerTimer: null,
    _toastTimer: null,
    _toastLeavingTimer: null,
    _loginCooldownTimer: null,
  };
}
