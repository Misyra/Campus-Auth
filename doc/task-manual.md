# Campus-Auth 任务编写手册

本文档详细描述 Campus-Auth 任务系统的格式规范、参数配置及校验规则，帮助用户编写标准化的认证任务。

## 目录

1. [任务结构概述](#任务结构概述)
2. [任务格式规范](#任务格式规范)
3. [步骤类型详解](#步骤类型详解)
4. [变量系统](#变量系统)
5. [条件判断](#条件判断)
6. [校验规则](#校验规则)
7. [最佳实践](#最佳实践)
8. [示例任务](#示例任务)

---

## 任务结构概述

一个完整的任务由以下部分组成：

```
任务定义
├── 基本信息（name, description, version）
├── 变量定义（variables）
├── 步骤列表（steps）
├── 成功条件（success_conditions）
└── 结果处理（on_success, on_failure）
```

---

## 任务格式规范

### 完整结构

```json
{
  "name": "任务名称",
  "description": "任务描述",
  "version": "1.0.0",
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
  }
}
```

### 字段说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | 任务名称，显示在任务列表中 |
| `description` | string | 否 | "" | 任务描述 |
| `version` | string | 否 | "1.0.0" | 任务版本 |
| `url` | string | 否 | "" | 任务基础URL，可用于自动导航 |
| `timeout` | number | 否 | 30000 | 全局超时时间（毫秒） |
| `variables` | object | 否 | {} | 变量定义，支持模板语法 |
| `steps` | array | 是 | [] | 步骤列表，按顺序执行 |
| `success_conditions` | array | 否 | [] | 成功条件，全部满足才算成功 |
| `on_success` | object | 否 | {} | 成功时的处理 |
| `on_failure` | object | 否 | {} | 失败时的处理 |

---

## 步骤类型详解

### 1. navigate - 页面导航

打开指定URL的页面。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："navigate" |
| `description` | string | 否 | "" | 步骤描述 |
| `url` | string | 是 | - | 目标URL（支持变量） |
| `wait_until` | string | 否 | "networkidle" | 等待条件：load/domcontentloaded/networkidle |
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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："input" |
| `description` | string | 否 | "" | 步骤描述 |
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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："click" |
| `description` | string | 否 | "" | 步骤描述 |
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

选择下拉框选项。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："select" |
| `description` | string | 否 | "" | 步骤描述 |
| `selector` | string | 是 | - | 下拉框选择器 |
| `value` | string | 是 | - | 选项值（支持变量） |
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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："wait" |
| `description` | string | 否 | "" | 步骤描述 |
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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："wait_url" |
| `description` | string | 否 | "" | 步骤描述 |
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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："eval" |
| `description` | string | 否 | "" | 步骤描述 |
| `script` | string | 是 | - | JavaScript代码（支持变量） |
| `store_as` | string | 否 | - | 结果存储到的变量名 |

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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："custom_js" |
| `description` | string | 否 | "" | 步骤描述 |
| `script` | string | 是 | - | JavaScript代码 |

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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："screenshot" |
| `description` | string | 否 | "" | 步骤描述 |
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
| `id` | string | 是 | - | 步骤唯一标识 |
| `type` | string | 是 | - | 固定值："sleep" |
| `description` | string | 否 | "" | 步骤描述 |
| `duration` | number | 否 | 1000 | 休眠时间（毫秒） |

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
| `USERNAME` | 环境变量 | 校园网用户名 |
| `PASSWORD` | 环境变量 | 校园网密码 |
| `LOGIN_URL` | 环境变量 | 认证页面地址 |
| `ISP` | 环境变量 | 运营商后缀 |
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
| eval | `script` |
| custom_js | `script` |
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

### 语义识别任务

```json
{
  "name": "语义识别登录",
  "description": "自动识别页面元素的智能登录",
  "version": "2.0.0",
  "url": "{{LOGIN_URL}}",
  "steps": [
    {
      "id": "navigate",
      "type": "navigate",
      "description": "打开页面",
      "url": "{{url}}"
    },
    {
      "id": "smart_fill",
      "type": "custom_js",
      "description": "智能填写账号密码",
      "script": "(() => { /* 智能识别代码 */ })()"
    },
    {
      "id": "smart_click",
      "type": "custom_js",
      "description": "智能点击登录",
      "script": "(() => { /* 智能识别代码 */ })()"
    },
    {
      "id": "wait_redirect",
      "type": "sleep",
      "description": "等待跳转",
      "duration": 3000
    }
  ],
  "success_conditions": [
    {
      "type": "url_contains",
      "pattern": "success"
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

---

## 附录

### 步骤类型速查表

| 类型 | 用途 | 关键参数 |
|------|------|----------|
| navigate | 打开页面 | url |
| input | 输入文本 | selector, value |
| click | 点击元素 | selector |
| select | 下拉选择 | selector, value |
| wait | 等待元素 | selector |
| wait_url | 等待URL | pattern |
| eval | JS求值 | script, store_as |
| custom_js | 执行JS | script |
| screenshot | 截图 | path |
| sleep | 休眠 | duration |

### 常见问题

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
