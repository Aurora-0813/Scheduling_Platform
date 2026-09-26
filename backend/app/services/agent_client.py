"""调度 Agent 客户端（mock 实现 + 真实接口占位）。

- 未配置 AGENT_URL 或调用失败时走 mock 调度器，保证模块可独立演示。
- 返回结构严格对齐团队 `docs/api.md` 模块 4 的**冻结契约**：
  `{plan, backupPlan, trace, needConfirm}`，其中 `trace` 是 **TraceStep 对象数组**
  （`step` / `result` / `timestamp` / `thought` / `action` / `actionInput` / `observation`），
  各步 `timestamp` 互不相同且递增，前端按它做时间轴回放。
  契约定义见 `app/schemas/agent.py`，本模块不自建 Agent 契约。
- mock 接收「已占用时段」作为输入，模拟 Agent 调 Tool 查询真实占用后动态挑空闲时段，
  避免与既有订单冲突（贴合「Agent 只调 Tool 查真实数据」§9.3）。
- 本模块不直连 LangChain，统一经此入口 HTTP 调用队友 Agent 服务。
"""
from datetime import datetime, timedelta

from ..core.config import AGENT_URL

#: mock 调度器固定选用的场地 ID（真实 Agent 由 Tool 查询决定）
MOCK_SPACE_ID = 1
#: trace 各步之间的时间间隔（秒），仅用于 mock 生成互不相同且递增的时间戳
_TRACE_STEP_SECONDS = 3


def _post_json(url: str, payload: dict, timeout: float = 5.0) -> dict | None:
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx 是硬依赖，此分支仅防御性存在
        return None
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _is_free(start: datetime, end: datetime, occupied: list) -> bool:
    for s, e in occupied:
        if start < e and end > s:
            return False
    return True


def _next_free(base: datetime, occupied: list) -> datetime:
    """从 base 起逐小时寻找第一个空闲时段，最多向后找 8 小时。"""
    cur = base
    for _ in range(8):
        if _is_free(cur, cur + timedelta(hours=1), occupied):
            return cur
        cur += timedelta(hours=1)
    return base  # 兜底：全忙则仍返回基准时间


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _mock_schedule(
    requirement: str, occupied: list, space_name: str | None = None
) -> dict:
    base = (datetime.now() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    start1 = _next_free(base, occupied)
    end1 = start1 + timedelta(hours=1)
    start2 = _next_free(end1, occupied)
    end2 = start2 + timedelta(hours=1)

    name = space_name or f"场地#{MOCK_SPACE_ID}"

    # 冻结契约要求：trace 是对象数组，且各步 timestamp 互不相同、递增。
    # 时间点取「本次请求时刻 + 递增间隔」，与团队 api.md 的响应示例口径一致
    # （思考发生在请求当下，plan 指向未来时段）。
    t0 = datetime.now()

    def _ts(offset: int) -> str:
        return _fmt(t0 + timedelta(seconds=offset))

    trace = [
        {
            "step": 1,
            "result": f"解析需求：{requirement}",
            "timestamp": _ts(0),
            "thought": "先确认人数、时间与设备三方面约束",
            "action": None,
            "actionInput": None,
            "observation": None,
        },
        {
            "step": 2,
            "result": "查询可用场地与设备资源",
            "timestamp": _ts(_TRACE_STEP_SECONDS),
            "thought": "按需求条件检索候选场地与设备",
            "action": "query_spaces",
            "actionInput": {"start_time": _fmt(start1), "end_time": _fmt(end1)},
            "observation": {"spaceId": MOCK_SPACE_ID, "spaceName": name},
        },
        {
            "step": 3,
            "result": "检测时段冲突，进行方案权衡",
            "timestamp": _ts(_TRACE_STEP_SECONDS * 2),
            "thought": f"已排除 {len(occupied)} 条占用时段记录",
            "action": "check_conflict",
            "actionInput": {"start_time": _fmt(start1), "end_time": _fmt(end1)},
            "observation": {"occupied": len(occupied)},
        },
        {
            "step": 4,
            "result": "生成主方案与备方案",
            "timestamp": _ts(_TRACE_STEP_SECONDS * 3),
            "thought": "主方案取最近空闲时段，备方案顺延一小时",
            "action": None,
            "actionInput": None,
            "observation": None,
        },
    ]
    plan = {
        "spaceId": MOCK_SPACE_ID,
        "spaceName": name,
        "deviceIds": [1],
        "startTime": _fmt(start1),
        "endTime": _fmt(end1),
        "reason": "场地空闲，满足需求",
    }
    backup_plan = {
        "spaceId": MOCK_SPACE_ID,
        "spaceName": name,
        "deviceIds": [1],
        "startTime": _fmt(start2),
        "endTime": _fmt(end2),
        "reason": "避开繁忙时段",
    }
    return {
        "plan": plan,
        "backupPlan": backup_plan,
        "trace": trace,
        "needConfirm": True,
    }


def schedule(
    requirement: str, occupied: list | None = None, space_name: str | None = None
) -> dict:
    """提交需求，返回 {plan, backupPlan, trace, needConfirm}（团队冻结契约 §5.3 模块4）。

    occupied: [(start_time, end_time), ...] 已占用时段，用于 mock 避让。
    space_name: mock 所选场地的真实名称；由调用方查库传入，避免 mock 编造场地名
                （真实 Agent 自行经 Tool 获取，此参数不参与远端调用）。
    """
    occupied = occupied or []

    # 真实接口：AGENT_URL 配置且可用则优先（身份从 JWT 解析，不随请求体传 §5.1）
    if AGENT_URL:
        data = _post_json(
            f"{AGENT_URL.rstrip('/')}/schedule",
            {"text": requirement, "imageContext": {}},
        )
        if data:
            return data

    # 降级 mock
    return _mock_schedule(requirement, occupied, space_name)


def transcribe_audio(audio_bytes: bytes) -> str:
    """语音转写占位：真实 ASR 由队友语音模块接入。"""
    return "帮我预约一个明天上午的会议室"


def recognize_image(image_bytes: bytes) -> str:
    """图像多模态识别占位：真实识别由队友视觉模块接入。"""
    return "识别到会议室预约需求：预订一间可容纳 5 人的会议室"
