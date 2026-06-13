// 可复用 Vue 组件定义

// 自定义下拉选择组件
export const CustomSelect = {
  props: {
    modelValue: { type: String, default: '' },
    options: { type: Array, default: () => [] },
    // { value, label }[]
    placeholder: { type: String, default: '请选择...' },
    compact: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
  },
  emits: ['update:modelValue', 'change'],
  data() {
    return { open: false, activeIndex: -1 };
  },
  computed: {
    selectedLabel() {
      const opt = this.options.find(o => o.value === this.modelValue);
      return opt ? opt.label : '';
    },
  },
  methods: {
    toggle() {
      if (this.disabled) return;
      this.open = !this.open;
      if (this.open) {
        this.activeIndex = this.options.findIndex(o => o.value === this.modelValue);
        this.$nextTick(() => {
          this.scrollToActive();
          // 全局点击监听关闭下拉
          document.addEventListener('mousedown', this.onDocClick);
        });
      } else {
        document.removeEventListener('mousedown', this.onDocClick);
      }
    },
    select(opt) {
      this.$emit('update:modelValue', opt.value);
      this.$emit('change', opt.value);
      this.open = false;
      document.removeEventListener('mousedown', this.onDocClick);
      this.$refs.trigger?.focus();
    },
    onDocClick(e) {
      if (!this.$el.contains(e.target)) {
        this.open = false;
        document.removeEventListener('mousedown', this.onDocClick);
      }
    },
    onKeydown(e) {
      if (!this.open) {
        if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
          e.preventDefault();
          this.toggle();
        }
        return;
      }
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          this.activeIndex = Math.min(this.activeIndex + 1, this.options.length - 1);
          this.scrollToActive();
          break;
        case 'ArrowUp':
          e.preventDefault();
          this.activeIndex = Math.max(this.activeIndex - 1, 0);
          this.scrollToActive();
          break;
        case 'Enter':
        case ' ':
          e.preventDefault();
          if (this.activeIndex >= 0 && this.activeIndex < this.options.length) {
            this.select(this.options[this.activeIndex]);
          }
          break;
        case 'Escape':
          e.preventDefault();
          this.open = false;
          document.removeEventListener('mousedown', this.onDocClick);
          this.$refs.trigger?.focus();
          break;
      }
    },
    scrollToActive() {
      this.$nextTick(() => {
        const el = this.$el.querySelector('.custom-select-option.active');
        el?.scrollIntoView({ block: 'nearest' });
      });
    },
  },
  beforeUnmount() {
    document.removeEventListener('mousedown', this.onDocClick);
  },
  template: `
    <div class="custom-select" :class="{ open, compact, disabled }">
      <button
        ref="trigger"
        type="button"
        class="custom-select-trigger"
        role="combobox"
        :aria-expanded="open"
        aria-haspopup="listbox"
        :aria-activedescendant="open && activeIndex >= 0 ? 'cs-opt-' + activeIndex : undefined"
        @click="toggle"
        @keydown="onKeydown"
      >
        <span v-if="!selectedLabel" class="custom-select-placeholder">{{ placeholder }}</span>
        <span v-else>{{ selectedLabel }}</span>
        <svg class="custom-select-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>
      <div v-if="open" class="custom-select-dropdown" role="listbox">
        <div
          v-for="(opt, i) in options"
          :key="opt.value"
          :id="'cs-opt-' + i"
          class="custom-select-option"
          role="option"
          :aria-selected="opt.value === modelValue"
          :class="{ selected: opt.value === modelValue, active: i === activeIndex }"
          @mousedown.prevent="select(opt)"
          @mouseenter="activeIndex = i"
        >{{ opt.label }}</div>
      </div>
    </div>
  `,
};

// 开关组件
export const ToggleSwitch = {
  props: {
    modelValue: { type: Boolean, default: false },
    label: { type: String, default: '' },
    description: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
  },
  emits: ['update:modelValue'],
  template: `
    <div class="toggle-row" :class="{ disabled }" @click="!disabled && $emit('update:modelValue', !modelValue)">
      <div class="toggle-content">
        <span v-if="label" class="toggle-label">{{ label }}</span>
        <span v-if="description" class="toggle-desc">{{ description }}</span>
      </div>
      <button
        type="button"
        role="switch"
        :aria-checked="modelValue"
        :disabled="disabled"
        class="toggle-switch"
        :class="{ active: modelValue }"
        @click.stop="$emit('update:modelValue', !modelValue)"
      >
        <span class="toggle-knob"></span>
      </button>
    </div>
  `,
};
