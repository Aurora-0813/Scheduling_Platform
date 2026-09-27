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

**例外（2026-09-28，模块 4）：下面四个阶段 3 的桩函数仍在此 re-export。**
合并 `origin/main`（`9f30d3a`）时两版在此冲突：正式版只留上面这段约定，模块 4
的版本额外 re-export 了 `query_spaces` / `query_devices` / `create_order` /
`generate_notification`。取并集，理由：

  · 这四个函数**集成组未提供**（`services/` 下没有 `space_service.py` /
    `device_service.py` / `order_service.py` / `notify_service.py`，只有模块 4
    阶段 3 建的桩），去掉 re-export 不会「收窄到正式版」，而是让功能消失；
  · 阶段 4 的 Tool 层按主文档 4.3 / 7.4 写的就是
    `from app.services import query_spaces, ...`（`tools/query_spaces.py:14`、
    `tools/query_devices.py:27`、`tools/lock_resources.py:30`、
    `tools/generate_notification.py:27`），阶段 7 的两个用例也直接导
    `order_service`——去掉即全线 `ImportError`；
  · 上面担心的循环导入在这里不成立：四个桩模块都是**叶子**，自身不 import
    `app.services`。

真实实现落地后，按 `docs/spec/done/stage-03-completion.md` 的替换清单改
**这一个文件**即可，Tool 层与用例一行不动——这正是阶段 3「桩函数先行」的前提。
"""
from app.services.device_service import query_devices
from app.services.notify_service import generate_notification
from app.services.order_service import create_order
from app.services.space_service import query_spaces

__all__ = [
    "query_spaces",
    "query_devices",
    "create_order",
    "generate_notification",
]
