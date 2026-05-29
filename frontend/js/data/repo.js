// 仓库导入相关数据
export function repoData() {
  return {
    repoImport: {
      visible: false,
      url: 'https://github.com/Misyra/campus-auth-tasks/blob/master/index.json',
      source: 'github',
      loading: false,
      error: '',
      tasks: [],
      searchQuery: '',
      disclaimer: null,
      disclaimerCountdown: 0,
    },
  };
}
