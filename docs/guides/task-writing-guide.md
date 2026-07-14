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
| `reveal_hidden` | 否 | `false` | 执行前强制显示所有隐藏输入框。通常无需开启——每个步骤在普通操作失败后会自动降级到强制模式处理隐藏元素 |
| `step_delay` | 否 | `0.5` | 步骤间休眠时间（秒），上一步完成后 → 休眠 → 执行下一步。第一步前不休眠。值越小任务执行越快，但网络延迟较大时可适当增大 |
| `navigation_wait` | 否 | `1` | 页面加载后额外等待时间（秒）。适用于页面加载后通过 AJAX 动态渲染表单的场景——等待时间不足会导致后续步骤找不到元素 |
| `success_condition` | 否 | `""` | 成功条件变量名。声明后，系统在步骤跑完后从运行时变量中读取该值做真值判定。留空走默认路径（登录任务走网络检测，普通任务步骤完成即成功）。详见 [成功判断](#成功判断) |
| `on_success` | 否 | `{}` | 成功时的处理，如 `{ "message": "登录成功" }` |
| `on_failure` | 否 | `{}` | 失败时的处理，如 `{ "message": "登录失败", "screenshot": true }`。`screenshot` 默认值为 `true`（不设也会截图） |

> **步骤间延时：** 默认情况下，执行器在每一步执行完后会休眠 0.5 秒，为页面渲染留出缓冲。你可以在任务 JSON 顶层设置 `step_delay` 字段来调整这个间隔。

> **页面加载等待：** 如果认证页面在 HTML 加载完成后通过 AJAX 动态渲染表单（如 ePortal 的 `fillData()` / `getServices()`），自动导航完成后立即执行步骤可能找不到元素。`navigation_wait`（默认 1 秒）控制页面加载后的额外等待时间。如果 1 秒不够，可适当增大到 3-5 秒。

---

## 步骤公共字段

所有步骤类型都支持以下字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 唯一标识，仅支持字母、数字、下划线和连字符，长度不超过 64，建议用描述性名称如 `fill_username`、`click_login` |
| `type` | 是 | 步骤类型 |
| `description` | 否 | 步骤描述，会输出到日志 |
| `timeout` | 否 | 超时时间（毫秒），默认值因类型而异 |
| `frame` | 否 | 目标 frame 的 name、URL 片段或 CSS 选择器（字符串，不支持布尔值），用于 frameset/iframe 页面 |
| `required` | 否 | 设为 `true` 时，元素/选项未找到则步骤失败（适用于 `select`、`click_select` 等自带容错的步骤），默认 `false` |

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

- **假占位框模式**：可见的 `type="text"` 假占位框 + 隐藏的 `type="password"` 真实密码框
- **readonly 占位框模式**：可见的 `readonly` tip 占位框 + 隐藏的真实输入框（账号和密码都隐藏）

**自动降级（推荐）：** 执行器在普通输入失败后会自动降级到强制输入模式，无需额外配置。如果是 readonly 占位框模式，建议在输入步骤前加一个 `click` 步骤先点击 tip 占位框以触发门户的状态切换。

**强制显示所有隐藏输入框：** 如果自动降级仍无法解决问题，可以在任务 JSON 顶层添加 `"reveal_hidden": true`，执行器会在步骤执行前强制将页面上所有隐藏的 input 显示出来。注意：这会同时显示验证码等本该隐藏的元素，可能导致部分校园网页面异常。

**AJAX 动态渲染：** 如果页面在 HTML 加载后通过 AJAX 动态渲染表单，`reveal_hidden` 可能无效——因为执行器跑完 reveal 时 AJAX 回调还没返回，回调回来后又可能覆盖 reveal 的效果。此时应同时设置 `"navigation_wait": 3`（秒），等待 AJAX 完成后再执行步骤。

```json
{
  "id": "fill_username",
  "type": "input",
  "description": "输入账号",
  "selector": "input[name='DDDDD'], #username",
  "value": "{{USERNAME}}",
  "clear": true
}
```

```json
{
  "id": "fill_password",
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
  "id": "click_login",
  "type": "click",
  "description": "点击登录按钮",
  "selector": "input[name='0MKKey'], button[type='submit']"
}
```

### select — 下拉选择

选择下拉框选项。有特殊容错行为：

- `value` 为空 → 步骤自动跳过（视为成功）
- 找不到下拉框元素 → 步骤自动跳过（视为成功）
- 精确匹配 `value` 失败 → 回退到按选项文本**子字符串包含**匹配（仅唯一匹配时采用，多个匹配时跳过以防误选）

这些设计是为了兼容不同校园网页面中运营商选择框的差异。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 下拉框选择器 |
| `value` | 是 | — | 选项值，支持变量和模糊匹配 |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |

```json
{
  "id": "select_carrier",
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

**选项搜索回退链：** 执行器点击触发器后会按以下顺序查找选项文本——`option_selector` 指定容器 → 触发器父容器 → 全局搜索。前一级未命中才尝试下一级，全局搜索仍未命中则步骤失败（`required: true` 时）或跳过。

**容错行为：**
- `value` 为空 → 步骤自动跳过
- 找不到触发器 → 步骤自动跳过
- 找不到匹配的选项文本 → 步骤自动跳过

**高级参数（通过 extra 传递）：**
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `select_delay` | `500` | 点击触发器后等待选项面板展开的延迟时间（毫秒） |

```json
{
  "id": "select_carrier",
  "type": "click_select",
  "description": "选择运营商",
  "selector": "#serviceSelector, .service-selector",
  "value": "{{ISP}}",
  "option_selector": ".service-option"
}
```

**带 `select_delay` 的完整示例**（选项面板展开较慢时调大延迟）：

```json
{
  "id": "select_carrier",
  "type": "click_select",
  "description": "选择运营商（慢展开）",
  "selector": "#serviceSelector",
  "value": "{{ISP}}",
  "option_selector": ".service-option",
  "select_delay": 1000
}
```

**按钮组模式：** 部分校园网的运营商选择是平铺的按钮组（多个 `<button>` 或 `<a>` 标签，无需点击展开），同样使用 `click_select`。此时 `selector` 指向按钮组容器或任一按钮，`value` 用 `{{ISP}}` 按文本模糊匹配对应按钮并点击。由于按钮已可见，`select_delay` 影响不大，但执行器仍会先点击 `selector` 再搜索选项。

```json
{
  "id": "select_carrier",
  "type": "click_select",
  "description": "选择运营商（按钮组）",
  "selector": ".isp-buttons",
  "value": "{{ISP}}",
  "option_selector": ".isp-buttons"
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
  "id": "wait_result",
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
  "id": "wait_redirect",
  "type": "wait_url",
  "description": "等待跳转到成功页",
  "pattern": "success|welcome",
  "timeout": 10000
}
```

### goto — 页面导航

导航到指定 URL。与任务顶层的 `url` 字段自动导航互补：顶层 `url` 在步骤执行前自动导航一次，`goto` 步骤用于在执行过程中切换页面（如登录后跳到打卡页、分步表单跨页操作）。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `url` | 是 | — | 目标 URL，支持 `{{变量}}` 模板 |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |
| `wait_until` | 否 | `"load"` | 等待页面加载到何种状态即视为完成。可选值：`load`/`domcontentloaded`/`networkidle`/`commit` |

**关于 `wait_until`**：
- `load`（默认）：等待 `window.load` 事件，页面所有资源（图片、CSS、iframe）加载完成
- `domcontentloaded`：DOM 解析完成即返回，不等图片/CSS，速度最快
- `networkidle`：等待 500ms 内没有网络请求，适合 SPA 单页应用
- `commit`：导航请求得到响应即返回，不等页面渲染

`wait_until` 通过 `extra` 字段传递（非顶层字段）。无效值会回退到 `load` 并记录警告日志。

```json
{
  "id": "goto_punch",
  "type": "goto",
  "description": "跳转到打卡页面",
  "url": "https://example.com/punch",
  "wait_until": "networkidle"
}
```

```json
{
  "id": "goto_auth",
  "type": "goto",
  "url": "{{LOGIN_URL}}",
  "timeout": 20000
}
```

> **与自动导航的关系**：任务顶层声明 `url` 时，runner 会在步骤执行前自动导航到该地址（并处理 JS 重定向链、`navigation_wait` 等）。`goto` 步骤用于执行过程中需要额外跳转的场景。如果任务顶层未声明 `url` 且第一个步骤是 `goto`，则跳过自动导航，由 `goto` 接管。

### eval — JavaScript 求值

执行 JavaScript 表达式并可选保存结果到变量。`code` 字段是 `script` 的已废弃别名，仍然支持但建议使用 `script`。`custom_js` 步骤类型已合并到 `eval`，旧任务中的 `custom_js` 仍会被自动映射到 `eval` 执行。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `script` | 是 | — | JavaScript 代码（支持变量模板） |
| `store_as` | 否 | — | 结果存储到的变量名，后续步骤可用 `{{变量名}}` 引用 |

**执行环境：** `script` 通过 Playwright 的 `page.evaluate()` 在浏览器页面上下文中执行，可访问 `document`、`window` 等页面 API。脚本可以是函数表达式（如 `() => { ... }`）或直接求值的表达式，返回值通过 `store_as` 存入运行时变量供后续步骤引用。变量模板（`{{变量}}`）会在执行前替换为实际值，含特殊字符的变量（如密码）会自动转义以防语法错误。

```json
{
  "id": "check_login_status",
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
{ "id": "screenshot_after", "type": "screenshot", "description": "截图保存" }
```

### sleep — 休眠等待

暂停指定时间。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `duration` | 否 | `1000` | 休眠时间（毫秒），最大 300000 |

```json
{ "id": "wait_load", "type": "sleep", "description": "等待加载", "duration": 2000 }
```

### ocr — 验证码识别

使用 ddddocr 识别验证码图片。截取 `selector` 指定的图片元素，进行 OCR 识别，结果自动填入 `target_selector` 输入框或存储到 `store_as` 变量。

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `selector` | 是 | — | 验证码图片元素选择器 |
| `target_selector` | 否 | — | 验证码输入框选择器，识别后自动填入 |
| `store_as` | 否 | — | 识别结果存储到的变量名 |
| `char_range` | 否 | — | 限定 OCR 识别的字符范围，提高准确度（见下方说明） |
| `timeout` | 否 | `10000` | 超时时间（毫秒） |
| `frame` | 否 | — | 验证码所在的 frame（字符串，不支持布尔值），可选值为 frame name、URL 片段或 CSS 选择器 |
| `old` | 否 | `false` | 使用旧版 OCR 模型（见下方说明） |

**关于 `char_range`：**

`char_range` 用于限定 ddddocr 识别时考虑的字符范围，排除不相关的字符以提高准确度。传入**字符串**限定允许的字符：
- `"0123456789"`：纯数字
- `"abcdefghijklmnopqrstuvwxyz"`：纯小写英文
- `"0123456789+-*/=xX÷"`：数字 + 运算符

用法举例：
- 纯数字验证码 → `"0123456789"`
- 数学运算验证码 → `"0123456789+-*/=xX÷"`
- 大写字母 + 数字 → `"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"`

```json
// 纯数字验证码
{ "id": "ocr_captcha", "type": "ocr", "selector": "#captcha-img", "target_selector": "#captcha-input", "char_range": "0123456789" }

// 数学运算验证码（数字 + 运算符）
{ "id": "ocr_captcha", "type": "ocr", "selector": "#captcha-img", "store_as": "captcha_expr", "char_range": "0123456789+-*/=xX÷" }
```

> **提示：** 数学运算验证码建议配合 `store_as` + `eval` 两步使用——`ocr` 识别图片存入变量，`eval` 从变量读取算式并计算结果填入输入框。
>
> **eval 脚本建议采用多重匹配策略：**
> 1. **字符修正**：`x`/`X`→`*`、`o`/`O`→`0`、`l`/`I`/`|`→`1`、`÷`→`/`、中文数字→阿拉伯数字
> 2. **末尾运算符修复**：OCR 可能把 `22-17` 识别成 `2217-`（运算符跑到末尾），检测末尾单个运算符后拆分数字并插入
> 3. **标准匹配**：正则 `/(\d+)\s*([+\-*\/])\s*(\d+)/` 匹配 `数字 运算符 数字`
> 4. **宽松匹配兜底**：分别提取所有数字和运算符，按出现顺序组合（处理运算符完全丢失，如 `2217`）

**关于新旧模型：**

ddddocr 内置两套模型，`old` 参数控制使用哪一套：

| `old` | 模型 | 说明 |
|-------|------|------|
| `false`（默认） | 新版模型 | 通用场景 |
| `true` | 旧版模型 | 部分校园网系统上识别率可能更高 |

如果你的校园网验证码识别不准，可以尝试切换 `old` 参数值（true/false），或使用 `char_range` 限定字符范围。

**三种使用模式：**

```json
// 模式一：自动填入（推荐）
{ "id": "ocr_captcha", "type": "ocr", "selector": "#captcha-img", "target_selector": "#captcha-input" }

// 模式二：存储到变量，后续步骤再填入
{ "id": "ocr_captcha", "type": "ocr", "selector": "#captcha-img", "store_as": "captcha_code" }

// 模式三：同时自动填入并存储
{ "id": "ocr_captcha", "type": "ocr", "selector": "#captcha-img", "target_selector": "#captcha-input", "store_as": "captcha_code" }
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

### 变量类型

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

1. 运行时变量（`eval` 步骤的 `store_as` 产生的变量）
2. 模板变量（认证地址、账号密码、运营商等运行时配置）
3. 任务文件内 `variables` 字段

未找到的变量会原样保留在输出中（不会报错）。

---

## 成功判断

任务步骤全部执行完后，系统需要判断这次任务算成功还是失败。判定方式有两种：**什么都不写**（默认走系统网络检测），或**用 `eval` 步骤写一个变量 + 顶层 `success_condition` 引用它**。

### 两种方式对比

| 方式 | 触发条件 | 判定依据 | 失败后处理 |
|------|---------|---------|-----------|
| 默认（网络检测） | 登录任务且未声明 `success_condition` | 探测网络是否恢复 | 按重试策略重试 |
| 默认（步骤完成） | 普通浏览器任务且未声明 `success_condition` | 步骤全部跑完即成功 | 步骤执行失败才重试 |
| `success_condition` | 任务顶层声明了 `success_condition`（非空字符串） | 读取变量值做真值判定 | 假值按重试策略重试 |

> **关键规则**：只要在任务顶层声明了非空 `success_condition`，登录任务就**跳过网络检测**，完全信任变量的真值判定结果。

### 方式一：默认（什么都不写）

**适用场景**：普通校园网登录任务，登录成功后网络就通了，无需关心页面文字。

**执行流程**：
1. 任务步骤全部执行完成
2. 系统等待 `post_login_delay` 秒（默认 5 秒，让认证服务器响应）
3. 使用 Web 控制台监控设置中配置的 TCP/HTTP/URL 探测方式检测网络
4. 网络恢复 → 判定成功；网络未恢复 → 判定失败，按重试策略重试

**配置方式**：无需在任务 JSON 中添加任何字段，保持原样即可。

**注意**：只有"登录任务"会自动检测网络。其他浏览器任务（比如打卡、签到）**不会**检测网络——步骤跑完就算成功（因为这些任务运行时本来就有网，不然页面打不开）。

### 方式二：用 `success_condition` 自己判断

**适用场景**：
- 想识别"密码错误""账号被锁定"等明确失败信号
- 登录成功后不想等 5 秒网络检测，想用页面特征快速判定
- 打卡/签到任务想通过页面文字判断是否成功

#### 工作原理

1. 你在 `steps` 里加一个 `eval` 步骤，写一段 JS 判定逻辑，用 `store_as` 把结果存到一个变量
2. 在任务 JSON 顶层用 `success_condition` 字段引用这个变量名
3. 系统在步骤跑完后读取该变量的值做真值判定

#### 字段定义

| 字段 | 位置 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `success_condition` | 任务顶层 | string | `""` | 变量名（不带 `{{}}`），系统从运行时变量中取该值做真值判定。留空走默认路径 |

#### 真值判定规则

系统读取 `success_condition` 指向的变量值后，按以下规则判定真假：

| 变量值类型 | 判定为 True | 判定为 False |
|----------|------------|-------------|
| bool | `True` | `False` |
| None | — | 总是 False |
| string | 非空且不等于 `"false"`/`"0"`/`"no"`/`"off"`（不区分大小写） | `""`/`"false"`/`"0"`/`"no"`/`"off"` |
| 数字 | 非零 | 零 |
| 其他 | `bool(value)` 为真 | `bool(value)` 为假 |

> **变量未设置**：如果声明的变量名在运行时变量中不存在（例如 `eval` 步骤未执行或 `store_as` 名字写错），判定为**失败**，日志会提示检查 `store_as`。

#### 失败后的处理

- 变量值为假值 → 判定失败，**按重试策略重试**（与默认路径一致）
- 重试耗尽后返回 EXHAUSTED

> **关于"密码错误不重试"**：本方案不区分"密码错误"和"网络抖动"，统一按重试策略处理。如果你希望密码错误时立即停止，可以在 `eval` 脚本里抛异常让步骤直接失败（步骤失败会立即终止任务，但仍计入重试）。

#### `eval` 步骤的 JS 写法

`eval` 步骤的 `script` 在浏览器页面上下文中执行，可访问 DOM、URL、Cookie、localStorage 等页面 API：

```javascript
// 检查页面文字（返回 true/false）
() => !document.body.innerText.includes('密码错误')

// 检查元素是否存在
() => document.querySelector('.welcome-user') !== null

// 检查 URL 跳转
() => location.href.includes('success')

// 组合判定（出现"密码错误"或"账号锁定"返回 false，否则 true）
() => !document.body.innerText.includes('密码错误') && !document.body.innerText.includes('账号锁定')

// 使用变量（自动替换）
() => document.body.innerText.includes('{{username}}')
```

> `script` 可以是函数表达式 `() => ...`，也可以是直接求值的表达式。返回值通过 `store_as` 存入运行时变量。详见 [eval 步骤](#eval--javascript-求值)。

#### 示例 1：登录任务识别密码错误

```json
{
  "name": "校园网登录",
  "steps": [
    {"id": "s1", "type": "goto", "url": "{{auth_url}}"},
    {"id": "s2", "type": "fill", "selector": "#username", "value": "{{username}}"},
    {"id": "s3", "type": "fill", "selector": "#password", "value": "{{password}}"},
    {"id": "s4", "type": "click", "selector": "#login"},
    {
      "id": "check_result",
      "type": "eval",
      "description": "检查是否登录成功（页面无错误提示即视为成功）",
      "script": "() => !document.body.innerText.includes('密码错误') && !document.body.innerText.includes('认证失败')",
      "store_as": "success_flag"
    }
  ],
  "success_condition": "success_flag"
}
```

**执行过程**：
- 点击登录后执行 `eval` 步骤，检查页面是否出现"密码错误"或"认证失败"
- 没有出现 → `success_flag` = `true` → 判定成功；因声明了 `success_condition`，**跳过网络检测**
- 出现了 → `success_flag` = `false` → 判定失败，按重试策略重试（密码错误会一直重试到耗尽，约 5 分钟后返回 EXHAUSTED）

#### 示例 2：组合多个判定条件

```json
{
  "name": "校园网登录",
  "steps": [
    {"id": "s1", "type": "goto", "url": "{{auth_url}}"},
    {"id": "s2", "type": "fill", "selector": "#username", "value": "{{username}}"},
    {"id": "s3", "type": "fill", "selector": "#password", "value": "{{password}}"},
    {"id": "s4", "type": "click", "selector": "#login"},
    {
      "id": "check_result",
      "type": "eval",
      "description": "综合判定：无错误提示且出现欢迎元素才算成功",
      "script": "() => !document.body.innerText.includes('密码错误') && !document.body.innerText.includes('认证失败') && document.querySelector('.welcome-user') !== null",
      "store_as": "success_flag"
    }
  ],
  "success_condition": "success_flag"
}
```

> **配合 `wait` 步骤**：如果想在判定前先等待某个元素出现，可以在 `eval` 之前加一个 `wait` 步骤（如 `{"type": "wait", "selector": ".welcome-user", "timeout": 5000}`）。`wait` 失败会直接终止任务（计入重试），`eval` 再做最终判定。

#### 示例 3：打卡任务靠页面文字判断

```json
{
  "name": "每日打卡",
  "steps": [
    {"id": "s1", "type": "goto", "url": "https://example.com/punch"},
    {"id": "s2", "type": "click", "selector": "#punch-btn"},
    {
      "id": "check_punch",
      "type": "eval",
      "description": "检查打卡结果文字",
      "script": "() => document.body.innerText.includes('打卡成功')",
      "store_as": "success_flag"
    }
  ],
  "success_condition": "success_flag"
}
```

**执行过程**：
- 打卡任务为普通浏览器任务，本就不走网络检测
- 声明 `success_condition` 后：`eval` 返回 `true` → 成功；返回 `false` → 失败

### 关于 `post_login_delay`

`post_login_delay` 控制默认方式中登录步骤跑完后到网络检测之间的等待时间，默认 5 秒。该字段在 **Web 控制台的监控设置**中配置，**不要写在任务 JSON 中**。

| 配置位置 | 取值范围 | 生效场景 |
|---------|---------|---------|
| Web 控制台 → 监控设置 → `post_login_delay` | 0~60 秒 | 仅默认方式（未声明 `success_condition` 的登录任务） |

- 仅在登录任务未声明 `success_condition` 时生效
- 声明 `success_condition` 后，登录任务跳过网络检测，此等待时间不生效
- 普通浏览器任务不涉及登录，不使用此参数
- 设为 0 表示不等待，立即检测

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
  "id": "fill_username",
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

系统会在执行步骤前**自动导航**到认证地址，**无需在任务中添加 navigate 步骤**（系统不识别 navigate 步骤类型，旧任务如果包含 navigate 步骤需手动移除）。导航地址优先级：

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
      "id": "fill_username",
      "type": "input",
      "description": "输入账号",
      "selector": "input[name='DDDDD'], input[name='username'], #username",
      "value": "{{username}}",
      "clear": true
    },
    {
      "id": "fill_password",
      "type": "input",
      "description": "输入密码",
      "selector": "input[name='upass'], input[type='password'], #password",
      "value": "{{password}}",
      "clear": true
    },
    {
      "id": "select_carrier",
      "type": "select",
      "description": "选择运营商",
      "selector": "select[name='ISP_select'], select[name='isp']",
      "value": "{{isp}}"
    },
    {
      "id": "click_login",
      "type": "click",
      "description": "点击登录",
      "selector": "input[name='0MKKey'], button[type='submit'], #login-btn"
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
    { "id": "fill_username", "type": "input", "selector": "#username", "value": "{{USERNAME}}" },
    { "id": "fill_password", "type": "input", "selector": "#password", "value": "{{PASSWORD}}" },
    { "id": "click_login", "type": "click", "selector": "#login-btn" }
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
    { "id": "fill_username", "type": "input", "selector": "#username", "value": "{{USERNAME}}" },
    { "id": "fill_password", "type": "input", "selector": "#password", "value": "{{PASSWORD}}" },
    {
      "id": "ocr_captcha",
      "type": "ocr",
      "description": "识别验证码并填入",
      "selector": "#captcha-img",
      "target_selector": "#captcha-input",
      "char_range": "0123456789"
    },
    { "id": "click_login", "type": "click", "selector": "#login-btn" }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

### 带数学运算验证码的登录任务

```json
{
  "name": "数学验证码登录",
  "description": "需要计算数学运算验证码的校园网登录",
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "steps": [
    { "id": "fill_username", "type": "input", "selector": "#username", "value": "{{USERNAME}}" },
    { "id": "fill_password", "type": "input", "selector": "#password", "value": "{{PASSWORD}}" },
    {
      "id": "ocr_captcha",
      "type": "ocr",
      "description": "识别数学验证码图片",
      "selector": "#captchaCanvas",
      "store_as": "captcha_expr",
      "char_range": "0123456789+-*/=xX÷"
    },
    {
      "id": "solve_captcha",
      "type": "eval",
      "description": "计算验证码结果并填入",
      "script": "() => { let expr = '{{captcha_expr}}'; const cnMap={'一':'1','二':'2','三':'3','四':'4','五':'5','六':'6','七':'7','八':'8','九':'9','零':'0'}; expr=expr.replace(/[xX]/g,'*').replace(/[oO]/g,'0').replace(/[lI|]/g,'1').replace(/记/g,'1').replace(/÷/g,'/').replace(/[一二三四五六七八九零]/g,c=>cnMap[c]||c); const tail=expr.match(/^(\\d+)([+\\-*\\/])$/); if(tail){const n=tail[1],op=tail[2];const mid=Math.ceil(n.length/2);expr=n.slice(0,mid)+op+n.slice(mid);} let m=expr.match(/(\\d+)\\s*([+\\-*\\/])\\s*(\\d+)/); if(!m){const ops=expr.match(/[+\\-*\\/]/g);const nums=expr.match(/\\d+/g);if(nums&&nums.length>=2&&ops&&ops.length>=1)m=[null,nums[0],ops[0],nums[1]];} if(!m)return'NO_MATCH:'+expr; const a=parseInt(m[1]),b=parseInt(m[3]),op=m[2]; let r; if(op==='+')r=a+b; else if(op==='-')r=a-b; else if(op==='*')r=a*b; else r=b!==0?Math.floor(a/b):0; const v=r.toString(); const el=document.querySelector('#captchaInput'); if(el){el.value=v;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));} return v; }",
      "store_as": "captcha_result"
    },
    { "id": "click_login", "type": "click", "selector": "#login-btn" }
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
      "id": "fill_username",
      "type": "input",
      "description": "在 iframe 中输入账号",
      "selector": "#username",
      "value": "{{USERNAME}}",
      "frame": "mainFrame"
    },
    {
      "id": "fill_password",
      "type": "input",
      "description": "在 iframe 中输入密码",
      "selector": "#password",
      "value": "{{PASSWORD}}",
      "frame": "mainFrame"
    },
    {
      "id": "click_login",
      "type": "click",
      "description": "在 iframe 中点击登录",
      "selector": "#login-btn",
      "frame": "mainFrame"
    }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

### 带隐藏输入框的登录任务

部分校园网认证页面的真实输入框是 `display:none` 的，页面上只有装饰性的 tip/占位元素。

**推荐做法：** 无需额外配置——执行器在普通操作失败后会自动降级到强制模式处理隐藏输入框。如果自动降级不生效，再在任务 JSON 顶层添加 `"reveal_hidden": true`。

```json
{
  "name": "隐藏输入框登录",
  "description": "适用于隐藏输入框的认证页面",
  "url": "{{LOGIN_URL}}",
  "timeout": 30000,
  "steps": [
    {
      "id": "fill_username",
      "type": "input",
      "description": "输入账号",
      "selector": "#username",
      "value": "{{USERNAME}}"
    },
    {
      "id": "fill_password",
      "type": "input",
      "description": "输入密码",
      "selector": "#password",
      "value": "{{PASSWORD}}"
    },
    {
      "id": "click_login",
      "type": "click",
      "description": "点击登录按钮",
      "selector": "#login_button"
    }
  ],
  "on_success": { "message": "登录成功" },
  "on_failure": { "message": "登录失败", "screenshot": true }
}
```

> **提示：** 无需 `reveal_hidden`，执行器会在 `fill()` 失败时自动降级到强制模式。如果自动降级不生效，再添加 `"reveal_hidden": true`。Campus-Auth 任务录制器（油猴脚本）的「隐藏检测」开关可以自动识别这种模式。

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

- 默认无需配置，登录任务靠系统网络检测兜底，普通任务步骤完成即成功
- 如需识别"密码错误"等页面特征，用 `eval` 步骤 + `store_as` 存判定结果，再在顶层声明 `success_condition` 引用该变量
- 详见 [成功判断](#成功判断) 章节

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
3. 变量来源是否正确：系统变量（账号、密码等）自动可用；任务变量需在任务 JSON 的 `variables` 字段中定义

**Q: 如何判断登录成功？**

A: 系统自动在网络检测成功后判定为登录成功，无需额外配置。网络检测失败通常表示密码错误或运营商不匹配。

**Q: 保存任务时弹出安全警告？**

A: 因为任务中包含 `eval` 步骤，该步骤可以执行任意 JavaScript 代码。系统会显示代码内容要求确认，确认代码安全后点击确认即可。

**Q: 内置任务和普通任务有什么区别？**

A: 内置任务是随项目分发的预设任务。你可以在内置任务的基础上复制、修改来创建自己的任务。

**Q: 输入框是隐藏的（display:none）怎么办？**

A: 部分校园网认证页面的真实输入框是隐藏的，页面上只显示占位 tip 或假输入框。解决方案：

1. 无需额外配置——执行器会在普通输入失败时自动降级到强制模式（JS 原生 setter），通常直接可用
2. 如果自动降级不生效，在任务 JSON 顶层添加 `"reveal_hidden": true`，执行器会在步骤执行前强制显示所有隐藏输入框。注意：这会同时显示验证码等本该隐藏的元素，可能导致部分页面异常
3. 如果页面通过 AJAX 动态渲染表单（如 ePortal），`reveal_hidden` 可能无效——需要同时设置 `"navigation_wait": 3` 等待 AJAX 完成
4. 使用 Campus-Auth 任务录制器（油猴脚本）的「隐藏检测」功能，打开 🔍 开关后点击占位区域即可自动识别

详见上方「带隐藏输入框的登录任务」完整示例。

**Q: 验证码识别不准怎么办？**

A: 两种方式可以提高识别准确度：

1. **限定字符范围**（推荐）：在 `ocr` 步骤中添加 `char_range` 参数，排除不相关的字符。例如纯数字验证码用 `"0123456789"`，数学验证码用 `"0123456789+-*/=xX÷"`
2. **切换模型**：尝试切换 `old` 参数（`true`/`false`），两套模型对不同风格的验证码效果不同

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
| `goto` | 页面导航 | `url`, `wait_until` | 与顶层 `url` 自动导航互补，用于执行中切换页面 |
| `eval` | JS 求值 | `script`, `store_as` | 结果可存入变量；`code` 为已废弃别名；`custom_js` 已合并到此类型 |
| `screenshot` | 截图 | `path` | — |
| `sleep` | 休眠 | `duration` | 最大 300000ms |
| `ocr` | 验证码识别 | `selector`, `target_selector`, `store_as`, `char_range`, `old` | 支持新旧模型切换；`char_range` 限定识别字符范围提高准确度 |

> 所有操作类步骤都支持 `frame` 公共字段，用于在 frameset/iframe 页面中定位子 frame 内的元素。

---

## 分享你创建的任务

如果你编写了一个适用于特定校园网的认证任务，欢迎将它分享给社区！分享的任务会收录在 [Campus-Auth 任务仓库](https://github.com/Misyra/campus-auth-tasks)，其他用户可以直接从仓库导入使用。

**分享方式：**

- **快速分享**：在 Web 控制台导出任务 JSON，到 [Issues](https://github.com/Misyra/campus-auth-tasks/issues/new) 提交
- **提交 PR**：Fork 仓库 → 添加任务文件 → 提交 Pull Request，详见 [任务仓库贡献指南](https://github.com/Misyra/campus-auth-tasks#贡献)
