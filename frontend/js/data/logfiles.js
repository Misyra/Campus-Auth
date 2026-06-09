// 日志文件查看器数据
export function logFileData() {
  return {
    logFileGroups: [],
    logViewer: {
      date: '',
      file: 'app.log',
      level: '',
      source: '',
      search: '',
      lines: [],
      loading: false,
      totalLines: 0,
    },
  };
}
