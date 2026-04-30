# Campus-Auth 任务编写手册

本文档详细描述 Campus-Auth 任务系统的格式规范、参数配置及校验规则，帮助用户编写标准化的认证任务。

## 目录

1. [任务结构概述](#任务结构概述)
2. [任务格式规范](#任务格式规范)
3. [步骤类型详解](#步骤类型详解)
4. [变量系统](#变量系统)
5. [条件判断](#条件判断)
6. [执行行为说明](#执行行为说明)
7. [多网络配置方案（Profiles）](#多网络配置方案profiles)
8. [任务管理功能](#任务管理功能)
9. [校验规则](#校验规则)
10. [最佳实践](#最佳实践)
11. [示例任务](#示例任务)
12. [API 参考](#api-参考)
13. [环境变量参考](#环境变量参考)

---

## 任务结构概述

一个完整的任务由以下部分组成：

```
任务定义
├── 基本信息（name, description, version, source）
├── 变量定义（variables）
├── 步骤列表（steps）
├── 成功条件（success_conditions）
├── 结果处理（on_success, on_failure）
└── 元数据（metadata）
```

---

## 任务格式规范

### 完整结构

```json
{
  "name": "任务名称",
  "description": "任务描述",
  "version": "1.0.0",
  "source": "api",
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "variables": {
    "username": "{{USERNAME}}",
    "password": "{{PASSWORD}}"
  },
  "steps": [
    {
      "id": "step_1",
      "type": "navigate",
      "description": "打开登录页面",
      "url": "{{url}}"
    }
  ],
  "success_conditions": [
    {
      "type": "variable",
      "variable": "login_success",
      "value": true
    }
  ],
  "on_success": {
    "message": "登录成功"
  },
  "on_failure": {
    "message": "登录失败",
    "screenshot": true
  },
  "metadata": {}
}
```

### 字段说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | 任务名称，显示在任务列表中 |
| `description` | string | 否 | "" | 任务描述 |
| `version` | string | 否 | "1.0.0" | 任务版本 |
| `source` | string | 否 | "api" | 任务来源：`builtin`（内置）、`signed`（签名）、`api`（用户创建） |
| `url` | string | 否 | "" | 任务基础URL，可用于自动导航 |
| `timeout` | number | 否 | 30000 | 全局超时时间（毫秒） |
| `variables` | object | 否 | {} | 变量定义，支持模板语法 |
| `steps` | array | 是 | [] | 步骤列表，按顺序执行 |
| `success_conditions` | array | 否 | [] | 成功条件，全部满足才算成功 |
| `on_success` | object | 否 | {} | 成功时的处理 |
| `on_failure` | object | 否 | {} | 失败时的处理 |
| `metadata` | object | 否 | {} | 用户自定义元数据，执行器不使用，可用于存储附加信息 |

#### 关于 `source` 字段

`source` 标识任务的来源，影响任务的编辑权限：

- `builtin`：内置任务，随项目分发。Web 控制台保存时会保留此来源，不会被覆盖为 `api`。
- `signed`：签名任务，来源可信。同样在保存时保留原始来源。
- `api`：用户通过 Web 控制台或 API 创建的任务，可自由编辑。

内置任务在 Web 控制台的任务列表中会显示"内置"标签。

#### 关于 `metadata` 字段

`metadata` 是一个自由结构的对象，执行器不会读取或使用其中的数据。你可以用它存储任务的附加信息，例如作者、创建时间、适配的校园网型号等。

---

## 步骤类型详解

### 步骤公共字段

所有步骤类型都支持以下公共字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 步骤类型 |
| `description` | string | 否 | "" | 步骤描述，会输出到日志 |
| `timeout` | number | 否 | 视类型而定 | 超时时间（毫秒） |

#### 扩展字段（extra）

步骤中任何未被识别的字段会被自动收集到 `extra` 中，并在序列化时合并回顶层。这意味着你可以在步骤中添加自定义字段，它们会被保留但不影响执行逻辑。

---

### 1. navigate - 页面导航

打开指定URL的页面。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `url` | string | 是 | - | 目标URL（支持变量） |
| `wait_until` | string | 否 | "networkidle" | 等待条件：`load` / `domcontentloaded` / `networkidle` |
| `timeout` | number | 否 | 30000 | 超时时间（毫秒） |

**示例：**

```json
{
  "id": "navigate_login",
  "type": "navigate",
  "description": "打开登录页面",
  "url": "{{LOGIN_URL}}",
  "wait_until": "domcontentloaded",
  "timeout": 10000
}
```

---

### 2. input - 文本输入

在输入框中填写文本。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `selector` | string | 是 | - | 元素选择器（支持多个，逗号分隔） |
| `value` | string | 是 | - | 输入值（支持变量） |
| `clear` | boolean | 否 | true | 是否先清空输入框 |
| `timeout` | number | 否 | 5000 | 超时时间（毫秒） |

**示例：**

```json
{
  "id": "input_username",
  "type": "input",
  "description": "输入用户名",
  "selector": "input[name='username'], #username",
  "value": "{{USERNAME}}",
  "clear": true
}
```

---

### 3. click - 点击元素

点击页面元素。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `selector` | string | 是 | - | 元素选择器（支持多个，逗号分隔） |
| `timeout` | number | 否 | 5000 | 超时时间（毫秒） |

**示例：**

```json
{
  "id": "click_login",
  "type": "click",
  "description": "点击登录按钮",
  "selector": "button[type='submit'], #login-btn",
  "timeout": 3000
}
```

---

### 4. select - 下拉选择

选择下拉框选项。此步骤有特殊容错行为：

- 如果 `value` 为空，步骤自动跳过（视为成功）。
- 如果找不到下拉框元素，步骤自动跳过（视为成功）。
- 如果精确匹配 `value` 失败，会回退到按选项文本进行模糊匹配（子字符串包含）。

这些设计是为了兼容不同校园网页面中运营商选择框的差异。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `selector` | string | 是 | - | 下拉框选择器 |
| `value` | string | 是 | - | 选项值（支持变量），支持模糊匹配 |
| `timeout` | number | 否 | 5000 | 超时时间（毫秒） |

**示例：**

```json
{
  "id": "select_isp",
  "type": "select",
  "description": "选择运营商",
  "selector": "select[name='isp']",
  "value": "{{ISP}}"
}
```

---

### 5. wait - 等待元素

等待元素出现在页面上。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `selector` | string | 是 | - | 等待的元素选择器 |
| `timeout` | number | 否 | 5000 | 超时时间（毫秒） |

**示例：**

```json
{
  "id": "wait_result",
  "type": "wait",
  "description": "等待结果出现",
  "selector": ".success-message, .error-message",
  "timeout": 10000
}
```

---

### 6. wait_url - 等待URL

等待URL匹配指定模式。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `pattern` | string | 是 | - | URL正则表达式模式 |
| `timeout` | number | 否 | 5000 | 超时时间（毫秒） |

**示例：**

```json
{
  "id": "wait_redirect",
  "type": "wait_url",
  "description": "等待跳转",
  "pattern": "success|welcome",
  "timeout": 10000
}
```

---

### 7. eval - JavaScript求值

执行JavaScript并可选保存结果。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `script` | string | 是 | - | JavaScript代码（支持变量） |
| `store_as` | string | 否 | - | 结果存储到的变量名 |

> **兼容性说明：** `code` 字段是 `script` 的已废弃别名，仍然支持但建议使用 `script`。

> **安全提示：** 包含 `eval` 步骤的任务在 Web 控制台保存时会弹出安全确认对话框，显示待执行的代码内容，需要用户明确确认。

**示例：**

```json
{
  "id": "check_login_status",
  "type": "eval",
  "description": "检查登录状态",
  "script": "document.querySelector('.user-name') !== null",
  "store_as": "is_logged_in"
}
```

---

### 8. custom_js - 自定义JavaScript

执行自定义JavaScript代码（不返回值）。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `script` | string | 是 | - | JavaScript代码 |

> **兼容性说明：** 同 `eval`，`code` 字段是 `script` 的已废弃别名。

> **安全提示：** 同 `eval`，保存时会弹出安全确认对话框。

**示例：**

```json
{
  "id": "custom_action",
  "type": "custom_js",
  "description": "自定义操作",
  "script": "document.querySelector('#agree').click();"
}
```

---

### 9. screenshot - 截图

截取当前页面截图。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `path` | string | 否 | 自动生成 | 截图保存路径 |

**示例：**

```json
{
  "id": "capture_result",
  "type": "screenshot",
  "description": "截图保存结果"
}
```

---

### 10. sleep - 休眠等待

暂停指定时间。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `duration` | number | 否 | 1000 | 休眠时间（毫秒），最大 300000 |

**示例：**

```json
{
  "id": "wait_loading",
  "type": "sleep",
  "description": "等待加载完成",
  "duration": 2000
}
```

---

## 变量系统

### 预定义变量

任务执行时自动提供以下变量：

| 变量名 | 来源 | 说明 |
|--------|------|------|
| `USERNAME` | 环境变量 / Profile | 校园网用户名 |
| `PASSWORD` | 环境变量 / Profile | 校园网密码 |
| `LOGIN_URL` | 环境变量 / Profile | 认证页面地址 |
| `ISP` | 环境变量 / Profile | 运营商后缀 |
| `url` | 任务配置 | 任务定义的 url 字段 |
| `name` | 任务配置 | 任务名称 |
| `description` | 任务配置 | 任务描述 |
| `version` | 任务配置 | 任务版本 |

### 用户自定义变量

通过 Web 控制台【账号设置】页面添加的自定义变量，可以在所有任务中使用。

**配置位置：** 设置 → 账号设置 → 自定义变量

**示例：**
- 变量名：`MY_PARAM`，变量值：`extra_value`
- 在任务中使用：`{{MY_PARAM}}`

**使用场景：**
- 存储额外的认证参数
- 定义环境特定的值
- 存储敏感信息（如密钥）

**注意：** 自定义变量优先级高于环境变量，如果名称冲突会覆盖环境变量。

### 任务级自定义变量

在 `variables` 中定义：

```json
{
  "variables": {
    "username": "{{USERNAME}}",
    "password": "{{PASSWORD}}",
    "full_username": "{{USERNAME}}{{ISP}}"
  }
}
```

### 运行时变量

通过 `eval` 步骤的 `store_as` 存储：

```json
{
  "id": "check_result",
  "type": "eval",
  "script": "document.title.includes('成功')",
  "store_as": "login_success"
}
```

### 模板语法

使用 `{{variable_name}}` 引用变量：

```json
{
  "value": "{{USERNAME}}",
  "url": "{{LOGIN_URL}}?user={{USERNAME}}"
}
```

### 变量解析顺序

1. 运行时变量（通过 `eval` 步骤的 `store_as` 写入）
2. 用户自定义变量（Web 控制台设置）
3. 环境变量（系统环境与 `.env`）
4. 任务文件内 `variables` 字段

---

## 条件判断

### 条件类型

#### 1. variable - 变量值判断

```json
{
  "type": "variable",
  "variable": "login_success",
  "value": true
}
```

#### 2. url_contains - URL包含判断

```json
{
  "type": "url_contains",
  "pattern": "success"
}
```

#### 3. url_matches - URL正则匹配

```json
{
  "type": "url_matches",
  "pattern": "success|welcome|home"
}
```

#### 4. element_exists - 元素存在判断

```json
{
  "type": "element_exists",
  "selector": ".welcome-message"
}
```

#### 5. js_expression - JS表达式判断

```json
{
  "type": "js_expression",
  "script": "document.body.innerText.includes('成功')"
}
```

### 空成功条件

如果 `success_conditions` 为空数组，只要所有步骤执行完毕且没有失败，任务即视为成功。这是一种简化的成功判定方式，适合不需要复杂判断的场景。

---

## 执行行为说明

### 自动导航

如果任务的第一个步骤不是 `navigate` 类型，但任务定义了 `url` 字段，执行器会在执行步骤之前自动导航到该 URL。这意味着你不必在步骤列表开头显式添加一个 navigate 步骤。

### select 步骤容错

`select` 步骤采用宽松策略：

1. 如果 `value` 为空，步骤自动跳过（成功）。
2. 如果找不到下拉框元素，步骤自动跳过（成功）。
3. 选择时优先按 `value` 精确匹配选项的值属性。
4. 精确匹配失败后，回退到按选项文本进行子字符串包含匹配。

这种设计确保运营商选择在不同页面结构下都能兼容。

### 危险步骤检测

`eval` 和 `custom_js` 步骤可以执行任意 JavaScript 代码。系统会在以下环节进行安全检测：

- **后端保存时：** 检测到危险步骤会记录警告日志，包含代码内容（截断至 2000 字符）。
- **前端保存时：** 弹出安全确认对话框，显示待执行的代码内容，需要用户明确确认后才能保存。

---

## 多网络配置方案（Profiles）

Profiles 系统允许你为不同的网络环境（如宿舍 WiFi、教学楼 WiFi、有线网络）配置不同的认证参数，系统可以根据当前网络自动切换。

### 工作原理

1. 每个 Profile 可以设置匹配条件：网关 IP 或 WiFi SSID。
2. 系统检测当前网络的网关 IP 和 WiFi SSID。
3. 优先按网关 IP 匹配，其次按 SSID 匹配。
4. 匹配成功后自动切换到对应 Profile 的配置。

### Profile 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 方案名称 |
| `match_gateway_ip` | string | 匹配的网关 IP（留空则不匹配） |
| `match_ssid` | string | 匹配的 WiFi SSID（留空则不匹配） |
| `username` | string | 该方案专用的用户名（`use_global_credentials` 为 false 时生效） |
| `password` | string | 该方案专用的密码（加密存储） |
| `use_global_credentials` | boolean | 是否使用全局凭证（默认 true） |
| `use_global_advanced` | boolean | 是否使用全局高级设置（默认 true） |
| `auth_url` | string | 认证页面地址 |
| `carrier` | string | 运营商 |
| `check_interval_minutes` | number | 检测间隔（分钟） |
| `headless` | boolean | 是否无头模式 |
| `browser_timeout` | number | 浏览器超时 |
| `pause_enabled` | boolean | 是否启用暂停时段 |
| `pause_start_hour` | number | 暂停开始小时 |
| `pause_end_hour` | number | 暂停结束小时 |
| `network_targets` | string | 探测目标列表 |
| `custom_variables` | object | 自定义变量 |

### 自动切换

启用自动切换后，监控核心每 60 秒检测一次网络环境变化。当检测到当前网络匹配到不同的 Profile 时，会自动切换配置并重新加载监控。

### Web 控制台操作

在"配置方案"页面可以：

- 查看所有方案列表及当前活动方案
- 新建、编辑、删除方案
- 检测当前网络环境（网关 IP、WiFi SSID、匹配的方案）
- 开启/关闭自动切换
- 为每个方案独立配置凭证和高级设置

---

## 任务管理功能

### 任务导入/导出

在 Web 控制台的任务页面：

- **导出：** 点击任务的导出按钮，将任务下载为 `.json` 文件。
- **导入：** 点击导入按钮，选择 `.json` 文件导入为新任务。

### 任务复制

点击任务的复制按钮，会创建一个以 `_copy` 为后缀的副本，方便基于现有任务快速创建新任务。

### 任务来源保护

内置任务（`source: builtin`）和签名任务（`source: signed`）在通过 API 保存时，系统会保留其原始来源字段，防止被意外覆盖为用户任务。

---

## 校验规则

### 任务级校验

- `name` 必须存在且不为空
- `steps` 必须存在且为数组
- 任务 ID 必须符合正则：`^[A-Za-z][A-Za-z0-9_]*$`

### 步骤级校验

每个步骤必须包含：
- `id` - 唯一标识
- `type` - 步骤类型（必须是预定义类型之一）

各类型必需字段：

| 类型 | 必需字段 |
|------|----------|
| navigate | `url` |
| input | `selector`, `value` |
| click | `selector` |
| select | `selector`, `value` |
| wait | `selector` |
| wait_url | `pattern` |
| eval | `script`（兼容已废弃的 `code`） |
| custom_js | `script`（兼容已废弃的 `code`） |
| screenshot | 无 |
| sleep | 无 |

### 验证工具

使用 TaskValidator 验证任务：

```python
from src.task_executor import TaskValidator

is_valid, errors = TaskValidator.validate(task_dict)
if not is_valid:
    print("验证失败:", errors)
```

---

## 最佳实践

### 1. 选择器编写

- 使用多个备选选择器，提高兼容性：
  ```json
  "selector": "input[name='username'], #username, .login-user"
  ```

- 优先使用稳定的属性（如 name、id），避免使用易变的 class

### 2. 错误处理

- 设置合理的超时时间
- 启用失败截图便于调试
- 提供清晰的步骤描述

### 3. 变量使用

- 将重复的值定义为变量
- 使用有意义的变量名
- 避免变量循环引用

### 4. 步骤组织

- 为每个步骤设置描述
- 使用有意义的步骤ID
- 合理拆分复杂操作

### 5. 成功判定

- 简单场景可以留空 `success_conditions`，步骤全部完成即为成功
- 复杂场景建议组合使用 `eval` + `variable` 条件
- 认证页面会跳转的场景，优先用 `url_contains` 或 `url_matches`

---

## 示例任务

### 基础登录任务

```json
{
  "name": "校园网基础登录",
  "description": "使用标准选择器的登录任务",
  "version": "1.0.0",
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "variables": {
    "username": "{{USERNAME}}",
    "password": "{{PASSWORD}}",
    "isp": "{{ISP}}"
  },
  "steps": [
    {
      "id": "navigate",
      "type": "navigate",
      "description": "打开认证页面",
      "url": "{{url}}",
      "wait_until": "domcontentloaded"
    },
    {
      "id": "input_username",
      "type": "input",
      "description": "输入账号",
      "selector": "input[name='DDDDD'], input[name='username']",
      "value": "{{username}}",
      "clear": true
    },
    {
      "id": "input_password",
      "type": "input",
      "description": "输入密码",
      "selector": "input[name='upass'], input[type='password']",
      "value": "{{password}}",
      "clear": true
    },
    {
      "id": "select_isp",
      "type": "select",
      "description": "选择运营商",
      "selector": "select[name='ISP_select'], select[name='isp']",
      "value": "{{isp}}"
    },
    {
      "id": "click_login",
      "type": "click",
      "description": "点击登录",
      "selector": "input[name='0MKKey'], button[type='submit']"
    },
    {
      "id": "wait_result",
      "type": "wait",
      "description": "等待结果",
      "selector": ".success, .error, #msg",
      "timeout": 10000
    },
    {
      "id": "check_result",
      "type": "eval",
      "description": "检查结果",
      "script": "() => { const text = document.body.innerText; return text.includes('成功') || text.includes('已连接'); }",
      "store_as": "login_success"
    }
  ],
  "success_conditions": [
    {
      "type": "variable",
      "variable": "login_success",
      "value": true
    }
  ],
  "on_success": {
    "message": "登录成功"
  },
  "on_failure": {
    "message": "登录失败",
    "screenshot": true
  }
}
```

### 精简登录任务（利用自动导航）

```json
{
  "name": "精简登录",
  "description": "利用自动导航和空成功条件的简化任务",
  "version": "1.0.0",
  "url": "{{LOGIN_URL}}",
  "timeout": 15000,
  "steps": [
    {
      "id": "input_username",
      "type": "input",
      "selector": "#username",
      "value": "{{USERNAME}}"
    },
    {
      "id": "input_password",
      "type": "input",
      "selector": "#password",
      "value": "{{PASSWORD}}"
    },
    {
      "id": "click_login",
      "type": "click",
      "selector": "#login-btn"
    },
    {
      "id": "wait",
      "type": "sleep",
      "duration": 3000
    }
  ],
  "success_conditions": [],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

> 注意：此任务的第一个步骤是 `input` 而非 `navigate`，执行器会自动先导航到 `url` 字段指定的地址。

---

## API 参考

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/{id}` | 获取指定任务 |
| PUT | `/api/tasks/{id}` | 创建/更新任务 |
| DELETE | `/api/tasks/{id}` | 删除任务（`default` 不可删除） |
| GET | `/api/tasks/active` | 获取当前活动任务 |
| POST | `/api/tasks/active/{id}` | 设置活动任务 |

### 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取当前配置 |
| PUT | `/api/config` | 保存配置 |
| GET | `/api/init-status` | 获取初始化状态 |

### 配置方案（Profiles）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/profiles` | 列出所有方案 |
| GET | `/api/profiles/active` | 获取活动方案详情 |
| GET | `/api/profiles/{id}` | 获取指定方案 |
| PUT | `/api/profiles/{id}` | 创建/更新方案（活动方案会热重载） |
| DELETE | `/api/profiles/{id}` | 删除方案（`default` 不可删除） |
| POST | `/api/profiles/active/{id}` | 设置活动方案 |
| POST | `/api/profiles/detect` | 检测当前网络环境 |
| POST | `/api/profiles/auto-switch` | 切换自动切换开关 |

### 监控控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 获取监控状态 |
| POST | `/api/monitor/start` | 启动监控 |
| POST | `/api/monitor/stop` | 停止监控 |

### 手动操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/actions/login` | 手动触发登录 |
| POST | `/api/actions/test-network` | 测试网络连通性 |

### 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs?limit=200` | 获取历史日志（内存缓冲区，最多 1200 条） |
| WS | `/ws/logs` | WebSocket 实时日志流 |

### 自启动

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/autostart/status` | 获取自启动状态 |
| POST | `/api/autostart/enable` | 启用自启动 |
| POST | `/api/autostart/disable` | 禁用自启动 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回状态和版本 |
| POST | `/api/shutdown` | 关闭服务 |

### API 鉴权

如果设置了 `API_TOKEN` 环境变量，所有写操作（POST/PUT/DELETE）需要在请求头中携带 `X-API-Token`。未设置 `API_TOKEN` 时不需要鉴权。

### 调试文件

`/debug/` 路径提供截图文件的静态访问，可用于查看失败截图。

---

## 环境变量参考

### 认证配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `USERNAME` | - | 校园网用户名 |
| `PASSWORD` | - | 校园网密码（支持 `ENC:` 前缀加密存储） |
| `LOGIN_URL` | `http://172.29.0.2` | 认证页面地址 |
| `ISP` | 空 | 运营商关键字 |

### 服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_PORT` | `50721` | Web 控制台端口 |
| `API_TOKEN` | 空 | API 写操作鉴权令牌 |
| `UVICORN_ACCESS_LOG` | `false` | 是否输出 HTTP 访问日志 |

### 监控配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_START_MONITORING` | `false` | 启动后是否自动开始监控 |
| `MONITOR_INTERVAL` | `300` | 检测间隔（秒） |
| `PING_TARGETS` | `8.8.8.8:53,114.114.114.114:53,www.baidu.com:443` | 探测目标 |
| `MAX_CONSECUTIVE_FAILURES` | `3` | 连续失败次数上限 |

### 暂停时段

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PAUSE_LOGIN_ENABLED` | `true` | 是否启用暂停时段 |
| `PAUSE_LOGIN_START_HOUR` | `0` | 暂停开始（0-23） |
| `PAUSE_LOGIN_END_HOUR` | `6` | 暂停结束（0-23） |

### 浏览器配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BROWSER_HEADLESS` | `true` | 无头模式 |
| `BROWSER_TIMEOUT` | `8000` | 浏览器超时（毫秒） |
| `BROWSER_LOW_RESOURCE_MODE` | `true` | 低资源模式 |
| `BROWSER_USER_AGENT` | 内置默认值 | 自定义 User-Agent |
| `BROWSER_EXTRA_HEADERS_JSON` | 空 | 额外请求头（JSON） |
| `BROWSER_DISABLE_WEB_SECURITY` | `false` | 禁用浏览器安全策略 |

### 系统配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMIZE_TO_TRAY` | `true` | 最小化到系统托盘 |
| `CUSTOM_VARIABLES` | `{}` | 自定义变量（JSON 格式） |
| `AUTO_INSTALL_PLAYWRIGHT` | `true` | 自动安装 Chromium |
| `PLAYWRIGHT_DOWNLOAD_HOST` | npmmirror 镜像 | Playwright 下载源 |

### 内部变量

以下变量由系统内部使用，通常无需手动设置：

| 变量 | 说明 |
|------|------|
| `Campus-Auth_PROJECT_ROOT` | 项目根目录路径 |
| `Campus-Auth_START_EXECUTABLE` | 打包可执行文件路径 |
| `Campus-Auth_AUTO_OPEN_BROWSER` | 是否自动打开浏览器 |
| `Campus-Auth_ENV_FILE` | .env 文件路径 |

---

## 步骤类型速查表

| 类型 | 用途 | 关键参数 | 特殊行为 |
|------|------|----------|----------|
| navigate | 打开页面 | `url`, `wait_until` | - |
| input | 输入文本 | `selector`, `value`, `clear` | - |
| click | 点击元素 | `selector` | - |
| select | 下拉选择 | `selector`, `value` | value 为空或元素不存在时跳过；支持模糊匹配 |
| wait | 等待元素 | `selector` | - |
| wait_url | 等待URL | `pattern` | - |
| eval | JS求值 | `script`, `store_as` | `code` 为已废弃别名 |
| custom_js | 执行JS | `script` | `code` 为已废弃别名 |
| screenshot | 截图 | `path` | - |
| sleep | 休眠 | `duration` | 最大 300000ms |

---

## 常见问题

**Q: 选择器怎么写？**

A: 支持 CSS 选择器，多个选择器用逗号分隔。常用形式：
- `input[name='username']` - 属性选择
- `#username` - ID选择
- `.login-input` - 类选择
- `button[type='submit']` - 组合选择

**Q: 变量不生效怎么办？**

A: 检查以下几点：
1. 变量名是否正确（区分大小写）
2. 模板语法是否正确（使用双大括号 `{{}}`）
3. 变量来源是否正确（环境变量或 task.variables）

**Q: 如何判断登录成功？**

A: 推荐组合使用：
1. `eval` 步骤检查页面内容，存储结果到变量
2. `success_conditions` 中检查该变量
3. 或使用 `url_contains` 检查跳转后的URL

**Q: 多个校园网怎么配置？**

A: 使用"配置方案"页面为每个网络创建独立的 Profile，设置匹配条件（网关 IP 或 WiFi SSID），并开启自动切换。

**Q: 保存任务时弹出安全警告？**

A: 这是因为任务中包含 `eval` 或 `custom_js` 步骤。这些步骤可以执行任意 JavaScript 代码，系统会显示代码内容要求确认。确认代码安全后点击确认即可。

**Q: 内置任务和普通任务有什么区别？**

A: 内置任务（`source: builtin`）是随项目分发的预设任务。通过 Web 控制台保存时会保留其内置来源，不会被覆盖为用户任务。你可以在内置任务的基础上复制、修改来创建自己的任务。
