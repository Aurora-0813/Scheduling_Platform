"""
统一响应体模块
====================================================================
⚠️ 临时实现，待基础支撑与集成组接管

    本文件由摄像头空间感知模块（模块 2）临时创建，仅为让本模块能先行跑通自测。
    集成组交付正式的 core/response.py 后，**直接覆盖本文件即可**，
    只要保持 success() / fail() 的函数签名与响应体结构不变，模块 2 无需改动。

规范依据：
    开发流程.md §5.2 统一响应体：
        {
          "code": 200,
          "message": "操作成功",
          "data": {}
        }

HTTP 状态码约定（**待集成组确认**）：
    所有响应 HTTP 状态码恒为 200，业务结果全部由 body 里的 code 表达。
    理由：前端 axios 默认会把非 2xx 当网络异常抛错，恒 200 可以让前端
    只写一处 `if (res.data.code !== 200)` 的拦截逻辑，心智负担最低。
    401 / 41001 等语义码一律放在 body.code 里，不放 HTTP 状态行。
"""
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

# 泛型参数：响应体里 data 的具体类型
T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    统一响应体模型。

    用途：
        在路由上用 `response_model=ApiResponse[SpaceAnalyzeData]` 声明，
        FastAPI 会自动生成正确的 OpenAPI 文档，Swagger 里能直接看到 data 的结构。

    注意：
        实际返回给前端的是普通 dict（由 success() 构造），
        这个类只服务于接口文档与类型提示。
    """
    code: int = Field(200, description="业务状态码：200 成功，其余见错误码表")
    message: str = Field("操作成功", description="给人看的提示信息")
    data: T | None = Field(None, description="业务数据，失败时为 null")


def _serialize(data):
    """
    把 Pydantic 模型转成可 JSON 序列化的普通 dict。

    参数：
        data : 任意。可能是 Pydantic 模型、dict、list、或 None

    返回：
        可直接交给 FastAPI 序列化的对象

    说明：
        之所以判断 model_dump 而不是 isinstance(BaseModel)，
        是为了同时兼容 Pydantic v1（dict()）与 v2（model_dump()），
        以及未来可能出现的自定义可序列化对象。
    """
    if data is None:
        return None
    if hasattr(data, "model_dump"):          # Pydantic v2
        return data.model_dump()
    if hasattr(data, "dict"):                # Pydantic v1
        return data.dict()
    return data


def success(data=None, message: str = "操作成功") -> dict:
    """
    构造「成功」响应体。

    参数：
        data    : 业务数据，可以是 Pydantic 模型 / dict / list / None
        message : 提示信息，默认"操作成功"

    返回：
        dict，形如 {"code": 200, "message": "...", "data": {...}}

    用法：
        return success(data=SpaceAnalyzeData(...), message="识别完成")
    """
    return {"code": 200, "message": message, "data": _serialize(data)}


def fail(code: int, message: str, data=None) -> dict:
    """
    构造「失败」响应体。

    参数：
        code    : 业务错误码，见开发流程.md §13 与各模块错误码表
        message : 面向用户的友好提示（禁止把堆栈、SQL 错误直接吐给前端）
        data    : 失败时通常为 None；某些场景可携带部分数据（如候选列表）

    返回：
        dict，形如 {"code": 41003, "message": "...", "data": null}

    用法：
        return fail(code=41003, message="图像识别服务暂时不可用")
    """
    return {"code": code, "message": message, "data": _serialize(data)}
