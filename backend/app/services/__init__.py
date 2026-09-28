"""
业务服务层

本层的三条约定（全组统一）：
1. **必须在业务结尾显式 `await session.commit()`** —— `get_db` 只负责回滚与
   关闭，不再兜底提交（见 app/core/database.py）。忘记提交不会报错，
   但数据不会落库，是本项目最容易踩的坑。
2. **失败一律抛 `BizError` 子类**，不构造 HTTP 响应，也不吞异常。
3. **入参用原始值**（str/int/模型），不接收 `Request` / `UploadFile` 之外的
   框架对象，保证同一段逻辑能被 HTTP 之外的入口复用。

本文件只放上述约定，不 re-export 子模块 —— 子模块之间互相 import 时
很容易与 `__init__` 形成循环导入。
"""
