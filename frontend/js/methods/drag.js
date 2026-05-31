import { TIMING } from '../constants.js';

// 拖拽排序支持 — 实时交换模式
let _dragState = null;
let _allowDrag = false;
let _swapCooldown = false;

export const dragMethods = {
  onHandleMouseDown(e) {
    _allowDrag = true;
    const item = e.currentTarget.closest('.task-item');
    if (item) item.setAttribute('draggable', 'true');
  },

  onHandleMouseUp(e) {
    const item = e.currentTarget.closest('.task-item');
    if (item && !_dragState) item.removeAttribute('draggable');
  },

  handleDragStart(e, index, listName) {
    if (!_allowDrag) {
      e.preventDefault();
      return;
    }

    const filtered = this[listName];
    if (!filtered || !filtered[index]) return;

    _dragState = {
      taskId: filtered[index].id,
      listName,
      currentIndex: index,
    };

    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', '');
    e.target.classList.add('dragging');
  },

  onDragOver(e, index, listName) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    if (!_dragState || _dragState.listName !== listName || _swapCooldown) return;

    const filtered = this[listName];
    if (!filtered || !filtered[index]) return;
    if (filtered[index].id === _dragState.taskId) return;

    // 判断是否越过目标中线
    const rect = e.currentTarget.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const crossed = (_dragState.currentIndex < index && e.clientY > midY) ||
                    (_dragState.currentIndex > index && e.clientY < midY);

    if (!crossed) return;

    // 实时交换
    _swapCooldown = true;
    setTimeout(() => { _swapCooldown = false; }, TIMING.DRAG_SWAP_COOLDOWN);

    if (listName === 'browserTasks') {
      const from = this.tasks.findIndex(t => t.id === _dragState.taskId);
      if (from === -1) return;
      const item = this.tasks.splice(from, 1)[0];
      let to = this.tasks.findIndex(t => t.id === filtered[index].id);
      if (_dragState.currentIndex < index) to++;
      this.tasks.splice(to, 0, item);
      _dragState.currentIndex = to;
    } else {
      const from = filtered.findIndex(t => t.id === _dragState.taskId);
      if (from === -1) return;
      const item = filtered.splice(from, 1)[0];
      let to = filtered.findIndex(t => t.id === filtered[index].id);
      if (_dragState.currentIndex < index) to++;
      filtered.splice(to, 0, item);
      _dragState.currentIndex = to;
    }
  },

  onDragLeave(e) {
    // 不需要处理
  },

  onDrop(e, index, listName) {
    e.preventDefault();
    if (!_dragState || _dragState.listName !== listName) return;
    _dragState = null;
    this._persistOrder();
  },

  onDragEnd(e) {
    e.target.classList.remove('dragging');
    e.target.removeAttribute('draggable');
    _dragState = null;
    _allowDrag = false;
    _swapCooldown = false;

    document.querySelectorAll('.drop-before, .drop-after').forEach(el => {
      el.classList.remove('drop-before', 'drop-after');
    });
  },

  async _persistOrder() {
    try {
      const order = {
        all: this.tasks.map(t => t.id),
        scripts: this.scripts.map(t => t.id),
      };
      await this.$api.post('/api/tasks/order', order);
    } catch {
      // 静默处理
    }
  },
};
