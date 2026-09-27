"""
业务服务层

本层的三条约定（全组统一）：
1. **必须在业务结尾显式 `await session.commit()`** —— `get_db` 只负责回滚与
   关闭，不再兜底提交（见 app/core/database.py）。忘记提交不会报错，
   但数据不会落库，是本项目最容易踩的坑。
2. **失败一律抛 `BizError` 子类**，不构造 HTTP 响应，也不吞异常。
3. **入参用原始值**（str/int/模型），不接收 `Request` / `UploadFile` 之外的
   框架对象，保证同一段逻辑能被 HTTP 之外的入口复用。

一般不在本文件 re-export 子模块 —— 子模块之间互相 import 时很容易与 `__init__`
形成循环导入。

下方是**一处例外**（模块 3）：预约单据的写入只有这两个入口，对外（模块 4 的
Agent Tool 层）暴露 `app.services.create_order` / `app.services.update_agent_trace`
这两个稳定名字，比让调用方记住子模块路径更合适。它们只是同一个函数对象的别名，
不可能与定义处漂移；写代码、评审、排查时一律以 `app/services/order_service.py`
里的定义为权威。
"""

from .order_service import create_order, update_agent_trace

__all__ = ["create_order", "update_agent_trace"]
