# 任务系统文档

本项目的任务系统由 tasks 目录下的 JSON 文件驱动，用于定义不同校园网认证页面的自动化步骤。

## 1. 目录结构

tasks 目录通常包含以下文件：

- active.txt：当前启用任务 ID，例如 default
- default.json：默认任务模板（不可删除）
- ruijie.json：锐捷模板
- srun.json：深澜模板
- drcom.json：哆点模板

说明：

- active.txt 内容是单行文本，值为任务文件名（不含 .json 后缀）
- 后端会自动扫描 tasks 下所有 json 文件并加载到任务列表

## 2. Web 控制台支持的操作

在任务管理页面可以完成：

- 查看任务列表
- 新建任务
- 编辑任务
- 保存任务
- 设置活动任务
- 删除任务（default 不可删除）

后端保存任务时会做基础校验：

- task_id 不能为空
- task_id 只能包含字母、数字、下划线
- name 不能为空
- steps 至少有一项

## 3. 任务 JSON 字段说明

任务 JSON 支持以下常用字段：

- name: string
  - 任务名称，必填
- description: string
  - 任务描述，可选
- version: string
  - 版本号，可选，默认 1.0
- url: string
  - 认证页地址，可选
- variables: object
  - 任务级变量定义，可选
- timeout: number
  - 全局超时（毫秒），可选，默认 30000
- steps: array
  - 步骤列表，必填
- success_conditions: array
  - 成功判定条件，可选
- on_success: object
  - 成功提示配置，可选
- on_failure: object
  - 失败提示配置，可选

## 4. 变量替换规则

步骤中字符串支持占位符 {{变量名}}，解析顺序如下：

1. 运行时变量（例如 eval 步骤通过 store_as 写入）
2. 环境变量（系统环境与 .env）
3. 任务文件内 variables 字段

示例：

- {{USERNAME}}、{{PASSWORD}} 来自环境变量
- {{username}}{{isp}} 可拼接账号与运营商后缀

## 5. 支持的步骤类型

以下步骤由任务引擎直接支持：

1) navigate

- 作用：打开页面
- 常用参数：
  - url: 页面地址（支持变量）
  - wait_until: 页面等待策略，默认 networkidle

2) input

- 作用：向输入框填值
- 常用参数：
  - selector: 目标选择器
  - value: 输入值（支持变量）
  - clear: 是否先清空，默认 true

3) click

- 作用：点击元素
- 常用参数：
  - selector: 目标选择器

4) select

- 作用：选择下拉框
- 常用参数：
  - selector: 下拉框选择器
  - value: 选项值（支持变量）

5) wait

- 作用：等待元素出现
- 常用参数：
  - selector: 目标选择器
  - timeout: 超时毫秒，默认 10000

6) wait_url

- 作用：等待 URL 匹配正则
- 常用参数：
  - pattern: 正则表达式字符串
  - timeout: 超时毫秒，默认 10000

7) eval

- 作用：执行 JavaScript
- 常用参数：
  - script: JS 代码
  - store_as: 可选，保存返回值到运行时变量

8) custom_js

- 作用：执行 JavaScript（无返回值保存）
- 常用参数：
  - script: JS 代码

9) screenshot

- 作用：保存截图
- 常用参数：
  - path: 截图路径，默认 debug/step_screenshot.png

## 6. 成功判定与失败处理

success_conditions 目前支持：

- variable
  - 判断变量是否等于指定值
  - 参数：variable、value
- url_contains
  - 判断当前 URL 是否包含指定字符串
  - 参数：pattern

on_success 常用字段：

- message: 成功消息

on_failure 常用字段：

- message: 失败消息
- screenshot: true 时，执行失败自动截图到 debug/task_failure.png

## 7. 最小可用示例

```json
{
  "name": "示例任务",
  "description": "最小可用模板",
  "version": "1.0",
  "url": "http://172.29.0.2",
  "variables": {
    "username": "{{USERNAME}}",
    "password": "{{PASSWORD}}"
  },
  "timeout": 30000,
  "steps": [
    {
      "type": "navigate",
      "url": "{{url}}",
      "wait_until": "networkidle",
      "description": "打开认证页"
    },
    {
      "type": "input",
      "selector": "#username",
      "value": "{{username}}",
      "clear": true,
      "description": "输入用户名"
    },
    {
      "type": "input",
      "selector": "#password",
      "value": "{{password}}",
      "clear": true,
      "description": "输入密码"
    },
    {
      "type": "click",
      "selector": "#login",
      "description": "点击登录"
    },
    {
      "type": "eval",
      "script": "document.body.innerText.includes('成功')",
      "store_as": "login_success",
      "description": "判断是否成功"
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

## 8. 调试建议

- 先用浏览器开发者工具确认 selector，再写入任务
- 复杂页面优先加 wait 或 wait_url，避免元素未加载导致失败
- 认证失败时查看 Web 控制台日志，并检查 debug 目录截图
- 任务修改后建议切换为该任务并手动执行一次登录进行验证
