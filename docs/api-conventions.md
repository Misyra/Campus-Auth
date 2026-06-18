# API 错误响应规范

## 规则

| 场景 | 响应方式 | 状态码 |
|------|----------|:------:|
| 资源不存在 | `HTTPException` | 404 |
| 参数非法 | `HTTPException` | 422 |
| 权限问题 | `HTTPException` | 403 |
| 业务可预期失败 | `ActionResponse(success=False)` | 200 |
| 程序异常（未捕获） | `HTTPException` | 500 |

## 说明

### 业务可预期失败 vs 程序异常

- **业务失败**：登录认证失败、任务执行超时、配置验证不通过 —— 正常业务流程的一部分
- **程序异常**：数据库连接失败、文件系统错误、未处理的 ValueError —— 程序 bug

### 关键原则

1. `ActionResponse(success=False)` 只用于业务可预期失败
2. 未捕获异常统一返回 500，不要用 `ActionResponse(success=False, message=str(e))` 掩盖
3. 资源不存在用 404，不要返回 200 + `success=false`

### 前端处理

- 4xx/5xx 状态码 → Axios 拦截器统一处理
- 200 + `success=false` → 业务层处理
