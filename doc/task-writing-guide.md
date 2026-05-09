# Campus-Auth 任务编写指南

本指南帮助你（或 AI）为 Campus-Auth 编写标准化的浏览器认证任务。任务以 JSON 格式定义，由 Playwright 驱动浏览器自动执行。

## 任务 JSON 完整结构

```json
{
  "name": "校园网登录",
  "description": "适用于 XX 型号认证页面",
  "metadata": {},
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "variables": {
    "username": "{{USERNAME}}",
    "password": "{{PASSWORD}}",
    "isp": "{{ISP}}"
  },
  "steps": [],
  "success_conditions": [],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

### 顶层字段

| 字段 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | 是 | — | 任务名称，显示在任务列表中 |
| `description` | 否 | `""` | 任务描述 |
| `metadata` | 否 | `{}` | 自由结构的附加信息（作者、适配型号等），执行器不读取，建议放在靠前位置便于阅读 |
| `url` | 否 | `""` | 自定义认证地址，填写后覆盖 `{{LOGIN_URL}}`；留空则使用系统设置的认证地址 |
| `timeout` | 否 | `30000` | 全局超时时间（毫秒） |
| `variables` | 否 | `{}` | 任务级变量，支持 `{{VAR}}` 模板引用其他变量 |
| `steps` | 是 | `[]` | 步骤列表，按顺序执行 |
| `success_conditions` | 否 | `[]` | 成功条件列表，全部满足才算成功；**留空则所有步骤完成即为成功** |
| `on_success` | 否 | `{}` | 成功时的处理，如 `{ "message": "登录成功" }` |
| `on_failure` | 否 | `{}` | 失败时的处理，如 `{ "message": "登录失败", "screenshot": true }` |

---

## 步骤公共字段

所有步骤类型都支持以下字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 唯一标识，格式须匹配 `^[A-Za-z][A-Za-z0-9_]*$`，建议用 `s1`、`s2` |
| `type` | 是 | 步骤类型 |
| `description` | 否 | 步骤描述，会输出到日志 |
| `timeout` | 否 | 超时时间（毫秒），默认值因类型而异 |
| `frame` | 否 | 目标 frame 的 name 或 URL 片段，用于 frameset/iframe 页面 |

---

## 步骤类型详解

### input — 文本输入

在输入框中填写文本。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 元素选择器，多个用逗号分隔 |
| `value` | 是 | — | 输入值，支持 `{{变量}}` 模板 |
| `clear` | 否 | `true` | 是否先清空输入框 |
| `timeout` | 否 | `5000` | 超时时间（毫秒） |

```json
{
  "id": "s1",
  "type": "input",
  "description": "输入账号",
  "selector": "input[name='DDDDD'], #username",
  "value": "{{USERNAME}}",
  "clear": true
}
```

### click — 点击元素

点击页面元素。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 元素选择器，多个用逗号分隔 |
| `timeout` | 否 | `5000` | 超时时间（毫秒） |

```json
{
  "id": "s2",
  "type": "click",
  "description": "点击登录按钮",
  "selector": "input[name='0MKKey'], button[type='submit']"
}
```

### select — 下拉选择

选择下拉框选项。有特殊容错行为：
- `value` 为空 → 步骤自动跳过（视为成功）
- 找不到下拉框元素 → 步骤自动跳过（视为成功）
- 精确匹配 `value` 失败 → 回退到按选项文本**子字符串包含**匹配

这些设计是为了兼容不同校园网页面中运营商选择框的差异。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 下拉框选择器 |
| `value` | 是 | — | 选项值，支持变量和模糊匹配 |
| `timeout` | 否 | `5000` | 超时时间（毫秒） |

```json
{
  "id": "s3",
  "type": "select",
  "description": "选择运营商",
  "selector": "select[name='ISP_select'], select[name='isp']",
  "value": "{{ISP}}"
}
```

### wait — 等待元素

等待指定元素出现在页面上。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 等待的元素选择器 |
| `timeout` | 否 | `5000` | 超时时间（毫秒） |

```json
{
  "id": "s4",
  "type": "wait",
  "description": "等待结果弹出",
  "selector": ".success, .error, #msg",
  "timeout": 10000
}
```

### wait_url — 等待 URL 匹配

等待当前 URL 匹配指定正则表达式。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `pattern` | 是 | — | URL 正则表达式 |
| `timeout` | 否 | `5000` | 超时时间（毫秒） |

```json
{
  "id": "s5",
  "type": "wait_url",
  "description": "等待跳转到成功页",
  "pattern": "success|welcome",
  "timeout": 10000
}
```

### eval — JavaScript 求值

执行 JavaScript 表达式并可选保存结果到变量。`code` 字段是 `script` 的已废弃别名。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `script` | 是 | — | JavaScript 代码（支持变量模板） |
| `store_as` | 否 | — | 结果存储到的变量名，后续步骤可用 `{{变量名}}` 引用 |

```json
{
  "id": "s6",
  "type": "eval",
  "description": "检查登录状态",
  "script": "() => { const text = document.body.innerText; return text.includes('成功') || text.includes('已连接'); }",
  "store_as": "login_success"
}
```

> **安全提示：** 包含 `eval` 或 `custom_js` 步骤的任务在 Web 控制台保存时会弹出安全确认对话框。

### custom_js — 执行 JavaScript

执行自定义 JavaScript 代码（不返回值）。`code` 字段是 `script` 的已废弃别名。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `script` | 是 | — | JavaScript 代码 |

```json
{
  "id": "s7",
  "type": "custom_js",
  "description": "勾选同意协议",
  "script": "document.querySelector('#agree').click();"
}
```

### screenshot — 截图

截取当前页面截图。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | 否 | 自动生成 | 截图保存路径 |

```json
{ "id": "s8", "type": "screenshot", "description": "截图保存" }
```

### sleep — 休眠等待

暂停指定时间。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `duration` | 否 | `1000` | 休眠时间（毫秒），最大 300000 |

```json
{ "id": "s9", "type": "sleep", "description": "等待加载", "duration": 2000 }
```

### ocr — 验证码识别

使用 ddddocr 识别验证码图片。截取 `selector` 指定的图片元素，进行 OCR 识别，结果自动填入 `target_selector` 输入框或存储到 `store_as` 变量。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 验证码图片元素选择器 |
| `target_selector` | 否 | — | 验证码输入框选择器，识别后自动填入 |
| `store_as` | 否 | — | 识别结果存储到的变量名 |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |
| `frame` | 否 | — | 验证码所在的 frame |
| `old` | 否 | `false` | 纯数字验证码设为 true；`false` 对数字+字母混合效果更好 |

**三种使用模式：**

```json
// 模式一：自动填入（推荐）
{ "id": "s1", "type": "ocr", "selector": "#captcha-img", "target_selector": "#captcha-input" }

// 模式二：存储到变量，后续步骤再填入
{ "id": "s1", "type": "ocr", "selector": "#captcha-img", "store_as": "captcha_code" }

// 模式三：同时自动填入并存储
{ "id": "s1", "type": "ocr", "selector": "#captcha-img", "target_selector": "#captcha-input", "store_as": "captcha_code" }
```

---

## 变量系统

### 预定义变量

| 变量 | 来源 | 说明 |
|------|------|------|
| `{{USERNAME}}` | 系统 | 校园网用户名 |
| `{{PASSWORD}}` | 系统 | 校园网密码 |
| `{{LOGIN_URL}}` | 系统 | 认证页面地址 |
| `{{ISP}}` | 系统 | 运营商后缀 |
| `{{url}}` | 任务 | 任务定义的 url 字段 |
| `{{name}}` | 任务 | 任务名称 |
| `{{description}}` | 任务 | 任务描述 |

### 自定义变量

- **用户自定义变量：** 通过 Web 控制台「账号设置」页面添加，可在所有任务中使用，优先级高于环境变量
- **任务级变量：** 在任务 JSON 的 `variables` 字段中定义，支持模板语法引用其他变量
- **运行时变量：** 通过 `eval` 步骤的 `store_as` 写入，仅在当前执行过程中有效

### 模板语法

使用 `{{变量名}}` 引用变量，可用于 `value`、`url`、`selector` 等任何字段：

```json
{
  "variables": {
    "username": "{{USERNAME}}",
    "full_user": "{{USERNAME}}{{ISP}}"
  }
}
```

### 变量解析优先级

1. 运行时变量（`eval` 的 `store_as`）
2. 用户自定义变量（Web 控制台设置）
3. 环境变量（系统环境与 `.env`）
4. 任务文件内 `variables` 字段

---

## 成功条件

`success_conditions` 为空数组时，所有步骤执行完毕且没有失败即视为成功。如需更精确的判定，可组合使用以下条件类型：

| 类型 | 说明 | 示例 |
|------|------|------|
| `variable` | 变量值等于指定值 | `{ "type": "variable", "variable": "login_ok", "value": true }` |
| `url_contains` | 当前 URL 包含字符串 | `{ "type": "url_contains", "pattern": "success" }` |
| `url_matches` | 当前 URL 匹配正则 | `{ "type": "url_matches", "pattern": "success\|welcome\|home" }` |
| `element_exists` | 页面存在指定元素 | `{ "type": "element_exists", "selector": ".welcome-message" }` |
| `js_expression` | JS 表达式返回 truthy | `{ "type": "js_expression", "script": "document.body.innerText.includes('成功')" }` |

多个条件全部满足才算成功。典型组合：先用 `eval` 步骤检查页面并存储结果到变量，再用 `variable` 条件判断该变量。

---

## Frame 支持

部分校园网认证页面使用 `<frameset>` 或 `<iframe>` 嵌套结构，登录表单在子 frame 中。通过步骤的 `frame` 字段指定目标 frame，执行器会自动切换上下文后再查找元素。

`frame` 值可以是：
- frame 的 `name` 属性（如 `"main"`）
- URL 匹配字符串（如 `"url=user/unionautologin.do"`）

所有操作类步骤（`input`、`click`、`select`、`wait`、`ocr`）都支持 `frame` 字段。

```json
{
  "id": "s1",
  "type": "input",
  "description": "在 iframe 中输入账号",
  "selector": "#username",
  "value": "{{USERNAME}}",
  "frame": "mainFrame"
}
```

---

## 选择器建议

- **优先使用稳定的属性**：`id`、`name` 等，避免使用易变的 `class`
- **提供多个备选选择器**，逗号分隔提高兼容性：`"input[name='user'], #username, .login-user"`
- 支持标准 CSS 选择器语法

---

## 自动导航

系统会在执行步骤前**自动导航**到认证地址，无需在任务中添加 navigate 步骤。导航地址优先级：

1. 任务 `url` 字段（支持变量模板）
2. 系统设置的认证地址（`LOGIN_URL`）

如果任务定义了 `url` 字段，执行时会用该值覆盖 `{{LOGIN_URL}}` 变量。

---

## 完整示例

```json
{
  "name": "校园网登录",
  "description": "适用于标准 Portal 认证页面",
  "metadata": {
    "author": "your-name",
    "device": "校园网设备型号",
    "created": "2025-01-01"
  },
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "variables": {
    "username": "{{USERNAME}}",
    "password": "{{PASSWORD}}",
    "isp": "{{ISP}}"
  },
  "steps": [
    {
      "id": "s1",
      "type": "input",
      "description": "输入账号",
      "selector": "input[name='DDDDD'], input[name='username'], #username",
      "value": "{{username}}",
      "clear": true
    },
    {
      "id": "s2",
      "type": "input",
      "description": "输入密码",
      "selector": "input[name='upass'], input[type='password'], #password",
      "value": "{{password}}",
      "clear": true
    },
    {
      "id": "s3",
      "type": "select",
      "description": "选择运营商",
      "selector": "select[name='ISP_select'], select[name='isp']",
      "value": "{{isp}}"
    },
    {
      "id": "s4",
      "type": "click",
      "description": "点击登录",
      "selector": "input[name='0MKKey'], button[type='submit'], #login-btn"
    },
    {
      "id": "s5",
      "type": "wait",
      "description": "等待结果",
      "selector": ".success, .error, #msg",
      "timeout": 10000
    },
    {
      "id": "s6",
      "type": "eval",
      "description": "检查登录结果",
      "script": "() => { const text = document.body.innerText; return text.includes('成功') || text.includes('已连接'); }",
      "store_as": "login_success"
    }
  ],
  "success_conditions": [
    { "type": "variable", "variable": "login_success", "value": true }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

---

## 步骤类型速查

| 类型 | 用途 | 关键参数 | 特殊行为 |
|------|------|----------|----------|
| `input` | 输入文本 | `selector`, `value`, `clear` | — |
| `click` | 点击元素 | `selector` | — |
| `select` | 下拉选择 | `selector`, `value` | value 为空或元素不存在时自动跳过；支持模糊匹配 |
| `wait` | 等待元素 | `selector` | — |
| `wait_url` | 等待 URL | `pattern` | — |
| `eval` | JS 求值 | `script`, `store_as` | 结果可存入变量；`code` 为已废弃别名 |
| `custom_js` | 执行 JS | `script` | 不返回值；`code` 为已废弃别名 |
| `screenshot` | 截图 | `path` | — |
| `sleep` | 休眠 | `duration` | 最大 300000ms |
| `ocr` | 验证码识别 | `selector`, `target_selector`, `store_as`, `old` | 支持新旧模型切换 |

> 所有操作类步骤都支持 `frame` 公共字段，用于在 frameset/iframe 页面中定位子 frame 内的元素。

---

## 分享你创建的任务

如果你编写了一个适用于特定校园网的认证任务，欢迎将它分享给社区！

1. **导出任务 JSON** — 在 Web 控制台的任务页面点击导出按钮，下载 `.json` 文件
2. **提交到 GitHub** — 在 [Campus-Auth Issues](https://github.com/Misyra/Campus-Auth/issues) 提交 Issue 或 Pull Request，附上你的任务 JSON 和适用的校园网信息
3. **标注信息** — 在任务的 `metadata` 字段中记录适用的校园网设备型号、页面特征等，方便其他人参考

你分享的任务可以帮助同一校园网的其他用户直接使用，省去他们从零编写的过程。
