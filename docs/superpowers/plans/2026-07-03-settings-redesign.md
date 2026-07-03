# Settings 页面重构实施计划

**日期**: 2026-07-03
**设计文档**: `docs/superpowers/specs/2026-07-03-settings-redesign-design.md`
**涉及页面**: 账号、浏览器、监控、系统、任务（5 个 Tab）

---

## 背景

外观页面（appearance）已完成视觉重构，采用统一的卡片头部图标规范。现需将其余 5 个设置页面对齐到同一视觉标准，同时修复 IA 结构问题（监控页 4→3、系统页 3→4）。

**约束**:
- 只改 HTML + CSS，不改 JS 逻辑
- 不修改外观页面（已定稿）
- 保持 v3.6.0 功能完整

---

## 任务列表

### Task 1: settings.css — 新增统一样式类

**文件**: `frontend/styles/pages/settings.css`

**新增类**（对齐 appearance.css 的命名风格）:

```css
.settings-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 48px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border);
}

.settings-card-icon {
  width: 20px;
  height: 20px;
  color: var(--accent);
  opacity: 0.7;
  flex-shrink: 0;
}

.settings-card-header h2 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
  flex: 1;
}
```

**新增工具类**:

```css
.settings-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.settings-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.settings-field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.settings-toggle-spacer {
  margin-top: 12px;
}

.settings-toggle-compact {
  margin-top: -4px;
}

.settings-monospace-textarea {
  font-family: monospace;
  font-size: 12px;
  resize: vertical;
}

@media (max-width: 700px) {
  .settings-grid-2col {
    grid-template-columns: 1fr;
  }
}
```

**保留的类**（保持兼容）:
- `.settings-log-columns` — 标记为 deprecated，功能由 `.settings-grid-2col` 替代
- `.settings-detect-columns` — 标记为 deprecated，功能由 `.settings-grid-2col` 替代
- 其余所有现有类保持不变

**预计变更**: +60 行 CSS，0 行删除

---

### Task 2: settings-monitor.html — IA 4→3（合并检测+重试）

**文件**: `frontend/partials/pages/settings/settings-monitor.html`

**变更说明**:
- 当前 4 个 section: 检测设置 / 网络检测方式 / 重试策略 / 暂停时段
- 重构为 3 个 section: **检测与重试**（合并检测设置+重试策略） / 网络检测方式 / 暂停时段

**卡片图标**:
| 卡片 | 图标 SVG |
|------|---------|
| 检测与重试 | `<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>`（eye） |
| 网络检测方式 | `<path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/>`（wifi） |
| 暂停时段 | `<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>`（clock） |

**具体操作**:

1. 给现有 3 个有 `.card-header` 的 section 加图标（检测设置、重试策略、暂停时段）
2. 把"检测设置"和"重试策略"的 card-body 内容合并到一个 section
3. 给合并后的 section 命名为"检测与重试"
4. 用 `.settings-grid-2col` 替换 `.settings-detect-columns`（在"网络检测方式"卡片内）
5. 删除所有内联 `style="margin-top: 12px;"` 和 `style="margin-top: -4px;"`，改用 `.settings-toggle-spacer` / `.settings-toggle-compact` CSS 类

**预计变更**: ~259 行 → ~230 行（减少重复的 card-header）

---

### Task 3: settings-system.html — IA 3→4（拆分启动与界面）

**文件**: `frontend/partials/pages/settings/settings-system.html`

**变更说明**:
- 当前 3 个 section: 日志设置 / 启动与界面（含分隔线） / 网络与端口
- 重构为 4 个 section: 日志设置 / **启动行为** / **界面行为** / 网络与端口

**卡片图标**:
| 卡片 | 图标 SVG |
|------|---------|
| 日志设置 | `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><polyline points="14 2 14 8 20 8"/>`（file-text） |
| 启动行为 | `<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>`（power） |
| 界面行为 | `<rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>`（monitor） |
| 网络与端口 | `<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>`（server） |

**具体操作**:

1. 将"启动与界面"卡片拆分为两个独立 `<section class="card settings-panel">`
2. "启动行为"包含: 自动启动监控、窗口启动行为、开机自启动
3. "界面行为"包含: 实时日志推送、启用动画
4. 删除 `.settings-section-divider` 分隔线
5. 用 `.settings-grid-2col` 替换 `.settings-log-columns`（在"日志设置"卡片内）
6. 给 4 个卡片都加上图标头部
7. 删除 `autostart-method-badge` 的内联样式引用（如有），保持 CSS 类

**预计变更**: ~192 行 → ~220 行（拆分增加结构，减少分隔线）

---

### Task 4: settings-account.html — 视觉对齐

**文件**: `frontend/partials/pages/settings/settings-account.html`

**变更说明**: IA 不变（2 卡片），仅加图标头部

**卡片图标**:
| 卡片 | 图标 SVG |
|------|---------|
| 账号配置 | `<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>`（user） |
| 自定义变量 | `<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>`（code） |

**具体操作**:

1. 将 `<div class="card-header"><h2>xxx</h2></div>` 替换为带图标的 `.settings-card-header` 结构
2. 保持 `.card-body` 内容不变

**预计变更**: ~140 行 → ~150 行

---

### Task 5: settings-browser.html — 视觉对齐 + 内联样式清理

**文件**: `frontend/partials/pages/settings/settings-browser.html`

**变更说明**: IA 不变（4 卡片），加图标头部 + 清理内联样式

**卡片图标**:
| 卡片 | 图标 SVG |
|------|---------|
| 浏览器类型 | `<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/><line x1="21.17" y1="8" x2="12" y2="8"/><line x1="3.95" y1="6.06" x2="8.54" y2="14"/>`（globe） |
| 基本设置 | `<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>`（settings gear — 太复杂，改用 sliders） |
| 基本设置（简化） | `<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>`（sliders） |
| 安全与反检测 | `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>`（shield） |
| 纯净模式与高级设置 | `<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>`（star） |

**具体操作**:

1. 替换 4 个 `<div class="card-header">` 为带图标的 `.settings-card-header`
2. 删除 textarea 上的内联 `style="font-family: monospace; font-size: 12px; resize: vertical;"`，改用 `.settings-monospace-textarea` CSS 类

**预计变更**: ~263 行 → ~275 行

---

### Task 6: settings-tasks.html — 视觉对齐 + 内联样式清理

**文件**: `frontend/partials/pages/settings/settings-tasks.html`

**变更说明**: IA 不变（3 卡片），加图标头部 + 清理内联样式

**卡片图标**:
| 卡片 | 图标 SVG |
|------|---------|
| 任务概览 | `<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>`（layout-grid） |
| 任务录制器 | `<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/>`（circle-dot / record） |
| OCR 依赖 | `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/>`（file-check） |

**具体操作**:

1. 任务概览卡片: 目前没有 card-header（直接是 card-body），需加图标头部
2. 任务录制器: 替换内联 SVG `style="width:18px;height:18px;color:var(--accent);vertical-align:-3px;margin-right:6px;"` 为 `.settings-card-icon` 类
3. OCR 依赖: 替换 card-header 为带图标的 `.settings-card-header`，保留右侧操作按钮

**预计变更**: ~123 行 → ~140 行

---

## 执行顺序

1. **Task 1** (CSS) — 先完成，后续 HTML 任务依赖这些类
2. **Task 2-6** (HTML) — 可并行，互不依赖

## 验证

每个 Task 完成后:
- 浏览器打开对应页面，确认视觉效果
- 检查响应式：浏览器窗口缩到 700px 以下，双列应变单列
- 检查无控制台错误
- 全部完成后运行 `uv run ruff check .` + `uv run ruff format .`
