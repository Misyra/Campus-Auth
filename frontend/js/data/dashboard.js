// 仪表盘相关数据
export function dashboardData() {
  return {
    logs: [],
    logFilter: { level: 'INFO', source: '', search: '' },
    autoScroll: true,
    newLogCount: 0,
    fetchStatusFailCount: 0,
    loginHistory: [],
  };
}
