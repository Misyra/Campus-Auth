/**
 * 零依赖虚拟滚动组件 — 只渲染可视区域 +/- 缓冲区的 DOM 节点。
 */
export class VirtualScroller {
  constructor(container, itemHeight, renderItem, bufferSize = 5) {
    this._container = container;
    this._itemHeight = itemHeight;
    this._renderItem = renderItem;
    this._bufferSize = bufferSize;
    this._items = [];
    this._startIndex = 0;
    this._endIndex = 0;

    this._spacer = document.createElement('div');
    this._spacer.style.cssText = 'position:relative;width:1px;';
    this._content = document.createElement('div');
    this._content.style.cssText = 'position:absolute;left:0;right:0;top:0;';

    this._container.style.position = 'relative';
    this._container.style.overflow = 'auto';
    this._container.appendChild(this._spacer);
    this._spacer.appendChild(this._content);

    this._onScroll = this._onScroll.bind(this);
    this._container.addEventListener('scroll', this._onScroll);
  }

  setItems(items) {
    this._items = items || [];
    this._spacer.style.height = (this._items.length * this._itemHeight) + 'px';
    this._render();
  }

  appendItems(newItems) {
    this._items = this._items.concat(newItems);
    this._spacer.style.height = (this._items.length * this._itemHeight) + 'px';
    this.scrollToBottom();
  }

  scrollToBottom() {
    this._container.scrollTop = this._container.scrollHeight;
  }

  destroy() {
    this._container.removeEventListener('scroll', this._onScroll);
    this._container.innerHTML = '';
    this._items = [];
  }

  _onScroll() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      this._render();
    });
  }

  _render() {
    const scrollTop = this._container.scrollTop;
    const containerHeight = this._container.clientHeight;
    const rawStart = Math.floor(scrollTop / this._itemHeight) - this._bufferSize;
    const rawEnd = Math.ceil((scrollTop + containerHeight) / this._itemHeight) + this._bufferSize;
    const start = Math.max(0, rawStart);
    const end = Math.min(this._items.length, rawEnd);
    if (start === this._startIndex && end === this._endIndex) return;
    this._startIndex = start;
    this._endIndex = end;
    this._content.innerHTML = '';
    this._content.style.transform = `translateY(${start * this._itemHeight}px)`;
    const fragment = document.createDocumentFragment();
    for (let i = start; i < end; i++) {
      const el = this._renderItem(this._items[i], i);
      fragment.appendChild(el);
    }
    this._content.appendChild(fragment);
  }
}
