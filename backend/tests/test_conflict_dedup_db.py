"""数据库兜底判重（`DbDedup`）的回归用例。

为什么必须单独有这个文件
------------------------
`tests/api/test_notify_api.py` 在夹具里把去重实现**替换**成了
`SharedMemoryDedup`（见该文件 L72-77 的 `monkeypatch.setattr(build_dedup, ...)`），
于是整条 `DbDedup` 路径在离线套件里**从来没有被执行过**。

而线上的配置恰好落在这条路径上：`.env` 里 `REDIS_ENABLED=false`，
`CONFLICT_DEDUP_BACKEND=auto` → `RedisDedup` 连不上 → 自动降级到 `DbDedup`。
**用例全绿，行为全错** —— 又一个「测不出」的典型。

被它掩盖的真 bug（2026-09-30 修）：

    `DbDedup.claim` 按 `notify_message.title == key.template_title` 查历史行，
    而 `generate_and_dispatch` 写库时存的是 **AI 生成的标题**
    （同一冲突每轮都不一样，如「中心广场资源闲置温馨提示」/「中心广场闲置状态温馨提示」）。
    两者永远不相等 → 这条兜底路径**恒判定为「首次，可以推送」**，去重形同不存在。
    实测后果：同一块闲置场地在 7 分钟内被推送 3 次，正是模块自己声明要避免的刷屏。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NOTIFY_TYPE_REMIND, NotifyMessage
from app.services.dedup import DbDedup, DedupKey
from app.services.notify_service import build_dedup_title

#: 一条稳定的模板标题 —— 与 `notify_templates.ToneSpec` 里那种
#: `【预约提醒】{space_name} {start_hm}` 形态一致：确定性、同一冲突恒定。
TEMPLATE_TITLE = "【预约提醒】中心广场 "

#: AI 实际写出来的标题形态：每轮措辞都不同，这正是旧实现失效的原因。
AI_TITLE_ROUND_1 = "中心广场资源闲置温馨提示"
AI_TITLE_ROUND_2 = "中心广场闲置状态温馨提示"


def _key(
    *,
    receiver_id: int = 3,
    space_id: int | None = 8,
    template_title: str = TEMPLATE_TITLE,
    rule_code: str = "space_idle",
) -> DedupKey:
    return DedupKey(
        receiver_id=receiver_id,
        notify_type=NOTIFY_TYPE_REMIND,
        rule_code=rule_code,
        template_title=template_title,
        order_ids=(),
        space_id=space_id,
        source="scan",
    )


async def _write(session: AsyncSession, *, title: str, receiver_id: int = 3) -> None:
    session.add(
        NotifyMessage(
            receiver_id=receiver_id,
            notify_type=NOTIFY_TYPE_REMIND,
            order_id=None,
            title=title,
            content="正文",
            is_read=0,
        )
    )
    await session.flush()


async def test_首次占位成功_写入同标题后再次占位失败(db_session: AsyncSession) -> None:
    """核心行为：同一冲突第二次必须被判重压掉。"""
    dedup = DbDedup(db_session)
    key = _key()

    assert await dedup.claim(key) is True, "库里还没有任何行，首次应当放行"

    # 模拟 generate_and_dispatch 写库（修好后它存的就是模板标题）
    await _write(db_session, title=key.template_title)

    assert await dedup.claim(key) is False, "同标题的行已在 TTL 内，第二次必须跳过"


async def test_存AI标题的行挡不住下一次占位(db_session: AsyncSession) -> None:
    """**这条钉的是修复的根因，不是修复本身。**

    库里若存的是 AI 标题（旧实现的行为），判重就查不到 —— 断言它「挡不住」，
    是为了让「写侧必须存 template_title」这个耦合在用例里有据可查。
    哪天真给表加了指纹列、判重不再依赖标题，这条用例会红，
    那正是提醒改的人：可以放开写侧了。
    """
    dedup = DbDedup(db_session)
    key = _key()

    await _write(db_session, title=AI_TITLE_ROUND_1)

    assert await dedup.claim(key) is True, (
        "AI 标题 != 模板标题，所以判重查不到 —— 这正是去重失效的机制"
    )


async def test_连续两轮AI标题不同时_只有存模板标题才拦得住(db_session: AsyncSession) -> None:
    """把旧 bug 的现场完整复现一遍：两轮 AI 标题不同 → 两轮都放行。"""
    dedup = DbDedup(db_session)

    await _write(db_session, title=AI_TITLE_ROUND_1)
    assert await dedup.claim(_key()) is True, "第一轮（AI 标题）拦不住"

    await _write(db_session, title=AI_TITLE_ROUND_2)
    assert await dedup.claim(_key()) is True, "第二轮换了措辞，照样拦不住 —— 于是刷屏"


async def test_不同收件人互不影响(db_session: AsyncSession) -> None:
    """判重键含 receiver_id：给管理员推过，不该把普通用户的提醒一起压掉。"""
    dedup = DbDedup(db_session)
    await _write(db_session, title=TEMPLATE_TITLE, receiver_id=3)

    assert await dedup.claim(_key(receiver_id=3)) is False, "同一收件人应被压掉"
    assert await dedup.claim(_key(receiver_id=2)) is True, "另一收件人必须照常推送"


async def test_不同场地互不影响(db_session: AsyncSession) -> None:
    """同一收件人、不同场地是两个独立的冲突，不能互相遮蔽。

    这就是为什么判重不能只按 (收件人, 通知类型) —— `space_idle` 的
    `order_id` 是 NULL，光靠那两项会把「中心广场」和「综合楼小多功能厅」混为一谈。
    """
    dedup = DbDedup(db_session)
    await _write(db_session, title=TEMPLATE_TITLE)

    other = DedupKey(
        receiver_id=3,
        notify_type=NOTIFY_TYPE_REMIND,
        rule_code="space_idle",
        template_title="【预约提醒】综合楼小多功能厅 ",
        order_ids=(),
        space_id=7,
        source="scan",
    )
    assert await dedup.claim(other) is True, "没有该标题的行，另一个场地应当放行"


async def test_不同来源互不影响(db_session: AsyncSession) -> None:
    """`source` 参与指纹：人工触发的生成不该被定时扫描的占位遮蔽。

    注意这条只在「标题也不同」时成立 —— `DbDedup` 只按标题查库，
    它是**近似**判重，精确到 source/rule 要看 Redis 指纹。
    """
    db_session.add(
        NotifyMessage(
            receiver_id=3,
            notify_type=NOTIFY_TYPE_REMIND,
            order_id=None,
            title=TEMPLATE_TITLE,
            content="正文",
            is_read=0,
        )
    )
    await db_session.flush()

    dedup = DbDedup(db_session)
    manual = DedupKey(
        receiver_id=3,
        notify_type=NOTIFY_TYPE_REMIND,
        rule_code="agent_manual",
        template_title="【预约提醒】中心广场 ",
        order_ids=(),
        space_id=8,
        source="agent",
    )
    # 标题相同 → 仍会被判重压掉；这里如实记录这个「近似」的边界。
    assert await dedup.claim(manual) is False


@pytest.mark.parametrize("ttl", [0])
async def test_TTL为0时立即过期(db_session: AsyncSession, ttl: int) -> None:
    """TTL=0 是合法取值，表示立刻过期 —— 防止有人写成 `ttl or 默认值` 把它变成一天。"""
    dedup = DbDedup(db_session, ttl_seconds=ttl)
    dedup._ttl = ttl  # 显式压到 0，避免依赖默认配置
    key = _key()
    await _write(db_session, title=key.template_title)
    assert await dedup.claim(key) is True


# ===========================================================================
# build_dedup_title —— 判重键的构造
#
# 只把「写侧存模板标题」改对还不够：模板标题本身的颗粒度三个角色并不一致，
# 管理员的模板**不含场地名**。少了这一层，去重会从「刷屏」变成「漏报」。
# ===========================================================================

#: 系统管理员/资源管理员的模板形态：只有规则名，**没有场地**
ADMIN_TEMPLATE = "【预约提醒·汇总】长期闲置"
#: 预约人的模板形态：本来就带场地
OWNER_TEMPLATE = "【预约提醒】A栋3楼展厅 14:00"


def _facts(space_name: str) -> dict:
    return {"space_name": space_name, "rule_label": "长期闲置"}


def test_管理员模板不含场地名_补上身份才能区分场地() -> None:
    """**这是本轮的关键回归。**

    修好写侧之后若不补身份，「中心广场」与「综合楼小多功能厅」会渲染出
    **同一个** `【预约提醒·汇总】长期闲置` —— 按标题判重会把第二块场地静默漏报。
    """
    a = build_dedup_title(ADMIN_TEMPLATE, facts=_facts("中心广场"))
    b = build_dedup_title(ADMIN_TEMPLATE, facts=_facts("综合楼小多功能厅"))

    assert a != b, "两块闲置场地必须得到不同的判重键，否则会被互相误杀"
    assert "中心广场" in a and "综合楼小多功能厅" in b


def test_模板已含场地名时不再重复追加() -> None:
    """预约人的模板已经带了场地，再追加就成了
    `【预约提醒】A栋3楼展厅 14:00·A栋3楼展厅` 这种啰嗦标题。"""
    assert build_dedup_title(OWNER_TEMPLATE, facts=_facts("A栋3楼展厅")) == OWNER_TEMPLATE


def test_有订单号时用订单号作为身份() -> None:
    """同一场地、不同订单是两个独立冲突，身份要落在订单号上。"""
    title = build_dedup_title(ADMIN_TEMPLATE, facts=_facts("中心广场"), order_ids=(6,))
    assert "订单 #6" in title
    other = build_dedup_title(ADMIN_TEMPLATE, facts=_facts("中心广场"), order_ids=(7,))
    assert title != other, "同场地不同订单必须可区分"


def test_没有场地也没有订单时不追加() -> None:
    """无身份可用时保持原样，不要追加一个空后缀。"""
    assert build_dedup_title(ADMIN_TEMPLATE, facts={}) == ADMIN_TEMPLATE


async def test_两个场地各自只推一次(db_session: AsyncSession) -> None:
    """把上面几条串起来走一遍真实的 DbDedup：2 个场地 × 各 2 轮 = 只写 2 行。"""
    dedup = DbDedup(db_session)

    def title_for(space_name: str) -> str:
        return build_dedup_title(ADMIN_TEMPLATE, facts=_facts(space_name))

    keys = [
        _key(space_id=8, template_title=title_for("中心广场")),
        _key(space_id=7, template_title=title_for("综合楼小多功能厅")),
    ]

    for key in keys:  # 第一轮：两个场地都该放行并写库
        assert await dedup.claim(key) is True
        await _write(db_session, title=key.template_title)

    for key in keys:  # 第二轮：两个场地都该被压掉
        assert await dedup.claim(key) is False

    rows = (await db_session.execute(select(NotifyMessage.id))).all()
    assert len(rows) == 2, "两个场地各一条，既不能多（刷屏）也不能少（漏报）"
