// 可复用 Vue 组件定义

// 通用卡片组件
export const GlassCard = {
  props: {
    title: { type: String, default: '' },
    subtitle: { type: String, default: '' },
    noPadding: { type: Boolean, default: false },
  },
  template: `
    <div class="card glass-card">
      <div v-if="title" class="card-header">
        <div>
          <h2>{{ title }}</h2>
          <p v-if="subtitle" class="card-subtitle">{{ subtitle }}</p>
        </div>
        <slot name="header-actions"></slot>
      </div>
      <div class="card-body" :class="{ 'no-padding': noPadding }">
        <slot></slot>
      </div>
      <div v-if="$slots.footer" class="card-footer">
        <slot name="footer"></slot>
      </div>
    </div>
  `,
};

// 表单组组件
export const FormGroup = {
  props: {
    label: { type: String, required: true },
    hint: { type: String, default: '' },
    required: { type: Boolean, default: false },
    error: { type: String, default: '' },
  },
  template: `
    <div class="form-group" :class="{ 'has-error': error }">
      <label>
        {{ label }}
        <span v-if="required" class="required-mark">*</span>
      </label>
      <slot></slot>
      <p v-if="hint && !error" class="form-hint">{{ hint }}</p>
      <p v-if="error" class="form-error">{{ error }}</p>
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

// 状态指示器组件
export const StatusDot = {
  props: {
    status: { type: String, default: 'idle' }, // idle, connected, disconnected, checking
    pulse: { type: Boolean, default: false },
  },
  template: `
    <span class="status-dot" :class="[status, { pulse }]"></span>
  `,
};

// 加载状态组件
export const LoadingSpinner = {
  props: {
    size: { type: String, default: '16px' },
    color: { type: String, default: 'var(--accent)' },
  },
  template: `
    <span class="spinner" :style="{ width: size, height: size, borderTopColor: color }"></span>
  `,
};

// 空状态组件
export const EmptyState = {
  props: {
    icon: { type: String, default: '📭' },
    title: { type: String, default: '暂无数据' },
    description: { type: String, default: '' },
  },
  template: `
    <div class="empty-state">
      <div class="empty-icon">{{ icon }}</div>
      <h3 class="empty-title">{{ title }}</h3>
      <p v-if="description" class="empty-desc">{{ description }}</p>
      <slot></slot>
    </div>
  `,
};
