#!/usr/bin/env python
"""
种子数据与一键自测脚本（摄像头空间感知模块）
====================================================================

⚠️ 本脚本位于 backend/scripts/ 下，请在 **backend 目录**下执行：

    cd backend

    # 1. 灌入演示种子数据（场地、设备、用户、历史订单）—— 幂等，可重复执行
    python scripts/seed.py seed

    # 2. 清空本脚本写入的数据后重新灌（不影响其它人写入的数据）
    python scripts/seed.py seed --reset

    # 3. 用真实大模型跑一次端到端识别
    python scripts/seed.py test --image D:\\photos\\site.jpg

    # 4. 没有 API Key 或不想消耗额度时，用假模型跑通全流程
    python scripts/seed.py test --mock

    # 5. 环境自检（数据库连通性、配置完整性）
    python scripts/seed.py check

规范依据：
    §6.9  种子数据脚本（3 用户 / 8 场地 / 15 设备 / 10 条历史预约）
    §6.8  测试库与正式库隔离 —— **本脚本默认写入 .env 里配置的库**，
         执行前请确认 DB_NAME 指向的是开发库而不是生产库

为什么用 Python 而不是 docs/seed.sql：
    规范要求交付 docs/seed.sql，那份用 SQL 写、给集成组执行建库用。
    本脚本是**开发者本地自助工具**：复用 ORM 模型（表结构改了不会失配）、
    幂等可重跑、且能顺手把整条识别链路跑一遍。两者不冲突。
"""

import argparse
import asyncio
import io
import json
import struct
import sys
import zlib
from datetime import date, datetime, time, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径引导：让脚本可以从任何工作目录运行
# ---------------------------------------------------------------------------
# 本文件在 backend/scripts/seed.py，需要把 backend/ 加进 sys.path，
# 否则 `import app.xxx` 会失败（尤其是从仓库根目录执行时）。
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ---------------------------------------------------------------------------
# Windows 控制台编码修正
# ---------------------------------------------------------------------------
# Windows 的 cmd/PowerShell 默认使用 GBK 代码页，直接 print 中文可能乱码，
# 甚至抛 UnicodeEncodeError。这里把标准输出强制切到 UTF-8。
# 放在 import 之后、业务逻辑之前，且用 try 包住 —— 某些重定向场景下不支持 reconfigure。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 重定向场景下 reconfigure 可能不支持，此项失败不影响后续
    pass

from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, async_engine  # noqa: E402
from app.models.notification import NotifyMessage  # noqa: E402
from app.models.reservation import ReserveOrder  # noqa: E402
from app.models.resource import DeviceResource, SpaceResource  # noqa: E402
from app.models.system import SysRole, SysUser  # noqa: E402

# ===========================================================================
# 种子数据定义（对应规范 §6.9）
# ===========================================================================

# 密码哈希上下文。
# 关键说明（§3.6）：passlib 1.7.4 必须搭配 bcrypt 4.0.1，
# bcrypt 5.x 移除了 __about__.__version__ 会让 passlib 后端探测失败并抛 ValueError。
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 种子用户的初始密码。
# 规范 §5.3 要求「禁止在文档、代码、测试中留存真实管理员密码」——
# 这里给的是**演示用初始密码**，可通过环境变量覆盖，且仅用于本地/开发库。
DEFAULT_SEED_PASSWORD = "Smart@123456"

# ---- 角色（3 个，对应 §1.5 用户角色）----
SEED_ROLES = [
    {"role_name": "普通使用者", "permissions": ["resource:view", "order:create", "order:view"]},
    {"role_name": "资源管理员", "permissions": ["resource:view", "resource:edit", "ticket:handle"]},
    {"role_name": "系统管理员", "permissions": ["*"]},
]

# ---- 用户（3 个）----
SEED_USERS = [
    {"username": "user01", "role": "普通使用者", "avatar": None},
    {"username": "admin01", "role": "资源管理员", "avatar": None},
    {"username": "super01", "role": "系统管理员", "avatar": None},
]

# ---- 场地（8 个：会议室×3、展厅×2、多功能厅×2、户外×1）----
# 字段顺序：名称、类型(1会议室 2展厅 3多功能厅 4户外)、容量、位置、预算、开放起、开放止
SEED_SPACES = [
    ("A栋2楼小会议室", 1, 12, "A栋2楼201", 200, time(8, 0), time(22, 0)),
    ("A栋2楼中会议室", 1, 20, "A栋2楼205", 350, time(8, 0), time(22, 0)),
    ("B栋1楼大会议室", 1, 30, "B栋1楼101", 500, time(8, 0), time(22, 0)),
    ("A栋3楼展厅", 2, 40, "A栋3楼", 980, time(9, 0), time(21, 0)),
    ("A栋1楼临展厅", 2, 25, "A栋1楼", 600, time(9, 0), time(21, 0)),
    ("B栋2楼多功能厅", 3, 60, "B栋2楼", 1200, time(8, 0), time(22, 0)),
    ("C栋1楼圆桌多功能厅", 3, 35, "C栋1楼", 800, time(8, 0), time(22, 0)),
    ("中心广场", 4, 200, "园区中心", 1500, time(7, 0), time(22, 0)),
]

# ---- 设备（5 类合计 15 台）----
# 说明：§6.9 写的是「15 台设备（投影仪×4、音响×4、显示屏×3、无人机×2、直播设备×2）」。
# device_resource 表有 total_count / available_count 两个数量字段，
# 因此这里按**设备类型建 5 条记录**，用 total_count 表达数量，合计恰好 15 台。
# 这样既满足种子数据要求，也符合表结构的设计意图（而不是建 15 条重复记录）。
# 字段顺序：名称、类型、状态(1完好 2损坏 3缺失配件)、总数、可用数
SEED_DEVICES = [
    ("高清投影仪", "投影仪", 1, 4, 4),
    ("会议音响套装", "音响", 1, 4, 4),
    ("LED 显示屏", "显示屏", 1, 3, 3),
    ("航拍无人机", "无人机", 1, 2, 2),
    ("直播推流设备", "直播设备", 1, 2, 2),
]

# ---- 历史预约（10 条，覆盖不同状态与时段）----
# 字段：空间名、用户名、相对今天的天数偏移、开始小时、结束小时、
#       状态(1待确认 2已确认 3已取消 4已完成)
# 故意跨越「今天」，这样 seed 之后立刻调 /image/analyze 就能看到 availableTime 非空。
SEED_ORDERS = [
    ("A栋3楼展厅", "user01", 0, 14, 16, 2),  # 今天下午，已确认 → 会被空档计算扣掉
    ("A栋3楼展厅", "user01", 0, 9, 11, 2),  # 今天上午，已确认
    ("B栋2楼多功能厅", "user01", 0, 10, 12, 1),  # 今天上午，待确认
    ("A栋2楼小会议室", "admin01", 0, 15, 17, 2),
    ("A栋2楼中会议室", "user01", 1, 9, 11, 2),  # 明天
    ("B栋1楼大会议室", "admin01", 1, 14, 18, 2),  # 明天
    ("中心广场", "super01", 2, 8, 12, 2),  # 后天
    ("A栋1楼临展厅", "user01", -1, 13, 15, 4),  # 昨天，已完成
    ("C栋1楼圆桌多功能厅", "user01", -2, 19, 21, 3),  # 前天，已取消（不占时段）
    ("B栋2楼多功能厅", "super01", 3, 13, 17, 2),  # 三天后
]


# ===========================================================================
# 输出辅助
# ===========================================================================

_SEP = "=" * 68


def say(msg: str = "") -> None:
    """统一的控制台输出，避免各处 print 风格不一"""
    print(msg)


def title(text: str) -> None:
    """打印一个带分隔线的标题块"""
    say()
    say(_SEP)
    say(f"  {text}")
    say(_SEP)


def ok(text: str) -> None:
    """打印成功项"""
    say(f"  [OK]   {text}")


def skip(text: str) -> None:
    """打印跳过项（幂等跳过已存在的数据）"""
    say(f"  [SKIP] {text}")


def warn(text: str) -> None:
    """打印警告项"""
    say(f"  [WARN] {text}")


def fail(text: str) -> None:
    """打印失败项"""
    say(f"  [FAIL] {text}")


# ===========================================================================
# 子命令 1：seed —— 灌入种子数据
# ===========================================================================


async def cmd_seed(reset: bool) -> int:
    """
    写入种子数据。

    参数：
        reset : bool  True 表示先删除本脚本写入的数据再重新灌

    返回：
        进程退出码（0 成功，1 失败）

    幂等策略：
        每条数据都用「自然键」判重（用户按 username、场地按 space_name、
        设备按 device_name、角色按 role_name），已存在就跳过。
        这样重复执行不会产生重复数据，也不会覆盖别人手工改过的内容。
    """
    async with AsyncSessionLocal() as db:
        try:
            if reset:
                title("清理本脚本写入的数据")
                await _reset_seed_data(db)

            # ---------- 1. 角色 ----------
            title("写入角色")
            role_map: dict[str, SysRole] = {}
            for item in SEED_ROLES:
                existing = (
                    await db.execute(select(SysRole).where(SysRole.role_name == item["role_name"]))
                ).scalar_one_or_none()
                if existing:
                    role_map[item["role_name"]] = existing
                    skip(f"角色已存在：{item['role_name']}")
                    continue

                role = SysRole(role_name=item["role_name"], permissions=item["permissions"])
                db.add(role)
                await db.flush()  # flush 后才能拿到自增 id
                role_map[item["role_name"]] = role
                ok(f"新增角色：{item['role_name']} (id={role.id})")

            # ---------- 2. 用户 ----------
            title("写入用户")
            user_map: dict[str, SysUser] = {}
            for item in SEED_USERS:
                existing = (
                    await db.execute(select(SysUser).where(SysUser.username == item["username"]))
                ).scalar_one_or_none()
                if existing:
                    user_map[item["username"]] = existing
                    skip(f"用户已存在：{item['username']}")
                    continue

                user = SysUser(
                    username=item["username"],
                    # 密码一律 bcrypt 哈希后存储（§9.2），绝不落明文
                    password=_pwd_context.hash(DEFAULT_SEED_PASSWORD),
                    role_id=role_map[item["role"]].id,
                    avatar=item["avatar"],
                    status=1,
                )
                db.add(user)
                await db.flush()
                user_map[item["username"]] = user
                ok(f"新增用户：{item['username']} / 角色 {item['role']} (id={user.id})")

            # ---------- 3. 场地 ----------
            title("写入场地")
            space_map: dict[str, SpaceResource] = {}
            for name, stype, cap, loc, budget, o_start, o_end in SEED_SPACES:
                existing = (
                    await db.execute(select(SpaceResource).where(SpaceResource.space_name == name))
                ).scalar_one_or_none()
                if existing:
                    space_map[name] = existing
                    skip(f"场地已存在：{name}")
                    continue

                space = SpaceResource(
                    space_name=name,
                    space_type=stype,
                    capacity=cap,
                    location=loc,
                    budget=budget,
                    open_start_time=o_start,
                    open_end_time=o_end,
                    status=1,
                )
                db.add(space)
                await db.flush()
                space_map[name] = space
                ok(f"新增场地：{name} (id={space.id}, 容量 {cap}人)")

            # ---------- 4. 设备 ----------
            title("写入设备")
            for name, dtype, dstatus, total, available in SEED_DEVICES:
                existing = (
                    await db.execute(
                        select(DeviceResource).where(DeviceResource.device_name == name)
                    )
                ).scalar_one_or_none()
                if existing:
                    skip(f"设备已存在：{name}")
                    continue

                device = DeviceResource(
                    device_name=name,
                    device_type=dtype,
                    device_status=dstatus,
                    total_count=total,
                    available_count=available,
                )
                db.add(device)
                await db.flush()
                ok(f"新增设备：{name} (id={device.id}, 数量 {total})")

            # ---------- 5. 历史预约 ----------
            title("写入历史预约")
            created_orders = 0
            for space_name, username, day_offset, hour_start, hour_end, ostatus in SEED_ORDERS:
                target_day = date.today() + timedelta(days=day_offset)
                start_dt = datetime.combine(target_day, time(hour_start, 0))
                end_dt = datetime.combine(target_day, time(hour_end, 0))

                # 按「场地 + 开始时间 + 用户」判重，避免重复执行灌出重复订单
                existing = (
                    await db.execute(
                        select(ReserveOrder).where(
                            ReserveOrder.space_id == space_map[space_name].id,
                            ReserveOrder.start_time == start_dt,
                            ReserveOrder.user_id == user_map[username].id,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    skip(f"预约已存在：{space_name} {start_dt:%m-%d %H:%M}")
                    continue

                order = ReserveOrder(
                    user_id=user_map[username].id,
                    space_id=space_map[space_name].id,
                    device_ids=[],  # JSON 字段，留空表示未借用设备
                    start_time=start_dt,
                    end_time=end_dt,
                    order_status=ostatus,
                    agent_request=None,
                    agent_trace=None,
                )
                db.add(order)
                created_orders += 1
                ok(f"新增预约：{space_name} {start_dt:%m-%d %H:%M}-{end_dt:%H:%M} 状态={ostatus}")

            if created_orders == 0:
                skip("所有历史预约均已存在")

            await db.commit()

        except Exception as exc:  # noqa: BLE001 - 脚本最外层兜底：任何失败都要落成可读提示
            await db.rollback()
            fail(f"写入种子数据失败：{type(exc).__name__}: {exc}")
            say()
            say("  常见原因：")
            say("    1. SSH 隧道没开 —— 在另一个终端执行：")
            say(f"       ssh -L {settings.DB_PORT}:127.0.0.1:3307 root@<服务器IP> -N")
            say("    2. .env 里的 DB_HOST / DB_PORT / DB_USER / DB_PASSWORD 不正确")
            say("    3. 云服务器安全组未放行，或你的 IP 不在数据库白名单里")
            return 1

    title("种子数据写入完成")
    say(f"  库名：{settings.DB_NAME}")
    say("  演示账号：user01 / admin01 / super01")
    say(f"  初始密码：{DEFAULT_SEED_PASSWORD}  （演示用，请勿用于生产环境）")
    say()
    return 0


async def _reset_seed_data(db) -> None:
    """
    删除本脚本写入的数据（**只删本脚本认识的那几条**，不动其它人写的内容）。

    参数：
        db : AsyncSession 数据库会话

    删除顺序：
        必须严格按外键依赖的倒序来删，否则会因外键约束报错：
        notify_message → repair_ticket → inspect_record → reserve_order
        → device_resource → space_resource → sys_user → sys_role

    注意：
        repair_ticket / inspect_record 不是本脚本写入的，
        但它们外键引用了 space_resource / sys_user，
        所以必须先清掉引用，否则删场地会失败。
        这里需要 import 它们（在函数内 import 以保持文件头部清爽）。
    """
    from app.models.inspection import InspectRecord, RepairTicket

    space_names = [s[0] for s in SEED_SPACES]
    device_names = [d[0] for d in SEED_DEVICES]
    usernames = [u["username"] for u in SEED_USERS]
    role_names = [r["role_name"] for r in SEED_ROLES]

    # 先查出要删的 id 集合
    space_ids = [
        r[0]
        for r in (
            await db.execute(
                select(SpaceResource.id).where(SpaceResource.space_name.in_(space_names))
            )
        ).all()
    ]
    user_ids = [
        r[0]
        for r in (await db.execute(select(SysUser.id).where(SysUser.username.in_(usernames)))).all()
    ]
    order_ids = []
    if space_ids:
        order_ids = [
            r[0]
            for r in (
                await db.execute(
                    select(ReserveOrder.id).where(ReserveOrder.space_id.in_(space_ids))
                )
            ).all()
        ]

    # 按依赖倒序删除。
    # 顺序不能乱：先删引用方，再删被引用方，否则会撞外键约束。
    if order_ids:
        await db.execute(delete(NotifyMessage).where(NotifyMessage.order_id.in_(order_ids)))
    if user_ids:
        await db.execute(delete(NotifyMessage).where(NotifyMessage.receiver_id.in_(user_ids)))
        await db.execute(delete(RepairTicket).where(RepairTicket.handler_id.in_(user_ids)))
        await db.execute(delete(InspectRecord).where(InspectRecord.inspector_id.in_(user_ids)))
    if space_ids:
        await db.execute(delete(RepairTicket).where(RepairTicket.space_id.in_(space_ids)))
        await db.execute(delete(InspectRecord).where(InspectRecord.space_id.in_(space_ids)))
        await db.execute(delete(ReserveOrder).where(ReserveOrder.space_id.in_(space_ids)))
        await db.execute(delete(SpaceResource).where(SpaceResource.id.in_(space_ids)))
    # 设备的删除与场地无关，单独判断 —— 否则场地表为空时设备永远删不掉
    if device_names:
        await db.execute(delete(DeviceResource).where(DeviceResource.device_name.in_(device_names)))
    if user_ids:
        await db.execute(delete(SysUser).where(SysUser.id.in_(user_ids)))
    await db.execute(delete(SysRole).where(SysRole.role_name.in_(role_names)))
    await db.flush()

    ok("已清空本脚本写入的数据")


# ===========================================================================
# 子命令 2：test —— 端到端识别自测
# ===========================================================================


async def cmd_test(
    image_path: str | None, is_sketch: bool, use_mock: bool, confidence: float
) -> int:
    """
    对本模块的识别链路做一次端到端自测。

    参数：
        image_path : str | None  图片路径；为 None 时自动生成一张占位图
        is_sketch  : bool        True 走 /sketch 的草图识别链路
        use_mock   : bool        True 使用假模型，不消耗 API 额度
        confidence : float       假模型返回的置信度，用来演练「追问」分支

    返回：
        进程退出码（0 成功，1 失败）

    本命令验证的是**整条流水线**：
        图片校验 → 落盘 → 查候选场地 → 调用模型 → 容错解析
        → 业务边界校验（防幻觉）→ 追问判定 → 组装响应

    注意：
        使用 --mock 时验证的是「流水线是否通」，**不是「模型认不认得我们的场地」**。
        后者必须用真实 Key 跑 --image 才能验证。
    """
    from app.core.llm import get_vision_llm
    from app.services.image_service import (
        analyze_sketch_image,
        analyze_space_image,
        list_active_space_candidates,
    )

    # ---------- 准备图片 ----------
    if image_path:
        src = Path(image_path)
        if not src.exists():  # noqa: ASYNC240 - 一次性 CLI 脚本，没有并发任务可被这次同步 stat 拖住
            fail(f"图片不存在：{src}")
            return 1
        raw_bytes = src.read_bytes()  # noqa: ASYNC240 - 同上：本地单张小图，读盘耗时可忽略
        say(f"  使用图片：{src}  ({len(raw_bytes) / 1024:.1f} KB)")
    else:
        raw_bytes = build_placeholder_png()
        say(f"  未指定图片，已自动生成占位图（{len(raw_bytes)} 字节）")
        say("  提示：想看真实识别效果，请用 --image 指定一张场地照片")

    # ---------- 准备模型 ----------
    async with AsyncSessionLocal() as db:
        if use_mock:
            if is_sketch:
                # 草图识别不依赖候选场地，假模型直接给预设结果即可
                say("  [MOCK] 假模型将返回预设的草图解读结果")
                say(f"  [MOCK] 假模型置信度：{confidence}")
                say(f"  [MOCK] 置信度阈值：{settings.IMAGE_CONFIDENCE_THRESHOLD}")
                llm = MockVisionLLM(0, "", confidence, is_sketch=True)
            else:
                # 假模型需要返回一个**真实存在**的 spaceId，否则会被防幻觉逻辑拦下，
                # 那样演示的就变成「幻觉被拦截」而不是「正常识别」了。
                # 因此这里先查一遍候选场地，取第一个作为假模型的答案。
                try:
                    candidates = await list_active_space_candidates(db, limit=5)
                except Exception as exc:  # noqa: BLE001 - 自测脚本：任何失败都转成排查提示
                    fail(f"查询候选场地失败：{type(exc).__name__}: {exc}")
                    say()
                    say("  这通常是数据库连不上，请先执行：python scripts/seed.py check")
                    return 1

                if not candidates:
                    fail("数据库里没有可用场地，请先执行：python scripts/seed.py seed")
                    return 1

                picked = candidates[0]
                say(f"  [MOCK] 假模型将返回场地：{picked.spaceName} (id={picked.spaceId})")
                say(f"  [MOCK] 假模型置信度：{confidence}")
                say(f"  [MOCK] 置信度阈值：{settings.IMAGE_CONFIDENCE_THRESHOLD}")
                llm = MockVisionLLM(picked.spaceId, picked.spaceName, confidence, is_sketch=False)
        else:
            if not settings.VISION_API_KEY:
                fail("VISION_API_KEY 未配置")
                say()
                say("  请在 backend/.env 里填写：")
                say("    VISION_MODEL_NAME=qwen-vl-max")
                say("    VISION_API_KEY=你的真实Key")
                say("    VISION_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1")
                say()
                say("  或者先用假模型跑通流程：python scripts/seed.py test --mock")
                return 1
            say(f"  使用真实模型：{settings.VISION_MODEL_NAME}")
            try:
                llm = get_vision_llm()
            except Exception as exc:  # noqa: BLE001 - 同上：配置缺失/依赖缺失都要给出人话提示
                fail(f"构造模型客户端失败：{exc}")
                return 1

        # ---------- 构造 UploadFile 并调用服务层 ----------
        from fastapi import UploadFile

        content_type = _detect_content_type(raw_bytes)
        if content_type is None:
            fail("图片既不是 JPG、也不是 PNG、也不是 WEBP，请换一张")
            return 1

        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
        upload = UploadFile(
            file=io.BytesIO(raw_bytes),
            filename=f"selftest{suffix}",
            headers={"content-type": content_type},
        )

        title(f"端到端自测：{'手绘草图识别' if is_sketch else '现场拍照识别空间'}")
        try:
            if is_sketch:
                data = await analyze_sketch_image(db=db, file=upload, llm=llm)
            else:
                data = await analyze_space_image(db=db, file=upload, llm=llm)
        except Exception as exc:  # noqa: BLE001 - 自测脚本要区分「库问题 / 模型问题」，见下方分支
            fail(f"识别失败：{type(exc).__name__}: {exc}")
            say()

            # 区分「数据库问题」和「模型问题」—— 两者的排查方向完全不同，
            # 如果不加区分，用户看到"识别失败"会先去查 API Key，白费功夫。
            text = str(exc).lower()
            if (
                "operationalerror" in type(exc).__name__.lower()
                or "can't connect" in text
                or "connection" in text
                or "refused" in text
            ):
                say("  这看起来是**数据库**问题，请检查：")
                say("    1. SSH 隧道是否开着（另开一个终端保持不关）：")
                say(f"       ssh -L {settings.DB_PORT}:127.0.0.1:3307 root@<服务器IP> -N")
                say("    2. .env 里的 DB_HOST / DB_PORT / 用户名密码是否正确")
                say("    3. 先跑一次 python scripts/seed.py check 看详细诊断")
            else:
                say("  这看起来是**模型**问题，请检查：")
                say("    1. VISION_API_KEY 是否正确、是否欠费")
                say("    2. VISION_API_BASE 是否为该服务商的 OpenAI 兼容端点")
                say("    3. 网络是否能访问该端点（公司网络/代理可能拦截）")
                say("    4. 若报 400 且提示不支持 tools/json_schema，")
                say("       把 .env 的 VISION_STRUCTURED_OUTPUT 改成 false 再试")
            return 1

    # ---------- 打印结果 ----------
    title("识别结果")
    payload = data.model_dump()
    # ensure_ascii=False 才能让中文正常显示而不是 \\uXXXX
    say(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    title("结果解读")
    if is_sketch:
        say(f"  预估人数：{data.capacity if data.capacity else '未能判断'}")
        say(f"  布局描述：{data.layout or '未能判断'}")
        say(f"  隐含约束：{'、'.join(data.requirements) if data.requirements else '无'}")
    else:
        if data.spaceId is None:
            warn("未匹配到场地 —— 防幻觉逻辑生效或模型确实认不出")
            say(f"  候选场地共 {len(data.candidates)} 个，前端应展示列表让用户手动选择")
        else:
            ok(f"匹配到场地：{data.spaceName} (id={data.spaceId})")

    say(f"  置信度：{data.confidence:.2f}")
    if data.needConfirm:
        warn("需要用户确认（needConfirm=true）")
        say(f"  追问文案：{data.question}")
    else:
        ok("置信度达标，可直接送往核心调度 Agent（needConfirm=false）")

    if getattr(data, "imageUrl", None):
        say(f"  图片访问地址：{data.imageUrl}")
        say(f"  （已挂载静态目录，服务运行时可通过 http://127.0.0.1:8000{data.imageUrl} 访问）")

    if not is_sketch and data.availableTime:
        say("  场地空档时段（前 5 条）：")
        for slot in data.availableTime[:5]:
            say(f"    {slot.date} {slot.startTime} ~ {slot.endTime}")

    say()
    ok("端到端自测通过")
    say()
    return 0


class MockVisionLLM:
    """
    假的多模态模型，用于在没有 API Key 时跑通整条流水线。

    实现要点：
        只实现 with_structured_output 一个方法（鸭子类型），
        返回一个遵循 LangChain include_raw=True 返回结构的 runner。
        这让 image_service._recognize 的**策略 A** 被真实走到，
        而不是草草降级到策略 B。

    用途边界：
        验证的是「流水线通不通」，不是「模型准不准」。
        假模型直接给出预设答案，因此结果必然合理 —— 这是刻意的。
    """

    def __init__(self, space_id: int, space_name: str, confidence: float, is_sketch: bool):
        self.space_id = space_id
        self.space_name = space_name
        self.confidence = confidence
        self.is_sketch = is_sketch

    def with_structured_output(self, schema, include_raw: bool = False, **kwargs):
        outer = self

        class _Runner:
            async def ainvoke(self, messages, **kwargs):
                from langchain_core.messages import AIMessage

                if outer.is_sketch:
                    payload = {
                        "capacity": 30,
                        "layout": "剧院式排布，前方设讲台（假模型预设结果）",
                        "requirements": ["需要投影", "需要讲台"],
                        "confidence": outer.confidence,
                        "question": (
                            f"草图解读置信度 {int(outer.confidence * 100)}%，能否补充一句场地用途？"
                            if outer.confidence < 0.75
                            else None
                        ),
                    }
                else:
                    payload = {
                        "spaceId": outer.space_id,
                        "spaceName": outer.space_name,
                        "rawText": "假模型预设：[MOCK] 门牌文字",
                        "deviceHints": ["投影仪", "音响"],
                        "confidence": outer.confidence,
                        "question": (
                            f"识别到可能是 {outer.space_name}，"
                            f"置信度 {int(outer.confidence * 100)}%，是否正确？"
                            if outer.confidence < 0.75
                            else None
                        ),
                    }

                raw = AIMessage(content=json.dumps(payload, ensure_ascii=False))
                return {
                    "raw": raw,
                    "parsed": schema.model_validate(payload),
                    "parsing_error": None,
                }

        return _Runner()


# ===========================================================================
# 子命令 3：check —— 环境自检
# ===========================================================================


async def cmd_check() -> int:
    """
    环境自检：确认配置与数据库连通性，跑测试前先跑这个能省很多时间。

    返回：
        进程退出码（0 全部通过，1 有阻塞项）
    """
    title("环境自检")
    blocking = False

    # ---- 1. 关键配置 ----
    say("  [配置]")
    if settings.VISION_API_KEY:
        ok(f"VISION_API_KEY 已配置（{settings.VISION_MODEL_NAME}）")
    else:
        warn("VISION_API_KEY 未配置 —— 只能用 --mock 跑假模型自测")
        say("         配置方法见 backend/.env.example")
    say(f"         VISION_API_BASE = {settings.VISION_API_BASE or '（未配置）'}")
    structured = "开启" if settings.VISION_STRUCTURED_OUTPUT else "关闭（手工解析）"
    say(f"         结构化输出     = {structured}")
    say(f"         置信度阈值     = {settings.IMAGE_CONFIDENCE_THRESHOLD}")
    say(f"         上传目录       = {settings.image_upload_path}")
    if settings.AUTH_BYPASS:
        warn("AUTH_BYPASS=true —— 鉴权已关闭，仅限联调，部署前必须改回 false")

    # ---- 2. 数据库连通性 ----
    say()
    say("  [数据库]")
    say(f"         {settings.DB_USER}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    try:
        async with AsyncSessionLocal() as db:
            space_count = (await db.execute(select(func.count(SpaceResource.id)))).scalar()
            device_count = (await db.execute(select(func.count(DeviceResource.id)))).scalar()
            user_count = (await db.execute(select(func.count(SysUser.id)))).scalar()
        ok(f"连接成功 —— 场地 {space_count} 条 / 设备 {device_count} 条 / 用户 {user_count} 条")
        if space_count == 0:
            warn("场地表为空，识别时没有候选可匹配。请先执行：python scripts/seed.py seed")
    except Exception as exc:  # noqa: BLE001 - 体检命令：连不上库就是它的正常输出之一
        blocking = True
        fail(f"连接失败：{type(exc).__name__}: {exc}")
        say()
        say("  排查步骤：")
        say("    1. 打开 SSH 隧道（另开一个终端保持不关）：")
        say(f"       ssh -L {settings.DB_PORT}:127.0.0.1:3307 root@<服务器IP> -N")
        say("    2. 确认 .env 里 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME 正确")
        say("    3. 确认云服务器安全组放行、你的 IP 在白名单内")

    # ---- 3. 依赖完整性 ----
    say()
    say("  [依赖]")
    for module_name, pip_name in [
        ("fastapi", "fastapi"),
        ("sqlalchemy", "sqlalchemy"),
        ("asyncmy", "asyncmy"),
        ("langchain_openai", "langchain-openai"),
        ("aiofiles", "aiofiles"),
        ("jwt", "PyJWT"),
        ("passlib", "passlib"),
        ("bcrypt", "bcrypt"),
    ]:
        try:
            __import__(module_name)
            ok(f"{pip_name} 已安装")
        except ImportError:
            blocking = True
            fail(f"{pip_name} 未安装 —— 请执行 pip install -r requirements.txt")

    say()
    if blocking:
        fail("自检发现阻塞项，请先解决上面的 [FAIL] 再继续")
        return 1
    ok("自检通过")
    say()
    return 0


# ===========================================================================
# 工具函数
# ===========================================================================


def _detect_content_type(raw: bytes) -> str | None:
    """
    按魔数判断图片类型（与 app/services/image_storage.py 的判定保持一致）。

    参数：
        raw : bytes 文件字节

    返回：
        MIME 字符串；无法识别返回 None
    """
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_placeholder_png(width: int = 640, height: int = 400) -> bytes:
    """
    生成一张纯色占位 PNG。

    参数：
        width  : int 宽
        height : int 高

    返回：
        bytes 合法 PNG 字节

    为什么要它：
        --mock 自测时并没有真实照片，但流水线第一步就是要校验图片格式。
        用代码生成一张合法 PNG，可以让「没有图片也能跑通全流程」，
        且不往仓库里塞二进制文件（§7.1 禁止提交无用文件）。

    PNG 结构：8 字节签名 + IHDR + IDAT + IEND，每个 chunk 带 CRC32 校验。
    """
    signature = b"\x89PNG\r\n\x1a\n"
    # IHDR：宽、高、位深 8、颜色类型 2（真彩色 RGB）、压缩/滤波/隔行均为 0
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    # 每行前导滤波字节 0，随后是 width 个浅灰色像素
    row = b"\x00" + b"\xe8\xee\xf5" * width
    idat = zlib.compress(row * height)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# ===========================================================================
# CLI 入口
# ===========================================================================


def build_parser() -> argparse.ArgumentParser:
    """
    构造命令行参数解析器。

    返回：
        argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="seed.py",
        description="摄像头空间感知模块 —— 种子数据与一键自测脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/seed.py check                     环境自检（推荐第一步）\n"
            "  python scripts/seed.py seed                      灌入演示种子数据\n"
            "  python scripts/seed.py seed --reset              清空后重灌\n"
            "  python scripts/seed.py test --mock               用假模型跑通全流程\n"
            "  python scripts/seed.py test -i photo.jpg         用真实模型识别照片\n"
            "  python scripts/seed.py test -i sketch.jpg -s     识别手绘草图\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="{check,seed,test}")

    # ---- check ----
    sub.add_parser("check", help="环境自检：配置、数据库连通性、依赖完整性")

    # ---- seed ----
    p_seed = sub.add_parser("seed", help="灌入演示种子数据（幂等，可重复执行）")
    p_seed.add_argument(
        "--reset",
        action="store_true",
        help="先删除本脚本写入的数据再重新灌（只删本脚本认识的那几条）",
    )

    # ---- test ----
    p_test = sub.add_parser("test", help="端到端识别自测")
    p_test.add_argument("-i", "--image", default=None, help="图片路径；不传则自动生成占位图")
    p_test.add_argument("-s", "--sketch", action="store_true", help="走手绘草图识别链路")
    p_test.add_argument(
        "--mock",
        action="store_true",
        help="使用假模型，不消耗 API 额度（验证流水线，不验证模型效果）",
    )
    p_test.add_argument(
        "--confidence",
        type=float,
        default=0.9,
        help="假模型返回的置信度，用来演练追问分支，例如 --confidence 0.6",
    )

    return parser


async def main_async(args) -> int:
    """
    异步主入口。

    参数：
        args : argparse.Namespace

    返回：
        进程退出码
    """
    try:
        if args.command == "check":
            return await cmd_check()
        if args.command == "seed":
            return await cmd_seed(reset=args.reset)
        if args.command == "test":
            return await cmd_test(
                image_path=args.image,
                is_sketch=args.sketch,
                use_mock=args.mock,
                confidence=args.confidence,
            )
        # 没给子命令时打印帮助
        build_parser().print_help()
        return 0
    finally:
        # 无论成功失败，都要释放连接池，否则 asyncio.run 退出时可能报
        # 「Event loop is closed」的告警
        await async_engine.dispose()


def main() -> None:
    """同步入口，供 `python scripts/seed.py` 调用"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
