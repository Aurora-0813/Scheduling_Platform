"""
模块 8 测试公共构件（夹具数据、假会话、假 LLM）

与 conftest.py 的分工：本文件放**可复用的构件与工厂**，conftest.py 只放 pytest fixture。
这样测试模块 `from tests.helpers import ...` 即可，不必去 import conftest
（那会依赖 pytest 的 importmode 细节，比较脆）。

设计原则（《规范》10.2）：
- **全程离线**：不连真库、不调真实 LLM
- **数据只读**：测试数据一律建在**内存 SQLite** 上，绝不向正式表写入
- **语义不重写**：除 `JSON_TABLE` 外，服务里的 ORM 语句都交给**真实 SQLite 引擎**
  执行 —— WHERE / IN / COUNT / 时间过滤的语义由数据库决定，而不是在测试里
  用 Python 复刻一遍。复刻出来的「语义」证明不了生产 SQL 正确，那等于测试自证。

唯一需要替换的是 MySQL 的 `JSON_TABLE`（SQLite 无此语法），换成 `json_each` 等价写法
—— 同样是真 SQL、真引擎。**本机 MySQL 上的真实 `JSON_TABLE` 行为仍属「依赖真库」项**，
由 docs/data-audit-todo.md 步骤 3A-2 覆盖。
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import Field
from sqlalchemy import bindparam, create_engine, event, text
from sqlalchemy.sql.elements import TextClause

# backend/ 加入 sys.path，使测试能以 `app.xxx` 导入（不依赖把项目装成包）
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import Base                                    # noqa: E402
import app.models                                                     # noqa: F401,E402
from app.models.inspection import RepairTicket                        # noqa: E402
from app.models.reservation import ReserveOrder                       # noqa: E402
from app.models.resource import DeviceResource, SpaceResource         # noqa: E402
from app.services import dashboard_ai_service as ai_svc               # noqa: E402


# ============================================================
# 一、内存 SQLite 引擎
# ============================================================
def new_engine():
    """每个测试一份独立内存库（`sqlite://` 无文件，天然隔离）"""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _register_mysql_compat(dbapi_conn, _record):
        """
        给 SQLite 补一个与 MySQL 同名的 `HOUR()`。

        只为让 `get_peak_hours` 的同一条 SQL 能在测试库上执行 ——
        补的是**函数**，不是查询语义。真实 MySQL `HOUR()` 的返回仍只在真库上验证。
        """
        def hour(value):
            if value is None:
                return None
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except ValueError:
                    return None
            return value.hour

        dbapi_conn.create_function("hour", 1, hour)

    return engine


# ============================================================
# 二、假会话
# ============================================================
class FakeResult:
    """SQLAlchemy `Result` 的最小替身：服务只用到 scalar() / all() / first()"""
    __slots__ = ("_rows",)

    def __init__(self, rows):
        self._rows = list(rows)

    def scalar(self):
        return self._rows[0][0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def scalars(self):
        return [row[0] for row in self._rows]

    def __iter__(self):
        return iter(self._rows)


# `JSON_TABLE` 的 SQLite 等价写法：json_each 展开数组 → JOIN 过滤不存在的设备 ID
# → COUNT(DISTINCT) 去重。与原 SQL 逐句对应，参数名刻意保持一致。
JSON_EACH_EQUIVALENT = text("""
    SELECT COUNT(DISTINCT jt.value)
    FROM reserve_order AS ro
    JOIN json_each(COALESCE(ro.device_ids, '[]')) AS jt
    JOIN device_resource AS dr ON dr.id = jt.value
    WHERE ro.order_status IN :statuses
      AND ro.start_time >= :since
""").bindparams(bindparam("statuses", expanding=True))


class FakeDashboardSession:
    """
    假 `AsyncSession`。

    除 `JSON_TABLE` 外一律交给真实 SQLite 执行，并记录已执行语句，
    便于断言「有没有多发一次查询」（如 I5 分母为 0 时应早退、D1 不应发起调用）。
    """

    def __init__(self, engine):
        self.engine = engine
        self.executed = []          # 已执行语句列表

    async def execute(self, statement, params=None):
        params = params or {}

        if isinstance(statement, TextClause):
            sql = str(statement)
            # 自检：本替身只为 JSON_TABLE 而生。若服务里出现别的 TextClause，
            # 必须立刻报错 —— 否则会用错误的等价写法糊弄过去，测试变成假绿。
            assert "JSON_TABLE" in sql, f"未预期的 TextClause，请扩展假会话:\n{sql}"
            assert "COUNT(DISTINCT" in sql.upper(), "JSON_TABLE 语句形状已变，请核对"
            self.executed.append("JSON_TABLE")
            return self._run(JSON_EACH_EQUIVALENT, params)

        self.executed.append(str(statement))
        return self._run(statement, params)

    def _run(self, statement, params):
        with self.engine.connect() as conn:
            # 必须先取完再关连接：Row 是惰性的，连接关了就取不到
            rows = conn.execute(statement, params).all()
        return FakeResult(rows)


# ============================================================
# 三、夹具数据构造
# ============================================================
def make_device_rows(count=15, total_count=1, id_start=1):
    """批量造 device_resource 行。默认每行 total_count=1 —— 即 docs/test.md 的「夹具 B」"""
    return [
        {
            "id": i,
            "device_name": f"设备{i}",
            "device_type": "投影仪",
            "device_status": 1,
            "total_count": total_count,
            "available_count": total_count,
        }
        for i in range(id_start, id_start + count)
    ]


def make_order(order_id, device_ids, status=2, end=None, duration_hours=2.0, space_id=1):
    """造一条预约订单。end 默认「1 小时前」，保证落在任何窗口内"""
    end = end or (datetime.now() - timedelta(hours=1))
    return {
        "id": order_id,
        "user_id": 1,
        "space_id": space_id,
        "device_ids": device_ids,
        "order_status": status,
        "start_time": end - timedelta(hours=duration_hours),
        "end_time": end,
    }


def make_order_between(order_id, start, end, status=2, device_ids=None, space_id=1):
    """显式指定起止时间，用于需要精确时长的用例（U 系列）"""
    return {
        "id": order_id,
        "user_id": 1,
        "space_id": space_id,
        "device_ids": device_ids,
        "order_status": status,
        "start_time": start,
        "end_time": end,
    }


def make_space(space_id, status=1, open_start=None, open_end=None):
    """
    造一条 space_resource。

    ⚠️ `open_*` **会影响**场地使用率的分母（2026-09-28 起逐行读实际时段）：
    传了就用真实差值，不传（NULL）则走 `OPEN_HOURS_FALLBACK = 14` 兜底。
    所以只想验「分母按场地数走」的时候，不传即可 —— 每个场地恰好 14h/天。
    """
    return {
        "id": space_id,
        "space_name": f"场地{space_id}",
        "space_type": 1,
        "capacity": 10,
        "status": status,
        "open_start_time": open_start,
        "open_end_time": open_end,
    }


def make_ticket(ticket_id, device_id, space_id=1):
    return {"id": ticket_id, "device_id": device_id, "space_id": space_id, "ticket_status": 1}


def build_session(devices=(), orders=(), spaces=(), tickets=()):
    """建一个装满夹具数据的内存库，返回假会话"""
    engine = new_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if devices:
            conn.execute(DeviceResource.__table__.insert(), list(devices))
        if spaces:
            conn.execute(SpaceResource.__table__.insert(), list(spaces))
        if orders:
            conn.execute(ReserveOrder.__table__.insert(), list(orders))
        if tickets:
            conn.execute(RepairTicket.__table__.insert(), list(tickets))
    return FakeDashboardSession(engine)


# ============================================================
# 四、假 LLM 夹具（《规范》10.2：LLM 一律用假模型）
# ============================================================
class CountingFakeModel(FakeMessagesListChatModel):
    """
    带调用计数的假模型，用于断言「精确调了几次 LLM」。

    ⚠️ 计数点必须是 `_generate`：基类的 `_agenerate` 会委托回 `_generate`，
    两处都计数会让一次 `ainvoke` 记成 2 次（H1/H4/H5/H6 断言的正是精确次数）。

    ⚠️ 基类自带的 `i` 会**回绕**（第 3 次调用后 `i` 又回到 0），不能当计数器 ——
    这正是本子类存在的唯一原因。
    """
    calls: int = 0
    received: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.received.append(messages)          # 供断言「重试指令是否送达」
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class SlowFakeModel(FakeMessagesListChatModel):
    """
    同步 `_generate` 里睡一会儿，用来触发超时降级（D7/D8）。

    基类在 executor 里跑 `_generate`，**不会阻塞事件循环**，
    所以 `asyncio.wait_for` 能准时中断（实测 0.3s 超时于 0.31s 触发）。

    `delay` 只须**大于被测的超时值**即可，不必真的睡很久 ——
    `wait_for` 会准时返回，但 executor 里那个线程仍会把睡眠睡完，
    测试收尾时要等它，睡 5 秒会让这两条用例白等 10 秒。
    """
    delay: float = 5.0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        time.sleep(self.delay)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def fake_model(*responses):
    """按顺序返回响应的假模型；接受 str（自动包成 AIMessage）或现成的 AIMessage"""
    wrapped = [r if isinstance(r, AIMessage) else AIMessage(content=r) for r in responses]
    return CountingFakeModel(responses=wrapped)


def install_fake_llm(monkeypatch, model):
    """
    把 `_build_llm` 换成返回假模型。

    只替换「网络边界」这一处，三层容错 / 业务边界校验 / 降级逻辑全部走真代码。
    答辩若问「离线怎么测大模型逻辑」，答案就是这一行。
    """
    monkeypatch.setattr(ai_svc, "_build_llm", lambda: model)
    return model


def human_text(messages) -> str:
    """
    取 messages 里最后一条 human 消息的**纯文本**。

    ⚠️ 判断「提示词里有没有某段文字」时，**不要用 `str(messages)`**：
    那走的是 `repr`，而 `repr` 会把真实换行转义成 `\\n` 两个字符，
    于是任何**含换行**的子串都永远匹配不上。更糟的是负向断言
    （`assert X not in str(messages)`）会因此**恒真假通过**。

    2026-09-27 自测时踩到：H1/H6 的「首轮不带重试指令」因 `_RETRY_INSTRUCTION`
    以 `\n\n` 开头而假通过，直到 H4 的正向断言（「第二轮必须收到重试指令」）失败才暴露。
    —— 这也是 docs/test.md 里 H4 用正向断言的价值。
    """
    for message in reversed(list(messages)):
        content = getattr(message, "content", message)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return ""


def suggestions_text(*rows) -> str:
    """拼一段合法的模型返回文本（纯 JSON，第 2 层 json.loads 可解析）

    用法：suggestions_text(("finding", "evidence", "suggestion"), ...)
    """
    items = [
        {"finding": f, "evidence": e, "suggestion": s}
        for f, e, s in rows
    ]
    return json.dumps({"suggestions": items}, ensure_ascii=False)
