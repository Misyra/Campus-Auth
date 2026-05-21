# Campus-Auth 任务编写指南

本指南帮助你（或 AI）为 Campus-Auth 编写标准化的浏览器认证任务。任务以 JSON 格式定义，由 Playwright 驱动浏览器自动执行。

## 目录

1. [任务 JSON 完整结构](#任务-json-完整结构)
2. [步骤公共字段](#步骤公共字段)
3. [步骤类型详解](#步骤类型详解)
4. [变量系统](#变量系统)
5. [成功条件](#成功条件)
6. [Frame 支持](#frame-支持)
7. [选择器建议](#选择器建议)
8. [自动导航](#自动导航)
9. [完整示例](#完整示例)
10. [最佳实践](#最佳实践)
11. [常见问题](#常见问题)
12. [步骤类型速查表](#步骤类型速查表)
13. [分享你创建的任务](#分享你创建的任务)

---

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
| `url` | 否 | `""` | 自定义认证地址。**提交/分享任务时请留空**，由用户自行在系统中设置认证地址或手动填入 |
| `timeout` | 否 | `30000` | 全局超时时间（毫秒） |
| `variables` | 否 | `{}` | 任务级变量，支持 `{{VAR}}` 模板引用其他变量 |
| `steps` | 是 | `[]` | 步骤列表，按顺序执行 |
| `reveal_hidden` | 否 | `true` | 执行前自动显示所有隐藏输入框，适用于深澜/Sangfor 等隐藏输入框场景 |
| `success_conditions` | 否（已废弃） | — | 原有成功条件字段，系统不再使用 |
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
| `frame` | 否 | 目标 frame 的 name、URL 片段或 CSS 选择器（字符串，不支持布尔值），用于 frameset/iframe 页面 |

**扩展字段（extra）：** 步骤中任何未被识别的字段会被自动收集并在序列化时保留，你可以在步骤中添加自定义字段而不影响执行逻辑。

---

## 步骤类型详解

### input — 文本输入

在输入框中填写文本。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 元素选择器，多个用逗号分隔 |
| `value` | 是 | — | 输入值，支持 `{{变量}}` 模板 |
| `clear` | 否 | `true` | 是否先清空输入框 |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |

**隐藏输入框处理：** 部分校园网认证页面的输入框是隐藏的（`display:none`），有两种常见模式：

- **深澜/Sangfor 系**：可见的 `type="text"` 假占位框 + 隐藏的 `type="password"` 真实密码框
- **杭州康工 HK Posi 系**：可见的 `readonly` tip 占位框 + 隐藏的真实输入框（账号和密码都隐藏）

**推荐方案：** 在任务 JSON 顶层添加 `"reveal_hidden": true`，执行器会在填写前自动显示所有隐藏输入框，后续 `input` 步骤无需任何特殊配置即可正常填入。

**自动降级：** 即使不设置 `reveal_hidden`，执行器在普通 `fill()` 失败后也会自动降级到强制输入模式（通过 JS 原生 setter 设置值并触发事件，模拟完整用户交互：focus → clear → set value → input → change → blur），无需额外配置。如果是 HK Posi 模式，建议在输入步骤前加一个 `click` 步骤先点击 tip 占位框以触发门户 JS 的状态切换。

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

```json
{
  "id": "s2",
  "type": "input",
  "description": "输入密码",
  "selector": "#password",
  "value": "{{PASSWORD}}"
}
```

### click — 点击元素

点击页面元素。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 元素选择器，多个用逗号分隔 |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |

**自动降级：** 如果普通 click 失败（元素不可见或不可交互），执行器会自动降级到强制模式，通过 JavaScript `dispatch_event('click')` 执行点击。此过程无需手动配置。

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
| `timeout` | 否 | `10000` | 超时时间（毫秒） |

```json
{
  "id": "s3",
  "type": "select",
  "description": "选择运营商",
  "selector": "select[name='ISP_select'], select[name='isp']",
  "value": "{{ISP}}"
}
```

### click_select — 点击式选择（自定义 div 下拉框）

用于自定义 div/span 实现的非原生下拉框选择（常见于运营商选择）。先点击触发器展开列表，再按文字匹配点击选项。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 触发器的 CSS 选择器（点击它展开下拉列表） |
| `value` | 是 | — | 要选择的选项文本，支持 `{{ISP}}` 变量和子串模糊匹配 |
| `option_selector` | 否 | — | 选项容器的 CSS 选择器（如 `.service-option`），限定文本搜索范围，避免误匹配 |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |

**容错行为：**
- `value` 为空 → 步骤自动跳过
- 找不到触发器 → 步骤自动跳过
- 找不到匹配的选项文本 → 步骤自动跳过

```json
{
  "id": "s3",
  "type": "click_select",
  "description": "选择运营商",
  "selector": "#serviceSelector, .service-selector",
  "value": "{{ISP}}",
  "option_selector": ".service-option"
}
```

### wait — 等待元素

等待指定元素出现在页面上。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 等待的元素选择器 |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |

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
| `timeout` | 否 | `10000` | 超时时间（毫秒） |

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

执行 JavaScript 表达式并可选保存结果到变量。`code` 字段是 `script` 的已废弃别名，仍然支持但建议使用 `script`。`custom_js` 步骤类型已合并到 `eval`，旧任务中的 `custom_js` 仍会被自动映射到 `eval` 执行。

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

> **安全提示：** 包含 `eval` 步骤的任务在 Web 控制台保存时会弹出安全确认对话框，显示待执行的代码内容，需要用户明确确认。

### screenshot — 截图

截取当前页面截图。截图保存到 `debug/` 目录下按日期分类的子目录中。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | 否 | 自动生成 | 截图保存路径（仅文件名生效，目录由系统管理） |

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
| `frame` | 否 | — | 验证码所在的 frame（字符串，不支持布尔值），可选值为 frame name、URL 片段或 CSS 选择器 |
| `old` | 否 | `false` | 使用旧版 OCR 模型（见下方说明） |

**关于新旧模型：**

ddddocr 内置两套模型，`old` 参数控制使用哪一套：

| `old` | 模型 | 说明 |
|-------|------|------|
| `false`（默认） | 新版模型 | 通用场景 |
| `true` | 旧版模型 | 旧版模型，部分校园网系统上识别率可能更高 |

如果你的校园网验证码识别不准，可以尝试切换 `old` 参数值（true/false）。

**三种使用模式：**

```json
// 模式一：自动填入（推荐）
{ "id": "s1", "type": "ocr", "selector": "#captcha-img", "target_selector": "#captcha-input" }

// 模式二：存储到变量，后续步骤再填入
{ "id": "s1", "type": "ocr", "selector": "#captcha-img", "store_as": "captcha_code" }

// 模式三：同时自动填入并存储
{ "id": "s1", "type": "ocr", "selector": "#captcha-img", "target_selector": "#captcha-input", "store_as": "captcha_code" }
```

**超时与错误处理：**
- 找不到验证码图片元素或输入框时，步骤失败并返回错误信息
- 建议 `timeout` 设置 >= 5000ms，给页面加载留足时间

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

- **用户自定义变量：** 通过 Web 控制台「设置 → 账号设置 → 自定义变量」添加，可在所有任务中使用，优先级高于环境变量
- **任务级变量：** 在任务 JSON 的 `variables` 字段中定义，支持模板语法引用其他变量
- **运行时变量：** 通过 `eval` 步骤的 `store_as` 写入，仅在当前执行过程中有效

### 模板语法

使用 `{{变量名}}` 引用变量，可用于 `value`、`url`、`selector` 等任何字段。支持递归引用（最大 8 层深度），系统会自动检测循环引用并报错。

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
2. 环境变量 + 自定义变量（系统环境 + config 覆盖；自定义变量由 `build_login_env_vars()` 合并进 `env_vars` 字典，不单独成级）
3. 任务文件内 `variables` 字段

未找到的变量会原样保留在输出中（不会报错）。

---

## 成功判断

系统统一使用网络连通性检测判断任务成功与否：任务步骤全部完成后，自动检测网络是否可达。网络通 = 认证成功，网络断 = 认证失败。

> **注意：** 原有 `success_conditions` 字段已被废弃，不再参与成功判断。任务文件中无需再添加该字段。

---

## Frame 支持

部分校园网认证页面使用 `<frameset>` 或 `<iframe>` 嵌套结构，登录表单在子 frame 中。通过步骤的 `frame` 字段指定目标 frame，执行器会自动切换上下文后再查找元素。

`frame` 值必须是字符串，可以是以下三种之一（按优先级依次尝试）：
- **frame 的 name 属性**，如 `"main"`、`"loginFrame"`
- **URL 匹配字符串**，如 `"url=user/unionautologin.do"`（匹配 frame.src 包含该片段）
- **CSS 选择器**，如 `"iframe[name='login']"`、`"#frameId"`、`"frame:nth-of-type(2)"`

> ⚠️ `frame` 不接收布尔值（`true`/`false`）。如果填写 `"frame": true`，系统会忽略该字段并回退到主页面执行。

所有操作类步骤（`input`、`click`、`select`、`wait`、`ocr`）都支持 `frame` 字段。如果指定的 frame 找不到，系统会回退到主页面继续执行（不会直接失败）。

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
- 验证码图片通常用 `img[src*='captcha']`、`#captcha-img`、`.code-img`

---

## 自动导航

系统会在执行步骤前**自动导航**到认证地址，无需在任务中添加 navigate 步骤（旧任务中的 navigate 步骤会被自动跳过）。导航地址优先级：

1. 任务 `url` 字段（支持变量模板）
2. 系统设置的认证地址（`LOGIN_URL`）

如果任务定义了 `url` 字段，执行时会用该值覆盖 `{{LOGIN_URL}}` 变量。

---

## 完整示例

### 标准登录任务

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
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

### 精简登录任务

利用自动导航的简化任务：

```json
{
  "name": "精简登录",
  "description": "适用于简单认证页面",
  "url": "{{LOGIN_URL}}",
  "timeout": 15000,
  "steps": [
    { "id": "s1", "type": "input", "selector": "#username", "value": "{{USERNAME}}" },
    { "id": "s2", "type": "input", "selector": "#password", "value": "{{PASSWORD}}" },
    { "id": "s3", "type": "click", "selector": "#login-btn" },
    { "id": "s4", "type": "sleep", "duration": 3000 }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

### 带验证码的登录任务

```json
{
  "name": "验证码登录",
  "description": "需要输入验证码的校园网登录",
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "steps": [
    { "id": "s1", "type": "input", "selector": "#username", "value": "{{USERNAME}}" },
    { "id": "s2", "type": "input", "selector": "#password", "value": "{{PASSWORD}}" },
    {
      "id": "s3",
      "type": "ocr",
      "description": "识别验证码并填入",
      "selector": "#captcha-img",
      "target_selector": "#captcha-input"
    },
    { "id": "s4", "type": "click", "selector": "#login-btn" },
    { "id": "s5", "type": "sleep", "duration": 3000 }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

### 带 Frame 的登录任务

```json
{
  "name": "iframe 登录",
  "description": "登录表单在 iframe 中的认证页面",
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "steps": [
    {
      "id": "s1",
      "type": "input",
      "description": "在 iframe 中输入账号",
      "selector": "#username",
      "value": "{{USERNAME}}",
      "frame": "mainFrame"
    },
    {
      "id": "s2",
      "type": "input",
      "description": "在 iframe 中输入密码",
      "selector": "#password",
      "value": "{{PASSWORD}}",
      "frame": "mainFrame"
    },
    {
      "id": "s3",
      "type": "click",
      "description": "在 iframe 中点击登录",
      "selector": "#login-btn",
      "frame": "mainFrame"
    },
    { "id": "s4", "type": "sleep", "duration": 3000 }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

### 带隐藏输入框的登录任务（深澜 / HK Posi 模式）

部分校园网认证页面（深澜/Sangfor、杭州康工 HK Posi）的真实输入框是 `display:none` 的，页面上只有装饰性的 tip/占位元素。

**推荐做法：** 在任务 JSON 顶层添加 `"reveal_hidden": true`，执行器会自动处理所有隐藏输入框，无需在步骤中手动配置 `force` 或添加额外的 `click` 占位步骤。

```json
{
  "name": "隐藏输入框登录",
  "description": "适用于深澜/Sangfor 或 HK Posi 隐藏输入框的认证页面",
  "url": "{{LOGIN_URL}}",
  "reveal_hidden": true,
  "timeout": 30000,
  "steps": [
    {
      "id": "s1",
      "type": "input",
      "description": "输入账号",
      "selector": "#username",
      "value": "{{USERNAME}}"
    },
    {
      "id": "s2",
      "type": "input",
      "description": "输入密码",
      "selector": "#password",
      "value": "{{PASSWORD}}"
    },
    {
      "id": "s3",
      "type": "click",
      "description": "点击登录按钮",
      "selector": "#login_button"
    },
    { "id": "s4", "type": "sleep", "duration": 3000 }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

> **提示：** Campus-Auth 任务录制器（油猴脚本）的「隐藏检测」开关可以自动识别这种模式，导出时会自动在任务顶层添加 `"reveal_hidden": true`，无需手动干预。

---

## 最佳实践

### 选择器编写

- 使用多个备选选择器提高兼容性：
  ```json
  "selector": "input[name='username'], #username, .login-user"
  ```
- 优先使用稳定的属性（`id`、`name`），避免使用易变的 `class`

### 错误处理

- 设置合理的超时时间，网络慢时适当调大
- 启用失败截图（`on_failure.screenshot: true`）便于调试
- 提供清晰的步骤描述，方便排查问题

### 变量使用

- 将重复的值定义为变量，避免硬编码
- 使用有意义的变量名
- 避免变量循环引用（系统会检测并报错）

### 任务分享

- **不要填写 `url` 字段**：分享或提交任务 JSON 时，将 `url` 留空或设为 `"{{LOGIN_URL}}"`，由用户自行在系统中设置认证地址。认证地址因学校/区域而异，硬编码会导致任务无法通用

### 步骤组织

- 为每个步骤设置 `description`
- 使用有意义的步骤 ID（如 `input_username`、`click_login`）
- 合理拆分复杂操作，每步只做一件事

### 成功判定

- 系统统一使用网络检测兜底判断成功，无需配置成功条件
- 任务 JSON 中无需添加 `success_conditions` 字段

---

## 常见问题

**Q: 选择器怎么写？**

A: 支持 CSS 选择器，多个选择器用逗号分隔。常用形式：
- `input[name='username']` — 属性选择
- `#username` — ID 选择
- `.login-input` — 类选择
- `button[type='submit']` — 组合选择

**Q: 变量不生效怎么办？**

A: 检查以下几点：
1. 变量名是否正确（区分大小写）
2. 模板语法是否正确（使用双大括号 `{{}}`）
3. 变量来源是否正确（环境变量或 task.variables）

**Q: 如何判断登录成功？**

A: 系统自动在网络检测成功后判定为登录成功，无需额外配置。网络检测失败通常表示密码错误或运营商不匹配。

**Q: 保存任务时弹出安全警告？**

A: 因为任务中包含 `eval` 步骤，该步骤可以执行任意 JavaScript 代码。系统会显示代码内容要求确认，确认代码安全后点击确认即可。

**Q: 内置任务和普通任务有什么区别？**

A: 内置任务是随项目分发的预设任务。你可以在内置任务的基础上复制、修改来创建自己的任务。

**Q: 输入框是隐藏的（display:none）怎么办？**

A: 部分校园网认证页面（深澜/Sangfor、杭州康工 HK Posi）的真实输入框是隐藏的，页面上只显示占位 tip 或假输入框。解决方案：

1. 在任务 JSON 顶层添加 `"reveal_hidden": true`，执行器会自动显示所有隐藏输入框，后续步骤无需特殊配置
2. 即使不设置 `reveal_hidden`，执行器也会在普通输入失败时自动降级到强制模式，通常无需手动设置 `force`
3. 使用 Campus-Auth 任务录制器（油猴脚本）的「隐藏检测」功能，打开 🔍 开关后点击占位区域即可自动识别

详见上方「带隐藏输入框的登录任务」完整示例。

**Q: 验证码识别不准怎么办？**

A: 尝试切换 `ocr` 步骤的 `old` 参数（`true`/`false`），两套模型对不同风格的验证码效果不同。

---

## 步骤类型速查表

| 类型 | 用途 | 关键参数 | 特殊行为 |
|------|------|----------|----------|
| `input` | 输入文本 | `selector`, `value`, `clear` | 支持 `reveal_hidden` 全局配置，自动处理隐藏输入框 |
| `click` | 点击元素 | `selector` | — |
| `select` | 下拉选择 | `selector`, `value` | value 为空或元素不存在时自动跳过；支持模糊匹配 |
| `click_select` | 点击式选择 | `selector`, `value`, `option_selector`(可选) | 点击触发器后按文字匹配选项；`option_selector` 限定搜索容器 |
| `wait` | 等待元素 | `selector` | — |
| `wait_url` | 等待 URL | `pattern` | — |
| `eval` | JS 求值 | `script`, `store_as` | 结果可存入变量；`code` 为已废弃别名；`custom_js` 已合并到此类型 |
| `screenshot` | 截图 | `path` | — |
| `sleep` | 休眠 | `duration` | 最大 300000ms |
| `ocr` | 验证码识别 | `selector`, `target_selector`, `store_as`, `old` | 支持新旧模型切换 |

> 所有操作类步骤都支持 `frame` 公共字段，用于在 frameset/iframe 页面中定位子 frame 内的元素。

---

## 分享你创建的任务

如果你编写了一个适用于特定校园网的认证任务，欢迎将它分享给社区！分享的任务会收录在 [Campus-Auth 任务仓库](https://github.com/Misyra/campus-auth-tasks)，其他用户可以直接从仓库导入使用。

**分享方式：**

- **快速分享**：在 Web 控制台导出任务 JSON，到 [Issues](https://github.com/Misyra/campus-auth-tasks/issues/new) 提交
- **提交 PR**：Fork 仓库 → 添加任务文件 → 提交 Pull Request，详见 [任务仓库贡献指南](https://github.com/Misyra/campus-auth-tasks#贡献)
