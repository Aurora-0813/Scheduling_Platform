"""
AI 数据洞察面板 - 报告生成服务

对应文档：《规范》5.3 模块 8（接口契约）、4.2（移除 AI 后降级为纯统计）、
        4.4 模块 8（三要素结构化建议）、7.4（AI 代码规范）、
        9.3（大模型输出业务边界校验）、13（风险表）

设计要点：
- 全异步：一律 await ainvoke()，禁止同步 invoke()（《规范》3.3）
- 8 秒总超时，超时即降级（演示脚本第 4 屏只有 20s 预算）
- JSON 三层容错：with_structured_output → json.loads → 正则抠块 → 模板降级
  每层失败都 log，便于排错和答辩溯源
- 任何情况下都返回 200 与可用的三要素建议：不返回空数组、不抛 500
- 降级不是「空」，而是用 stats 里的真实数字模板化成 finding/evidence/suggestion
- 业务边界校验（《规范》9.3）：stats 里的数字是白名单，AI 输出引用了白名单外的
  数字即判定为幻觉并丢弃该条；全部被丢弃时走降级（见 _filter_by_business_bounds）

注：Prompt 目前内联在本模块（本次交付范围限定为
    services/dashboard_ai_service.py + api/dashboard.py）。
    《规范》7.4 要求 Prompt 集中管理，待 agent/ 目录建好后迁至
    app/agent/prompts/。
"""
import asyncio
import json
import logging
import re
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import dashboard_export_service, dashboard_service

logger = logging.getLogger(__name__)


def _json_default(value):
    """`json.dumps` 的兜底编码器：把 `Decimal` 编成 float。

    为什么需要它（2026-09-29 实测踩到）
    ----------------------------------
    `_invoke_llm` 要把 stats 塞进 Prompt，用的是 `json.dumps(stats)`。
    而 `get_device_idle_rate` 在 **MySQL** 上返回 `Decimal`（`SUM()` 是 DECIMAL），
    `json.dumps` 不认识它 → 抛 `TypeError: Object of type Decimal is not JSON serializable`
    → 被 `generate_report` 的外层 except 收成「走纯统计降级」。

    表现是：**根本没调到大模型**，页面上却是一份看起来像模像样的报告
    （规则模板拼的），只有 `degraded=true` 一个字段在提示异常 ——
    而它太容易被读成「模型不稳定」，导致真因被掩盖。

    根因已在 `dashboard_service` 修掉（返回 float）。这里再兜一层是**防复发**：
    以后统计口径再加字段时，不会因为一个 Decimal 又把整份 AI 报告打回降级。
    """
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


# LLM 超时（秒）。超时即走纯统计降级。
#
# ⚠️ **2026-09-29：由硬编码 8 秒改为跟随 `settings.LLM_TIMEOUT`。**
#
# 原来写死 8 秒，理由是「演示脚本第 4 屏只有 20s 预算」。但它**同时**被用作
# `ChatOpenAI` 的 HTTP 超时（见下方 `_build_llm`），而真模型根本来不及 ——
# 实测 `qwen3.7-flash` 生成这份报告需要 **51.6 秒**；8 秒下三层容错各自超时、
# 合计 16.7 秒后抛 `_LLMUnavailable`，**整份报告静默降级成规则模板**。
#
# 这个失败方式极具误导性：页面上仍有一份「看起来像模像样」的报告，
# 只有 `degraded=true` 一个字段在提示异常，极易被读成「模型不稳定」。
# 实测定位过程见 `docs/spec/后端改动1.md` §5.18。
#
# 现在跟随 `.env` 的 `LLM_TIMEOUT`（当前 60），与其它 LLM 配置同一口径；
# 需要为演示压缩预算时改 `.env` 即可，不必改代码。
#
# 注：`tests/test_ai_resilience.py` 用 `monkeypatch.setattr(ai_svc,
# "LLM_TIMEOUT_SECONDS", 0.2)` 驱动超时分支 —— 它在本模块**被调用时**读取该全局变量，
# 所以把值来源换成 settings 不影响那些用例。
LLM_TIMEOUT_SECONDS = float(settings.LLM_TIMEOUT)

# 单次报告最多返回的建议条数
MAX_SUGGESTIONS = 5

# ---------- 业务边界校验（《规范》9.3「大模型输出必须做业务边界校验」）----------
# 开启后：把 stats 里的所有数字收集成白名单，逐条校验 AI 输出中的
# finding / evidence 是否只引用了白名单内的数字；引用了白名单外的数字，
# 说明模型在编造数据，该条建议被丢弃（详见 _filter_by_business_bounds）。
HALLUCINATION_CHECK_ENABLED = True

# 全部建议都被判定为幻觉时，是否重试一次（《开发计划》阶段 2 第 5 条）。
# 默认关闭，原因是演示预算：
#   演示脚本第 4 屏给 /report 的总预算是 20s，超时上限 8s。
#   开启重试最坏情况 = 8s（首次超时）+ 8s（重试）= 16s，加上取数与序列化，
#   会吃掉几乎整个预算，风险大于收益。
# 若答辩环境 LLM 稳定、想更严格，把它改成 True 即可（无需改其他代码）。
HALLUCINATION_RETRY_ENABLED = False

# 重试时的追加指令：明确告诉模型上一轮错在哪
_RETRY_INSTRUCTION = (
    "\n\n【重要】上一次输出中的部分数字并未出现在上面的统计数据里。"
    "请重新输出，evidence 中**只能引用上面 JSON 中确实存在的数字**，"
    "绝对不要自行计算或推演出新的数字。"
)


# ============ 1. 结构化输出用的内部模型 ============
# 仅供 with_structured_output 使用，不对外暴露，故不放入 schemas/
# （《规范》4.4 模块 8：每条建议必须同时具备三要素）
class _Suggestion(BaseModel):
    """单条数据洞察建议，三要素缺一不可"""
    finding: str = Field(description="发现的事实，必须包含具体数字")
    evidence: str = Field(description="数据依据，引用统计结果中的真实数字")
    suggestion: str = Field(description="可执行的建议动作")


class _ReportSuggestions(BaseModel):
    """报告建议集合"""
    suggestions: list[_Suggestion] = Field(description="3 到 5 条数据洞察建议")


# ============ 2. Prompt ============
# TODO(迁移点): 《规范》7.3 / 7.4 要求 Prompt 集中管理在 app/agent/prompts/。
#   本模块的 _SYSTEM_PROMPT 与 _USER_PROMPT_TEMPLATE 是唯一需要迁走的内容，
#   迁移时只需把下面两个常量移到 app/agent/prompts/dashboard_report.py 并改为导入，
#   其余逻辑（三层容错、超时、降级）不动。
#   当前内联的原因：agent/ 目录尚未建立，且属核心调度 Agent 负责人范畴。
_SYSTEM_PROMPT = (
    "你是企业空间与设备调度平台的数据分析助手。"
    "你只能依据用户提供的统计数据作答，严禁编造统计中不存在的场地、设备或数字。"
    "每条建议必须包含三个字段：finding（事实，含具体数字）、"
    "evidence（数据依据，引用统计中的真实数字）、suggestion（可执行动作）。"
)

_USER_PROMPT_TEMPLATE = """以下是近 {days} 天的平台运营统计数据（JSON）：

{stats_json}

请据此输出 {max_suggestions} 条以内的数据洞察建议，每条包含 finding、evidence、suggestion 三个字段。
要求：
1. finding 只陈述事实，必须带具体数字
2. evidence 必须引用上面 JSON 中出现过的数字，不得虚构；
   引用时请**原样照抄**（保留原有小数位），不要自行四舍五入或换算精度 ——
   例如 JSON 里是 46.7 就写 46.7，不要写成 47
3. suggestion 必须是可执行的具体动作
4. 仅输出 JSON，格式为 {{"suggestions": [{{"finding": "...", "evidence": "...", "suggestion": "..."}}]}}
"""


# ============ 3. 异常定义 ============
class _LLMUnavailable(Exception):
    """LLM 任一环节不可用（无 key、网络失败、解析失败），调用方据此走降级"""
    pass


# ============ 4. 工具函数 ============
def _num(value):
    """把统计值转成 float；无法转换时返回 None"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _content_to_text(message) -> str:
    """
    从 AIMessage 取出纯文本。
    content 可能是 str，也可能是 [{"type": "text", "text": "..."}] 形式的分块。
    """
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return "" if content is None else str(content)


_FENCED_JSON = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _extract_json_block(text: str) -> str:
    """第 3 层容错：从自由文本里抠出 JSON。先找 ```json 围栏，再退到最外层括号"""
    if not text:
        return ""
    match = _FENCED_JSON.search(text)
    if match:
        return match.group(1).strip()
    for open_char, close_char in (("[", "]"), ("{", "}")):
        start = text.find(open_char)
        end = text.rfind(close_char)
        if start != -1 and end > start:
            return text[start:end + 1]
    return ""


def _normalize(payload) -> list:
    """
    把任意形态的解析结果规整成 [{"finding","evidence","suggestion"}, ...]。
    三要素缺一即丢弃该条（《规范》4.4 模块 8 强制三要素）。
    """
    if isinstance(payload, dict):
        payload = payload.get("suggestions", [payload])
    if not isinstance(payload, list):
        return []

    result = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        row = {}
        for key in ("finding", "evidence", "suggestion"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                row = None
                break
            row[key] = value.strip()
        if row:
            result.append(row)
        if len(result) >= MAX_SUGGESTIONS:
            break
    return result


# ============ 4.5 业务边界校验（《规范》9.3） ============
# 思路：stats 里的数字是唯一事实来源，AI 输出只能引用它们。
# 把 stats 递归展开成白名单，再逐个比对 AI 文字里的数字。
#
# 为什么这样能防幻觉：
#   模型编造数字时，编出来的值（如「使用率 85%」而实际是 20%）几乎不可能
#   恰好命中 stats 中的某个值，因此会被抓住并丢弃该条建议。
#
# 已知取舍（宁可少给也不编造）：
#   模型**自行推算**的数字（如「5 条预约占 3 条，即 60%」中的 60%）也不在白名单内，
#   会被判定为幻觉。这是刻意的：规范要求「业务边界校验」，而模型算出来的比例
#   无法验证对错，放行等于把校验做空。代价是可能丢弃个别合理的推算 ——
#   这类情况会记 warning 日志（含被拒数字），便于事后调整白名单策略。

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")


def _collect_allowed_numbers(stats, days: int) -> set:
    """
    把 stats 递归展开成「允许出现的数字」白名单。

    ⚠️ 变体只能加在**白名单这一侧**，绝不能反过来把待校验的数字四舍五入后
    再来比对 —— 那等于给每个允许值开了 ±0.5 的口子：白名单里有 3（某设备
    故障 3 单），编造的「闲置率 3.2%」会被 round(3.2) == 3 放行。
    （2026-09-27 自测发现，已修正；`_is_allowed` 现按容差比对而非取整。）

    收录的写法变体：
    - 原值本身（统计值出库前已 round 到 1 位小数，模型照抄必然精确相等）
    - 整数写法：仅当原值本就是整数时才收录，避免 46.7 被"约等于"成 47
    - 分数 ↔ 百分比：46.7 也允许写成 0.467；0.2 也允许写成 20
      （纯换算，不引入新信息）
    """
    allowed = set()

    def _add(value):
        num = _num(value)
        if num is None:
            return
        allowed.add(num)
        if float(num).is_integer():
            allowed.add(float(int(num)))
        # 比例/百分比两种写法互通
        if 0 <= num <= 1:
            allowed.add(round(num * 100, 1))
            allowed.add(round(num * 100, 0))
        if 0 <= num <= 100:
            allowed.add(round(num / 100, 3))

    def _walk(node):
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple, set)):
            for v in node:
                _walk(v)
        else:
            _add(node)

    _walk(stats)
    _add(days)          # 「近 7 天」里的 7
    return allowed


def _extract_numbers(text: str) -> list:
    """
    取出文本里的数字。HH:MM 形式的时间只取小时部分，
    否则 "14:00" 会被拆成 14 和 0 两个数字，0 通常不在白名单里，造成误判。
    """
    if not text:
        return []
    normalized = _TIME_RE.sub(lambda m: m.group(0).split(":")[0], text)
    return [float(m) for m in _NUMBER_RE.findall(normalized)]


def _is_allowed(num: float, allowed: set) -> bool:
    """
    白名单里存在与 num 相等的值（容差仅吸收浮点误差，不放宽到"近似"）。

    对比在数值上做，而不是把 num 取整后去 in allowed —— 后者会把 3.2 判成 3。
    """
    return any(abs(num - cand) <= 1e-6 * max(1.0, abs(cand)) for cand in allowed)


def _unverified_numbers(text: str, allowed: set) -> list:
    """返回 text 中无据可依的数字列表（空列表 = 通过校验）"""
    return [n for n in _extract_numbers(text) if not _is_allowed(n, allowed)]


def _filter_by_business_bounds(suggestions: list, stats: dict, days: int):
    """
    逐条校验建议。返回 (通过的建议, 被丢弃的 [(建议, 可疑数字), ...])。

    校验范围是 finding 与 evidence —— 这两个字段断言「事实」；
    suggestion 是行动建议，其中的数字（如「避开 14:00 时段」）来自 finding，
    已在 finding 中校验过，故不重复校验。
    """
    if not HALLUCINATION_CHECK_ENABLED:
        return suggestions, []

    allowed = _collect_allowed_numbers(stats, days)
    kept, dropped = [], []
    for item in suggestions:
        bad = (_unverified_numbers(item.get("finding", ""), allowed)
               + _unverified_numbers(item.get("evidence", ""), allowed))
        if bad:
            dropped.append((item, bad))
        else:
            kept.append(item)

    for item, bad in dropped:
        logger.warning(
            "report: 建议未通过业务边界校验（数字 %s 不在统计结果中），已丢弃: %s",
            bad, item.get("finding", "")[:60],
        )
    return kept, dropped


# ============ 5. LLM 调用（三层容错） ============
def _build_llm():
    """
    构造 ChatOpenAI。api_key 必须显式传入 ——
    否则 ChatOpenAI 会隐式读环境变量 OPENAI_API_KEY，可能连到非预期账号。
    langchain 相关依赖延迟导入：缺失时走降级，而不是让整个应用起不来。
    """
    if not settings.LLM_API_KEY:
        raise _LLMUnavailable("未配置 LLM_API_KEY，跳过大模型调用")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise _LLMUnavailable(f"langchain-openai 未安装: {e}") from e

    try:
        return ChatOpenAI(
            model=settings.LLM_MODEL_NAME or "gpt-4o-mini",
            api_key=settings.LLM_API_KEY,          # 显式传入，不依赖环境变量
            base_url=settings.LLM_BASE_URL or None,
            temperature=0.2,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,                         # 重试交给上层降级，避免叠加超时
        )
    except Exception as e:
        raise _LLMUnavailable(f"ChatOpenAI 初始化失败: {type(e).__name__}: {e}") from e


async def _invoke_llm(stats: dict, days: int, extra_instruction: str = "") -> list:
    """
    三层 JSON 容错调用大模型。任一层成功即返回，全部失败抛 _LLMUnavailable。
    每层失败都 log。

    extra_instruction：追加到用户提示末尾（用于幻觉校验失败后的重试，
    见 HALLUCINATION_RETRY_ENABLED）。
    """
    llm = _build_llm()
    messages = [
        ("system", _SYSTEM_PROMPT),
        ("human", _USER_PROMPT_TEMPLATE.format(
            days=days,
            stats_json=json.dumps(stats, ensure_ascii=False, indent=2, default=_json_default),
            max_suggestions=MAX_SUGGESTIONS,
        ) + extra_instruction),
    ]

    # ---------- 第 1 层：with_structured_output（function calling） ----------
    try:
        # method 必须显式指定：langchain-openai 1.5.0 起默认值是 "json_schema"，
        # 而 DashScope 的 OpenAI 兼容模式对 qwen-plus **只支持 json_object、不支持 json_schema**
        # （传了可能被忽略、也可能报错）。default 若不显式覆盖，第 1 层在真模型上会失败，
        # 每个请求白付一次失败调用 —— 8s 超时包着整个 _invoke_llm，
        # 两次串联可能超时，表现为「假性 degraded=true」，会被误读成模型不稳定。
        # function calling 是 qwen-plus 明确支持的（徐川 2026-09-27 LLM 配置定案实测确认），
        # 且比 json_mode 强：有 schema 强约束。
        structured = llm.with_structured_output(
            _ReportSuggestions, method="function_calling"
        )
        result = await structured.ainvoke(messages)
        items = _normalize(
            result.model_dump() if hasattr(result, "model_dump") else result
        )
        if items:
            logger.info("report: 第 1 层 with_structured_output 成功，%d 条", len(items))
            return items
        logger.warning("report: 第 1 层 with_structured_output 返回空或三要素不全")
    except Exception as e:
        logger.warning("report: 第 1 层 with_structured_output 失败: %s: %s",
                       type(e).__name__, e)

    # ---------- 第 2 层：裸调用 + json.loads ----------
    text = ""
    try:
        raw = await llm.ainvoke(messages)
        text = _content_to_text(raw)
        items = _normalize(json.loads(text))
        if items:
            logger.info("report: 第 2 层 json.loads 成功，%d 条", len(items))
            return items
        logger.warning("report: 第 2 层 json.loads 解析成功但三要素不全")
    except Exception as e:
        logger.warning("report: 第 2 层裸调用或 json.loads 失败: %s: %s",
                       type(e).__name__, e)

    # ---------- 第 3 层：正则抠 JSON 块 ----------
    if text:
        block = _extract_json_block(text)
        if block:
            try:
                items = _normalize(json.loads(block))
                if items:
                    logger.info("report: 第 3 层正则抠块成功，%d 条", len(items))
                    return items
                logger.warning("report: 第 3 层正则抠块解析成功但三要素不全")
            except Exception as e:
                logger.warning("report: 第 3 层正则抠块解析失败: %s: %s",
                               type(e).__name__, e)
        else:
            logger.warning("report: 第 3 层未在返回文本中找到 JSON 块")
    else:
        logger.warning("report: 第 2 层未取得文本，跳过第 3 层")

    raise _LLMUnavailable("JSON 三层容错全部失败")


# ============ 6. 纯统计降级（《规范》4.2） ============
def _has_window_data(stats: dict) -> bool:
    """
    判断窗口内是否真的有业务数据。
    用 peakHours / faultFrequency 作代理指标 —— 它们由订单和工单聚合而来，
    为空说明窗口内没有已确认预约或故障记录。

    为什么必须有这个前置判断：
    窗口内无数据时，spaceUsageRate 会是 0、deviceIdleRate 会是 100，
    纯看数字会被规则判定成「使用率 0%，严重闲置」并给出一串优化建议 ——
    但「没有数据」和「资源闲置」是两回事，前者是数据缺失，后者是业务结论。
    直接按数字输出会误导使用者，也与《规范》9.3「防止 AI 幻觉」的精神相悖
    （据空数据编出业务结论，本质是同一种幻觉）。
    因此无数据时只输出一条「数据不足」的说明，不输出任何统计结论。
    """
    return bool(stats.get("peakHours") or stats.get("faultFrequency"))


def _degraded_suggestions(stats: dict, days: int = dashboard_service.DEFAULT_DAYS) -> list:
    """
    纯统计降级：不调用大模型，完全基于 stats 的真实数字模板化生成三要素建议。

    《规范》4.2：本模块移除 AI 后应「降级为纯统计」，因此这条路径是必交能力，
    不是异常兜底。LLM 不可用 / 超时 / JSON 解析失败时都会走到这里。

    设计前提：**stats 必须是有效取数结果**。本函数只在「取数成功但 LLM 不可用」
    时被调用，每个数字都来自数据库聚合，可安全引用。
    取数本身失败（数据库不可达）时不走这里 —— 见 generate_report 中
    「取数失败」分支，那里刻意不输出任何统计数字。
    即：**宁可不给数字，也不编造数字**（《规范》9.3 防止 AI 幻觉）。
    """
    usage = _num(stats.get("spaceUsageRate"))
    idle = _num(stats.get("deviceIdleRate"))
    peaks = stats.get("peakHours") or []
    faults = stats.get("faultFrequency") or []

    # 窗口内没有业务数据时，不输出「严重闲置」这类会误导的结论
    if not _has_window_data(stats):
        return [{
            "finding": f"近 {days} 天窗口内没有已确认预约与故障记录",
            "evidence": (
                f"统计结果：场地使用率 {usage}%、设备闲置率 {idle}%、"
                f"高峰时段 0 项、故障频次 0 项"
            ),
            "suggestion": (
                "建议确认种子数据是否已导入（docs/seed.sql），"
                "或将统计周期调整为更长的区间后重试"
            ),
        }]

    suggestions = []

    # 1. 场地使用率
    if usage is not None:
        if usage >= 85:
            suggestions.append({
                "finding": f"近 {days} 天场地使用率 {usage}%，接近饱和",
                "evidence": f"已确认预约占用时长达到场地开放总时长的 {usage}%",
                "suggestion": "建议将部分活动疏导至使用率较低的时段，或增开备用场地",
            })
        elif usage <= 30:
            suggestions.append({
                "finding": f"近 {days} 天场地使用率仅 {usage}%，存在闲置",
                "evidence": f"已确认预约占用时长只占场地开放总时长的 {usage}%",
                "suggestion": "建议将活动向低峰时段集中，释放的场地可临时停用以节省运维成本",
            })

    # 2. 设备闲置率
    if idle is not None and idle >= 60:
        suggestions.append({
            "finding": f"设备闲置率 {idle}%，大量设备未被预约使用",
            "evidence": f"近 {days} 天内被预约订单引用的设备只占登记总量的一小部分，闲置率 {idle}%",
            "suggestion": "建议核查高闲置设备的配置必要性，或将闲置设备调拨至高频使用区域",
        })

    # 3. 高峰时段
    if peaks:
        top = peaks[0]
        hour = top.get("hour")
        count = top.get("count")
        suggestions.append({
            "finding": f"{hour}:00 前后是预约最高峰，共 {count} 条预约",
            "evidence": f"近 {days} 天按小时统计的预约次数中，{hour} 点以 {count} 条居首",
            "suggestion": f"建议将非紧急活动避开 {hour}:00 时段，改约至统计中的低谷时段",
        })

    # 4. 设备故障频次
    if faults:
        top = faults[0]
        name = top.get("deviceName")
        count = top.get("count")
        suggestions.append({
            "finding": f"设备「{name}」故障工单最多，共 {count} 单",
            "evidence": f"近 {days} 天维修工单按设备聚合，{name} 以 {count} 单排第一",
            "suggestion": f"建议优先排查「{name}」的故障根因，必要时安排整体更换或加装备机",
        })

    return suggestions[:MAX_SUGGESTIONS]


# ============ 7. 对外入口 ============
async def generate_report(
    db: AsyncSession,
    days: int = dashboard_service.DEFAULT_DAYS,
) -> dict:
    """
    生成数据洞察报告，返回《规范》5.3 模块 8 的 data 结构：

        {"suggestions": [...], "exportUrl": str | None, "degraded": bool}

    - suggestions：3–5 条三要素建议，**永不为空数组**
    - exportUrl：CSV 报告的**相对路径**（如 `/static/exports/dashboard_20260927_194500.csv`）。
      两种情况下为 None：① 数据库不可达（无 stats 可导出，直接 return，不走收尾步骤）
      ② 写盘失败（磁盘满 / 无权限）—— 见下方的 `_finalize`
    - degraded：本次是否走了纯统计降级（我额外加的字段，见下方说明）

    本函数不抛异常：LLM 不可用、超时、数据库不可达、**导出写盘失败**都各自降级，
    保证演示时不会出现 500 或空白页面（《规范》13.1 演示应急预案）。
    """
    # ---------- 取数：数据库不可达时也要能返回 200 ----------
    # 刻意不调用 _degraded_suggestions：那条路径会引用 stats 里的数字，
    # 而此处 stats 根本不存在。若强行传空 dict 进去，模板会产出
    # 「场地使用率 0%」「设备闲置率 100%」这类**看似具体、实则编造**的数字 ——
    # 使用者无法分辨这是真实统计还是取数失败，比直接说"不可用"危险得多。
    # 故此分支只陈述失败事实（evidence 写真实异常类型），不输出任何统计数字。
    # 取舍：宁可少给信息，也不编造数据（《规范》9.3 防止 AI 幻觉）。
    try:
        stats = await dashboard_service.get_all_stats(db, days)
    except Exception as e:
        logger.exception("report: 读取统计数据失败，降级为数据源不可用提示")
        return {
            "suggestions": [{
                "finding": "统计数据当前不可用，无法生成数据洞察",
                "evidence": f"读取统计接口失败：{type(e).__name__}",
                "suggestion": "请检查数据库连接（.env 中 DB_HOST / DB_PORT）后重试",
            }],
            "exportUrl": None,
            "degraded": True,
        }

    # ---------- 收尾：写 CSV 报告并填 exportUrl（阶段 3） ----------
    # 只做「写 CSV + 填 exportUrl」，不参与建议的生成与校验 ——
    # AI 容错与业务边界校验（下方）的逻辑不受此步骤影响。
    #
    # ⚠️ 关键是 stats 用**上面刚取到的那一份**：CSV 里的统计数字与 AI 建议的依据
    #    因此必然同源。若改成在这里重新调 get_all_stats()，两次取数之间若有写入，
    #    就会出现「建议说 46.7%、导出表格写 48.2%」的自相矛盾报告。
    async def _finalize(items: list, is_degraded: bool) -> dict:
        export_url = None
        try:
            export_url = await dashboard_export_service.write_report_csv(
                stats, items, days, is_degraded
            )
        except Exception as e:
            # 磁盘满 / 无权限 / 目录不可写 —— 导出失败不能让整份报告失败，
            # 但也不能静默吞掉，否则「导出按钮一直是灰的」会无从排查
            logger.warning("report: 导出 CSV 失败，exportUrl 置空: %s: %s", type(e).__name__, e)
        return {"suggestions": items, "exportUrl": export_url, "degraded": is_degraded}

    # ---------- 调用大模型，失败即纯统计降级 ----------
    try:
        suggestions = await asyncio.wait_for(
            _invoke_llm(stats, days), timeout=LLM_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("report: LLM 调用超过 %s 秒，走纯统计降级", LLM_TIMEOUT_SECONDS)
        return await _finalize(_degraded_suggestions(stats, days), True)
    except _LLMUnavailable as e:
        logger.warning("report: LLM 不可用，走纯统计降级: %s", e)
        return await _finalize(_degraded_suggestions(stats, days), True)
    except Exception as e:
        logger.exception("report: 调用大模型出现未预期异常，走纯统计降级: %s", e)
        return await _finalize(_degraded_suggestions(stats, days), True)

    # ---------- 业务边界校验（《规范》9.3），拦不住就走降级 ----------
    kept, dropped = _filter_by_business_bounds(suggestions, stats, days)
    if kept:
        return await _finalize(kept, False)

    logger.warning(
        "report: %d 条建议全部未通过业务边界校验（疑似幻觉），%s",
        len(dropped), "尝试重试一次" if HALLUCINATION_RETRY_ENABLED else "直接走纯统计降级",
    )

    if HALLUCINATION_RETRY_ENABLED:
        try:
            retry_raw = await asyncio.wait_for(
                _invoke_llm(stats, days, extra_instruction=_RETRY_INSTRUCTION),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            kept2, _ = _filter_by_business_bounds(retry_raw, stats, days)
            if kept2:
                logger.info("report: 重试后通过业务边界校验，%d 条", len(kept2))
                return await _finalize(kept2, False)
            logger.warning("report: 重试后仍未通过业务边界校验，走纯统计降级")
        except Exception as e:
            logger.warning("report: 重试失败，走纯统计降级: %s: %s", type(e).__name__, e)

    # 降级建议的数字全部取自 stats，天然通过业务边界校验
    return await _finalize(_degraded_suggestions(stats, days), True)
