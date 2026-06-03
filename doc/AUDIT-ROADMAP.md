# Campus-Auth 审计路线图

> 生成于 2026-06-03

---

## 1. 审计全景

2026-06-02 审计报告 (`doc/audit-2026-06-02.md`) 共发现 **140 项**问题：

| 等级 | 数量 | 说明 |
|------|------|------|
| P0 (关键) | 22 | 必须立即修复 |
| P1 (重要) | 45 | 下一迭代修复 |
| P2 (中等) | 45 | 计划内修复 |
| P3 (低) | 28 | 未来改进 |

经 P0 二次验证后调整：在本地约束(仅 `127.0.0.1` 运行、单用户、无远程访问面)下，部分 P0 降级为 P1 或更低。

---

## 2. Stage 路径

### Stage 1: P0 + 降级 P1（已合并）

8 项关键修复，已合入 main 分支。涵盖并发死锁、WS 重连竞态、Worker 崩溃恢复等核心问题。

### Stage 2: 45 项 P1（进行中）

15 个任务，覆盖后端并发/状态、前端生命周期、安全策略、测试覆盖等方面。

### Stage 3: 78 项 P2（本计划，9 任务修订版）

中等问题修复，包括死代码清理、CSS 兼容性、日志规范、边界条件处理等。

### Stage 4: 28 P3 + 残余（未来）

低优先级改进和 Stage 1-3 中未能覆盖的遗留项。

---

## 3. 显式跳过项（~15 项）

### 已修复/不存在（8 项，初版误判）

| 编号 | 描述 | 原因 |
|------|------|------|
| FE-WS-区分 | WS 异常区分 | `main.py:199` 已正确处理 |
| FE-API-422 | extractApiError 422 | `utils.js:9` 已处理 |
| FE-WS-UI | WS 重连 UI 提示 | `lifecycle.js:238` 已有 |
| FE-quit-守卫 | quitApp WS 重连守卫 | `ui.js:169` 已有 |
| FE-watch-冗余 | watch 冗余 localStorage | 无 immediate，不存在 |
| SR-net-ok | net_ok force 参数 | 不在 `login.py` |
| SEC-ENC | password ENC 检测 | `crypto.py` 已处理 |
| BE-subprocess | scheduler_service.py subprocess.run | 用的 asyncio |

### 本地约束无影响（6 项 P0 降级）

| 编号 | 描述 | 降级理由 |
|------|------|----------|
| P0-SEC-1 | SSRF | 仅本地运行，无远程攻击面 |
| P0-SEC-3 | 日志目录遍历 | 本机服务，用户已拥有完整文件系统权限 |
| P0-CSS-1 | .fade-in | Vue 内置 transition，无需自定义动画 |
| P0-CSS-4 | 对比度 | 4.0:1 边缘可读，满足 WCAG AA 最低要求 |
| P0-FE-2 | quitApp 闪 | 150ms 自愈，用户体验影响极小 |
| P0-FE-3 | closeRepoImport | 3s 自愈，非关键路径 |

### 代码异味/设计决策（~12 项草稿 L-*）

L-1 `print()` 残留、L-2/L-11 `console.warn`、L-3 magic strings、L-5/L-6/L-7/L-10/L-13~15/L-17/L-19/L-20 等——属于代码风格偏好，不影响功能正确性，留作未来统一清理。

### 有意设计（3 项）

| 项目 | 说明 |
|------|------|
| shortcuts 全局快捷键 | 全局导航功能，非 bug |
| applyAppearanceEarly | pre-Vue 保底，防止 FOUC |
| mask_password 固定 8 bullet | 防止密码长度泄露，有意设计 |

---

## 4. Stage 4 起点

28 项 P3 中约 **15 项高 ROI**，可在 Stage 3 完成后优先处理：

- 前端死代码清理（未使用的 CSS 类、废弃的事件绑定）
- 日志规范化（统一日志级别和格式）
- 边界条件加固（空数组/空对象防御性检查）
- 测试补全（`app.py` 入口路径、前端组件快照）
