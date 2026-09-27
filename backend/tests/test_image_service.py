"""
摄像头空间感知 —— 服务层单元测试
====================================================================

覆盖设计文档 §9.1 用例清单中的 T01–T10、T15–T17。

**不连数据库、不联网**：
    - 候选场地查询通过 monkeypatch 替换成固定数据
    - 模型调用通过 tests/conftest.py 里的假模型替换
    - 落盘目录通过 temp_upload_dir 重定向到临时目录

真实数据库的全链路联调放在接口级测试里（使用独立测试库 smart_scheduler_test），
真实大模型 API 只做一次冒烟验证（标记 @pytest.mark.smoke，默认跳过）。
"""
import pytest

from app.core.config import settings
from app.schemas.image import SpaceCandidate
from app.services import image_service
from app.services.image_service import (
    ImageRecognitionError,
    _clamp01,
    _clean_str_list,
    _extract_json,
    _match_candidate,
    _normalize_message_text,
    analyze_sketch_image,
    analyze_space_image,
)
from app.schemas.image import SpaceRecognition

# ===========================================================================
# 公共夹具
# ===========================================================================

# 与 seed 数据保持一致的测试候选场地（id 101/102 便于断言）
CANDIDATE_A = SpaceCandidate(
    spaceId=101, spaceName="A栋3楼展厅", spaceType=2, location="A栋3楼", capacity=40
)
CANDIDATE_B = SpaceCandidate(
    spaceId=102, spaceName="B栋2楼多功能厅", spaceType=3, location="B栋2楼", capacity=60
)


@pytest.fixture
def patch_candidates(monkeypatch):
    """把候选场地查询替换成固定数据，测试不碰数据库"""

    async def _fake(db, limit=None):
        return [CANDIDATE_A, CANDIDATE_B]

    monkeypatch.setattr(image_service, "list_active_space_candidates", _fake)


@pytest.fixture(autouse=True)
def _disable_slots(monkeypatch):
    """
    关闭空档时段计算。

    autouse=True 让它对所有用例自动生效 —— 空档计算要查 reserve_order 表，
    而单元测试里没有数据库，关掉可以让每个用例只剩「解析 + 校验 + 降级」这条主线。
    """
    monkeypatch.setattr(settings, "IMAGE_ENABLE_AVAILABLE_SLOTS", False)


# ===========================================================================
# T01 / T02：正常识别与追问判定
# ===========================================================================


async def test_high_confidence_success(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T01：高置信度正常识别，不应触发追问，且场地信息取自数据库"""
    llm = fake_llm([
        '{"spaceId": 101, "spaceName": "A栋3楼展厅", "rawText": "A-3F 展厅", '
        '"deviceHints": ["投影仪", "音响"], "confidence": 0.92, "question": null}'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.type == "space"
    assert data.spaceId == 101
    assert data.spaceName == "A栋3楼展厅"
    assert data.confidence == pytest.approx(0.92)
    assert data.needConfirm is False
    assert data.question is None
    assert data.rawText == "A-3F 展厅"
    assert [d.deviceType for d in data.devices] == ["投影仪", "音响"]
    # 命中时不需要回传候选列表，减小载荷
    assert data.candidates == []
    # 图片正常落盘
    assert data.imageUrl is not None


async def test_low_confidence_triggers_question(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T02：置信度低于阈值 → needConfirm=true，且追问文案含场地名与百分比"""
    llm = fake_llm([
        '{"spaceId": 101, "spaceName": "A栋3楼展厅", "confidence": 0.65, "question": null}'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 101
    assert data.needConfirm is True
    # 模型没给 question，后端用模板兜底
    assert data.question is not None
    assert "A栋3楼展厅" in data.question
    assert "65%" in data.question
    # 需要确认时必须回传候选列表，供用户改选
    assert len(data.candidates) == 2


async def test_model_generated_question_is_preferred(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """模型自己生成了追问文案时，应优先采用模型版本（§4.4：AI 主动生成追问文案）"""
    model_question = "这张照片看着像 A栋3楼展厅，我只有六成把握，是这里吗？"
    llm = fake_llm([
        '{"spaceId": 101, "spaceName": "A栋3楼展厅", "confidence": 0.6, '
        f'"question": "{model_question}"}}'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.question == model_question


# ===========================================================================
# T03 / T04 / T05：JSON 容错解析（§10.2 硬性要求覆盖的降级用例）
# ===========================================================================


async def test_non_json_reply_degrades_gracefully(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T03：模型返回大白话 → 降级为友好提示，**绝不抛异常**"""
    llm = fake_llm(["抱歉，我无法看清这张照片，建议你重新拍摄一张更清晰的照片。"])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId is None
    assert data.spaceName is None
    assert data.confidence == 0.0
    assert data.needConfirm is True
    assert data.question                      # 必须有引导语
    assert len(data.candidates) == 2          # 给出候选让用户手动选
    assert data.imageUrl is not None          # 落盘与识别解耦，图片照常保存


async def test_markdown_fenced_json_is_parsed(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T04：模型用 ```json 围栏包裹 → 能正确剥离并解析成功"""
    llm = fake_llm([
        '好的，我分析完了：\n```json\n'
        '{"spaceId": 102, "spaceName": "B栋2楼多功能厅", "confidence": 0.88}\n'
        '```\n希望对你有帮助。'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 102
    assert data.confidence == pytest.approx(0.88)
    assert data.needConfirm is False


async def test_json_wrapped_in_chatter_is_parsed(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T05：JSON 前后夹带寒暄语 → 正则截取花括号后解析成功"""
    llm = fake_llm([
        '根据照片判断，结果如下：{"spaceId": 101, "confidence": 0.9} 以上是我的判断。'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 101
    assert data.confidence == pytest.approx(0.9)


# ===========================================================================
# T06 / T07：防幻觉（§9.3 的核心用例）
# ===========================================================================


async def test_hallucinated_space_id_is_rejected(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """
    T06：模型编造了不存在的 spaceId=999 → 必须被后端拦下。

    这是整个模块**最重要的安全用例**：
    §9.3「图像识别只做业务需求解析，业务真实性由后端校验」
    §13 「大模型幻觉，编造不存在的场地设备」
    """
    llm = fake_llm([
        '{"spaceId": 999, "spaceName": "火星会议室", "confidence": 0.99, "question": null}'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId is None            # 幻觉 id 被丢弃
    assert data.spaceName is None
    assert data.confidence == 0.0          # 模型自评的 0.99 不作数
    assert data.needConfirm is True
    assert len(data.candidates) == 2


async def test_name_match_when_id_missing(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T07：模型只填了名称没填 id，但名称与候选完全一致 → 应能匹配上"""
    llm = fake_llm([
        '{"spaceId": null, "spaceName": "B栋2楼多功能厅", "confidence": 0.85}'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 102
    assert data.spaceName == "B栋2楼多功能厅"
    assert data.needConfirm is False


async def test_fuzzy_name_match_single_hit(patch_candidates, fake_llm, make_upload_file, temp_upload_dir):
    """名称互相包含且候选中唯一命中（模型输出「3楼展厅」，库里是「A栋3楼展厅」）→ 采纳"""
    llm = fake_llm([
        '{"spaceId": null, "spaceName": "3楼展厅", "confidence": 0.9}'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 101
    # 返回的必须是数据库里的规范名称，而不是模型输出的简称
    assert data.spaceName == "A栋3楼展厅"


async def test_fuzzy_name_match_ambiguous_is_rejected(monkeypatch, fake_llm, make_upload_file, temp_upload_dir):
    """名称模糊匹配到多个候选 → 不猜，返回 None 交由用户确认"""
    async def _two_similar(db, limit=None):
        return [
            SpaceCandidate(spaceId=101, spaceName="A栋3楼展厅", spaceType=2, capacity=40),
            SpaceCandidate(spaceId=103, spaceName="B栋3楼展厅", spaceType=2, capacity=45),
        ]

    monkeypatch.setattr(image_service, "list_active_space_candidates", _two_similar)

    llm = fake_llm(['{"spaceId": null, "spaceName": "3楼展厅", "confidence": 0.9}'])
    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId is None
    assert data.needConfirm is True


# ===========================================================================
# T08 / T09：置信度归一化
# ===========================================================================


async def test_percentage_confidence_is_normalized(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T08：模型把置信度写成百分数 85 → 归一化为 0.85"""
    llm = fake_llm(['{"spaceId": 101, "spaceName": "A栋3楼展厅", "confidence": 85}'])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.confidence == pytest.approx(0.85)
    assert data.needConfirm is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.42, 0.42),
        (85, 0.85),        # 百分数归一化
        (-0.5, 0.0),       # 负数裁剪到 0
        (2.0, 0.02),       # 2.0 落在 (1, 100]，按百分数 2% 处理
        (None, 0.0),       # None 兜底
        ("abc", 0.0),      # 非数值兜底
        (150, 1.0),        # 超过 100 的离谱值 → 裁剪到 1
    ],
)
def test_clamp01(raw, expected):
    """
    T09：置信度裁剪到 [0, 1]。

    注意 (2.0, 0.02) 这一例：2.0 落在 (1, 100] 区间，会被当成百分数 2% → 0.02。
    这里刻意把期望写成 0.02 以固化该行为 —— 若将来调整归一化策略，
    这条用例会立刻失败，提醒开发者评估影响。
    """
    assert _clamp01(raw) == pytest.approx(expected)


# ===========================================================================
# T10：模型不可用 → 41003，绝不裸抛 500
# ===========================================================================


async def test_llm_failure_raises_business_error(
    monkeypatch, patch_candidates, failing_llm, make_upload_file, temp_upload_dir
):
    """T10：模型超时 → 抛 ImageRecognitionError(41003)，且提示面向用户友好"""
    # 关掉结构化输出，让异常直接从 ainvoke 抛出，精确命中「策略 B 失败」路径
    monkeypatch.setattr(settings, "VISION_STRUCTURED_OUTPUT", False)

    with pytest.raises(ImageRecognitionError) as exc:
        await analyze_space_image(
            db=None, file=make_upload_file(), llm=failing_llm(TimeoutError("model timeout"))
        )

    assert exc.value.code == 41003
    # 提示里必须给出可执行的下一步，而不是一句「系统错误」
    assert "重试" in exc.value.message or "文字" in exc.value.message


async def test_structured_output_path_works(
    patch_candidates, structured_llm, make_upload_file, temp_upload_dir
):
    """
    策略 A（with_structured_output）主路径验证。

    注意这个假模型**只实现了 with_structured_output，没有 ainvoke** ——
    所以只要用例通过，就证明 _recognize 确实走了策略 A 并且直接返回，
    没有意外跌落到策略 B（否则会因缺少 ainvoke 抛 AttributeError）。
    """
    llm = structured_llm({"spaceId": 101, "spaceName": "A栋3楼展厅", "confidence": 0.93})

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 101
    assert data.confidence == pytest.approx(0.93)
    assert data.needConfirm is False


async def test_structured_output_salvages_json_from_raw_text(
    patch_candidates, structured_llm, make_upload_file, temp_upload_dir
):
    """策略 A 解析失败但原始文本里藏着 JSON → 应能抢救出来，不直接降级"""
    llm = structured_llm(
        None, raw_text='{"spaceId": 102, "spaceName": "B栋2楼多功能厅", "confidence": 0.8}'
    )

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 102
    assert data.needConfirm is False


async def test_structured_output_fallback_to_plain_call(
    monkeypatch, patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """
    模型不支持结构化输出时，必须自动降级到策略 B 而不是报错。

    FakeMessagesListChatModel 没有实现 bind_tools，
    调用 with_structured_output 会抛 NotImplementedError —— 正是要模拟这个场景。
    """
    monkeypatch.setattr(settings, "VISION_STRUCTURED_OUTPUT", True)  # 显式开启策略 A

    llm = fake_llm(['{"spaceId": 101, "spaceName": "A栋3楼展厅", "confidence": 0.9}'])
    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    # 策略 A 失败后降级到策略 B，结果依然正确
    assert data.spaceId == 101
    assert data.confidence == pytest.approx(0.9)


# ===========================================================================
# T15 / T16 / T17：草图识别
# ===========================================================================


async def test_sketch_success(patch_candidates, fake_llm, make_upload_file, temp_upload_dir):
    """T15：草图识别正常路径"""
    llm = fake_llm([
        '{"capacity": 30, "layout": "剧院式排布，前方设讲台", '
        '"requirements": ["需要投影", "需要讲台"], "confidence": 0.85, "question": null}'
    ])

    data = await analyze_sketch_image(db=None, file=make_upload_file(), llm=llm)

    assert data.type == "sketch"
    assert data.capacity == 30
    assert data.layout == "剧院式排布，前方设讲台"
    assert data.requirements == ["需要投影", "需要讲台"]
    assert data.needConfirm is False
    assert data.question is None


async def test_sketch_invalid_capacity_is_cleared(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T16：模型给出离谱人数 999999 → 置空，而不是让 Pydantic 校验炸掉整个请求"""
    llm = fake_llm(['{"capacity": 999999, "layout": "会议桌", "confidence": 0.9}'])

    data = await analyze_sketch_image(db=None, file=make_upload_file(), llm=llm)

    assert data.capacity is None
    assert data.layout == "会议桌"      # 其它字段不受影响


async def test_sketch_requirements_are_cleaned(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """T17：requirements 需去重、去空白、丢弃非字符串、限制条数"""
    llm = fake_llm([
        '{"capacity": 20, "requirements": '
        '["需要投影", "需要投影", "  需要投影  ", 123, null, "需要音响"], "confidence": 0.9}'
    ])

    data = await analyze_sketch_image(db=None, file=make_upload_file(), llm=llm)

    # "需要投影" 的三个变体归一成一条；123 与 null 被丢弃
    assert data.requirements == ["需要投影", "需要音响"]


async def test_sketch_non_json_degrades(patch_candidates, fake_llm, make_upload_file, temp_upload_dir):
    """草图解析失败也要走友好降级"""
    llm = fake_llm(["这张草图我看不太明白呢。"])

    data = await analyze_sketch_image(db=None, file=make_upload_file(), llm=llm)

    assert data.capacity is None
    assert data.layout is None
    assert data.requirements == []
    assert data.needConfirm is True
    assert data.question


async def test_sketch_semantically_empty_result_degrades(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """
    结构合法但内容全空的结果必须按「没读懂」处理。

    场景：模型返回 `{}`，或把所有字段填成 null，却给了一个高 confidence。
    若不加这道判断，前端会显示「90% 置信度但什么都没识别出来」的自相矛盾结果。
    """
    llm = fake_llm([
        '{"capacity": null, "layout": null, "requirements": [], "confidence": 0.9}'
    ])

    data = await analyze_sketch_image(db=None, file=make_upload_file(), llm=llm)

    assert data.capacity is None
    assert data.layout is None
    assert data.requirements == []
    assert data.confidence == 0.0        # 空结果的「高置信度」必须归零
    assert data.needConfirm is True
    assert data.question                 # 必须给出引导语


async def test_sketch_validates_when_only_one_field_present(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """只要有一个核心字段有内容，就不算「空结果」，正常返回"""
    llm = fake_llm(['{"layout": "圆桌围坐", "confidence": 0.9}'])

    data = await analyze_sketch_image(db=None, file=make_upload_file(), llm=llm)

    assert data.layout == "圆桌围坐"
    assert data.capacity is None
    assert data.needConfirm is False


# ===========================================================================
# 模型输出类型脏数据的容错（schema 层 before-validator）
# ===========================================================================


async def test_space_junk_field_types_do_not_break_parsing(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """
    字段类型全是脏数据时，不能整份响应报废。

    场景：模型把数组给了 null、把 confidence 给了字符串、把 id 给了非数字。
    期望：能救的字段救回来，救不回的置空走人工确认 —— 而不是直接降级丢失全部信息。
    """
    llm = fake_llm([
        '{"spaceId": "101", "spaceName": "A栋3楼展厅", '
        '"deviceHints": null, "confidence": "0.9", "question": null}'
    ])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    # "101" 这类数字字符串能转成整数，属于「能救的」，应当救回来
    assert data.spaceId == 101
    assert data.confidence == pytest.approx(0.9)
    # null 的数组按空数组处理
    assert data.devices == []
    assert data.needConfirm is False


async def test_space_non_numeric_id_is_rejected(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """
    spaceId 转不出整数时必须置 None。

    这是防幻觉的一部分：**绝不猜一个 id 出来**。
    宁可返回未匹配让用户手动选，也不能把一个来路不明的数字当场地 id 用。
    """
    llm = fake_llm(['{"spaceId": "unknown", "spaceName": "A栋3楼展厅", "confidence": 0.9}'])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    # id 被丢弃，但名称仍可用于匹配 —— 这就是「能救的救回来」的体现
    assert data.spaceId == 101
    assert data.spaceName == "A栋3楼展厅"


async def test_space_garbage_confidence_falls_back_to_conservative_value(
    patch_candidates, fake_llm, make_upload_file, temp_upload_dir
):
    """
    confidence 无法解析 → 归一化为 0.0，随后被校准为保守值 0.5（逼出人工确认）。

    注意这里体现的不是「类型转换」，而是业务规则：
    模型选了场地却说不出有多确定，就不该直接放行。
    """
    llm = fake_llm(['{"spaceId": 101, "spaceName": "A栋3楼展厅", "confidence": "high"}'])

    data = await analyze_space_image(db=None, file=make_upload_file(), llm=llm)

    assert data.spaceId == 101
    assert data.confidence == pytest.approx(0.5)
    assert data.needConfirm is True


# ===========================================================================
# 纯函数单元测试
# ===========================================================================


@pytest.mark.parametrize(
    "text,expected_keys",
    [
        ('{"a": 1}', ["a"]),                                       # 策略 1：直接解析
        ('```json\n{"a": 1}\n```', ["a"]),                          # 策略 2：剥离围栏
        ('前面有一堆话 {"a": 1} 后面还有一堆话', ["a"]),              # 策略 3：截取花括号
        ("完全没有 JSON", None),                                     # 全部失败
        ("", None),                                                  # 空串
        ("[1, 2, 3]", None),                                         # 数组不是我们要的结构
    ],
)
def test_extract_json(text, expected_keys):
    """_extract_json 三策略容错解析"""
    result = _extract_json(text)
    if expected_keys is None:
        assert result is None
    else:
        assert result is not None
        assert sorted(result.keys()) == expected_keys


def test_normalize_message_text_handles_content_blocks():
    """
    部分模型把 content 返回成内容块列表而非字符串，
    _normalize_message_text 必须能拼回纯文本，否则后续 json.loads 会 TypeError。
    """
    blocks = [
        {"type": "text", "text": '{"spaceId": '},
        {"type": "text", "text": "101}"},
        {"type": "image_url", "image_url": {"url": "http://example.com/x.jpg"}},
    ]
    assert _normalize_message_text(blocks) == '{"spaceId": 101}'
    assert _normalize_message_text("纯字符串") == "纯字符串"
    assert _normalize_message_text(None) == ""
    assert _normalize_message_text([]) == ""


def test_clean_str_list_limits():
    """条数与长度限制必须生效，避免模型吐出超长数组撑爆响应体"""
    items = [f"关键词{i}" for i in range(50)]
    result = _clean_str_list(items, max_items=10, max_len=64)

    assert len(result) == 10

    long_item = "x" * 200
    assert _clean_str_list([long_item], max_items=10, max_len=64) == ["x" * 64]

    # 非列表输入必须安全返回空列表，而不是抛异常
    assert _clean_str_list("not a list", max_items=10, max_len=64) == []
    assert _clean_str_list(None, max_items=10, max_len=64) == []


def test_match_candidate_priority():
    """_match_candidate 的匹配优先级：id > 名称完全一致 > 唯一模糊包含"""
    candidates = [CANDIDATE_A, CANDIDATE_B]

    # id 命中优先级最高
    by_id = SpaceRecognition(spaceId=101, spaceName="随便写的名字")
    assert _match_candidate(by_id, candidates) == CANDIDATE_A

    # id 不存在时退化为名称完全一致
    by_name = SpaceRecognition(spaceId=999, spaceName="B栋2楼多功能厅")
    assert _match_candidate(by_name, candidates) == CANDIDATE_B

    # 都不匹配返回 None
    assert _match_candidate(SpaceRecognition(spaceName="不存在的地方"), candidates) is None

    # 空名称不应误匹配
    assert _match_candidate(SpaceRecognition(), candidates) is None
