"""
权限判定单元测试（模块 9）

被测对象：`app/core/permissions.py`。这里全部是不碰数据库、不碰网络的纯逻辑，
因为该模块的难点**不在算法，而在容错边界**：

- `sys_role.permissions` 是 MySQL 的 JSON 列，但实际写入者可能是人（Navicat
  手工填）、可能是别的同学写的一次性脚本。于是同一个字段在真实环境里可能长成
  `NULL` / `[]` / `{"order:create": true}` / `'["order:create"]'` /
  `"order:create,order:view"` 六种形态。**鉴权绝不能因为存储形态而抛异常或
  误判为「有权限」**，这组用例就是把这些形态逐个钉死。
- 通配符 `*` 的语义（视为拥有全部权限）与「权限清单为空时回落到静态映射」
  是两条容易被后人改坏的隐式约定，因此各有专门用例。
"""

from __future__ import annotations

import re

import pytest

from app.core.permissions import (
    KNOWN_ROLES,
    ROLE_ADMIN,
    ROLE_PERMISSIONS,
    ROLE_RESOURCE_ADMIN,
    ROLE_USER,
    WILDCARD,
    Permission,
    effective_permissions,
    has_permission,
    normalize_permissions,
    permissions_for_role,
)

pytestmark = pytest.mark.unit

# 权限码格式：`模块:动作`（决策 4），全小写、下划线分词
_CODE_PATTERN = re.compile(r"^[a-z_]+:[a-z_]+$")


# ==========================================================================
# 角色 → 权限清单
# ==========================================================================
def test_known_roles_are_exactly_the_mapped_roles() -> None:
    """`KNOWN_ROLES` 与 `ROLE_PERMISSIONS` 的键必须一致。

    两者不一致会出现「登录通过了但权限为空」这种只在演示时才发现的故障：
    `_read_version` 之前的角色校验用 KNOWN_ROLES，鉴权用 ROLE_PERMISSIONS。
    """
    assert set(KNOWN_ROLES) == set(ROLE_PERMISSIONS)
    assert (ROLE_ADMIN, ROLE_RESOURCE_ADMIN, ROLE_USER) == KNOWN_ROLES


def test_role_hierarchy_is_cumulative() -> None:
    """admin ⊇ resource_admin ⊇ user：高一级角色必须包含低一级的全部权限。"""
    admin = set(permissions_for_role(ROLE_ADMIN))
    resadmin = set(permissions_for_role(ROLE_RESOURCE_ADMIN))
    user = set(permissions_for_role(ROLE_USER))

    assert user <= resadmin <= admin
    # 层层必须真的多出东西，否则「升级角色」在演示时看不出变化
    assert resadmin - user and admin - resadmin


def test_permissions_for_role_deduplicates_and_keeps_order() -> None:
    """清单里的重复项要去掉且保持原顺序。

    `_ADMIN_PERMISSIONS` 是在 `_RESOURCE_ADMIN_PERMISSIONS` 基础上追加的，
    而追加项里有几个已经存在（conflict:view / notify:send / dashboard:view）——
    若某天把 `dict.fromkeys` 去掉，`/auth/info` 的 permissions 就会出现重复元素，
    前端菜单会渲染出两个相同条目。
    """
    for role in KNOWN_ROLES:
        codes = permissions_for_role(role)
        assert len(codes) == len(set(codes)), f"{role} 的权限清单有重复项"
        assert list(dict.fromkeys(codes)) == list(codes), f"{role} 的权限顺序不稳定"


def test_permissions_for_unknown_or_empty_role_is_empty() -> None:
    """未知角色 / None / 空串一律返回空元组，不抛异常。"""
    assert permissions_for_role("superman") == ()
    assert permissions_for_role(None) == ()
    assert permissions_for_role("") == ()


def test_every_permission_code_matches_the_naming_convention() -> None:
    """全部权限码都要符合 `模块:动作`，且与 `Permission` 里的常量对得上。

    权限码是跨模块契约（后端判定、前端渲染菜单、文档 5.3 都要引用），
    冒出 `orderCreate` 或 `ORDER:CREATE` 这类写法会让前端匹配不上。
    """
    all_codes = {code for codes in ROLE_PERMISSIONS.values() for code in codes}
    assert all_codes, "权限清单不能为空"

    bad = sorted(code for code in all_codes if not _CODE_PATTERN.match(code))
    assert not bad, f"以下权限码不符合「模块:动作」格式: {bad}"

    constants = {
        value
        for name, value in vars(Permission).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    # 清单里出现的码必须都是 Permission 上声明过的常量，避免手写字符串
    assert all_codes <= constants, f"清单里有未声明的权限码: {sorted(all_codes - constants)}"


# ==========================================================================
# normalize_permissions：容错形态
# ==========================================================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 空形态：四种写法都必须等价于「无权限」
        (None, set()),
        ([], set()),
        ("", set()),
        ("   ", set()),
        # 标准形态：字符串数组（种子数据与 `permissions_for_role` 的写法）
        (["order:create", "order:view"], {"order:create", "order:view"}),
        (("order:create",), {"order:create"}),
        ({"order:create"}, {"order:create"}),
        # 数组元素里混入空白
        ([" order:create "], {"order:create"}),
        # 形态二：权限位映射（手工用 Navicat 填 JSON 对象时最常见）
        ({"order:create": True, "order:view": False}, {"order:create"}),
        # 形态一：{"permissions": [...]} 包装（别的同学把响应结构直接存了进来）
        ({"permissions": ["order:create"]}, {"order:create"}),
        # 形态三：JSON 文本
        ('["order:create", "order:view"]', {"order:create", "order:view"}),
        ('{"order:create": true}', {"order:create"}),
        ('"order:create"', {"order:create"}),
        # 形态四：分隔符文本，含中文逗号与空格
        ("order:create,order:view", {"order:create", "order:view"}),
        ("order:create; order:view", {"order:create", "order:view"}),
        ("order:create，order:view", {"order:create", "order:view"}),
        ("order:create order:view", {"order:create", "order:view"}),
        # 嵌套数组/对象
        (["a:b", ["c:d", {"e:f": True}]], {"a:b", "c:d", "e:f"}),
        # 数字形态：误把角色 ID 数组存进来的场景，保留为字符串但不解析成权限
        ([1, 2], {"1", "2"}),
        # 单个字符串未做任何包装
        ("order:create", {"order:create"}),
        # 顶层标量
        (123, {"123"}),
    ],
)
def test_normalize_permissions_handles_every_stored_shape(raw, expected) -> None:
    assert normalize_permissions(raw) == expected


def test_normalize_permissions_ignores_booleans() -> None:
    """True / False 单独出现时没有权限语义，忽略而不是转成 "True"。"""
    assert normalize_permissions([True, False, None]) == set()


def test_normalize_permissions_keeps_broken_json_text_as_is() -> None:
    """以 `[` / `{` 开头但 **JSON 解析失败**的文本，按普通字符串处理。

    这是刻意的：宁可得到一个匹配不上任何权限码的垃圾码（等价于无权限），
    也不要抛异常让整个 `/auth/info` 500。
    """
    assert normalize_permissions("[broken") == {"[broken"}
    assert normalize_permissions('{"a": ') == {'{"a":'}


def test_normalize_permissions_never_raises_on_odd_input() -> None:
    """兜底：一批畸形输入只要求「不抛异常」，形态本身不重要。"""
    for raw in (0, 0.5, b"bytes", object(), {"permissions": None}, [[[[]]]]):
        normalize_permissions(raw)  # 不抛即通过


# ==========================================================================
# has_permission
# ==========================================================================
@pytest.mark.parametrize(
    ("owned", "required", "expected"),
    [
        # required 为空 = 该接口不要求权限
        (None, None, True),
        (None, "", True),
        (set(), "", True),
        # 正常命中与未命中
        ({"order:create"}, "order:create", True),
        ({"order:view"}, "order:create", False),
        (set(), "order:create", False),
        (None, "order:create", False),
        # 通配符
        ({WILDCARD}, "order:create", True),
        ({"*"}, "anything:at_all", True),
        # 各种可迭代容器
        (["order:create"], "order:create", True),
        (("order:create",), "order:create", True),
        (frozenset({"order:create"}), "order:create", True),
    ],
)
def test_has_permission_matrix(owned, required, expected) -> None:
    assert has_permission(owned, required) is expected


def test_has_permission_does_not_match_on_substring_or_case() -> None:
    """不做前缀匹配、不忽略大小写：`order:creat` 不能命中 `order:create`。"""
    assert has_permission({"order:create"}, "order:creat") is False
    assert has_permission({"order:create"}, "ORDER:CREATE") is False
    assert has_permission({"order:create"}, "order") is False


# ==========================================================================
# effective_permissions：数据库为准 + 空清单回落
# ==========================================================================
def test_effective_permissions_prefers_database_value() -> None:
    """数据库里的值优先，**不与角色静态清单合并**。

    合并会让「临时收回某个权限」无法生效（收回了但静态清单又补回来），
    这是决策 3「以 sys_role.permissions 为准」的核心含义。
    """
    assert effective_permissions(ROLE_ADMIN, ["order:view"]) == {"order:view"}


def test_effective_permissions_falls_back_when_database_is_empty() -> None:
    """数据库没填（NULL / [] / 空 JSON 文本）时才回落到静态映射。

    云库的 `permissions` 列如果还是空的，演示不至于整个鉴权失效 ——
    调用方会把「发生了回落」记进日志（见 app/api/deps.py）。
    """
    expected = set(permissions_for_role(ROLE_USER))
    assert effective_permissions(ROLE_USER, None) == expected
    assert effective_permissions(ROLE_USER, []) == expected
    assert effective_permissions(ROLE_USER, "[]") == expected


def test_effective_permissions_unknown_role_and_empty_db_is_empty() -> None:
    assert effective_permissions(None, None) == set()
    assert effective_permissions("superman", None) == set()


def test_effective_permissions_wildcard_stays_wildcard() -> None:
    """通配符原样返回 `{"*"}`，不展开成完整清单。

    展开会让 `/auth/info` 把几十个权限码铺给前端；而前端只需要知道
    「`*` 代表全部」，菜单渲染逻辑据此分支（种子数据刻意不使用通配符）。
    """
    assert effective_permissions(ROLE_ADMIN, ["*"]) == {WILDCARD}
    assert effective_permissions(None, "*") == {WILDCARD}


def test_effective_permissions_keeps_unrecognizable_values_out_of_the_way() -> None:
    """误存角色 ID 数组时：结果非空 → 不回落 → 等价于无权限（而不是报错）。

    这条边界容易被人「顺手修好」（比如认出数字就回落到静态映射），
    但那样等于把脏数据当成权限授予，宁可少给权限。
    """
    granted = effective_permissions(ROLE_ADMIN, [1, 2])
    assert granted == {"1", "2"}
    assert not has_permission(granted, Permission.USER_VIEW)
