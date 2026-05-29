// 快捷键支持
export const shortcutMethods = {
  // 初始化快捷键
  initShortcuts() {
    this._shortcutHandler = (e) => this._handleShortcut(e);
    document.addEventListener('keydown', this._shortcutHandler);
  },

  // 清理快捷键
  destroyShortcuts() {
    if (this._shortcutHandler) {
      document.removeEventListener('keydown', this._shortcutHandler);
    }
  },

  // 处理快捷键
  _handleShortcut(e) {
    // 忽略输入框内的快捷键
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      // 但允许 Ctrl+S 保存
      if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        this._shortcutSave();
      }
      return;
    }

    // Ctrl+S: 保存
    if (e.ctrlKey && e.key === 's') {
      e.preventDefault();
      this._shortcutSave();
      return;
    }

    // Escape: 关闭弹窗/返回
    if (e.key === 'Escape') {
      e.preventDefault();
      this._shortcutEscape();
      return;
    }

    // Ctrl+1-6: 切换设置标签页
    if (e.ctrlKey && e.key >= '1' && e.key <= '6') {
      e.preventDefault();
      const index = parseInt(e.key) - 1;
      if (this.settingsTabs[index]) {
        this.setSettingsTab(this.settingsTabs[index].id);
        if (this.currentPage !== 'settings') {
          this.currentPage = 'settings';
        }
      }
      return;
    }

    // Ctrl+D: 仪表盘
    if (e.ctrlKey && e.key === 'd') {
      e.preventDefault();
      this.currentPage = 'dashboard';
      return;
    }

    // Ctrl+T: 任务管理
    if (e.ctrlKey && e.key === 't') {
      e.preventDefault();
      this.currentPage = 'tasks';
      return;
    }
  },

  // 快捷键保存
  _shortcutSave() {
    if (this.currentPage === 'settings') {
      if (this.currentSettingsTab === 'appearance') {
        this.saveAppearance();
      } else if (this.currentSettingsTab !== 'tasks') {
        this.saveConfig();
      }
    } else if (this.currentPage === 'tasks' && this.editingTask) {
      this.saveEditingTask();
    } else if (this.currentPage === 'scripts') {
      // 脚本保存由 scripts 模块处理
    }
  },

  // 快捷键 Escape
  _shortcutEscape() {
    // 关闭全屏预览
    if (this.fullscreenSrc) {
      this.closeFullscreen();
      return;
    }

    // 关闭调试面板
    if (this.debugSession?.running) {
      this.debugStop();
      return;
    }

    // 关闭仓库导入
    if (this.repoImport?.visible) {
      this.repoImport.visible = false;
      return;
    }

    // 返回仪表盘
    if (this.currentPage !== 'dashboard') {
      if (this.editingTask) {
        this.editingTask = null;
      } else if (this.editingProfile) {
        this.editingProfile = null;
      }
      this.currentPage = 'dashboard';
    }
  },
};
