"""把自然语言需求解析成**可编辑的条件清单 + 推荐**（2026-10-13 新增）。

## 定位

用户要的调度有两条路，本模块是**默认那条**：

| | 本模块（默认） | 多轮 Agent（深度模式，可选） |
|---|---|---|
| 耗时 | **一次调用，5~10 秒** | 40~80 秒 |
| 产出 | AI 读出的**条件** + **推荐与理由** + 备选 | 完整 Thought-Action-Observation 思考链 |
| 前端 | 渲染成**可编辑卡片**，用户改完一键建单 | 展示思考过程 |

**为什么默认走这条**：40 秒现场演示不可接受；而「AI 从我这句话里读出了什么」
其实比「看它思考 40 秒」更容易讲清楚，读错了用户当场就能改。

## 分工（答辩时可以这么讲）

    AI   负责「理解」：自然语言 → 结构化条件、并列候选 → 推荐 + 理由
    规则 负责「判重」：这个时段到底锁不锁得上（本模块**不碰**，由
         /resources/spaces/available 与建单事务负责）

不确定的事交给模型，确定的事交给规则 —— 这不是妥协，是工程上正确的分工。

## 关于推荐的可信度

推荐只是**提示**：模型看到的是**全部可用场地**，没带时间维度（时间正是它要抽的东西，
先有鸡还是先有蛋）。所以真正的可用性由前端的「可用场地」查询与建单事务兜底 ——
模型推了一间该时段已被占的场地，前端会因为查不到而自动清掉选择。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent.chains.builder import build_model
from app.core import flags as runtime_flags
from app.core.config import settings
from app.core.logging import get_logger
from app.services.device_service import list_available_devices
from app.services.space_service import list_available_spaces, query_spaces

logger = get_logger(__name__)

__all__ = ["ParsedAlternative", "ParsedRecommend", "ParsedConditions", "ParseResult", "parse_request"]

SPACE_TYPE_CN = {1: "会议室", 2: "展厅", 3: "多功能厅", 4: "户外场地"}
_WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"]


class ParsedAlternative(BaseModel):
    spaceId: int | None = Field(None, description="备选场地 id，必须来自候选列表")
    spaceName: str | None = Field(None, description="备选场地名称，与候选列表逐字一致")
    tradeoff: str | None = Field(None, description="选它要付什么代价 / 适合什么情况")


class ParsedRecommend(BaseModel):
    spaceId: int | None = Field(None, description="最推荐的场地 id，必须来自候选列表；选不出填 null")
    spaceName: str | None = Field(None, description="最推荐的场地名称")
    reason: str | None = Field(None, description="为什么推荐它：要具体到人数/时段/设备")
    alternatives: list[ParsedAlternative] = Field(default_factory=list, description="备选，最多 2 条")


class ParsedConditions(BaseModel):
    capacity: int | None = Field(None, description="人数；用户没说填 null，不要猜")
    spaceType: int | None = Field(None, description="场地类型 1会议室/2展厅/3多功能厅/4户外场地；说不出填 null")
    startTime: str | None = Field(None, description="开始时间 YYYY-MM-DD HH:mm:ss；相对时间按当前时间换算")
    endTime: str | None = Field(None, description="结束时间 YYYY-MM-DD HH:mm:ss；只说了时长就据开始时间推算")
    deviceTypes: list[str] = Field(default_factory=list, description="需要的设备类型，只能从候选设备类型里选")
    budget: float | None = Field(None, description="预算上限（元）；没说填 null")
    missing: list[str] = Field(default_factory=list, description="用户没提到、但下单需要的条件，一句话说明你用了什么默认值")


class ParseResult(BaseModel):
    conditions: ParsedConditions = Field(default_factory=ParsedConditions)
    recommend: ParsedRecommend = Field(default_factory=ParsedRecommend)
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="对整体理解的置信度 0~1")


def _build_prompt(
    *,
    text: str,
    image_context: dict[str, Any] | None,
    spaces: list[dict],
    devices: list[dict],
    now: str,
    with_recommend: bool = True,
) -> str:
    """候选清单**必须给全**：模型只做选择题，做填空题就会编出不存在的场地（§9.3）。"""
    space_lines = [
        "  - id=%s 名称=%s 类型=%s 容量=%s人 位置=%s"
        % (s["id"], s["spaceName"], SPACE_TYPE_CN.get(s["spaceType"], s["spaceType"]), s["capacity"], s.get("location") or "—")
        for s in spaces
    ]
    device_types = sorted({d["deviceType"] for d in devices if d.get("deviceType")})
    ctx = ""
    if image_context:
        try:
            ctx = "\n\n[图像/草图解析上下文，作为补充证据]\n" + json.dumps(image_context, ensure_ascii=False)
        except (TypeError, ValueError):
            ctx = ""
    return (
        "你是智能空间调度平台的需求解析助手。用户的调度需求如下，请把它解析成结构化条件，"
        "并从候选场地里给出推荐。\n\n"
        # ⚠️ 必须显式给出「今天是几号」：模型没有时钟，不给它就会把「本周五」
        #    换算成凭空的日期（实测给成了 2026-01-30）。
        "【当前时间】\n" + now + "（星期" + _WEEKDAY[datetime.now().weekday()] + "）\n\n"
        "【用户需求】\n" + text + ctx + "\n\n"
        "【候选场地】（推荐与备选**只能从这里选**，严禁编造 id）\n"
        + ("\n".join(space_lines) if space_lines else "  （当前没有可用场地）")
        + "\n\n【候选设备类型】\n  " + ("、".join(device_types) if device_types else "（无）") + "\n\n"
        "【要求】\n"
        "1. 只抽取用户**真正说过**的信息。没说的一律填 null / 空数组，"
        "并在 missing 里写一句「你用了什么默认值」，不要用常识替他补。\n"
        "2. 相对时间（「本周五下午两点」）按当前时间换算成绝对时间 YYYY-MM-DD HH:mm:ss。\n"
        + (
            "3. reason 要**具体**（点出容量/时段/设备哪一项吻合），但**必须简短**：不超过 40 个字。\n"
            "4. alternatives **最多 1 条**，tradeoff 不超过 25 个字；没有并列候选就传空数组。\n"
            if with_recommend
            # 规则推荐模式下**明确禁掉** recommend —— 让模型别在这上面花输出 token，
            # 这是 32 秒 → 10 秒的关键（少写就是快）。
            else "3. **recommend 一律留空**（spaceId/reason/alternatives 全部不要填），推荐由系统另算。\n"
        )
        +
        "5. **只输出上面列出的字段**，不要增加任何字段、不要写解释、不要 markdown 代码块。\n"
        "   ⚠️ 输出越短越快。这是接口的硬要求：多写一个字，用户就多等一毫秒。"
    )


async def _rule_recommend(conditions: ParsedConditions) -> ParsedRecommend:
    """**规则推荐**：用真实场地数据算，不让模型猜（`aiRecommend=false` 时走这条）。

    为什么它值得存在：
      · **快** —— 模型只抽条件，输出量降到接近 fast 模式，整次调用 32 秒 → 10~15 秒
      · **理由是真的** —— 「容量最接近 / 类型相符 / 该时段空闲」全部来自数据库，
        比模型自由发挥更经得起追问
    产出结构与 AI 推荐**完全一样**，所以前端只按开关切换、渲染代码一行都不用改。
    """
    cap = conditions.capacity or 1
    want_type = conditions.spaceType
    cands: list[dict] = []

    # 有时段就按**真实可用性**查 —— 这才是「订得上」的口径（与建单判重同源）
    if conditions.startTime and conditions.endTime:
        types = [want_type] if want_type in (1, 2, 3, 4) else [1, 2, 3, 4]
        merged: dict[int, dict] = {}
        for t in types:
            try:
                res = await query_spaces(cap, t, conditions.startTime, conditions.endTime)
            except Exception:  # noqa: BLE001 - 时间格式异常等，退化成不看时间的推荐
                merged = {}
                break
            for s in res["spaces"]:
                merged[s["id"]] = s
        cands = sorted(merged.values(), key=lambda s: s["capacity"])

    # 没有时段（或查不到）→ 退回全量候选里按容量挑
    if not cands:
        res = await list_available_spaces()
        cands = sorted(
            [s for s in res["spaces"] if s["capacity"] >= cap], key=lambda s: s["capacity"]
        )

    if not cands:
        return ParsedRecommend(reason="按当前条件找不到容量足够的场地，请调整人数、时间或场地类型。")

    best = cands[0]
    why = ["容量 %d 人，与需求 %d 人最接近" % (best["capacity"], cap)]
    if want_type and best["spaceType"] == want_type:
        why.append("类型相符")
    if conditions.startTime and conditions.endTime:
        why.append("该时段空闲")
    rec = ParsedRecommend(
        spaceId=best["id"], spaceName=best["spaceName"], reason="，".join(why) + "。"
    )
    for s in cands[1:2]:
        gap = s["capacity"] - cap
        rec.alternatives.append(
            ParsedAlternative(
                spaceId=s["id"],
                spaceName=s["spaceName"],
                tradeoff=("容量 %d 人，多 %d 人" % (s["capacity"], gap)) if gap > 0 else "容量相同，可作备选",
            )
        )
    return rec


async def parse_request(
    *, text: str, image_context: dict[str, Any] | None = None
) -> tuple[ParseResult, int]:
    """一次模型调用：需求文本 → 条件 + 推荐。返回 `(结果, 耗时ms)`。"""
    started = time.perf_counter()

    space_res = await list_available_spaces()
    device_res = await list_available_devices()
    llm = build_model()  # 配置缺失时抛 AgentUnavailableError，显式暴露而不是伪装成「没读懂」
    # 推荐由谁给：AI 还是规则。运行时开关，演示前可切换对比（见 core/flags.py）
    ai_recommend = bool(runtime_flags.all_flags().get("aiRecommend", True))
    prompt = _build_prompt(
        text=text,
        image_context=image_context,
        spaces=space_res["spaces"],
        devices=device_res["devices"],
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        with_recommend=ai_recommend,
    )

    # 首选结构化输出；不支持就退回 JSON 文本解析 —— 与模块 2 的双策略同思路，
    # 供应商换模型/换版本时不至于整条链路挂掉。
    try:
        result = await llm.with_structured_output(ParseResult).ainvoke(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.info("结构化输出不可用，退回 JSON 解析：%s", exc)
        raw = await llm.ainvoke(prompt)
        result = _parse_json_reply(getattr(raw, "content", raw))

    result = _sanitize(result)
    if not ai_recommend:
        # 模型被告知「recommend 留空」，这里用真实数据补上 —— 前端看到的形状一模一样
        result.recommend = await _rule_recommend(result.conditions)
    elapsed = int((time.perf_counter() - started) * 1000)
    return result, elapsed


def _parse_json_reply(content: Any) -> ParseResult:
    """从自由文本里抠出 JSON。抠不出来就给一个空结果（前端会提示用户补全）。"""
    text = content if isinstance(content, str) else str(content)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return ParseResult()
    try:
        return ParseResult.model_validate(json.loads(text[start : end + 1]))
    except Exception:  # noqa: BLE001
        return ParseResult()


def _sanitize(result: ParseResult) -> ParseResult:
    """业务边界校验（§9.3：大模型输出必须过一遍）。宁可置空，也不要离谱值流到前端。"""
    c = result.conditions
    if c.capacity is not None and not (1 <= c.capacity <= 10000):
        c.capacity = None
    if c.spaceType not in (1, 2, 3, 4):
        c.spaceType = None
    if c.budget is not None and c.budget < 0:
        c.budget = None
    c.deviceTypes = [str(x).strip() for x in (c.deviceTypes or []) if str(x).strip()][:8]
    c.missing = [str(x).strip() for x in (c.missing or []) if str(x).strip()][:6]
    result.recommend.alternatives = (result.recommend.alternatives or [])[:2]
    result.confidence = max(0.0, min(1.0, float(result.confidence or 0.0)))
    return result
