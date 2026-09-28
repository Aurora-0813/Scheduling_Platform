"""
camelCase 转换与自定义字段类型单元测试（模块 10 的接口契约基础）

被测对象：`app/core/camel.py`（`CamelModel` / `DateTimeStr` / `MoneyStr`）
与 `app/core/response.py` 的 `_format_validation_error`。

为什么这组用例是「跨模块的地基」
--------------------------------
文档 6.2 要求接口字段 camelCase、文档 5.1 要求时间格式
`YYYY-MM-DD HH:mm:ss`。这两条**不是**某个接口的实现细节，而是全组共用的约定：
模块 1/2/3/5/6/7/8 的每个出参模型都继承 `CamelModel`，每个时间字段都该用
`DateTimeStr`。约定一旦漂移，症状是「某个接口的时间带 T」「某个接口返回了
access_token」——而那种问题通常到最后联调那天才被发现。

本文件把三种最容易出事的边界钉住：

1. **`model_dump()` 默认给 snake_case**，出参必须显式 `by_alias=True`
   （统一响应体已封装，所以真正要防的是「有人绕过响应体直接返回 dict/模型」）；
2. **`when_used="json"`**：Python 模式下 `DateTimeStr` / `MoneyStr` 仍是
   `datetime` / `Decimal`，只有 JSON 序列化才转字符串 —— 若被丢掉，
   写库时会把字符串塞进 DATETIME 列；
3. **校验错误的字段名**：无论前端传 `createdAt` 还是 `created_at`，
   报错里的 `field` 都必须是 camelCase（前端要拿它定位高亮哪个输入框）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.camel import DATETIME_FORMAT, CamelModel, DateTimeStr, MoneyStr, to_camel_alias
from app.core.response import _format_validation_error
from app.models.system import SysUser

pytestmark = pytest.mark.unit


class _Inner(CamelModel):
    """用于验证嵌套模型的别名同样生效。"""

    space_id: int


class _Demo(CamelModel):
    user_id: int
    created_at: DateTimeStr
    budget: MoneyStr
    avatar_url: str | None = None
    inner: _Inner | None = None
    optional_time: DateTimeStr | None = None


# ==========================================================================
# CamelModel：出参别名
# ==========================================================================
def test_json_dump_uses_camel_case_at_every_level() -> None:
    """JSON 出参（接口真正返回的东西）里所有层级都是 camelCase。"""
    demo = _Demo(
        user_id=1,
        created_at=datetime(2026, 9, 27, 10, 30, 0),
        budget=Decimal("980.1"),
        avatar_url="/static/a.png",
        inner=_Inner(space_id=7),
    )

    dumped = demo.model_dump(by_alias=True, mode="json")

    assert dumped == {
        "userId": 1,
        "createdAt": "2026-09-27 10:30:00",
        "budget": "980.10",
        "avatarUrl": "/static/a.png",
        "inner": {"spaceId": 7},
        "optionalTime": None,
    }


def test_python_dump_keeps_snake_case_unless_by_alias() -> None:
    """`model_dump()` 默认是 snake_case —— 这正是必须传 `by_alias=True` 的原因。

    若某个接口直接 `return SomeModel(...)` 而它没继承 `CamelModel`（或有人
    手动 `model_dump()`），前端会看到 `access_token` 而成功响应里是
    `accessToken`，且**只在错误分支或个别接口上暴露**。
    """
    demo = _Demo(user_id=1, created_at=datetime(2026, 9, 27, 10, 30, 0), budget=Decimal("980"))

    snake = demo.model_dump()
    assert "user_id" in snake and "created_at" in snake
    assert "userId" not in snake
    assert "spaceId" not in snake


def test_python_dump_keeps_datetime_and_decimal_types() -> None:
    """`when_used="json"` 的效果：Python 模式下**不**转字符串，类型不丢。

    这条是给「用模型出参去写库」的场景兜底的：若 `model_dump()` 就把
    `datetime` 变成字符串，那个值塞进 DATETIME 列会被 MySQL 静默转换或报错。
    """
    demo = _Demo(user_id=1, created_at=datetime(2026, 9, 27, 10, 30, 0), budget=Decimal("980.1"))

    python_dump = demo.model_dump()
    assert isinstance(python_dump["created_at"], datetime)
    assert isinstance(python_dump["budget"], Decimal)


def test_input_accepts_both_camel_case_and_snake_case() -> None:
    """`populate_by_name=True`：两种写法都能构造，内部代码不必迁就接口风格。"""
    from_camel = _Demo(userId=1, createdAt="2026-09-27 10:30:00", budget="1")
    from_snake = _Demo(user_id=1, created_at="2026-09-27 10:30:00", budget="1")

    assert from_camel == from_snake


def test_unknown_fields_are_ignored_not_rejected() -> None:
    """`extra="ignore"`：前端多传一个字段不该让接口 400。

    （若改成 `forbid`，前端上线一个比后端新的版本就会整片接口不可用；
    这里的取舍是「多传忽略、少传才报错」。）
    """
    demo = _Demo(user_id=1, created_at="2026-09-27", budget="1", unknown_field="x")
    assert demo.user_id == 1


def test_model_can_be_built_from_orm_object() -> None:
    """`from_attributes=True`：可以直接把 ORM 对象交给响应模型。"""

    class _UserOut(CamelModel):
        username: str
        avatar_url: str | None = None

    orm_user = SysUser(username="admin", password="irrelevant", status=1)

    assert _UserOut.model_validate(orm_user).model_dump(by_alias=True) == {
        "username": "admin",
        "avatarUrl": None,
    }


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [
        ("id", "id"),
        ("user_id", "userId"),
        ("avatar_url", "avatarUrl"),
        ("space_id", "spaceId"),
        ("open_start_time", "openStartTime"),
        ("access_token", "accessToken"),
        ("refresh_token", "refreshToken"),
    ],
)
def test_to_camel_alias_for_real_field_names(field_name: str, expected: str) -> None:
    """项目里真实存在的字段名逐个转换一遍（含文档 5.3 契约里的三个）。"""
    assert to_camel_alias(field_name) == expected


# ==========================================================================
# DateTimeStr
# ==========================================================================
@pytest.mark.parametrize(
    "raw",
    [
        "2026-09-27 10:30:00",  # 契约格式（文档 5.1）
        "2026-09-27T10:30:00",  # ISO 8601（浏览器/小程序更容易产出这个）
        "2026-09-27 10:30",  # 省略秒
        "2026-09-27",  # 只有日期 → 00:00:00
        "  2026-09-27 10:30:00  ",  # 带首尾空格
    ],
)
def test_datetime_accepts_common_input_formats(raw: str) -> None:
    """入参容忍若干常见写法，出参一律规范化。"""
    demo = _Demo(user_id=1, created_at=raw, budget="1")

    assert demo.created_at == datetime(2026, 9, 27, 10, 30, 0) or raw == "2026-09-27"
    assert demo.model_dump(by_alias=True, mode="json")["createdAt"] == (
        "2026-09-27 00:00:00" if raw == "2026-09-27" else "2026-09-27 10:30:00"
    )


def test_datetime_serialization_drops_microseconds_and_uses_space_separator() -> None:
    """出参格式固定为 `YYYY-MM-DD HH:mm:ss`：没有 T、没有毫秒、没有时区后缀。"""
    demo = _Demo(
        user_id=1,
        created_at=datetime(2026, 9, 27, 10, 30, 0, 123456),
        budget="1",
    )

    text = demo.model_dump(by_alias=True, mode="json")["createdAt"]
    assert text == "2026-09-27 10:30:00"
    assert "T" not in text and "+" not in text and "." not in text
    assert DATETIME_FORMAT == "%Y-%m-%d %H:%M:%S"


def test_datetime_accepts_but_does_not_convert_timezone_aware_input() -> None:
    """
    ⚠️ 已知边界：带时区（或毫秒）的输入能被 Pydantic 接受，但**不做时区换算**。

    `Z` / `+08:00` 这类写法会走到 Pydantic 的宽松日期解析（我们的
    `BeforeValidator` 解析失败时会把原值原样交回去），解析结果是**带时区**的
    datetime；而我们的序列化用 `strftime`，直接照字面输出墙上时间，不做换算。

    于是 `2026-09-27T10:30:00.000Z`（UTC 10:30）会被原样当作本地 10:30，
    与真实时间差 8 小时（东八区）。前端若用 `new Date().toISOString()`
    取值就会踩到这里，因此 `docs/api.md` 明确要求**入参一律传本地
    `YYYY-MM-DD HH:mm:ss`**。本用例把这个行为固定下来，避免有人以为它已经
    被自动换算（真正修法是显式拒绝带时区的输入，属于跨模块契约变更，
    已列入汇报文档的待确认项）。
    """
    aware = _Demo(user_id=1, created_at="2026-09-27T10:30:00.000Z", budget="1")

    assert aware.created_at.utcoffset() is not None, "Pydantic 把它解析成了带时区的时间"
    # 字面照抄，没有 +8 小时换算
    assert aware.model_dump(by_alias=True, mode="json")["createdAt"] == "2026-09-27 10:30:00"

    # 对比：明确带 +08:00 的输入同样只是照抄墙上时间
    plus8 = _Demo(user_id=1, created_at="2026-09-27T10:30:00+08:00", budget="1")
    assert plus8.model_dump(by_alias=True, mode="json")["createdAt"] == "2026-09-27 10:30:00"


def test_datetime_rejects_unparsable_input() -> None:
    """完全无法解析的字符串 → ValidationError（接口层会转成 400/40001）。"""
    with pytest.raises(ValidationError) as excinfo:
        _Demo(user_id=1, created_at="昨天下午", budget="1")

    assert [error["loc"] for error in excinfo.value.errors()] == [("created_at",)]


def test_datetime_none_stays_none() -> None:
    """可空时间字段输出 null，而不是空字符串。"""
    demo = _Demo(user_id=1, created_at="2026-09-27", budget="1", optional_time=None)
    assert demo.model_dump(by_alias=True, mode="json")["optionalTime"] is None


# ==========================================================================
# MoneyStr
# ==========================================================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("980.1", "980.10"),  # 补齐 2 位
        (Decimal("980"), "980.00"),  # DECIMAL(10,2) 的整数形态
        (980, "980.00"),
        ("0.01", "0.01"),
        ("-12.5", "-12.50"),
        ("99999999.99", "99999999.99"),  # DECIMAL(10,2) 的上界
    ],
)
def test_money_is_serialized_as_two_decimal_string(raw, expected: str) -> None:
    """金额出参固定 2 位小数的**字符串**。

    刻意不用 JSON number：`DECIMAL(10,2)` 走 IEEE754 双精度会出现
    `980.0999999999999` 这类值，前端显示预算时会多出一串小数。
    """
    demo = _Demo(user_id=1, created_at="2026-09-27", budget=raw)

    dumped = demo.model_dump(by_alias=True, mode="json")["budget"]
    assert dumped == expected
    assert isinstance(dumped, str), "金额必须是字符串，不能是 JSON number"


def test_money_keeps_decimal_type_in_python_mode() -> None:
    demo = _Demo(user_id=1, created_at="2026-09-27", budget="980.10")
    assert isinstance(demo.model_dump()["budget"], Decimal)


# ==========================================================================
# 校验错误的字段名（_format_validation_error）
# ==========================================================================
@pytest.mark.parametrize(
    ("loc", "expected_field"),
    [
        # 前缀 body/query/path/... 会被剥掉
        (("body", "created_at"), "createdAt"),
        (("body", "createdAt"), "createdAt"),
        (("query", "page_size"), "pageSize"),
        (("path", "order_id"), "orderId"),
        # 只剩前缀时退化成 "body"，不能是空字符串（前端要拿它定位输入框）
        (("body",), "body"),
        ((), "body"),
        # 嵌套结构与数组下标：下标保持数字，其余转 camelCase
        (("body", "items", 0, "space_id"), "items.0.spaceId"),
        (("body", "client_info", "user_name"), "clientInfo.userName"),
    ],
)
def test_validation_error_field_name_is_always_camel_case(loc, expected_field: str) -> None:
    """报错里的 `field` 一律 camelCase，与前端传参写法无关。"""
    formatted = _format_validation_error({"loc": loc, "type": "missing", "msg": "Field required"})
    assert formatted["field"] == expected_field


def test_validation_error_messages_are_localized_and_carry_constraints() -> None:
    """常见错误类型给中文提示，并把约束值带进去（前端可直接展示）。"""
    missing = _format_validation_error({"loc": ("body", "username"), "type": "missing"})
    assert missing == {"field": "username", "message": "该字段为必填项"}

    too_short = _format_validation_error(
        {"loc": ("body", "password"), "type": "string_too_short", "ctx": {"limit": 6}}
    )
    assert too_short["message"] == "长度不足（要求 6）"

    too_long = _format_validation_error(
        {"loc": ("body", "password"), "type": "string_too_long", "ctx": {"limit": 72}}
    )
    assert too_long["message"] == "长度超出限制（要求 72）"

    too_big = _format_validation_error(
        {"loc": ("query", "count"), "type": "less_than_equal", "ctx": {"le": 500}}
    )
    assert too_big["message"] == "数值过大（须不大于 500）"

    # 时间格式错误要直接把契约写进提示里，前端不用猜该传什么格式
    bad_time = _format_validation_error({"loc": ("body", "start_time"), "type": "datetime_parsing"})
    assert bad_time == {
        "field": "startTime",
        "message": "时间格式不正确，应为 YYYY-MM-DD HH:mm:ss",
    }

    bad_enum = _format_validation_error(
        {"loc": ("body", "status"), "type": "enum", "ctx": {"expected": "'1', '0'"}}
    )
    assert bad_enum["message"] == "取值不在允许范围内：'1', '0'"

    unknown = _format_validation_error(
        {"loc": ("body", "x"), "type": "某未知类型", "msg": "原始信息"}
    )
    assert unknown["message"] == "原始信息", "未收录的类型要回退到 Pydantic 原文，不能丢信息"


def test_validation_error_falls_back_to_default_message() -> None:
    """连 `msg` 都没有时给默认文案，不能出现空 message。"""
    formatted = _format_validation_error({"loc": ("body", "x"), "type": "unknown"})
    assert formatted["message"]


def test_timezone_math_sanity_for_the_known_limitation() -> None:
    """给上面那条「已知边界」补一个量级断言：东八区差 8 小时。

    这样即使将来某台机器的时区变了，本文件仍能说明「差 8 小时」这个数字
    是从哪来的（而不是照着某次输出的巧合写死）。
    """
    naive = datetime(2026, 9, 27, 10, 30, 0)
    utc_same_wall_clock = datetime(2026, 9, 27, 10, 30, 0, tzinfo=UTC)

    assert utc_same_wall_clock.utcoffset() == timedelta(0)
    # 同一时刻的本地墙上时间
    assert utc_same_wall_clock.astimezone().replace(tzinfo=None) - naive == timedelta(hours=8)
