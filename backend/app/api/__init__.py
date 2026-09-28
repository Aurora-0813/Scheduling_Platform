"""
接口层

`deps.py` 放全组共用的依赖（认证、鉴权、资源获取），
`v1/` 按负责人拆分的路由模块。

路由模块的共同约定：
- 出参一律是 `ApiResponse[...]`，用返回值 `return ok(data)` 而不是
  `return JSONResponse(...)` —— 所有异常由 app/core/response.py 的
  处理器统一收口，路由里出现手写错误响应就会破坏「成功与失败结构一致」；
- 想清楚 `response_model`：FastAPI 会按它**过滤**实际返回的字段，
  声明得过窄会静默丢字段（见 app/schemas/monitor.py 的说明）。
"""
