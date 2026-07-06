# 设置页重构设计文档

**日期**：2026-07-03
**版本**：v1.0

## 背景

Campus-Auth 设置页（settings）共 5 个 tab：account / browser / monitor / system / tasks，共 16 张卡片。当前问题：

1. **卡片头部无图标**：除 tasks 的「任务录制器」卡有内联 SVG 外，其他 15 张卡 header 无图标，与已重构的 appearance 页风格不一致
2. **字段容器不统一**：散乱使用 form-group / form-row / settings-log-columns / settings-detect-columns，双栏参数不一致（gap 16 vs 24 vs 32）
3. **内联样式泛滥**：monitor 的 `margin-top: 12px/-4px`、browser 的 `font-family: monospace`、tasks 的 SVG inline style
4. **无响应式降级**：双栏布局（log/detect columns）在窄屏会溢出，仅有 save-bar 在 560px 响应
5. **信息架构不一致**：system 的「启动与界面」卡内塞了 3 个 section divider 分组，密度太高；monitor 的「检测设置」和「重试策略」逻辑上应合并

## 目标

1. 视觉层与 appearance 对齐：统一卡片头部图标、字段容器、双栏参数、响应式
2. 信息架构轻度重组：system 拆「启动行为」+「界面行为」，monitor 合并「检测与重试」
3. 消除内联样式，统一 CSS 类
4. 保留全局 save-bar 交互不变

## 非目标

- 不改 JavaScript（data/methods/app-options）
- 不改后端 API
- 不改 tasks 页信息架构（仅视觉对齐）
- 不加 per-card 恢复默认按钮（保持 save-bar 交互）

## 决策记录

| 决策项 | 选择 | 理由 |
|---|---|---|
| 重构范围 | 视觉层 + 信息架构 | 最小风险、快速迭代 |
| Tasks 页 | 仅视觉对齐 | 无表单控件，信息架构重组无意义 |
| IA 方向 | 轻度重组 A，browser 不合并 | 与 appearance 风格一致，browser 4 卡各有主题 |
| 卡片图标 | 所有 16 张卡统一 Lucide 描边图标 | 视觉延续性强 |
| 字段容器 | 新建 settings- 前缀类 | settings 自治，避免 appearance- 语义混淆 |
| 响应式 | ≤700px 降级单列 | 与 appearance 一致 |
| 内联样式 | 全部抽为 CSS 类 | 代码可维护性 |

## 信息架构变更

### monitor（4 卡 → 3 卡）

**原结构**：
1. 检测设置（间隔、超时、屏蔽代理）
2. 网络检测方式（双栏：网络状态检测 / 登录前检测）
3. 重试策略（最大重试、重试间隔、并发数）
4. 暂停时段（开关 + 时间段）

**新结构**：
1. **检测与重试**（合并原 1+3）：检测间隔、超时、屏蔽代理、最大重试、重试间隔、并发数
2. **网络检测方式**（不变）
3. **暂停时段**（不变）

### system（3 卡 → 4 卡）

**原结构**：
1. 日志设置（双栏：日志级别+保留天数 / 日志路径+最大文件数）
2. 启动与界面（3 个 section divider：启动行为 / 开机自启动 / 界面行为）
3. 网络与端口（端口 + Shell 模式）

**新结构**：
1. **日志设置**（不变）
2. **启动行为**（从原卡 2 拆出）：启动后执行、开机自启动模式、自启动方法徽标
3. **界面行为**（从原卡 2 拆出）：轻量模式托盘、最小化到托盘、静默启动
4. **网络与端口**（不变）

### 其他页面

- **account**：2 卡 → 2 卡（不变）
- **browser**：4 卡 → 4 卡（不变，仅视觉对齐）
- **tasks**：3 卡 → 3 卡（不变，仅视觉对齐）

## 视觉规范

### 卡片头部（新增）

参照 appearance 的 `.appearance-card-header`，新建 `.settings-card-header`：

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

.settings-card-header h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
  flex: 1;
}
```

所有 16 张卡都使用此结构，图标选用 Lucide 风格描边 SVG。

### 字段容器（新增）

新建 `.settings-field` / `.settings-field-label` / `.settings-grid-2col`：

```css
.settings-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 20px;
}

.settings-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.settings-field-label {
  font-size: 12px;
  color: var(--text-secondary);
}
```

废弃的类（从 settings.css 移除）：
- `.form-group`（全局类，settings.css 不再覆写）
- `.form-row`（settings.css 不再定义）
- `.settings-log-columns`（替换为 `.settings-grid-2col`）
- `.settings-detect-columns`（替换为 `.settings-grid-2col`）

### 响应式

```css
@media (max-width: 700px) {
  .settings-grid-2col {
    grid-template-columns: 1fr;
  }
}
```

### 内联样式清理

| 页面 | 原内联样式 | 替换为 CSS 类 |
|---|---|---|
| monitor | `style="margin-top: 12px;"` | `.settings-toggle-spacer` |
| monitor | `style="margin-top: -4px;"` | `.settings-toggle-compact` |
| browser | `style="font-family: monospace; font-size: 12px; resize: vertical;"` | `.settings-monospace-textarea` |
| tasks | `style="width:18px;height:18px;..."`（SVG） | `.settings-card-icon`（复用卡片图标类） |

## 变更文件

| 文件 | 改动 |
|---|---|
| `frontend/styles/pages/settings.css` | 重写：新增卡片头部、字段容器、响应式；废弃旧类 |
| `frontend/partials/pages/settings/settings-monitor.html` | 合并「检测设置」+「重试策略」为「检测与重试」 |
| `frontend/partials/pages/settings/settings-system.html` | 拆「启动与界面」为「启动行为」+「界面行为」 |
| `frontend/partials/pages/settings/settings-account.html` | 卡片头部加图标 |
| `frontend/partials/pages/settings/settings-browser.html` | 卡片头部加图标 + 消除内联样式 |
| `frontend/partials/pages/settings/settings-tasks.html` | 卡片头部加图标 + 消除内联样式 |

## 验收标准

1. 所有 16 张卡都有 Lucide 描边图标 + accent 色
2. 所有双栏布局使用 `.settings-grid-2col`，参数一致（1fr 1fr, gap 16×20）
3. 所有字段使用 `.settings-field` + `.settings-field-label`
4. 响应式：≤700px 双栏降级单列
5. 无内联样式（`style="..."`）
6. monitor 合并后「检测与重试」卡功能完整
7. system 拆分后「启动行为」和「界面行为」卡功能完整
8. save-bar 交互不变（全局保存、三态：dirty/saving/failed）
9. tasks 页视觉对齐，信息架构不变
