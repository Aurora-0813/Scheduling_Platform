"""
模块 6：AI 智能巡检与维修工单 —— 服务层

对应 `docs/api.md` 的三条契约（形状由 `app/api/v1/mock_data.py` 冻结）：
    POST /inspect/submit              提交巡检照片 → AI 判定 → 落巡检记录 → 异常时建工单
    GET  /tickets/list                工单列表（分页）
    PUT  /tickets/{ticketId}/status   处理工单（状态流转）

为什么**不需要改表结构**
------------------------
契约要的 `deviceStatus` / `report` / `repairSuggestion` 三个字段，
`repair_ticket` 里没有；但 `inspect_record.ai_result` 是 JSON 列、
注释写着「AI识别结果」—— 这三个值正是 AI 的识别结果，放进去是它的本职。
工单列表要的 `report` 于是靠 `repair_ticket.inspect_id` **JOIN** 回巡检记录取。
好处：零 DDL。团队约定「DDL 一律走集成组」，零 DDL 就不需要过那道审批，
也不用动共享的开发库结构、不用写迁移。

为什么复用 `image_service._recognize`
-----------------------------------
它是「调模型 → 拿结构化结果」的统一入口，内置策略 A（`with_structured_output`）
与策略 B（普通 ainvoke + JSON 容错解析）两条路，并在模型彻底不可用时抛 41003。
这里**刻意不重写一份**：重写出来的解析只会与模块 2 的实现悄悄漂移，
而「同一件事两处实现」正是本仓库反复踩过的坑。跨模块引用私有名有先例 ——
`scripts/check_data.py` 就引用了 `dashboard_service._open_hours`，理由相同。

状态口径
--------
`repair_ticket.ticket_status`：1 待处理 / 2 处理中 / 3 已完成（模型注释即此口径）。
`deviceStatus` 只允许四个取值（见 `inspect_prompt`）；**只有 损坏 / 缺失配件 会建工单**，
完好 与 无法识别 都不建 —— 后者尤其重要：照片拍糊了就建工单，是制造垃圾数据。
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts.inspect_prompt import build_handle_verify_messages, build_inspect_messages
from app.core.exceptions import (
    ParamInvalidError,
    SpaceNotFoundError,
    TicketNotFoundError,
)
from app.core.utils import format_time
from app.models.inspection import InspectRecord, RepairTicket
from app.models.resource import DeviceResource, SpaceResource
from app.schemas.inspect import (
    HandleVerifyAnalysis,
    InspectAnalysis,
    InspectSubmitData,
    TicketHandleData,
    TicketItem,
    TicketListData,
    TicketUpdatedData,
)
from app.services.image_service import _recognize
from app.services.image_storage import read_and_validate_image, save_image, to_data_url

logger = logging.getLogger(__name__)

__all__ = [
    "DEVICE_STATUSES",
    "ABNORMAL_STATUSES",
    "VERIFIED_OK",
    "TICKET_STATUS_TEXT",
    "ALL_IN_REPAIR",
    "submit_inspection",
    "list_tickets",
    "update_ticket_status",
    "handle_ticket",
]

#: 模型唯一允许输出的四个取值。Prompt 里已钉死，这里是**兜底白名单**：
#: 模型不听话时判为「无法识别」，而不是把自由文本写进库、再让下游去猜。
DEVICE_STATUSES: frozenset[str] = frozenset({"完好", "损坏", "缺失配件", "无法识别"})

#: 需要建维修工单的取值。**不含「无法识别」** —— 照片拍糊不是设备坏了。
ABNORMAL_STATUSES: frozenset[str] = frozenset({"损坏", "缺失配件"})

UNRECOGNIZED = "无法识别"

#: 核验通过的唯一取值。其余三个（损坏 / 缺失配件 / 无法识别）都算未通过。
#: **判定只此一处** —— 接口把它翻译成 `passed` 布尔值给前端，
#: 前端不得再拿 verifyStatus 和字符串比一次（那是第二处口径）。
VERIFIED_OK = "完好"

#: 工单状态 → 文案（ticket_status 的取值口径见 models/inspection.py）
TICKET_STATUS_TEXT: dict[int, str] = {1: "待处理", 2: "处理中", 3: "已完成"}

#: 核验通过后工单流转到的状态
_STATUS_DONE = 3

#: `verify_report` 列宽上限 1000（见 models/inspection.py），入库前收一道
_VERIFY_REPORT_MAX = 1000

#: 模型不可用 / 输出无法解析时写给处理人的核验说明。
#: 刻意**不**说「设备损坏」—— 我们并不知道设备怎么样，只知道这次没验成。
_VERIFY_UNAVAILABLE_REPORT = (
    "AI 核验未能完成（视觉模型不可用或返回内容无法解析），"
    "本次未做判定。请确认已配置 VISION_API_KEY 后重试。"
)

_PARSE_FAILED_REPORT = (
    "巡检照片未能得到有效分析结果（模型输出无法解析）。"
    "建议重新拍摄一张光线充足、设备主体清晰的正面照片后再次提交。"
)

#: 落进 `inspect_record.ai_result` 的原始回复最多留这么长，避免 JSON 列被撑爆
_RAW_TEXT_MAX = 500


# ===========================================================================
# 内部辅助
# ===========================================================================
def _normalize_status(raw: object) -> str:
    """把模型给的 deviceStatus 归一到白名单内；不在名单里一律判为「无法识别」。"""
    text = str(raw or "").strip()
    if text in DEVICE_STATUSES:
        return text
    # 容错：模型爱写「设备损坏」「轻微损坏」这类带修饰的说法，包含即算命中。
    # 顺序有讲究 —— 先判「缺失配件」，否则「配件缺失导致损坏」会被判成「损坏」，
    # 而两者的处理建议完全不同（补配件 vs 换设备）。
    if "缺失配件" in text or "缺少配件" in text or "配件缺失" in text:
        return "缺失配件"
    if "损坏" in text or "故障" in text:
        return "损坏"
    if "完好" in text or "正常" in text:
        return "完好"
    return UNRECOGNIZED


def _status_text(status: int) -> str:
    """工单状态码 → 文案。未知状态不抛异常，回一句可读的兜底。"""
    return TICKET_STATUS_TEXT.get(status, f"未知状态({status})")


#: AI 的 `deviceStatus` 文案 → `device_resource.device_status` 数值。
#: 口径来自 models/resource.py 的列注释：1完好 2损坏 3缺失配件。
#: `无法识别` **刻意不在表里** —— 照片拍糊了不代表设备坏了，
#: 拿它去改台账会把好设备误标成故障（与「不建工单」同一口径，见 ABNORMAL_STATUSES）。
_DEVICE_STATUS_CODE: dict[str, int] = {"完好": 1, "损坏": 2, "缺失配件": 3}


#: `_match_device` 在「命中的设备**全部**已在维修处理中」时回的标记。
#:
#: ⚠️ 为什么不能只靠「device 为 None」判断：那混淆了两种完全不同的情况 ——
#:   ① **没认出台账里的设备**（模型报了个台账里没有的名字）→ 用户无需知道，
#:      记日志即可（前台只看到「巡检已记录」，不该被技术细节打扰）；
#:   ② **设备已全在维修中**（命中了，只是每台都已在处理）→ 这**必须告诉用户**，
#:      否则他重复提交同一台设备的故障、每次都被静默忽略，只会认为是 bug。
#: 两者都用 None 表示「没改成」，所以必须另带一个可判别的标记。
#: 用常量而不是让调用方 `in` 匹配中文文案 —— 文案是要给用户看的、随时可能改。
ALL_IN_REPAIR = "__all_in_repair__"


#: `_sync_device_status` 的**原因码**（给代码判断，不是给用户看的文案）。
#:
#: 为什么单给原因码而不是让调用方去匹配 warning 的中文：warning 是给用户看的、
#: 随时可能改；一旦改了文案，「命中全部已在维修中 → 跳过建单」这个**业务判断**
#: 就会静默失效 —— 属于「看起来正常、实际错了」的问题。
REASON_NOT_FOUND = "not_found"
REASON_ALL_IN_REPAIR = "all_in_repair"


async def _has_open_ticket(db: AsyncSession, device_id: int) -> bool:
    """该设备是否已有**未完成**的维修工单（待处理 1 / 处理中 2）。

    ⚠️ 为什么查工单而不是只看 `device_status`
    ----------------------------------------
    「已损坏」与「已在维修流程中」是两件事：一台设备可能已被人工改成损坏，
    但还没建过工单；也可能工单正在处理中。判断「要不要再报一次」时，
    两者都算「已经在处理了」，任一命中就不该重复建单 —— 否则同一台设备
    会被反复报修，工单列表越堆越长（用户反馈过「很多一样的」）。
    """
    row = (
        await db.execute(
            select(RepairTicket.id)
            .where(
                RepairTicket.device_id == device_id,
                RepairTicket.ticket_status != _STATUS_DONE,
            )
            .limit(1)
        )
    ).first()
    return row is not None


def _pick_device_candidate(candidates: list[DeviceResource]) -> DeviceResource:
    """
    从多个候选里挑一台**最该被报损**的。

    优先级（2026-10-10 起，按业务方要求「自动分配设备名称」）：
        ① `device_status == 1`（完好）优先 —— 报损一台好设备才有意义；
        ② 同为完好时取 **id 最小**的，保证同一输入每次挑到同一台（可预期、可复现）。

    ⚠️ 为什么要「自动分配」而不是像原先那样放弃
    ------------------------------------------
    原设计是「子串命中多台就放弃」（理由：怕把好设备误标成损坏）。但实测代价更大：
    台账里是 `投影仪01..04`，模型报 `投影仪` —— 永远命中 4 台、永远放弃，
    于是**AI 说损坏、设备台账却永远是完好**，这正是用户反复反馈的问题。

    业务方明确要求改为自动分配。挑选规则取「完好 + 最小 id」，把风险压到最低：
    只动本来就完好的设备，且选择是确定的（不是随机的）。
    """
    healthy = [d for d in candidates if d.device_status == 1]
    pool = healthy or candidates
    return sorted(pool, key=lambda d: d.id)[0]


async def _match_device(db: AsyncSession, name: str) -> tuple[DeviceResource | None, str]:
    """
    把模型报的设备名匹配到台账里的**一台**设备，必要时自动分配。

    返回 `(设备行或 None, 说明)`。说明会进日志，用于回答「为什么这次没同步/没建单」
    —— 没有说明的话，用户看到的只是「什么都没发生」，无从排查。

    匹配顺序：
        ① 精确相等（走 SQL 主路径）
        ② 唯一子串包含（模型报品类、台账写品牌型号时靠它命中）
        ③ **多台子串命中 → 自动分配一台**（2026-10-10 起；原先放弃，见下）
        ④ 命中的设备**全都已损坏 / 已在未完成工单里** → 返回 None + 明确说明,
           调用方据此提示「该设备已在维修工单列表中」，**不重复建单**

    ⚠️ 第 ③ 步推翻了原先「宁可不写也不猜」的设计
    --------------------------------------------
    原注释写着「挑错一台就会把一台好设备标成损坏…少改一次台账，比把错误的设备
    标成故障要轻得多」。实测证明那个取舍**代价更大**：台账是 `投影仪01..04`、
    模型报 `投影仪` → 永远命中 4 台 → 永远放弃 → 用户眼中的现象就是
    「AI 说有设备损坏，但设备列表里状态没变」。业务方要求改为自动分配，
    挑选规则见 `_pick_device_candidate`（只动完好设备、确定性地取最小 id）。

    第二级为什么在 Python 里做而不是 `LIKE`
    --------------------------------------
    `LIKE '%无人机%'` 依赖数据库的排序规则与转义（名字里的 `%` `_` 要转义），
    跨 SQLite / MySQL 行为不完全一致。而设备台账是**一张小表**
    （一个场地几十台设备），全表取回在 Python 里判断既清晰又不会有方言差异。
    第一级仍走 SQL，正常路径不会退化。
    """
    # ---- ① 精确相等（走索引/主路径）----
    rows = (
        (await db.execute(select(DeviceResource).where(DeviceResource.device_name == name)))
        .scalars()
        .all()
    )
    if len(rows) == 1:
        candidates = list(rows)
        matched_by = "精确匹配"
    elif len(rows) > 1:
        # 名字不唯一（台账里重名）：同样是「多候选」，交给同一套挑选逻辑
        candidates = list(rows)
        matched_by = f"精确匹配到 {len(rows)} 台（重名，自动分配）"
    else:
        # ---- ② 唯一子串包含 ----
        all_devices = (
            (await db.execute(select(DeviceResource).order_by(DeviceResource.id))).scalars().all()
        )
        hits = [d for d in all_devices if name in d.device_name]
        if not hits:
            return None, "没有找到（精确与子串都没命中）"
        candidates = hits
        matched_by = (
            f"唯一子串命中「{hits[0].device_name}」"
            if len(hits) == 1
            else f"子串命中 {len(hits)} 台，自动分配"
        )

    # ---- ④ 全部已在处理中 → 不重复报损 ----
    # 「已在处理中」= 损坏/缺失配件（台账状态）或 已有未完成工单。
    # 两者都查（业务方确认），任一命中即认为这台不必再报。
    #
    # ⚠️ 只对**全部候选都如此**时才放弃：只要还有一台是完好的，就该报那一台 ——
    # 否则「4 台投影仪坏了 2 台」这种情况会漏报，而那正是最需要建单的场景。
    async def _in_progress(d: DeviceResource) -> bool:
        if d.device_status != 1:
            return True
        return await _has_open_ticket(db, d.id)

    pending = [d for d in candidates if await _in_progress(d)]
    if len(pending) == len(candidates):
        names = "、".join(d.device_name for d in candidates)
        # 回 ALL_IN_REPAIR 标记而不是普通说明：调用方据此给**用户**提示
        # （详见该常量的注释：这与「没认出来」必须区别对待）
        return None, f"{ALL_IN_REPAIR}命中 {len(candidates)} 台且全部已在维修处理中（{names}）"

    # ---- ③ 自动分配 ----
    chosen = _pick_device_candidate(candidates)
    return chosen, f"{matched_by} → 选中「{chosen.device_name}」"


async def _sync_device_status(
    db: AsyncSession,
    *,
    device_name: str | None,
    status: str,
    device_id: int | None = None,
) -> tuple[int | None, str | None, str]:
    """
    按 AI 认出的设备名，把判定结果回写到设备台账：
    `device_status` 改为损坏/缺失配件，并把 `available_count` **减 1**。

    返回 `(device_id, warning, reason)`：

    · `device_id` 为 None 表示没改到设备台账。
    · `warning` 非 None 是一句**给用户看**的提示（已可借数为 0、或已在维修中）。
    · `reason` 是**给代码判断**的原因码（本次新增）：
      `""`           正常改到了台账
      `REASON_NOT_FOUND`  名字在台账里找不到（模型报了个台账没有的名字）
      `REASON_ALL_IN_REPAIR` 命中了，但每台都已在维修处理中

      ⚠️ 为什么单给 reason 而不是让调用方去 `in` 匹配 warning 的中文：
        文案是给用户看的、随时可能改（改文案是常事），一旦改了，
        「跳过建单」这个**业务判断**就会静默失效 —— 属于「看起来正常、实际错了」。
        能用常量判的绝不比字符串。

    为什么需要这一步
    ----------------
    原先巡检只落 `inspect_record` 与 `repair_ticket`，**从不碰设备台账**：
    工单的 `device_id` 写死 None，注释理由是「前端只传 spaceId，认出的设备名
    映射不回 device_resource.id」。后果是用户明确反馈的那个不一致 ——
    AI 判定「损坏」、工单也建了，可「资源与设备」页里那台设备**还显示完好**。

    ⚠️ 匹配口径（2026-10-10 改）
    ---------------------------
    只做**精确相等**是不够的，实测就撞上了：设备台账里叫 `大疆无人机`，
    而视觉模型报的是 `无人机` —— 模型给的是**品类**，台账里存的是**带品牌的型号**，
    两者永不相等，于是「AI 说损坏、设备还是完好」这个用户反馈的问题依然存在。
    （模型不可能稳定地输出台账里的精确名字：它看的是像素，不是我们的字典。）

    所以改为：**精确相等 → 唯一子串 → 多台时自动分配**。
    第二级能处理品牌前缀/后缀这类差异（`无人机` ⊂ `大疆无人机`）。

    ⚠️ 「多台时自动分配」取代了原先的「多台就放弃」
    ---------------------------------------------
    原设计是「子串命中多台就放弃」，理由是怕把好设备误标成损坏。但实测代价更大：
    台账是 `投影仪01..04`、模型报 `投影仪` → 永远命中 4 台 → 永远放弃 →
    用户看到的现象就是「AI 说有设备损坏，但设备台账里状态没变」，
    这正是他反复反馈的问题。业务方明确要求改为自动分配，
    挑选规则见 `_pick_device_candidate`（只动完好设备、确定性地取最小 id）。
    见 `_match_device` 的完整说明。

    ⚠️ 命中的设备**全部已在维修处理中**时 → 返回 `REASON_ALL_IN_REPAIR`，
       调用方据此**跳过建单**并给用户提示（否则同一台设备每提交一次就多一条工单）。

    为什么不改回「完好」
    ------------------
    本函数只在 `status in ABNORMAL_STATUSES` 时被调用（见 `submit_inspection`），
    所以**永远不会把设备改回完好**。理由：巡检是「发现故障」的入口，
    而「修好了」应当由维修流程处置（工单流转 / 人工在「资源与设备」页修改）。
    让巡检顺手把设备标回完好，等于凭一张照片宣称修好了，绕过了维修确认。
    """
    code = _DEVICE_STATUS_CODE.get(status)
    if code is None:
        return None, None, ""

    # ---- 分支 A：显式指定了设备（扫码 / 下拉选中的那一台）----
    # 2026-10-13 新增的「精确识别」路径。原先只有下面那条模糊匹配，而视觉模型
    # 天生分不出「投影仪01」与「投影仪02」（照片里长得一样），4 台命中就自动分配
    # —— 坏的是 03，系统却把 01 标成损坏。现在由人（扫码/下拉）明确指定是哪一台。
    if device_id is not None:
        device = await db.get(DeviceResource, device_id)
        if device is None:
            logger.info("巡检指定了 deviceId=%s，但设备台账里没有这台", device_id)
            return None, None, REASON_NOT_FOUND
        # 显式指定同样要挡重复报修：同一台已在处理中就不该再建单
        if device.device_status != 1 or await _has_open_ticket(db, device.id):
            logger.info(
                "巡检指定设备 #%s「%s」，但它已在维修处理中", device.id, device.device_name
            )
            return (
                None,
                (
                    f"该设备（{device.device_name}）已在维修工单列表中，"
                    "处理完成后状态会恢复正常。本次仅记录巡检结果，未重复建单。"
                ),
                REASON_ALL_IN_REPAIR,
            )
        how = f"按指定设备 #{device.id}「{device.device_name}」"
    else:
        # ---- 分支 B：兼容旧路径 —— 按 AI 认出的名字模糊匹配 ----
        if not device_name:
            return None, None, ""
        name = device_name.strip()
        if not name:
            return None, None, ""
        device, how = await _match_device(db, name)

    if device is None:
        # 命中了、但每台都已在处理 → 给用户一句可读提示，别让他重复提交
        if how.startswith(ALL_IN_REPAIR):
            logger.info("巡检判定「%s」，%s", status, how[len(ALL_IN_REPAIR) :])
            return (
                None,
                (
                    f"该设备（{name}）已在维修工单列表中，处理完成后状态会恢复正常。"
                    "本次仅记录巡检结果，未重复建单。"
                ),
                REASON_ALL_IN_REPAIR,
            )
        logger.info(
            "巡检判定「%s」，但设备名「%s」在台账里%s，未回写状态（宁可不写，也不猜是哪一台）",
            status,
            name,
            how,
        )
        return None, None, REASON_NOT_FOUND

    if device.device_status != code:
        logger.info(
            "设备 #%s「%s」状态由 %s 改为 %s（巡检判定，%s）",
            device.id,
            device.device_name,
            device.device_status,
            code,
            how,
        )
        device.device_status = code

    # ---- 可借数 −1（2026-10-06 口径变更，取代原先的「刻意不写」）----
    #
    # ⚠️ **这一条推翻了本函数上一版的注释。** 上一版写着「刻意不写
    # `available_count`，因为它是静态上限」。按业务方明确要求改为：
    #     报损 → 可借数 −1；维修核验通过 → 可借数 +1
    # 即 `available_count` 现在的语义是「**台账上可用的物理台数**」。
    #
    # 为什么这跟 `docs/available_count口径判据.md` 的「只读不写」不冲突
    # --------------------------------------------------------------
    # 那份文档禁止的是**下单时扣减**（「谁扣：没人扣」），理由是
    # `available_count` 不带时间维度、而「还剩几台」是 (设备,时段) 的函数 ——
    # 用一维列记二维事实必然串台（周一借走吃掉周二的名额）。
    # 这条理由**只适用于预约占用**，不适用于**设备物理损坏**：
    # 「报损」是一个不带时间维度的、持久的状态变更，减掉它是精确的。
    # 所以现在的分工是：
    #     `available_count`  = 物理可用台数（报损减、修好加）→ 管理员/系统维护
    #     订单占用导致的减少  = **仍然用时推导**，即 `remainingCount`
    # 两款用例（`test_successful_order_never_writes_available_count`）依旧成立：
    # 下单那条路径依然一行都不写。
    #
    # 下限 0：可借数已经为 0 时不再往下减（不允许负库存），
    # 并把这件事作为提示回给调用方 —— 见 `_sync_device_status` 的返回值说明。
    warning: str | None = None
    if device.available_count is None or device.available_count <= 0:
        # 已经 0 台可借，说明这台设备的可借台数用光了（或台账本就对不上）。
        # 状态照改（它确实报损了），但不再减，并明确告诉用户**已经有人报修**。
        warning = (
            f"{device.device_name} 已无可借台数，该设备已有人报修，本次仅记录故障、未再减少可借数"
        )
        logger.info(
            "设备 #%s「%s」可借数为 0，报损不再减（%s）",
            device.id,
            device.device_name,
            status,
        )
    else:
        device.available_count -= 1
        logger.info(
            # 用 ASCII 减号而不是 U+2212：Windows 控制台是 GBK 码页，
            # 日志里出现 U+2212 会抛 UnicodeEncodeError（"--- Logging error ---"），
            # 功能不受影响，但日志会被刷脏、真问题被淹没。
            "设备 #%s「%s」可借数 -1 → %s（巡检判定「%s」）",
            device.id,
            device.device_name,
            device.available_count,
            status,
        )

    return int(device.id), warning, ""


async def _restore_device(db: AsyncSession, ticket: RepairTicket) -> tuple[int | None, int | None]:
    """
    维修完成 → 把设备改回可借：`device_status` 置「完好」、`available_count` **加 1**。

    返回 `(device_id 或 None, 恢复后的 available_count 或 None)`。
    两个都为 None 表示没匹配到设备（工单照常关掉，只是没有设备可恢复）。

    为什么需要这个函数（这是上一轮漏掉的一半）
    ----------------------------------------
    上一轮只实现了**单向**同步：巡检判定异常 → 设备标为损坏。
    却没有任何路径把它改回来，于是设备**永远**停在损坏状态、
    再也借不出去 —— 用户反馈的「修复完成后可用的设备没有增加」正是这个。
    状态机少了一半，比不做同步还糟：不做同步时设备至少还能借。

    改 `device_status` **并把 `available_count` 加 1**（与报损时的 −1 对称）
    --------------------------------------------------------------------
    上一版这里写着「只改 device_status，不动 available_count」，理由是那一列
    是静态上限。按业务方明确要求改为**对称加减**：
        报损 → 可借数 −1 ；维修核验通过 → 可借数 +1
    于是 `available_count` 的语义是「台账上可用的物理台数」。
    口径变更的完整理由见 `_sync_device_status` 里那段注释。

    ⚠️ **加 1 不能超过 `total_count`**（上限保护）。
    报损时遇到下限 0 会**不再减**（并回传 warning），所以「减」的次数可能少于
    「加」的次数。若这里无脑 +1，报损被挡下的那几台会在修好时凭空多出来 ——
    2 台的设备能被加成 3 台。用 `min(total_count, available + 1)` 夹住。

    为什么只认核验通过（`passed`）
    -----------------------------
    恢复可借 = 宣称「这台设备能用了」，必须有凭据。核验通过的照片就是凭据。
    人工把工单标成已完成也是一条**合法**路径（那是人的判断，见
    `update_ticket_status`），但它的凭据强度低于核验，所以两条路径都放行、
    都走本函数，只是备注不同。

    设备怎么找
    ---------
    新工单在 `_sync_device_status` 命中时已经写上了 `device_id`，直接用。
    旧工单（本次改动之前建的）`device_id` 为 NULL，退回用关联巡检记录里
    AI 认出的 `deviceName` 走 `_match_device` 再匹配一次。
    两条都失败就返回 None —— 工单照样关掉，只是没有设备可恢复。
    """
    device: DeviceResource | None = None

    if ticket.device_id is not None:
        device = await db.get(DeviceResource, ticket.device_id)

    if device is None and ticket.inspect_id is not None:
        record = await db.get(InspectRecord, ticket.inspect_id)
        name = ((record.ai_result or {}).get("deviceName") if record else None) or None
        if name:
            device, how = await _match_device(db, name.strip())
            if device is not None:
                logger.info("工单 #%s 按巡检记录里的「%s」%s，恢复设备", ticket.id, name, how)

    if device is None:
        logger.info("工单 #%s 维修完成，但没有匹配到设备，跳过状态恢复", ticket.id)
        return None, None

    if device.device_status != _DEVICE_STATUS_CODE["完好"]:
        logger.info(
            "工单 #%s 维修完成：设备 #%s「%s」状态由 %s 恢复为完好(1)",
            ticket.id,
            device.id,
            device.device_name,
            device.device_status,
        )
        device.device_status = _DEVICE_STATUS_CODE["完好"]
        # 本函数会真的改一行，但**不在这里 commit** —— 由调用方决定事务边界
        # （`handle_ticket` 要把工单状态与设备恢复放进同一个提交里）。

    # ---- 可借数 +1（上限保护：不得超过 total_count）----
    cap = device.total_count if device.total_count is not None else None
    current = device.available_count or 0
    target = current + 1
    if cap is not None and target > cap:
        logger.info(
            "设备 #%s「%s」可借数已是上限 %s，不再 +1（工单 #%s 维修完成）",
            device.id,
            device.device_name,
            cap,
            ticket.id,
        )
    else:
        device.available_count = target
        logger.info(
            "设备 #%s「%s」可借数 +1 → %s（工单 #%s 维修完成）",
            device.id,
            device.device_name,
            target,
            ticket.id,
        )

    return int(device.id), device.available_count


def _ticket_item(
    ticket: RepairTicket,
    ai_result: dict | None,
    inspect_image_url: str | None = None,
    ledger_device_name: str | None = None,
) -> TicketItem:
    """把 (工单行, 巡检记录, 台账设备名) 组装成列表项。"""
    ai = ai_result or {}
    return TicketItem(
        id=ticket.id,
        spaceId=ticket.space_id,
        deviceId=ticket.device_id,
        deviceStatus=ai.get("deviceStatus"),
        # 设备名**以台账为准**（「投影仪04」这种带编号的），AI 报的品类名只是兜底。
        # 为什么：照片里两台投影仪长得一样，模型只报得出「投影仪」；到底是哪一台
        # 由 deviceId 决定（扫码 / 下拉指定）。拿 AI 的品类名当标题的话，
        # 用户看到的就是一个分不清是哪台的词 —— 这正是「工单里没有具体编号」的根因。
        deviceName=ledger_device_name or ai.get("deviceName"),
        # 固定设施（插座 / 门把手）不在设备台账里，位置是它们唯一的精度来源
        locationHint=ai.get("locationHint"),
        status=ticket.ticket_status,
        statusText=_status_text(ticket.ticket_status),
        report=ai.get("report"),
        createTime=format_time(ticket.create_time),
        # 原始巡检照片：工单表不存这一列，靠 inspect_id JOIN 回巡检记录取。
        # 不透出的话，管理员在工单里看不到「当初拍的到底是哪张」。
        # 空串归一成 None：落盘失败时巡检记录里存的是 ""（该列 NOT NULL），
        # 直接透出去前端会拿到一个「有值但加载不出来」的图片地址。
        inspectImageUrl=inspect_image_url or None,
        handleImageUrl=ticket.handle_image_url,
        verifyStatus=ticket.verify_status,
        verifyReport=ticket.verify_report,
    )


# ===========================================================================
# 对外入口 1：提交巡检
# ===========================================================================
async def submit_inspection(
    db: AsyncSession,
    *,
    file,
    space_id: int,
    inspector_id: int,
    llm: BaseChatModel,
    device_id: int | None = None,
    location_hint: str | None = None,
) -> InspectSubmitData:
    """
    提交一张巡检照片：AI 判定 → 落巡检记录 → 异常时建维修工单。

    参数：
        db           : AsyncSession    请求级会话（由 get_db 注入）
        file         : UploadFile      照片，JPG/PNG/WEBP，≤ IMAGE_MAX_SIZE_MB
        space_id     : int             拍摄所在场地
        inspector_id : int             巡检人，**必须来自 JWT**（§5.1，禁止从 FormData 传）
        llm          : BaseChatModel   视觉模型（由 get_vision_llm 注入；测试用假模型替换）
        device_id    : int | None      用户**明确指定**的设备 ID（扫码或下拉选中）。
                                       **传了就精确更新这一台**，跳过 AI 名称模糊匹配；
                                       不传则保持原行为（按 AI 认出的名字匹配 → 多台时自动分配）。
                                       为什么需要它：照片里两台投影仪长得一样，模型只报得出
                                       「投影仪」这个品类，命中 4 台只能自动分配 —— 会标错设备。
        location_hint: str | None      **用户填的具体位置**（如「3楼走廊东侧」），可选。
                                       为什么需要它：固定设施（插座/门把手/电路）**不在设备台账里**，
                                       只有场地一级的精度 —— 光说「这个场地有个插座坏了」
                                       无法定位到是哪一个。位置是这类设施唯一的精度来源。
                                       用户填的**优先于** AI 从画面里推断的位置。

    返回：
        InspectSubmitData(datasetStatus, report, repairSuggestion, ticketId)

    抛出：
        ImageValidationError(41001/41002)  图片格式 / 大小不合法（由 image_storage 抛）
        SpaceNotFoundError(40402)          场地不存在
        ImageRecognitionError(41003)       视觉模型不可用（未配置 / 超时 / 服务端错误）

    执行流程：
        ┌─ ① 校验图片（格式 / 大小 / 魔数）
        ├─ ② 场地必须存在 —— 云库上 inspect_record.space_id 是**真外键**，
        │     不先查会以 MySQL 1452 炸成 500（这个坑 order_service 注释里记过）
        ├─ ③ 落盘（失败不阻断，与模块 2 的 D6 口径一致）
        ├─ ④ 调视觉模型（复用 image_service._recognize，含两级策略与容错解析）
        ├─ ⑤ 解析失败 → 降级：记录仍落库，deviceStatus=无法识别，**不建工单**
        ├─ ⑥ 落 inspect_record（ai_result 装四个业务字段）
        ├─ ⑦ 判定异常 → 落 repair_ticket（status=1 待处理）
        └─ ⑧ 一次 commit 收口

    ⚠️ 为什么⑥⑦在一个 commit 里：工单挂着 inspect_id 外键。
    若先提交巡检记录再单独提交工单，中间失败会留下「有巡检、没工单」的孤儿，
    而那条巡检记录的 ai_result 明明白白写着「损坏」—— 对不上账。
    """
    # ---- ① 校验图片 ----
    raw, mime = await read_and_validate_image(file)

    # ---- ② 场地必须存在 ----
    space = await db.get(SpaceResource, space_id)
    if space is None:
        raise SpaceNotFoundError("场地不存在")

    # ---- ③ 落盘 ----
    # save_image 失败返回 None（故意不阻断主流程）。但 inspect_record.image_url 是
    # NOT NULL，所以这里退化成空串 —— 宁可丢图片地址，也不要整个巡检提交失败。
    image_url = await save_image(raw, mime) or ""

    # ---- ④ 调视觉模型 ----
    messages = build_inspect_messages(
        image_data_url=to_data_url(raw, mime),
        space_name=space.space_name,
    )
    parsed, raw_reply = await _recognize(llm, messages, InspectAnalysis)

    # ---- ⑤ 解析失败 → 降级，但仍然留一条记录（否则用户无从知道这次提交发生了什么）----
    parse_failed = parsed is None
    if parse_failed:
        logger.info("巡检照片解析失败，已降级为「无法识别」（场地 %s）", space_id)
        status = UNRECOGNIZED
        report = _PARSE_FAILED_REPORT
        suggestion = ""
        device_name = None
        device_type = None
    else:
        status = _normalize_status(parsed.deviceStatus)
        report = (parsed.report or "").strip() or _PARSE_FAILED_REPORT
        suggestion = (parsed.repairSuggestion or "").strip()
        device_name = parsed.deviceName or None
        device_type = parsed.deviceType or None
        # 完好 / 无法识别 时不留维修建议 —— 模型偶尔会「顺便」写一条，那是噪音
        if status not in ABNORMAL_STATUSES:
            suggestion = ""

    # 具体位置：**用户填的优先** —— 他就在现场，比模型从画面里推断的可靠；
    # 用户没填才用模型给的。两者都空就是 None（不是空串），前端按空值处理。
    ai_location = None if parse_failed else ((parsed.locationHint or "").strip() or None)
    final_location = (location_hint or "").strip() or ai_location

    ai_result: dict = {
        "deviceStatus": status,
        "report": report,
        "repairSuggestion": suggestion,
        "deviceName": device_name,
        "deviceType": device_type,
        "locationHint": final_location,
        "parseFallback": parse_failed,
    }
    if parse_failed and raw_reply:
        ai_result["rawText"] = raw_reply[:_RAW_TEXT_MAX]

    # ---- ⑥ 落巡检记录 ----
    record = InspectRecord(
        space_id=space_id,
        image_url=image_url,
        ai_result=ai_result,
        inspector_id=inspector_id,
    )
    db.add(record)
    await db.flush()  # 取库侧自增 id，工单要拿它当 inspect_id

    # ---- ⑦ 判定异常 → 建工单 + 同步设备台账 ----
    ticket: RepairTicket | None = None
    linked_device_id: int | None = None
    device_warning: str | None = None
    if status in ABNORMAL_STATUSES:
        # 先按 AI 认出的设备名回写设备台账（状态 + 可借数 −1），拿到 device_id
        # 再建工单 —— 这样 `repair_ticket.device_id` 不再恒为 NULL，
        # 「资源与设备」页里那台设备的状态与可借数会真的跟着变。
        linked_device_id, device_warning, sync_reason = await _sync_device_status(
            db, device_name=device_name, status=status, device_id=device_id
        )

        # ⚠️ 命中的设备**全部已在维修处理中**时**不重复建单**（2026-10-10 加）。
        #
        # 为什么必须跳过：原实现无条件建工单，于是同一台设备每提交一次巡检就多一条
        # 工单 —— 用户看到的正是「维修工单列表里很多一样的」。
        # 「该设备已在维修工单列表」这句话要成立，前提就是这里不再往里塞新单。
        #
        # 判断用**原因码**而不是 warning 的中文（理由见 REASON_* 的注释）。
        #
        # 注意**只跳这一种**：名字完全没命中的情况仍照原样建单（`device_id=None`），
        # 那是既有行为、另有用例钉住（`ticket.device_id is None`），不在本次改动范围。
        if sync_reason != REASON_ALL_IN_REPAIR:
            ticket = RepairTicket(
                inspect_id=record.id,
                device_id=linked_device_id,
                space_id=space_id,
                ticket_status=1,  # 待处理
                handler_id=None,  # 处理时才由 PUT 接口写入
            )
            db.add(ticket)
            await db.flush()

    # ---- ⑧ 提交 ----
    await db.commit()

    return InspectSubmitData(
        deviceStatus=status,
        report=report,
        repairSuggestion=suggestion,
        ticketId=ticket.id if ticket is not None else None,
        # 可借数已经为 0、本次未再减时把原因带回给用户。
        # 不回传的话，用户看到「工单建了、可借数没变」会以为是 bug。
        deviceWarning=device_warning,
        locationHint=final_location,
        # 照片在步骤 ③ 就已落盘（落盘失败是空串），这里原样回传，前端可立即回看
        imageUrl=image_url or None,
    )


# ===========================================================================
# 对外入口 2：工单列表
# ===========================================================================
async def list_tickets(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 10,
    status: int | None = None,
) -> TicketListData:
    """
    工单列表（分页，倒序）。

    参数：
        status : int | None  按工单状态筛选（1/2/3）；None 表示全部

    `report` / `deviceStatus` 不在 repair_ticket 上，靠 `inspect_id` **LEFT JOIN** 回
    `inspect_record` 取 `ai_result` —— 用 LEFT 而不是 INNER：
    工单关联的巡检记录若被清理掉，工单本身仍应出现在列表里（宁可少几个字段，
    也不要整条工单凭空消失）。
    """
    if page < 1 or page_size < 1:
        raise ParamInvalidError("page / pageSize 必须为正整数")
    if status is not None and status not in TICKET_STATUS_TEXT:
        raise ParamInvalidError("status 只能为 1(待处理) / 2(处理中) / 3(已完成)")

    where = [] if status is None else [RepairTicket.ticket_status == status]

    total = (
        await db.execute(select(func.count()).select_from(RepairTicket).where(*where))
    ).scalar_one()

    rows = (
        await db.execute(
            select(
                RepairTicket,
                InspectRecord.ai_result,
                InspectRecord.image_url,
                # 台账里的设备名（带编号的那种）—— 见 _ticket_item 里的说明
                DeviceResource.device_name,
            )
            .outerjoin(InspectRecord, InspectRecord.id == RepairTicket.inspect_id)
            # LEFT JOIN 设备台账：工单可能未关联设备（插座/门把手这类非台账设施），
            # 用 INNER 会让那些工单整条从列表里消失。
            .outerjoin(DeviceResource, DeviceResource.id == RepairTicket.device_id)
            .where(*where)
            .order_by(RepairTicket.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    return TicketListData(
        page=page,
        pageSize=page_size,
        total=int(total),
        list=[_ticket_item(ticket, ai, img, dev_name) for ticket, ai, img, dev_name in rows],
    )


# ===========================================================================
# 对外入口 3：处理工单
# ===========================================================================
async def update_ticket_status(
    db: AsyncSession,
    *,
    ticket_id: int,
    status: int,
    handler_id: int,
) -> TicketUpdatedData:
    """
    流转工单状态（1 待处理 → 2 处理中 → 3 已完成）。

    参数：
        handler_id : int  处理人，**必须来自 JWT**（§5.1）

    抛出：
        TicketNotFoundError(40405)  工单不存在
        ParamInvalidError(40001)    status 不在 1/2/3 内

    为什么不做「必须按 1→2→3 顺序流转」的硬约束：
        实际维修中存在「直接标记完成」的场景（到场发现是误报）。真正的状态机约束
        应先由业务方确认口径再定；这里只校验取值合法，避免凭空发明一条规则。
    """
    if status not in TICKET_STATUS_TEXT:
        raise ParamInvalidError("status 只能为 1(待处理) / 2(处理中) / 3(已完成)")

    ticket = await db.get(RepairTicket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError("维修工单不存在")

    ticket.ticket_status = status
    ticket.handler_id = handler_id

    # 人工把工单推成「已完成」时，也恢复设备可借（状态 → 完好、可借数 +1）。
    # 与 /handle 的区别只是凭据来源：这里是人的判断（如到场发现是误报、
    # 或换了配件后人工确认），/handle 是 AI 核验通过的照片。
    # 不恢复的话，这条人工路径同样会把设备永久留在损坏状态 ——
    # 那就等于「只能修坏、不能修好」，比不做同步更糟。
    restored_device_id: int | None = None
    restored_available: int | None = None
    if status == _STATUS_DONE:
        restored_device_id, restored_available = await _restore_device(db, ticket)

    await db.commit()
    await db.refresh(ticket)

    return TicketUpdatedData(
        id=ticket.id,
        status=ticket.ticket_status,
        statusText=_status_text(ticket.ticket_status),
        handlerId=ticket.handler_id,
        handleTime=format_time(ticket.update_time),
        deviceId=restored_device_id,
        availableCount=restored_available,
    )


# ===========================================================================
# 对外入口 4：提交处理结果 + AI 核验
# ===========================================================================
async def handle_ticket(
    db: AsyncSession,
    *,
    ticket_id: int,
    file,
    handler_id: int,
    llm: BaseChatModel | None,
) -> TicketHandleData:
    """
    提交处理结果照片 → AI 核验 → **核验通过才置为已完成**。

    参数：
        ticket_id  : int                工单 ID
        file       : UploadFile         维修后的照片，JPG/PNG/WEBP，≤ IMAGE_MAX_SIZE_MB
        handler_id : int                处理人，**必须来自 JWT**（§5.1，禁止从 FormData 传）
        llm        : BaseChatModel|None 视觉模型。**允许为 None** —— 见下

    返回：
        TicketHandleData(passed, verifyStatus, verifyReport, status, handleImageUrl, …)

    核验未通过时的状态口径（业务已确认）
    ----------------------------------
    | 情形                        | 工单状态        | passed |
    | --------------------------- | --------------- | ------ |
    | 核验「完好」                | 置为 3 已完成   | True   |
    | 核验 损坏/缺失配件/无法识别 | **保持原状态**  | False  |
    | 模型不可用 / 输出无法解析   | **保持原状态**  | False  |

    即：**核验不通过绝不把工单标成已完成**。否则会出现「AI 说没修好、
    工单却已关闭」的账面不一致，而工单状态是后续统计与追责的依据。
    处理人可以重拍再传；流程不会被卡死，因为处理人始终可以改用既有的
    `PUT /tickets/{id}/status` 直接流转（那是人工决定，与本核验无关）。

    为什么不复用 submit_inspection
    ----------------------------
    两者都要「校验图片 → 调模型 → 解析」，但**落库目标完全不同**：
    提交巡检要新建 inspect_record、异常时建工单；核验只更新既有工单的三列。
    硬合并会让函数里塞进一个「这次是提交还是核验」的分支，两边的字段宽严
    也不一样（核验没有 repairSuggestion）。共用的部分是 `_recognize` 与
    `read_and_validate_image`，它们已经是独立函数，这就够了。

    为什么核验未通过也把照片与结论落库
    --------------------------------
    那是「这台设备修过一次但没修好」的证据，正是后续追责与再次派工的依据。
    只记通过的那次等于把失败记录丢掉。

    抛出：
        ImageValidationError(41001/41002)  图片格式 / 大小不合法
        TicketNotFoundError(40405)         工单不存在
    """
    # ---- ① 校验图片（与提交巡检同一套：格式 / 大小 / 魔数）----
    raw, mime = await read_and_validate_image(file)

    # ---- ② 工单必须存在 ----
    ticket = await db.get(RepairTicket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError("维修工单不存在")

    # ---- ③ 落盘（失败不阻断核验，口径同 submit_inspection）----
    image_url = await save_image(raw, mime)

    # ---- ④ 取原巡检上下文，喂给模型做对照 ----
    # LEFT JOIN 拿不到是有可能的（工单的 inspect_id 可为 NULL），此时只少一层上下文。
    original_report: str | None = None
    device_name: str | None = None
    space_name: str | None = None
    if ticket.inspect_id is not None:
        record = await db.get(InspectRecord, ticket.inspect_id)
        if record is not None:
            ai = record.ai_result or {}
            original_report = ai.get("report")
            device_name = ai.get("deviceName")
    if ticket.space_id is not None:
        space = await db.get(SpaceResource, ticket.space_id)
        if space is not None:
            space_name = space.space_name

    # ---- ⑤ 调视觉模型核验 ----
    status: str | None = None
    report: str | None = None
    model_failed = False

    if llm is None:
        # 模型未配置：明确说明「无法核验」，而不是假装通过或假装设备坏了。
        # 这条路径让「没配 VISION_API_KEY 的机器」仍能跑通前端流程而不 500。
        model_failed = True
        logger.info("核验工单 %s：视觉模型未配置，跳过核验", ticket_id)
    else:
        messages = build_handle_verify_messages(
            image_data_url=to_data_url(raw, mime),
            space_name=space_name,
            device_name=device_name,
            original_problem=original_report,
        )
        parsed, _raw_reply = await _recognize(llm, messages, HandleVerifyAnalysis)
        if parsed is None:
            model_failed = True
            logger.info("核验工单 %s：模型输出无法解析，视为未通过", ticket_id)
        else:
            status = _normalize_status(parsed.deviceStatus)
            report = (parsed.report or "").strip() or None

    if model_failed:
        status = None
        report = _VERIFY_UNAVAILABLE_REPORT

    passed = status == VERIFIED_OK

    # ---- ⑥ 落库 ----
    # 无论通过与否都记录照片与核验结论（理由见 docstring）。
    ticket.handle_image_url = image_url
    ticket.verify_status = status
    # 为空时留 NULL 而不是空串：NULL 的语义是「没有说明」，空串会被当成「说明是空的」
    ticket.verify_report = report[:_VERIFY_REPORT_MAX] if report else None
    ticket.handler_id = handler_id
    restored_device_id: int | None = None
    restored_available: int | None = None
    if passed:
        ticket.ticket_status = _STATUS_DONE
        # 核验通过 = 设备修好了 → 状态置「完好」且可借数 +1，让它重新可借。
        # **必须与工单状态在同一个事务里提交**：否则工单说「已完成」而设备
        # 仍不可借，又回到「修好了也借不出去」那个问题。
        restored_device_id, restored_available = await _restore_device(db, ticket)
    # 未通过：**不动 ticket_status**，保持原状态
    await db.commit()
    await db.refresh(ticket)

    return TicketHandleData(
        id=ticket.id,
        status=ticket.ticket_status,
        statusText=_status_text(ticket.ticket_status),
        handlerId=ticket.handler_id,
        handleTime=format_time(ticket.update_time),
        passed=passed,
        verifyStatus=status,
        verifyReport=report,
        handleImageUrl=image_url,
        deviceId=restored_device_id,
        availableCount=restored_available,
    )
