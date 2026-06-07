// 可复用 Vue 组件定义

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
