# 外观设置页面 Redesign 设计文档

- 日期：2026-07-03
- 范围：仅前端 `frontend/` 目录，主要涉及 `partials/pages/appearance.html`、`styles/pages/appearance.css`、`js/data/appearance.js`、`js/methods/appearance.js`、`js/constants.js`、`js/app-options.js`
- 不涉及后端改动

## 一、目标

优化外观设置页的视觉层级、控件一致性、现代美学，并删除缩放设置。

### 改进重点

1. 视觉层级与信息密度 — 当前 6 张同权重卡片平铺，主次不分
2. 控件体验与一致性 — 颜色控件、滑块、重置按钮散落各处，模式不统一
3. 整体美学与现代感 — 卡片样式、配色、毛玻璃、阴影等视觉语言偏旧
4. 删除缩放设置 — zoom 卡片整体移除

## 二、信息架构

### 当前结构

- 背景图片卡片（全宽）
- 6 张设置卡片（3 列网格）：主题色、毛玻璃、背景颜色、卡片样式、缩放、侧边栏

### 新结构

合并为 **4 张分区卡**，单列纵向排列（每张占整行），不再用 3 列网格。窄屏无需降级（本来就是单列）。

| 分区卡 | 子项 |
|---|---|
| 背景与氛围 | 背景图（缩略图+lightbox）、模糊、遮罩、毛玻璃开关+模糊度 |
| 主题与配色 | 主题切换（浅/深/跟随系统）、主题色、背景色 |
| 卡片样式 | 卡片不透明度、边框强度 |
| 侧边栏 | 不透明度、侧边栏色、侧边栏高亮色 |

### 删除项

- 缩放卡片整体移除
- 删除 `appearance.zoom` 字段
- 删除 `applyAppearance` 中 zoom 相关逻辑（wrapper transform）
- 删除 `DEFAULT_APPEARANCE.zoom` 默认值

## 三、统一控件规范

所有控件统一为 3 类原子控件，跨 4 张卡复用。

### 颜色控件

适用于：主题色、背景色、侧边栏色、侧边栏高亮色。

- 预设圆点行 + 末尾一个「+」圆点（虚线边框）
- 点击预设圆点 = 直接选中
- 点击「+」= 唤起原生 color picker，选色后该自定义色以实心圆点加入预设区末尾
- 当前选中色：圆点加白色描边 + 主题色光晕
- 旁边小字显示当前 hex（如 `#22d3ee`），用 `var(--font-mono)`
- 自定义色持久化：存 localStorage 单独 key `appearance.custom_colors`，结构按类型分组：
  ```json
  {
    "accent": ["#ff6b6b"],
    "bg": ["#1a2b3c"],
    "sidebar": [],
    "sidebar_accent": []
  }
  ```
  - 下次刷新仍在
  - 长按或右键自定义色圆点 = 删除该自定义色（系统预设色不可删，无删除交互）
  - 删除时若该色正被使用，回退到默认色

### 滑块控件

适用于：模糊、遮罩、毛玻璃模糊度、卡片不透明度、边框强度、侧边栏不透明度。

- 三栏 grid：`label (48px) | track (1fr) | value (44px 右对齐)`
- track 用原生 `<input type="range">` + 自定义 CSS（轨道、滑块圆点主题色化）
- value 用等宽字体显示（如 `12px`、`45%`、`1.0x`）
- 禁用态（如关闭毛玻璃时模糊度滑块）：轨道+圆点 opacity 0.4，禁止交互

### 开关控件

适用于：毛玻璃开关。

- 沿用现有 toggle，去掉说明文字「启用毛玻璃效果」，改为卡片内副标题
- 关闭时连带禁用的子项用浅色包裹（视觉提示「以下无效」）

### 主题切换控件

- 三段式 segmented control：`浅色 | 深色 | 跟随系统`
- 选中段背景为主题色弱化版（`rgba(accent, 0.15)`）+ 文字主题色
- 未选中段透明背景
- 新增 `theme: 'auto'` 值
- applyAppearance 中：当 theme === 'auto' 时，监听 `matchMedia('(prefers-color-scheme: dark)')`，按系统主题设置 `data-theme`；系统主题变化时实时切换

## 四、卡片视觉与交互

### 卡片 header

- 高度 48px
- 左侧图标（20×20，主题色 30% 透明填充 + 主题色描边）+ 标题（14px 600）
- 右侧「恢复默认」文字按钮（仅当卡片内有项偏离默认时显示，hover 主题色化）
- 底部 1px 分隔线（`var(--border)`）

### 卡片 body

- padding 20px
- 双栏 grid：`grid-template-columns: 1fr 1fr; gap: 16px 20px`
- 子项高度不一时按 row 自动对齐
- 窄屏（≤700px）降级为单列

### 背景图缩略图

- 80×80 圆角（`var(--radius-md)`）
- 无图时：虚线边框 + 占位图标 + 「点击选择」
- 有图时：显示缩略图，hover 右下角放大图标，点击放大 lightbox，右上角 × 移除
- 与按钮组（选择图片、随机壁纸）同在左列

### 实时应用

- 沿用现有 applyAppearance（`js/methods/appearance.js`）
- 所有控件 `v-model` 绑定 `appearance.*`
- watcher 触发 applyAppearance + 100ms 防抖持久化到 localStorage
- 主题切换「跟随系统」：监听 `matchMedia('(prefers-color-scheme: dark)')`，变化时按系统主题设置 `data-theme`，存储用户选择为 `'auto'`

### 字体

- 标题：Inter 600
- hex 值、滑块数值：JetBrains Mono（`var(--font-mono)`）
- 提示文字（form-hint）：Inter 400 12px `var(--text-secondary)`

### 动画

- 卡片进入：复用现有 `pageEnter` 动画
- 分区卡 hover：轻微 border-color 变化（不抬升，避免分心）
- 颜色圆点 hover：scale 1.15（沿用现状）
- 「恢复默认」按钮出现/隐藏：fadeIn 0.2s

## 五、重置入口

- 每张分区卡右上角一个「恢复默认」文字按钮
- 仅当该卡片内有项偏离默认值时显示
- 点击后重置该卡片内所有项到默认值（不影响其他卡片）
- 不再有全局「恢复默认」按钮（移除当前页面底部的 `.appearance-actions`）

## 六、文件改动清单

### 新增

无新建文件，全部在现有文件上改动。

### 修改

| 文件 | 改动 |
|---|---|
| `frontend/partials/pages/appearance.html` | 重构整个页面结构：4 张分区卡 + 双栏 grid + 统一控件 |
| `frontend/styles/pages/appearance.css` | 重写卡片样式、新增颜色控件/滑块/segmented 样式、移除 zoom 相关样式、移除 `.appearance-settings-grid` 3 列网格 |
| `frontend/js/data/appearance.js` | 新增 `customColors` 数据（从 localStorage 加载） |
| `frontend/js/methods/appearance.js` | 新增 addCustomColor / removeCustomColor / resetCard 方法，删除 zoom 相关逻辑，新增 theme='auto' 处理 |
| `frontend/js/constants.js` | 删除 `DEFAULT_APPEARANCE.zoom`，新增 customColors 默认结构 |
| `frontend/js/app-options.js` | watcher 中持久化 customColors，移除 zoom 持久化 |

### 删除

- `appearance.zoom` 字段及所有引用
- `.appearance-settings-grid` 3 列网格样式
- `.appearance-font-preview` 字体预览样式
- 页面底部 `.appearance-actions` 全局重置按钮

## 七、验收标准

1. 外观页显示 4 张分区卡，单列纵向排列
2. 缩放卡片及 zoom 字段完全移除，无残留引用
3. 4 个颜色选择控件（主题色、背景色、侧边栏色、高亮色）行为一致：预设圆点 + 「+」唤 picker，自定义色持久化，长按/右键可删
4. 6 个滑块控件三栏对齐，禁用态视觉弱化
5. 主题切换三段式 segmented，含「跟随系统」选项，自动跟随系统主题
6. 每张分区卡右上角「恢复默认」仅在偏离默认时显示，点击只重置该卡
7. 背景图缩略图 80×80，点击放大 lightbox，右上角 × 移除
8. 所有控件改动实时应用到全局（applyAppearance），100ms 防抖持久化
9. 窄屏（≤700px）卡片内双栏降级为单列
10. 浅色/深色主题下视觉一致
