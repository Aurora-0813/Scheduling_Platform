"""统一响应体 {code, message, data}（开发流程 §5.2）。"""


def ok(data=None, message: str = "操作成功", code: int = 200) -> dict:
    return {"code": code, "message": message, "data": data}
