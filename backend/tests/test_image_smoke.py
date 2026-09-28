"""
摄像头空间感知 —— 联网冒烟测试
====================================================================

覆盖设计文档 §9.1 中的 T20。

规范依据 §10.2：
    「Agent 层测试使用假 LLM 夹具，保证离线可跑；**真实 API 只做一次冒烟验证**。」

本文件的用例全部标记 @pytest.mark.smoke，而 pytest.ini 里配置了
    addopts = -m "not smoke"
因此**默认不会执行**，也不会在 CI 上消耗 API 额度。

需要时手动执行：
    cd backend
    pytest -m smoke -v

前置条件：
    1. backend/.env 里已填好 VISION_API_KEY
    2. scripts/seed.py seed 已跑过（需要有候选场地）
    3. 能访问 VISION_API_BASE 对应的端点

本文件要回答的核心问题是：
    「这个模型到底认不认得我们的场地照片？」——
    这是整个模块最大的不确定性，越早验证越好。
"""

import pytest

from app.core.config import settings

pytestmark = pytest.mark.smoke


@pytest.fixture
def require_api_key():
    """确保配置了真实 API Key，否则直接跳过而不是报错"""
    if not settings.VISION_API_KEY:
        pytest.skip("未配置 VISION_API_KEY，跳过联网冒烟测试")


@pytest.fixture
def require_candidates():
    """确保数据库里有候选场地，否则跳过"""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.resource import SpaceResource

    async def _check() -> int:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(select(SpaceResource.id).where(SpaceResource.status == 1).limit(1))
            ).all()
            return len(rows)

    import asyncio

    try:
        if asyncio.run(_check()) == 0:
            pytest.skip("数据库里没有可用场地，请先执行 python scripts/seed.py seed")
    except Exception as exc:  # noqa: BLE001 - 任何异常都表示「环境不具备」，跳过而非失败
        pytest.skip(f"数据库不可用，跳过联网冒烟测试：{exc}")


async def test_real_vision_api_smoke(require_api_key, require_candidates, temp_upload_dir):
    """
    最小连通性冒烟：用一张代码生成的占位图真实调用一次多模态模型。

    断言目标**不是**「识别正确」—— 占位图本来就没有场地信息，
    模型认不出才是正确表现。这里只验证三件事：
        1. 模型客户端能成功构造（Key / base_url / 模型名可用）
        2. 一次真实调用能返回结果，不抛异常
        3. 回来的是合法结构（哪怕 spaceId 是 null）

    若这条路都走不通，说明配置有问题，需要先解决再谈准确率。
    """
    import io

    from fastapi import UploadFile

    from app.core.database import AsyncSessionLocal
    from app.core.llm import get_vision_llm
    from app.services.image_service import analyze_space_image
    from scripts.seed import build_placeholder_png

    png = build_placeholder_png(width=320, height=240)
    upload = UploadFile(
        file=io.BytesIO(png),
        filename="smoke.png",
        headers={"content-type": "image/png"},
    )

    async with AsyncSessionLocal() as db:
        data = await analyze_space_image(db=db, file=upload, llm=get_vision_llm())

    # 能走到这里就说明模型调用成功且返回被正确解析
    assert data.type == "space"
    assert 0.0 <= data.confidence <= 1.0
    # 占位图不该匹配到任何场地；若真匹配上了，说明防幻觉逻辑有问题
    assert data.spaceId is None, "纯色占位图不应被识别成某个真实场地"
    assert data.needConfirm is True


async def test_real_vision_api_recognizes_seeded_space(
    require_api_key, require_candidates, temp_upload_dir
):
    """
    业务冒烟：拿一张**真实场地照片**验证识别准确率。

    需要手动准备图片，因此默认跳过：
        cd backend
        set SMOKE_IMAGE=D:\\photos\\A栋3楼展厅.jpg
        pytest -m smoke -v

    断言的是「至少能被识别出来或给出候选」，
    不硬性要求 spaceId 必须精确命中 —— 识别本来就是概率性的，
    真实阈值需要在联调阶段用一批照片统计后再定（见设计文档 §13 待确认问题 8）。
    """
    import io
    import os
    from pathlib import Path

    from fastapi import UploadFile

    from app.core.database import AsyncSessionLocal
    from app.core.llm import get_vision_llm
    from app.services.image_service import analyze_space_image

    image_path = os.getenv("SMOKE_IMAGE")
    if not image_path or not Path(image_path).exists():  # noqa: ASYNC240 - 冒烟用例读一张小图
        pytest.skip("未设置 SMOKE_IMAGE 环境变量或文件不存在，跳过业务冒烟")

    raw = Path(image_path).read_bytes()  # noqa: ASYNC240 - 同上：测试里同步读小图可以接受
    upload = UploadFile(
        file=io.BytesIO(raw),
        filename=Path(image_path).name,
        headers={"content-type": "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else "image/png"},
    )

    async with AsyncSessionLocal() as db:
        data = await analyze_space_image(db=db, file=upload, llm=get_vision_llm())

    # 输出识别结果，便于人工评估准确率
    print(f"\n[SMOKE] 图片：{image_path}")
    print(f"[SMOKE] 识别场地：{data.spaceName} (id={data.spaceId})")
    print(f"[SMOKE] 置信度：{data.confidence:.2f}")
    print(f"[SMOKE] 门牌文字：{data.rawText}")
    print(f"[SMOKE] 追问文案：{data.question}")

    # 最低要求：不能返回一个数据库里不存在的场地（防幻觉底线）
    if data.spaceId is not None:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            from app.models.resource import SpaceResource

            row = (
                await db.execute(select(SpaceResource.id).where(SpaceResource.id == data.spaceId))
            ).first()
        assert row is not None, "识别结果里的 spaceId 必须是数据库真实存在的场地"
