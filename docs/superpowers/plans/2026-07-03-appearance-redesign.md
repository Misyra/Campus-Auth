# 外观设置页面 Redesign 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构外观设置页面为 4 张分区卡 + 统一控件，删除缩放设置，新增自定义色持久化与「跟随系统」主题。

**Architecture:** 纯前端改造。HTML 重构页面结构为 4 张分区卡（双栏 grid）；CSS 重写卡片与控件样式；JS 在 appearance data/methods、constants、app-options 中新增 customColors 数据、addCustomColor/removeCustomColor/resetCard 方法、theme='auto' 处理，删除 zoom 相关逻辑。所有改动沿用现有 applyAppearance 实时应用机制。

**Tech Stack:** Vue 3（CDN，原生 ES Module）、原生 CSS（无预处理器）、localStorage 持久化、原生 `<input type="range">` / `<input type="color">`。

**Spec:** `docs/2026-07-03-appearance-redesign-design.md`

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `frontend/js/constants.js` | `DEFAULT_APPEARANCE`（删 zoom）、`DEFAULT_CUSTOM_COLORS`、`ACCENT_COLORS`、`BG_COLORS` |
| `frontend/js/data/appearance.js` | `appearanceData()` 返回 appearance + customColors + randomWallpaperDialog + bgLightbox |
| `frontend/js/methods/appearance.js` | applyAppearance（删 zoom、增 auto）、addCustomColor/removeCustomColor/resetCard、selectBackgroundImage 等 |
| `frontend/js/app-options.js` | watcher 持久化 appearance + customColors |
| `frontend/partials/pages/appearance.html` | 4 张分区卡 HTML 结构 |
| `frontend/styles/pages/appearance.css` | 卡片、颜色控件、滑块、segmented、缩略图样式 |

---

## Task 1: constants.js — 删除 zoom、新增 customColors 默认结构

**Files:**
- Modify: `frontend/js/constants.js:169-207`

- [ ] **Step 1: 修改 DEFAULT_APPEARANCE，删除 zoom 字段，新增 sidebar_accent 已有无需改**

将 `frontend/js/constants.js` 中的 `DEFAULT_APPEARANCE` 改为：

```javascript
// 外观设置默认值
export const DEFAULT_APPEARANCE = {
  background_url: '',
  background_filename: '',
  wallpaper_api_url: '',
  background_blur: 10,
  background_opacity: 0.3,
  background_color: '#0f172a',
  card_opacity: 0.45,
  card_blur: 12,
  border_intensity: 1.0,
  sidebar_opacity: 0.95,
  sidebar_color: '',
  sidebar_accent: '',
  backdrop_filter: false, // 毛玻璃效果
  accent_color: '#22d3ee',
  theme: 'light', // light | dark | auto
};
```

变更点：删除 `zoom: 100`，`theme` 注释改为 `light | dark | auto`。

- [ ] **Step 2: 在 BG_COLORS 后新增 DEFAULT_CUSTOM_COLORS**

在 `frontend/js/constants.js` 文件中 `BG_COLORS` 数组定义之后插入：

```javascript
// 自定义颜色默认结构（按类型分组，持久化到 localStorage 'appearance.custom_colors'）
export const DEFAULT_CUSTOM_COLORS = {
  accent: [],
  bg: [],
  sidebar: [],
  sidebar_accent: [],
};
```

- [ ] **Step 3: 全局搜索确认无残留 zoom 引用**

运行：`grep -rn "appearance.zoom\|appearance\.zoom\|\.zoom" frontend/`
预期：仅可能命中无关的 zoom（如 lightbox 的 zoom-out 类名），不应再有 `appearance.zoom` 或 `DEFAULT_APPEARANCE.zoom` 引用。

- [ ] **Step 4: Commit**

```bash
git add frontend/js/constants.js
git commit -m "refactor(appearance): 删除 zoom 默认值，新增 customColors 默认结构"
```

---

## Task 2: data/appearance.js — 加载 customColors

**Files:**
- Modify: `frontend/js/data/appearance.js`

- [ ] **Step 1: 重写 appearanceData 加载 customColors**

将 `frontend/js/data/appearance.js` 全文替换为：

```javascript
import { DEFAULT_APPEARANCE, DEFAULT_CUSTOM_COLORS } from '../constants.js';

// 外观设置数据
export function appearanceData() {
  // 从 localStorage 加载保存的外观设置
  const saved = localStorage.getItem('appearance');
  let appearance = { ...DEFAULT_APPEARANCE };
  if (saved) {
    try {
      appearance = { ...DEFAULT_APPEARANCE, ...JSON.parse(saved) };
    } catch (e) {
      console.warn('外观设置解析失败，使用默认值:', e);
      localStorage.removeItem('appearance');
    }
  }

  // 从 localStorage 加载自定义颜色
  const savedColors = localStorage.getItem('appearance.custom_colors');
  let customColors = { ...DEFAULT_CUSTOM_COLORS };
  if (savedColors) {
    try {
      customColors = { ...DEFAULT_CUSTOM_COLORS, ...JSON.parse(savedColors) };
    } catch (e) {
      console.warn('自定义颜色解析失败，使用默认值:', e);
      localStorage.removeItem('appearance.custom_colors');
    }
  }

  return {
    appearance,
    customColors,
    randomWallpaperDialog: { visible: false, url: '', loading: false },
    bgLightbox: { visible: false },
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/data/appearance.js
git commit -m "feat(appearance): 加载 customColors 数据"
```

---

## Task 3: methods/appearance.js — 删除 zoom、新增 auto 主题、customColor 操作、resetCard

**Files:**
- Modify: `frontend/js/methods/appearance.js`

- [ ] **Step 1: 重写文件顶部 import 与新增 addCustomColor/removeCustomColor/resetCard**

将 `frontend/js/methods/appearance.js` 顶部 import 改为：

```javascript
import { DEFAULT_APPEARANCE, DEFAULT_CUSTOM_COLORS, ACCENT_COLORS, BG_COLORS, LIMITS } from '../constants.js';
```

在 `appearanceMethods` 对象内 `resetAppearance` 方法后插入以下方法：

```javascript
  // 新增自定义颜色（picker 选色后调用）
  addCustomColor(type, hex) {
    if (!hex || !DEFAULT_CUSTOM_COLORS.hasOwnProperty(type)) return;
    hex = hex.toLowerCase();
    // 去重：系统预设或已存在的自定义色不重复加入
    const systemColors = type === 'accent' ? ACCENT_COLORS : type === 'bg' ? BG_COLORS : [];
    if (systemColors.some(c => c.value.toLowerCase() === hex)) return;
    if (this.customColors[type].some(c => c.toLowerCase() === hex)) return;
    this.customColors[type].push(hex);
    localStorage.setItem('appearance.custom_colors', JSON.stringify(this.customColors));
  },

  // 删除自定义颜色（长按或右键触发）
  removeCustomColor(type, hex) {
    if (!DEFAULT_CUSTOM_COLORS.hasOwnProperty(type)) return;
    const idx = this.customColors[type].findIndex(c => c.toLowerCase() === hex.toLowerCase());
    if (idx === -1) return;
    this.customColors[type].splice(idx, 1);
    localStorage.setItem('appearance.custom_colors', JSON.stringify(this.customColors));
    // 若该色正被使用，回退到默认色
    const defaultKey = type === 'accent' ? 'accent_color'
      : type === 'bg' ? 'background_color'
      : type === 'sidebar' ? 'sidebar_color'
      : 'sidebar_accent';
    if ((this.appearance[defaultKey] || '').toLowerCase() === hex.toLowerCase()) {
      this.appearance[defaultKey] = DEFAULT_APPEARANCE[defaultKey];
    }
  },

  // 重置单张分区卡（cardKey: 'background' | 'theme' | 'card' | 'sidebar'）
  resetCard(cardKey) {
    const fields = {
      background: ['background_url', 'background_filename', 'wallpaper_api_url', 'background_blur', 'background_opacity', 'backdrop_filter', 'card_blur'],
      theme: ['theme', 'accent_color', 'background_color'],
      card: ['card_opacity', 'border_intensity'],
      sidebar: ['sidebar_opacity', 'sidebar_color', 'sidebar_accent'],
    }[cardKey];
    if (!fields) return;
    fields.forEach(f => {
      this.appearance[f] = DEFAULT_APPEARANCE[f];
    });
    // 背景卡重置时清理已上传文件
    if (cardKey === 'background' && this.appearance.background_filename) {
      this.$api.delete(`/api/background/${this.appearance.background_filename}`).catch(() => {});
    }
    this.applyAppearance();
    this.toastOnly(true, '已恢复默认');
  },

  // 判断分区卡是否有项偏离默认
  cardDirty(cardKey) {
    const fields = {
      background: ['background_url', 'background_blur', 'background_opacity', 'backdrop_filter', 'card_blur'],
      theme: ['theme', 'accent_color', 'background_color'],
      card: ['card_opacity', 'border_intensity'],
      sidebar: ['sidebar_opacity', 'sidebar_color', 'sidebar_accent'],
    }[cardKey] || [];
    return fields.some(f => this.appearance[f] !== DEFAULT_APPEARANCE[f]);
  },

  // 触发自定义色 picker（hidden input click）
  pickCustomColor(type) {
    const input = document.querySelector(`input[data-color-picker="${type}"]`);
    if (input) input.click();
  },

  // picker onchange：选色后加入自定义列表并设为当前值
  onCustomColorPicked(type, event) {
    const hex = event.target.value;
    this.addCustomColor(type, hex);
    const fieldMap = {
      accent: 'accent_color',
      bg: 'background_color',
      sidebar: 'sidebar_color',
      sidebar_accent: 'sidebar_accent',
    };
    this.appearance[fieldMap[type]] = hex;
    event.target.value = '#000000'; // 重置 picker
  },

  // 长按/右键删除自定义色
  onColorLongPress(type, hex, event) {
    event.preventDefault();
    if (confirm(`删除自定义颜色 ${hex}？`)) {
      this.removeCustomColor(type, hex);
    }
  },

  // 获取合并后的颜色列表（系统预设 + 自定义）
  getColorList(type) {
    const systemColors = type === 'accent' ? ACCENT_COLORS
      : type === 'bg' ? BG_COLORS
      : [];
    const custom = (this.customColors[type] || []).map(hex => ({ value: hex, label: hex, custom: true }));
    return [...systemColors, ...custom];
  },
```

- [ ] **Step 2: 修改 applyAppearance，删除 zoom 逻辑、新增 theme='auto' 处理**

将 `applyAppearance` 方法中以下代码块**删除**：

```javascript
    // 页面缩放 — 只缩放内容区域，顶栏和侧边栏不受影响
    const wrapper = document.querySelector('.content-wrapper'); // 无 ref 可用，保留 querySelector
    if (wrapper) {
      const scale = (this.appearance.zoom || 100) / 100;
      if (scale !== 1) {
        wrapper.style.transform = `scale(${scale})`;
        wrapper.style.transformOrigin = 'top left';
        wrapper.style.width = `${100 / scale}%`;
      } else {
        wrapper.style.transform = '';
        wrapper.style.transformOrigin = '';
        wrapper.style.width = '';
      }
    }
```

将 applyAppearance 中主题设置部分改为：

```javascript
    // 主题
    const themeMode = this.appearance.theme || 'light';
    let effectiveTheme = themeMode;
    if (themeMode === 'auto') {
      effectiveTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    root.setAttribute('data-theme', effectiveTheme);

    const isLight = effectiveTheme === 'light';
```

替换原 `root.setAttribute('data-theme', this.appearance.theme);` 与 `const isLight = this.appearance.theme === 'light';`。

- [ ] **Step 3: 在 mounted 时注册 prefers-color-scheme 监听器**

在 `frontend/js/app-options.js` 的 `mounted()` 中 `this.applyAppearance();` 后追加：

```javascript
    // 监听系统主题变化（仅当用户选择 'auto' 时生效）
    this._mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    this._onSystemThemeChange = (e) => {
      if (this.appearance.theme === 'auto') {
        document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
        // 触发 applyAppearance 重算 isLight 相关变量
        this.applyAppearance();
      }
    };
    this._mediaQuery.addEventListener('change', this._onSystemThemeChange);
```

在 `beforeUnmount()` 中追加清理：

```javascript
    if (this._mediaQuery && this._onSystemThemeChange) {
      this._mediaQuery.removeEventListener('change', this._onSystemThemeChange);
    }
```

- [ ] **Step 4: 修改 resetAppearance 适配 customColors 清理**

将 `resetAppearance` 方法改为：

```javascript
  // 重置外观设置
  resetAppearance() {
    if (!confirm('确定要恢复默认外观设置吗？')) return;
    this.appearance = { ...DEFAULT_APPEARANCE };
    this.customColors = { ...DEFAULT_CUSTOM_COLORS };
    localStorage.removeItem('appearance');
    localStorage.removeItem('appearance.custom_colors');
    this.applyAppearance();
    this.toastOnly(true, '已恢复默认外观');
  },
```

- [ ] **Step 5: Commit**

```bash
git add frontend/js/methods/appearance.js frontend/js/app-options.js
git commit -m "feat(appearance): 自定义色持久化、resetCard、auto 主题，移除 zoom"
```

---

## Task 4: appearance.html — 重构为 4 张分区卡

**Files:**
- Modify: `frontend/partials/pages/appearance.html`

- [ ] **Step 1: 用新结构替换整个外观页内容**

将 `frontend/partials/pages/appearance.html` 中 `<div v-if="currentPage === 'appearance'" class="page-content">` 内的 `.appearance-page` 内容全部替换为：

```html
<div class="appearance-page">
  <!-- 卡片 1：背景与氛围 -->
  <div class="card appearance-card appearance-section-card">
    <div class="appearance-card-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="appearance-card-icon">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
      </svg>
      <h3>背景与氛围</h3>
      <button v-if="cardDirty('background')" type="button" class="appearance-reset-btn" @click="resetCard('background')">恢复默认</button>
    </div>
    <div class="appearance-card-body appearance-grid-2col">
      <!-- 背景图缩略图 + 按钮 -->
      <div class="appearance-bg-thumb-group">
        <div v-if="appearance.background_url" class="appearance-bg-thumb" @click="openBgLightbox">
          <img :src="appearance.background_url" alt="背景预览" />
          <div class="appearance-bg-thumb-zoom">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="icon-sm">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              <line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>
            </svg>
          </div>
          <button type="button" class="appearance-bg-thumb-remove" @click.stop="clearBackgroundImage" title="移除背景">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="icon-sm">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div v-else class="appearance-bg-thumb empty" @click="selectBackgroundImage">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:24px;height:24px;">
            <rect x="3" y="3" width="18" height="18" rx="2"/>
            <circle cx="8.5" cy="8.5" r="1.5"/>
            <polyline points="21 15 16 10 5 21"/>
          </svg>
          <span>选择图片</span>
        </div>
        <div class="appearance-bg-thumb-actions">
          <button type="button" class="btn btn-secondary btn-sm" @click="selectBackgroundImage">选择图片</button>
          <button type="button" class="btn btn-secondary btn-sm" @click="openRandomWallpaperDialog">随机壁纸</button>
        </div>
      </div>

      <!-- 滑块组 -->
      <div class="appearance-sliders appearance-sliders-col">
        <div class="appearance-slider-item">
          <label for="bg-blur">模糊</label>
          <input id="bg-blur" type="range" v-model.number="appearance.background_blur" min="0" max="30" step="1" />
          <span>{{ appearance.background_blur }}px</span>
        </div>
        <div class="appearance-slider-item">
          <label for="bg-opacity">遮罩</label>
          <input id="bg-opacity" type="range" v-model.number="appearance.background_opacity" min="0" max="0.8" step="0.05" />
          <span>{{ Math.round(appearance.background_opacity * 100) }}%</span>
        </div>
        <div class="appearance-slider-item" :class="{ disabled: !appearance.backdrop_filter }">
          <label for="card-blur">玻璃模糊</label>
          <input id="card-blur" type="range" v-model.number="appearance.card_blur" min="0" max="24" step="1" :disabled="!appearance.backdrop_filter" />
          <span>{{ appearance.card_blur }}px</span>
        </div>
        <label class="toggle appearance-toggle-row">
          <input type="checkbox" v-model="appearance.backdrop_filter" />
          <span class="toggle-slider"></span>
          <span class="toggle-label">毛玻璃效果</span>
        </label>
      </div>
    </div>
  </div>

  <!-- 卡片 2：主题与配色 -->
  <div class="card appearance-card appearance-section-card">
    <div class="appearance-card-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="appearance-card-icon">
        <circle cx="12" cy="12" r="10"/>
        <path d="M12 2a10 10 0 0 1 0 20"/>
      </svg>
      <h3>主题与配色</h3>
      <button v-if="cardDirty('theme')" type="button" class="appearance-reset-btn" @click="resetCard('theme')">恢复默认</button>
    </div>
    <div class="appearance-card-body appearance-grid-2col">
      <!-- 主题切换 -->
      <div class="appearance-field">
        <div class="appearance-field-label">主题</div>
        <div class="appearance-segmented">
          <button type="button" :class="{ active: appearance.theme === 'light' }" @click="appearance.theme = 'light'">浅色</button>
          <button type="button" :class="{ active: appearance.theme === 'dark' }" @click="appearance.theme = 'dark'">深色</button>
          <button type="button" :class="{ active: appearance.theme === 'auto' }" @click="appearance.theme = 'auto'">跟随系统</button>
        </div>
      </div>
      <div></div>
      <!-- 主题色 -->
      <div class="appearance-field">
        <div class="appearance-field-label">主题色</div>
        <div class="appearance-color-row">
          <div class="appearance-colors">
            <button
              v-for="color in getColorList('accent')"
              :key="color.value"
              type="button"
              class="appearance-color-btn"
              :class="{ active: appearance.accent_color === color.value, custom: color.custom }"
              :style="{ background: color.value }"
              @click="appearance.accent_color = color.value"
              @contextmenu.prevent="color.custom ? onColorLongPress('accent', color.value, $event) : null"
              @touchstart="color.custom ? startLongPress('accent', color.value, $event) : null"
              :title="color.label"
            >
              <svg v-if="appearance.accent_color === color.value" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" class="icon-sm">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </button>
            <button type="button" class="appearance-color-btn appearance-color-add" @click="pickCustomColor('accent')" title="自定义颜色">+</button>
          </div>
          <span class="appearance-color-hex">{{ appearance.accent_color }}</span>
        </div>
        <input type="color" data-color-picker="accent" class="sr-only" @change="onCustomColorPicked('accent', $event)" />
      </div>
      <!-- 背景色 -->
      <div class="appearance-field">
        <div class="appearance-field-label">背景颜色</div>
        <div class="appearance-color-row">
          <div class="appearance-colors">
            <button
              v-for="color in getColorList('bg')"
              :key="color.value"
              type="button"
              class="appearance-color-btn"
              :class="{ active: appearance.background_color === color.value, custom: color.custom }"
              :style="{ background: color.value }"
              @click="appearance.background_color = color.value"
              @contextmenu.prevent="color.custom ? onColorLongPress('bg', color.value, $event) : null"
              @touchstart="color.custom ? startLongPress('bg', color.value, $event) : null"
              :title="color.label"
            >
              <svg v-if="appearance.background_color === color.value" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" class="icon-sm">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </button>
            <button type="button" class="appearance-color-btn appearance-color-add" @click="pickCustomColor('bg')" title="自定义颜色">+</button>
          </div>
          <span class="appearance-color-hex">{{ appearance.background_color }}</span>
        </div>
        <input type="color" data-color-picker="bg" class="sr-only" @change="onCustomColorPicked('bg', $event)" />
      </div>
    </div>
  </div>

  <!-- 卡片 3：卡片样式 -->
  <div class="card appearance-card appearance-section-card">
    <div class="appearance-card-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="appearance-card-icon">
        <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
        <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
      </svg>
      <h3>卡片样式</h3>
      <button v-if="cardDirty('card')" type="button" class="appearance-reset-btn" @click="resetCard('card')">恢复默认</button>
    </div>
    <div class="appearance-card-body appearance-grid-2col">
      <div class="appearance-slider-item">
        <label for="card-opacity">不透明度</label>
        <input id="card-opacity" type="range" v-model.number="appearance.card_opacity" min="0" max="1" step="0.05" />
        <span>{{ Math.round(appearance.card_opacity * 100) }}%</span>
      </div>
      <div class="appearance-slider-item">
        <label for="border-intensity">边框</label>
        <input id="border-intensity" type="range" v-model.number="appearance.border_intensity" min="0" max="2" step="0.1" />
        <span>{{ appearance.border_intensity.toFixed(1) }}x</span>
      </div>
    </div>
  </div>

  <!-- 卡片 4：侧边栏 -->
  <div class="card appearance-card appearance-section-card">
    <div class="appearance-card-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="appearance-card-icon">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <line x1="9" y1="3" x2="9" y2="21"/>
      </svg>
      <h3>侧边栏</h3>
      <button v-if="cardDirty('sidebar')" type="button" class="appearance-reset-btn" @click="resetCard('sidebar')">恢复默认</button>
    </div>
    <div class="appearance-card-body appearance-grid-2col">
      <div class="appearance-slider-item">
        <label for="sidebar-opacity">不透明度</label>
        <input id="sidebar-opacity" type="range" v-model.number="appearance.sidebar_opacity" min="0.3" max="1" step="0.05" />
        <span>{{ Math.round(appearance.sidebar_opacity * 100) }}%</span>
      </div>
      <div></div>
      <div class="appearance-field">
        <div class="appearance-field-label">侧边栏色</div>
        <div class="appearance-color-row">
          <div class="appearance-colors">
            <button
              v-for="color in getColorList('sidebar')"
              :key="color.value"
              type="button"
              class="appearance-color-btn"
              :class="{ active: appearance.sidebar_color === color.value, custom: color.custom }"
              :style="{ background: color.value }"
              @click="appearance.sidebar_color = color.value"
              @contextmenu.prevent="color.custom ? onColorLongPress('sidebar', color.value, $event) : null"
              @touchstart="color.custom ? startLongPress('sidebar', color.value, $event) : null"
              :title="color.label"
            >
              <svg v-if="appearance.sidebar_color === color.value" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" class="icon-sm">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </button>
            <button type="button" class="appearance-color-btn appearance-color-add" @click="pickCustomColor('sidebar')" title="自定义颜色">+</button>
          </div>
          <span class="appearance-color-hex">{{ appearance.sidebar_color || '跟随背景色' }}</span>
        </div>
        <input type="color" data-color-picker="sidebar" class="sr-only" @change="onCustomColorPicked('sidebar', $event)" />
      </div>
      <div class="appearance-field">
        <div class="appearance-field-label">高亮色</div>
        <div class="appearance-color-row">
          <div class="appearance-colors">
            <button
              v-for="color in getColorList('sidebar_accent')"
              :key="color.value"
              type="button"
              class="appearance-color-btn"
              :class="{ active: appearance.sidebar_accent === color.value, custom: color.custom }"
              :style="{ background: color.value }"
              @click="appearance.sidebar_accent = color.value"
              @contextmenu.prevent="color.custom ? onColorLongPress('sidebar_accent', color.value, $event) : null"
              @touchstart="color.custom ? startLongPress('sidebar_accent', color.value, $event) : null"
              :title="color.label"
            >
              <svg v-if="appearance.sidebar_accent === color.value" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" class="icon-sm">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </button>
            <button type="button" class="appearance-color-btn appearance-color-add" @click="pickCustomColor('sidebar_accent')" title="自定义颜色">+</button>
          </div>
          <span class="appearance-color-hex">{{ appearance.sidebar_accent || '跟随主题色' }}</span>
        </div>
        <input type="color" data-color-picker="sidebar_accent" class="sr-only" @change="onCustomColorPicked('sidebar_accent', $event)" />
      </div>
    </div>
  </div>

  <!-- 随机壁纸弹窗与 lightbox 沿用原结构 -->
</div>
```

保留文件末尾的 `bgLightbox` 与 `randomWallpaperDialog` 两个 overlay 不变。

- [ ] **Step 2: 在 appearanceMethods 中补充 startLongPress 方法**

在 `frontend/js/methods/appearance.js` 的 `appearanceMethods` 对象内追加：

```javascript
  // 长按触发删除（移动端）
  startLongPress(type, hex, event) {
    let timer = setTimeout(() => {
      this.onColorLongPress(type, hex, event);
    }, 600);
    // 触摸结束或移动时取消
    const cancel = () => {
      clearTimeout(timer);
      event.target.removeEventListener('touchend', cancel);
      event.target.removeEventListener('touchmove', cancel);
    };
    event.target.addEventListener('touchend', cancel);
    event.target.addEventListener('touchmove', cancel);
  },
```

- [ ] **Step 3: 启动应用，浏览器访问外观页确认结构渲染**

```bash
python main.py
```

打开浏览器访问外观页，确认：
- 4 张分区卡单列纵向
- 每卡 header 含图标 + 标题 + 条件重置按钮
- 控件双栏 grid 排列

- [ ] **Step 4: Commit**

```bash
git add frontend/partials/pages/appearance.html frontend/js/methods/appearance.js
git commit -m "feat(appearance): 重构为 4 张分区卡 + 统一控件"
```

---

## Task 5: appearance.css — 重写卡片与控件样式

**Files:**
- Modify: `frontend/styles/pages/appearance.css`

- [ ] **Step 1: 用新样式替换文件全文**

将 `frontend/styles/pages/appearance.css` 全文替换为：

```css
/* ==================== 外观设置 ==================== */

.appearance-page {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 分区卡 */
.appearance-section-card {
  overflow: hidden;
}

.appearance-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 48px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
}

.appearance-card-icon {
  width: 20px;
  height: 20px;
  color: var(--accent);
  opacity: 0.7;
  flex-shrink: 0;
}

.appearance-card-header h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
  flex: 1;
}

.appearance-reset-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  transition: color 0.2s ease, background 0.2s ease;
  animation: fadeIn 0.2s ease;
}

.appearance-reset-btn:hover {
  color: var(--accent);
  background: rgba(34, 211, 238, 0.08);
}

.appearance-card-body {
  padding: 20px;
}

/* 双栏 grid */
.appearance-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 20px;
  align-items: start;
}

.appearance-grid-2col > .appearance-field,
.appearance-grid-2col > .appearance-slider-item,
.appearance-grid-2col > .appearance-bg-thumb-group,
.appearance-grid-2col > .appearance-sliders-col {
  min-width: 0;
}

/* 字段容器 */
.appearance-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.appearance-field-label {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

/* segmented 主题切换 */
.appearance-segmented {
  display: inline-flex;
  background: var(--bg-glass-light);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 2px;
  gap: 2px;
}

.appearance-segmented button {
  padding: 6px 14px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.appearance-segmented button:hover {
  color: var(--text-primary);
}

.appearance-segmented button.active {
  background: rgba(34, 211, 238, 0.15);
  color: var(--accent);
}

/* 颜色控件 */
.appearance-color-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.appearance-colors {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.appearance-color-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  flex-shrink: 0;
  position: relative;
}

.appearance-color-btn:hover {
  transform: scale(1.15);
}

.appearance-color-btn.active {
  border-color: var(--text-primary);
  box-shadow: var(--shadow-accent);
}

.appearance-color-btn.custom::after {
  content: '';
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  border: 1.5px solid var(--bg-primary);
}

.appearance-color-add {
  background: transparent !important;
  border: 2px dashed var(--border-hover);
  color: var(--text-muted);
  font-size: 16px;
  font-weight: 300;
  line-height: 1;
}

.appearance-color-add:hover {
  border-color: var(--accent);
  color: var(--accent);
  transform: scale(1.1);
}

.appearance-color-hex {
  font-size: 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

/* 滑块控件 */
.appearance-slider-item {
  display: grid;
  grid-template-columns: 56px 1fr 48px;
  align-items: center;
  gap: 12px;
}

.appearance-slider-item label {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0;
}

.appearance-slider-item span {
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
  font-family: var(--font-mono);
}

.appearance-slider-item input[type="range"] {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  outline: none;
  cursor: pointer;
}

.appearance-slider-item input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent);
  cursor: pointer;
  transition: transform 0.2s ease;
}

.appearance-slider-item input[type="range"]::-webkit-slider-thumb:hover {
  transform: scale(1.2);
}

.appearance-slider-item input[type="range"]::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent);
  border: none;
  cursor: pointer;
}

.appearance-slider-item.disabled {
  opacity: 0.4;
  pointer-events: none;
}

.appearance-slider-item.disabled input[type="range"] {
  cursor: not-allowed;
}

.appearance-sliders-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.appearance-toggle-row {
  margin-top: 4px;
}

/* 背景图缩略图 */
.appearance-bg-thumb-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-start;
}

.appearance-bg-thumb {
  width: 80px;
  height: 80px;
  border-radius: var(--radius-md);
  overflow: hidden;
  position: relative;
  cursor: pointer;
  border: 1px solid var(--border);
}

.appearance-bg-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.appearance-bg-thumb.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 2px dashed var(--border-hover);
  color: var(--text-muted);
  font-size: 11px;
  background: var(--bg-glass-light);
  transition: border-color 0.2s ease, color 0.2s ease;
}

.appearance-bg-thumb.empty:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.appearance-bg-thumb-zoom {
  position: absolute;
  bottom: 4px;
  right: 4px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s ease;
  backdrop-filter: blur(4px);
}

.appearance-bg-thumb:hover .appearance-bg-thumb-zoom {
  opacity: 1;
}

.appearance-bg-thumb-remove {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  border: none;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease, transform 0.2s ease;
}

.appearance-bg-thumb-remove:hover {
  background: var(--error);
  transform: scale(1.1);
}

.appearance-bg-thumb-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

/* sr-only */
.appearance-field .sr-only,
.appearance-color-row + .sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

/* form-hint */
.form-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  margin-bottom: 0;
}

/* 背景图 lightbox */
.bg-lightbox-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-max);
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
  cursor: zoom-out;
}

.bg-lightbox-content {
  position: relative;
  max-width: 90vw;
  max-height: 90vh;
}

.bg-lightbox-content img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: var(--radius-md);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.bg-lightbox-close {
  position: absolute;
  top: -12px;
  right: -12px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.7);
  border: 2px solid rgba(255, 255, 255, 0.2);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease, transform 0.2s ease;
}

.bg-lightbox-close:hover {
  background: var(--error);
  transform: scale(1.1);
}

/* 自定义背景样式 */
body.has-custom-bg::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: var(--bg-image);
  background-size: cover;
  background-position: center;
  filter: var(--bg-blur);
  opacity: var(--bg-opacity, 0.3);
  z-index: -1;
}

/* 随机壁纸弹窗 */
.random-wallpaper-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal);
  backdrop-filter: var(--blur-sm);
}

.random-wallpaper-modal {
  background: var(--bg-modal);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  width: 420px;
  max-width: 90vw;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.random-wallpaper-header {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-primary);
}

.random-wallpaper-header h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.random-wallpaper-hint {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.5;
}

.random-wallpaper-modal .form-input {
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.random-wallpaper-modal .form-input:focus-visible {
  border-color: var(--accent);
}

.random-wallpaper-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* 响应式：窄屏降级为单列 */
@media (max-width: 700px) {
  .appearance-grid-2col {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 2: 浏览器中确认样式生效**

刷新外观页，确认：
- 卡片 header 高度 48px、图标主题色
- 双栏 grid 子项对齐
- 颜色圆点 hover scale、active 描边光晕
- 滑块三栏对齐、thumb 主题色圆点
- segmented 选中态主题色背景
- 背景图缩略图 80×80 圆角

- [ ] **Step 3: Commit**

```bash
git add frontend/styles/pages/appearance.css
git commit -m "style(appearance): 重写卡片与控件样式"
```

---

## Task 6: app-options.js — watcher 持久化 customColors

**Files:**
- Modify: `frontend/js/app-options.js:225-237`

- [ ] **Step 1: 在 appearance watcher 中追加 customColors 持久化**

将 `frontend/js/app-options.js` 中 `watch.appearance` 块改为：

```javascript
    appearance: {
      handler() {
        // 防抖：避免频繁操作 DOM 导致卡顿
        if (this._appearanceTimer) clearTimeout(this._appearanceTimer);
        this._appearanceTimer = setTimeout(() => {
          this.applyAppearance();
          localStorage.setItem('appearance', JSON.stringify(this.appearance));
        }, 100);
      },
      deep: true,
    },
    customColors: {
      handler() {
        localStorage.setItem('appearance.custom_colors', JSON.stringify(this.customColors));
      },
      deep: true,
    },
```

- [ ] **Step 2: 浏览器中验证**

刷新外观页：
- 选择自定义颜色 → 刷新页面 → 自定义色仍在
- 长按/右键自定义色 → 确认删除 → 刷新 → 已删除

- [ ] **Step 3: Commit**

```bash
git add frontend/js/app-options.js
git commit -m "feat(appearance): watcher 持久化 customColors"
```

---

## Task 7: 最终验收 — 全部验收标准核对

**Files:** 无改动，仅验证

- [ ] **Step 1: 启动应用并访问外观页**

```bash
python main.py
```

- [ ] **Step 2: 逐条核对验收标准**

1. ✓ 4 张分区卡单列纵向排列
2. ✓ 缩放卡片及 zoom 字段完全移除（grep `zoom` 仅命中 lightbox zoom-out 类名等无关项）
3. ✓ 4 个颜色控件行为一致：预设圆点 + 「+」唤 picker，自定义色持久化，长按/右键可删
4. ✓ 6 个滑块三栏对齐，禁用态（关闭毛玻璃时玻璃模糊滑块）opacity 0.4
5. ✓ 主题切换三段式 segmented，含「跟随系统」，切换系统主题时自动响应
6. ✓ 每卡右上角「恢复默认」仅在偏离默认时显示，点击只重置该卡
7. ✓ 背景图缩略图 80×80，点击放大 lightbox，右上角 × 移除
8. ✓ 所有控件改动实时应用（改颜色/滑块立即生效）
9. ✓ 窄屏（缩窗至 ≤700px）双栏降级为单列
10. ✓ 浅色/深色主题下视觉一致

- [ ] **Step 3: grep 确认无残留引用**

```bash
grep -rn "appearance.zoom\|DEFAULT_APPEARANCE.zoom\|appearance-font-preview\|appearance-settings-grid\|appearance-actions" frontend/
```

预期：无输出（或仅命中注释，无功能引用）。

- [ ] **Step 4: 运行 ruff 检查（前端 JS 不在 ruff 范围，跳过）**

无需 ruff，前端文件不参与 Python lint。

- [ ] **Step 5: Commit 验收记录**

无需 commit，验收通过即完成。

---

## 自审

**1. Spec 覆盖**：
- 信息架构 4 卡 → Task 4 ✓
- 颜色控件统一 + 自定义持久化 → Task 1/2/3/6 ✓
- 滑块统一 → Task 5 ✓
- 主题切换三选一含 auto → Task 3 ✓
- 重置入口每卡 → Task 3/4 ✓
- 背景图缩略图 + lightbox → Task 4/5 ✓
- 删除 zoom → Task 1/3 ✓
- 实时应用 + 100ms 防抖 → Task 6 ✓
- 窄屏降级 → Task 5 ✓

**2. 占位符扫描**：无 TBD/TODO；所有代码块完整。

**3. 类型一致性**：
- `customColors` 在 constants/data/methods/app-options 中字段名一致（accent/bg/sidebar/sidebar_accent）
- `resetCard(cardKey)` 接受 'background' | 'theme' | 'card' | 'sidebar'，与 `cardDirty` 一致
- `getColorList(type)` 接受 'accent' | 'bg' | 'sidebar' | 'sidebar_accent'，与 addCustomColor/removeCustomColor/onCustomColorPicked 一致
- `fieldMap` 在 onCustomColorPicked 中映射 type → appearance 字段，与 resetCard 的 fields 映射一致

自审通过。
