"""
权限码与角色-权限映射

权威来源（决策 3）
------------------
角色权限以 `sys_role.permissions`（MySQL JSON 列）为准，
`sys_permission` 表降级为前端菜单渲染用的字典，鉴权时不查它。
好处是鉴权只需一次 `sys_user` + `sys_role` 查询，不需要三表 join。

权限码格式：`模块:动作`（决策 4），例如 `order:create`。
模块名取自项目文档 4.2 的模块划分，便于全组对齐。

容错
----
`sys_role.permissions` 是 JSON 列，理论上存的是字符串数组，但实际
（手工建表、中途改过结构、别的同学用 Navicat 填数据）可能出现：
NULL、`[]`、`{"order:create": true}`、`"[\\"order:create\\"]"`、
`"order:create,order:view"`、甚至单个字符串。`normalize_permissions()`
把这些形态全部归一成 `set[str]`，鉴权逻辑不必关心存储形态。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

__all__ = [
    "Permission",
    "ROLE_ADMIN",
    "ROLE_RESOURCE_ADMIN",
    "ROLE_USER",
    "KNOWN_ROLES",
    "ROLE_PERMISSIONS",
    "WILDCARD",
    "normalize_permissions",
    "has_permission",
    "effective_permissions",
    "permissions_for_role",
]


class Permission:
    """权限码常量。格式 `模块:动作`。"""

    # 用户与角色（模块 9 本体）
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_RESET_PASSWORD = "user:reset_password"
    ROLE_ASSIGN = "role:assign"

    # 资源与设备管理（文档 4.2「资源与设备管理」）
    RESOURCE_VIEW = "resource:view"
    RESOURCE_CREATE = "resource:create"
    RESOURCE_UPDATE = "resource:update"
    RESOURCE_DELETE = "resource:delete"

    # 预约订单（文档 4.2「移动端预约与通知」）
    ORDER_VIEW = "order:view"
    ORDER_CREATE = "order:create"
    ORDER_CANCEL = "order:cancel"
    ORDER_APPROVE = "order:approve"

    # 核心调度 Agent（文档 4.2）
    AGENT_SCHEDULE = "agent:schedule"
    AGENT_VIEW_TRACE = "agent:view_trace"

    # 语音输入（文档 4.2）
    VOICE_ANALYZE = "voice:analyze"

    # 摄像头空间感知（文档 4.2）
    VISION_ANALYZE = "vision:analyze"

    # AI 智能巡检（文档 4.2）
    INSPECT_VIEW = "inspect:view"
    INSPECT_SUBMIT = "inspect:submit"

    # AI 冲突预警与智能通知（文档 4.2）
    CONFLICT_VIEW = "conflict:view"
    CONFLICT_RESOLVE = "conflict:resolve"
    NOTIFY_VIEW = "notify:view"
    NOTIFY_SEND = "notify:send"

    # AI 数据洞察面板（文档 4.2）
    DASHBOARD_VIEW = "dashboard:view"

    # 系统集成与联调（模块 10）
    MONITOR_VIEW = "monitor:view"


ROLE_ADMIN = "admin"
ROLE_RESOURCE_ADMIN = "resource_admin"
ROLE_USER = "user"

KNOWN_ROLES: tuple[str, ...] = (ROLE_ADMIN, ROLE_RESOURCE_ADMIN, ROLE_USER)

# 通配符：拥有该权限等价于拥有全部权限。
# 保留它是为了将来加角色时不必同步维护清单，但**种子数据里不用它** ——
# 答辩演示「管理员拥有全部权限」时，显式列出清单更直观可查。
WILDCARD = "*"

# 普通用户：查资源、下预约单、看自己的通知、用 AI 能力
_USER_PERMISSIONS: tuple[str, ...] = (
    Permission.RESOURCE_VIEW,
    Permission.ORDER_VIEW,
    Permission.ORDER_CREATE,
    Permission.ORDER_CANCEL,
    Permission.AGENT_SCHEDULE,
    Permission.AGENT_VIEW_TRACE,
    Permission.VOICE_ANALYZE,
    Permission.VISION_ANALYZE,
    Permission.NOTIFY_VIEW,
    Permission.INSPECT_VIEW,
)

# 资源管理员：普通用户权限 + 资源/巡检/冲突/通知的管理权
_RESOURCE_ADMIN_PERMISSIONS: tuple[str, ...] = _USER_PERMISSIONS + (
    Permission.RESOURCE_CREATE,
    Permission.RESOURCE_UPDATE,
    Permission.RESOURCE_DELETE,
    Permission.INSPECT_SUBMIT,
    Permission.CONFLICT_VIEW,
    Permission.CONFLICT_RESOLVE,
    Permission.NOTIFY_SEND,
    Permission.ORDER_APPROVE,
    Permission.DASHBOARD_VIEW,
)

# 系统管理员：全部权限 + 用户管理 + 监控
#
# 注意：这里只列**增量**。CONFLICT_VIEW / NOTIFY_SEND / DASHBOARD_VIEW 已在
# _RESOURCE_ADMIN_PERMISSIONS 里，**不要重复列举** —— 重复项虽然不影响鉴权
# （has_permission 做的是成员判断），但会让 permissions_for_role() 返回 29 项
# 含 3 个重复的清单，与 docs/seed.sql 手写的 26 项不一致，
# 按 JSON_LENGTH 做的健康检查也会得出 29。有测试保证去重，但源头保持干净更好。
_ADMIN_PERMISSIONS: tuple[str, ...] = _RESOURCE_ADMIN_PERMISSIONS + (
    Permission.USER_VIEW,
    Permission.USER_CREATE,
    Permission.USER_UPDATE,
    Permission.USER_DELETE,
    Permission.USER_RESET_PASSWORD,
    Permission.ROLE_ASSIGN,
    Permission.MONITOR_VIEW,
)

# 角色 → 权限清单。写入 `sys_role.permissions` 时用 permissions_for_role()。
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    ROLE_ADMIN: _ADMIN_PERMISSIONS,
    ROLE_RESOURCE_ADMIN: _RESOURCE_ADMIN_PERMISSIONS,
    ROLE_USER: _USER_PERMISSIONS,
}


def permissions_for_role(role_name: str | None) -> tuple[str, ...]:
    """取某角色的权限清单（去重后保持稳定顺序）。未知角色返回空元组。"""
    if not role_name:
        return ()
    raw = ROLE_PERMISSIONS.get(role_name, ())
    # dict.fromkeys 去重且保序
    return tuple(dict.fromkeys(raw))


def _iter_candidates(raw: Any) -> Iterable[Any]:
    """把任意形态的原始值摊平成候选元素序列。"""
    if raw is None:
        return

    if isinstance(raw, dict):
        # 形态一：{"permissions": [...]} 包装
        if "permissions" in raw and isinstance(raw["permissions"], (list, tuple, set, str)):
            yield from _iter_candidates(raw["permissions"])
        # 形态二：{"order:create": true, "order:view": false} 权限位映射
        for key, value in raw.items():
            if key == "permissions":
                continue
            if value:
                yield key
        return

    if isinstance(raw, (list, tuple, set, frozenset)):
        for item in raw:
            # 数组里嵌套数组的情况
            if isinstance(item, (list, tuple, set, frozenset, dict)):
                yield from _iter_candidates(item)
            else:
                yield item
        return

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return
        # 形态三：JSON 文本，如 '["order:create"]' 、'{"order:create": true}'
        # 或 '"order:create"'。开头的引号也要认：把 JSON 字符串整体存进
        # 一个字符串列（例如 JSON 列的值为 `"order:create"` 时被读成带引号的
        # 文本）在手工填数据的环境里真的会出现，不认它就等于静默丢掉权限。
        if text[0] in '[{"':
            try:
                decoded = json.loads(text)
            except (ValueError, TypeError):
                yield text
                return
            if isinstance(decoded, (list, dict)):
                yield from _iter_candidates(decoded)
            else:
                yield decoded
            return
        # 形态四：逗号/分号/空白分隔，如 "order:create,order:view"
        for part in text.replace(";", ",").replace("，", ",").replace(" ", ",").split(","):
            part = part.strip()
            if part:
                yield part
        return

    yield raw


def normalize_permissions(raw: Any) -> set[str]:
    """
    把 `sys_role.permissions` 的任意形态归一成权限码集合。

    无法识别为字符串的标量（例如误存了角色 ID 数组 `[1, 2]`）会被转成
    `"1"`、`"2"` 保留 —— 它们匹配不上任何权限码，等价于无权限，
    但不会让鉴权抛异常。
    """
    result: set[str] = set()
    for item in _iter_candidates(raw):
        if item is None:
            continue
        if isinstance(item, str):
            code = item.strip()
            if code:
                result.add(code)
        elif isinstance(item, bool):
            # True/False 本身没有权限语义，忽略
            continue
        elif isinstance(item, (int, float)):
            result.add(str(item))
    return result


def has_permission(permissions: Iterable[str] | None, required: str | None) -> bool:
    """
    判断权限集合是否满足要求。

    - `required` 为空表示该接口不要求权限，直接通过。
    - 集合里含通配符 `*` 视为满足任何要求。
    """
    if not required:
        return True
    owned = permissions or ()
    owned_set = owned if isinstance(owned, (set, frozenset)) else set(owned)
    return WILDCARD in owned_set or required in owned_set


def effective_permissions(role_name: str | None, raw_permissions: Any) -> set[str]:
    """
    计算某用户的最终权限集合。

    以数据库里的 `sys_role.permissions` 为准（决策 3）。仅当其解析结果为空、
    而 `role_name` 是已知角色时，才回落到本文件的静态映射 —— 这样即使
    云库的 `permissions` 列还没填数据，演示也不会整个鉴权失效。
    回落时角色名会由调用方记入日志（见 app/api/deps.py）。
    """
    normalized = normalize_permissions(raw_permissions)
    if WILDCARD in normalized:
        # 通配符展开成完整清单，便于 /auth/info 把权限列表返回给前端渲染菜单
        return {WILDCARD}
    if normalized:
        return normalized
    return set(permissions_for_role(role_name))
