// 拖拽排序支持
export const dragMethods = {
  // 拖拽状态
  _dragState: null,

  // 开始拖拽
  onDragStart(e, index, listName) {
    this._dragState = {
      index,
      listName,
      startY: e.clientY,
    };
    e.dataTransfer.effectAllowed = 'move';
    e.target.classList.add('dragging');

    // 设置拖拽图像
    const ghost = e.target.cloneNode(true);
    ghost.style.opacity = '0.5';
    ghost.style.position = 'absolute';
    ghost.style.left = '-9999px';
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, 0, 0);
    setTimeout(() => document.body.removeChild(ghost), 0);
  },

  // 拖拽经过
  onDragOver(e, index, listName) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    if (!this._dragState || this._dragState.listName !== listName) return;
    if (this._dragState.index === index) return;

    const target = e.currentTarget;
    target.classList.add('drag-over');
  },

  // 拖拽离开
  onDragLeave(e) {
    e.currentTarget.classList.remove('drag-over');
  },

  // 放置
  onDrop(e, index, listName) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');

    if (!this._dragState || this._dragState.listName !== listName) return;

    const fromIndex = this._dragState.index;
    const toIndex = index;

    if (fromIndex === toIndex) return;

    // 获取列表
    const list = this[listName];
    if (!list) return;

    // 移动元素
    const item = list.splice(fromIndex, 1)[0];
    list.splice(toIndex, 0, item);

    this._dragState = null;
  },

  // 拖拽结束
  onDragEnd(e) {
    e.target.classList.remove('dragging');
    this._dragState = null;

    // 清理所有 drag-over 样式
    document.querySelectorAll('.drag-over').forEach(el => {
      el.classList.remove('drag-over');
    });
  },
};
