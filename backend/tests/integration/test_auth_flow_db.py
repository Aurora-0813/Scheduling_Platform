"""
认证全流程集成测试（模块 9 的端到端路径）

与 `tests/api/test_auth_api.py` 的分工
-------------------------------------
接口测试逐条覆盖「一个接口的各个分支」；本文件只做**多步、跨接口、有状态**的路径，
也就是联调时前端真正会走的那条路：

    登录 → 取信息 → 续期 → 用新令牌 → 登出 → 旧令牌必须失效

以及三条只有把「数据库 + 令牌白名单 + 依赖注入」连起来才看得见的一致性问题：

1. **决策 3 的落点**：改 `sys_role.permissions` 或改 `sys_user.role_id` 之后，
   同一个 accessToken **立刻**按新权限判定 —— 判定必须发生在**鉴权关卡**上
   （`require_permission`），而不只是 `/auth/info` 的返回内容里。
   接口测试只能看 `permissions` 字段，看不到「关卡」本身。
2. **手工填写的权限仍要生效**：`sys_role.permissions` 可能被人在 Navicat 里
   填成 JSON 文本、权限位对象、逗号串（见 `app/core/permissions.py`）。
   容错必须一路到达关卡：形态不认识就等于**静默少给权限**，前端表现为菜单点不动。
3. **强制下线的时间窗**：`revoke_all()` 之后 refreshToken 立即作废（40105），
   而 accessToken 因为不查 Redis 仍能用到自然过期 —— 这是刻意的取舍
   （app/api/deps.py 的模块说明），本文件把它钉住而不是假装不存在。

为什么放在 `tests/integration/` 却用 `api` 标记
-----------------------------------------------
目录表达的是「跨层路径」，标记表达的是「怎么被执行」。本文件仍然
全程离线（SQLite 临时文件库 + 生产降级实现 `InMemoryTokenStore`），
不需要云库与 Redis，因此标记与 `tests/api/` 一致，CI 里会正常执行。
真正需要外部依赖的用例才用 `integration` 标记。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_permission
from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.permissions import (
    ROLE_ADMIN,
    ROLE_USER,
    Permission,
    permissions_for_role,
)
from app.core.response import ApiResponse, ok
from app.models.system import SysRole, SysUser
from tests.fakes.factories import ADMIN_PASSWORD, create_admin, create_role

pytestmark = pytest.mark.api

LOGIN = "/api/v1/auth/login"
INFO = "/api/v1/auth/info"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


# ==========================================================================
# 工具
# ==========================================================================
def _bearer(data: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {data['accessToken']}"}


async def _refresh(client: httpx.AsyncClient, data: dict) -> httpx.Response:
    return await client.post(REFRESH, json={"refreshToken": data["refreshToken"]})


def _register_gated_probe(application: FastAPI, required: str, path: str) -> str:
    """
    在测试用应用上挂一个受权限保护的路由，用来观察**关卡**的行为。

    真实接口目前还没有用到 `require_permission`（模块 1/2/3 的接口由各自的
    负责人落位），因此这里用同样的写法注册一个探针路由：它跑的是
    `app/api/deps.py` 里原封不动的依赖链，与将来业务接口的判定路径一致。
    """

    @application.get(path, response_model=ApiResponse[dict], name=f"probe_{required}")
    async def _gated(
        current: CurrentUser = Depends(require_permission(required)),
    ) -> ApiResponse[dict]:
        return ok({"userId": current.id})

    return path


ORDER_GATE = "/api/v1/_probe/gate/order"
MONITOR_GATE = "/api/v1/_probe/gate/monitor"


# ==========================================================================
# 1. 完整生命周期
# ==========================================================================
async def test_full_lifecycle_login_info_refresh_logout(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """登录 → 信息 → 续期 → 新令牌可用 → 登出 → 旧令牌被拒，全程无人工干预。"""
    user, _role = await create_admin(db_session)

    # --- 登录 ---
    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    assert set(tokens) == {"accessToken", "refreshToken", "role"}
    assert tokens["role"] == ROLE_ADMIN

    # --- 信息 ---
    info = (await client.get(INFO, headers=auth_headers(tokens))).json()["data"]
    assert info["id"] == user.id
    assert info["username"] == "admin"
    assert Permission.MONITOR_VIEW in info["permissions"]

    # --- 续期：换成一对全新的令牌 ---
    refreshed = await _refresh(client, tokens)
    assert refreshed.status_code == 200
    pair = refreshed.json()["data"]
    assert pair["refreshToken"] != tokens["refreshToken"], "续期必须轮换 refreshToken"

    # --- 新 accessToken 立刻可用 ---
    assert (await client.get(INFO, headers=auth_headers(pair))).status_code == 200

    # --- 登出：带上本次会话的 refreshToken，只吊销它 ---
    out = await client.post(
        LOGOUT, headers=auth_headers(pair), json={"refreshToken": pair["refreshToken"]}
    )
    assert out.status_code == 200
    assert out.json()["data"] is None

    # --- 已登出的 refreshToken 不能再续期（40106：不在白名单） ---
    denied = await _refresh(client, pair)
    assert denied.status_code == 401
    assert denied.json()["code"] == ErrorCode.REFRESH_TOKEN_INVALID

    # 这里刻意**不**断言「首次登录那对（已被轮换掉的）也失效」：
    # 被轮换掉的令牌在 60 秒宽限期内仍可重放一次，这是刻意设计
    # （避免前端并发续期把用户踢下线）。它与登出叠加后的行为有专门的
    # 用例：test_superseded_token_can_revive_the_session_within_the_grace_window。


async def test_rotation_chain_keeps_only_the_newest_token_alive(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    连续续期三次后，**只有最新**的 refreshToken 还能换（白名单不残留旧条目）。

    轮换不只是「换新令牌」，还要保证旧的被清掉：若旧条目留在白名单里，
    一台设备登出后另一台拿着几个月前的令牌还能续期，等于登出没生效。
    链越长越容易看出白名单是否泄漏，因此这里连做三次并回头逐个重放。

    把宽限期设为 0 是本用例的**关键**：默认的 60 秒宽限期会让上一代令牌
    在重放时被放行一次，那样就分不清「白名单清干净了」还是「宽限期兜住了」。
    宽限期的行为另有用例专门覆盖。
    """
    monkeypatch.setattr(settings, "JWT_REFRESH_GRACE_SECONDS", 0)
    await create_admin(db_session)
    chain = [(await login(client, "admin", ADMIN_PASSWORD)).json()["data"]]

    for _ in range(3):
        response = await _refresh(client, chain[-1])
        assert response.status_code == 200, response.text
        chain.append(response.json()["data"])

    # 最新的一定可用
    assert (await client.get(INFO, headers=_bearer(chain[-1]))).status_code == 200

    # 其余全部被拒（不只是「不在白名单的地址」，而是 40106 这个明确的错误码）
    for superseded in chain[:-1]:
        denied = await _refresh(client, superseded)
        assert denied.status_code == 401
        assert denied.json()["code"] == ErrorCode.REFRESH_TOKEN_INVALID


async def test_superseded_token_can_revive_the_session_within_the_grace_window(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    ⚠️ 现状（已记入汇报文档的待确认项）：宽限期内的**上一代** refreshToken
    能把刚被登出的会话「换回来」。

    步骤：登录得 A → 用 A 续期得 B（A 被替换，但 A 的 60 秒宽限标记还在）
    → 用 B 登出（只吊销 B 这个会话）→ 拿 A 再续期 → **成功**。

    原因：白名单按 **jti** 记账，登出只清掉「当前」那个 jti 的条目与宽限标记；
    上一代 jti 的宽限标记不在吊销范围内 —— 而它本来就是为「前端并发重试」
    刻意保留的（见 `app/core/token_store.py` 的 `RotationOutcome`）。
    两者叠加，就是「登出后 ≤60 秒内，留着上一代令牌即可复活会话」。

    影响面有限：上一代令牌通常就在同一个客户端手里（刚被新令牌替换掉），
    因此**不是**可远程利用的漏洞；但「登出即彻底失效」这句话在 60 秒内不成立，
    使用方（前端演示、答辩讲解）需要知道。

    彻底的修法是给轮换链一个会话标识（例如令牌里加 `sid` 声明，登出按 `sid`
    吊销整条链）。这会改动 JWT 声明契约与 Redis 键设计，属于跨模块的安全语义
    变更，因此这里只把现状钉住：哪天真的改了，本用例会失败并提醒同步文档。
    """
    await create_admin(db_session)

    tokens_a = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    tokens_b = (await _refresh(client, tokens_a)).json()["data"]

    # 用 B 登出：只吊销 B 这一个会话
    logged_out = await client.post(
        LOGOUT, headers=auth_headers(tokens_b), json={"refreshToken": tokens_b["refreshToken"]}
    )
    assert logged_out.status_code == 200
    assert (await _refresh(client, tokens_b)).json()["code"] == ErrorCode.REFRESH_TOKEN_INVALID

    # 但上一代 A 仍在宽限期内 → 会话被换回来
    revived = await _refresh(client, tokens_a)
    assert revived.status_code == 200, (
        "宽限期行为变了：若上一代令牌不再被放行，说明吊销已能按会话链生效。"
        "请同步更新本用例、docs/api.md 的「登出」说明与汇报文档的待确认项。"
    )
    assert (await client.get(INFO, headers=auth_headers(revived.json()["data"]))).status_code == 200

    # 宽限标记消费即失效：A 只能换回这一次
    assert (await _refresh(client, tokens_a)).json()["code"] == ErrorCode.REFRESH_TOKEN_INVALID


# ==========================================================================
# 2. 多设备会话
# ==========================================================================
async def test_two_sessions_are_independent_until_a_full_logout(
    client: httpx.AsyncClient, db_session: AsyncSession, login, auth_headers
) -> None:
    """
    同一账号的两个会话互不干扰；**不带 refreshToken** 的登出才踢掉全部会话。

    这是「登出只吊销本次会话」与「登出全部会话」两条语义的边界：
    前者用于手机上退出但不影响 Pad，后者用于「我怀疑账号被盗」。
    """
    await create_admin(db_session)

    session_a = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    session_b = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    assert session_a["refreshToken"] != session_b["refreshToken"], "两次登录必须是两个会话"

    # 只登出 A
    assert (
        await client.post(
            LOGOUT,
            headers=auth_headers(session_a),
            json={"refreshToken": session_a["refreshToken"]},
        )
    ).status_code == 200

    # A 被吊销，B 不受影响
    assert (await _refresh(client, session_a)).json()["code"] == ErrorCode.REFRESH_TOKEN_INVALID
    still_alive = await _refresh(client, session_b)
    assert still_alive.status_code == 200, "另一个设备的会话不应被牵连"

    # 不带 refreshToken 登出 = 吊销全部会话：令牌版本号提升，
    # 刚才续期拿到的令牌也一起失效（40105，而不是 40106）
    session_b_new = still_alive.json()["data"]
    assert (await client.post(LOGOUT, headers=auth_headers(session_b_new))).status_code == 200

    revoked = await _refresh(client, session_b_new)
    assert revoked.status_code == 401
    assert revoked.json()["code"] == ErrorCode.TOKEN_REVOKED


# ==========================================================================
# 3. 权限以数据库为准（决策 3）
# ==========================================================================
async def test_permission_revoked_in_the_database_stops_at_the_gate_immediately(
    application: FastAPI,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    auth_headers,
) -> None:
    """
    改 `sys_role.permissions` 后，**同一个** accessToken 立刻被关卡拦下。

    刻意把权限改成一个**非空**但不含 `monitor:view` 的清单：空清单会在
    `effective_permissions` 里回落到静态映射（`app/core/permissions.py`），
    那样测到的就不是「数据库说了算」，而是回落逻辑。
    """
    _role_id = (await create_admin(db_session))[1].id
    _register_gated_probe(application, Permission.MONITOR_VIEW, MONITOR_GATE)

    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    headers = auth_headers(tokens)

    assert (await client.get(MONITOR_GATE, headers=headers)).status_code == 200

    # 后台把该角色的权限改成「只剩 order:view」
    await db_session.execute(
        update(SysRole).where(SysRole.id == _role_id).values(permissions=[Permission.ORDER_VIEW])
    )

    denied = await client.get(MONITOR_GATE, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == ErrorCode.PERMISSION_DENIED
    assert Permission.MONITOR_VIEW in denied.json()["message"], "错误信息要说明缺哪个权限"

    # /auth/info 同步收敛，前端菜单因此即刻更新
    info = (await client.get(INFO, headers=headers)).json()["data"]
    assert info["role"] == ROLE_ADMIN, "角色没变，变的是权限清单"
    assert info["permissions"] == [Permission.ORDER_VIEW]

    # 恢复权限后同一个 token 又能过 —— 证明判定每次读的是数据库，
    # 而不是令牌里（或首次登录时）的快照
    await db_session.execute(
        update(SysRole)
        .where(SysRole.id == _role_id)
        .values(permissions=list(permissions_for_role(ROLE_ADMIN)))
    )
    assert (await client.get(MONITOR_GATE, headers=headers)).status_code == 200


async def test_role_downgrade_stops_at_the_gate_on_the_same_token(
    application: FastAPI,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    auth_headers,
) -> None:
    """
    改 `sys_user.role_id` 降级后，旧 accessToken 立刻丢掉管理权限。

    与上一条的区别是**换了个杠杆**：上一条改角色的权限清单，这一条改用户的角色
    归属。两条路径都必须即时生效，否则「降权」在演示里是假的。
    """
    _register_gated_probe(application, Permission.MONITOR_VIEW, MONITOR_GATE)
    user_role = await create_role(db_session, name=ROLE_USER)
    await create_admin(db_session)

    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    headers = auth_headers(tokens)
    assert (await client.get(MONITOR_GATE, headers=headers)).status_code == 200

    await db_session.execute(
        update(SysUser).where(SysUser.username == "admin").values(role_id=user_role.id)
    )

    assert (await client.get(MONITOR_GATE, headers=headers)).status_code == 403
    info = (await client.get(INFO, headers=headers)).json()["data"]
    assert info["role"] == ROLE_USER
    assert Permission.MONITOR_VIEW not in info["permissions"]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        # 标准形态（种子数据与 permissions_for_role 的写法）
        (["order:view"], {"order:view"}),
        # 形态三：JSON 文本（有人手工 UPDATE 成字符串）
        ('["order:view", "order:create"]', {"order:view", "order:create"}),
        # 形态二：权限位对象
        ({"order:view": True, "order:create": False}, {"order:view"}),
        # 形态四：分隔符文本（含中文逗号 / 分号 / 空格）
        ("order:view，order:create", {"order:view", "order:create"}),
        ("order:view; order:create", {"order:view", "order:create"}),
        ("order:view order:create", {"order:view", "order:create"}),
        # 单个字符串，未做任何包装
        ("order:view", {"order:view"}),
    ],
)
async def test_hand_written_permission_shapes_reach_the_gate(
    application: FastAPI,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    auth_headers,
    stored,
    expected: set[str],
) -> None:
    """
    `sys_role.permissions` 被手工填成任意形态时，鉴权关卡都要认得。

    容错只在 `/auth/info` 上生效是不够的：前端菜单渲染正常、点进去 403，
    排查起来要跨三个人。这里让每种形态都真的走一遍 `require_permission`。
    """
    role_id = (await create_admin(db_session))[1].id
    _register_gated_probe(application, Permission.ORDER_VIEW, ORDER_GATE)
    _register_gated_probe(application, Permission.MONITOR_VIEW, MONITOR_GATE)

    await db_session.execute(
        update(SysRole).where(SysRole.id == role_id).values(permissions=stored)
    )

    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    headers = auth_headers(tokens)

    info = (await client.get(INFO, headers=headers)).json()["data"]
    assert info["permissions"] == sorted(expected)

    # 清单里有的权限：放行；清单里没有的权限：拦下
    assert (await client.get(ORDER_GATE, headers=headers)).status_code == 200
    assert (await client.get(MONITOR_GATE, headers=headers)).status_code == 403


# ==========================================================================
# 4. 强制下线的时间窗
# ==========================================================================
async def test_forced_logout_rejects_refresh_but_the_access_token_lives_out_its_window(
    application: FastAPI,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    login,
    token_store,
) -> None:
    """
    `revoke_all()`（强制下线）后：refresh 立刻 40105，accessToken 仍可用。

    ⚠️ 这是**已知且刻意保留**的限制，不是 bug：accessToken 不查 Redis，
    换来的是「Redis 挂掉时已登录用户不受影响」（决策 7）。代价是强制下线
    存在最长为 `JWT_EXPIRE_MINUTES`（默认 30 分钟）的时间窗 —— 对「发现账号
    被盗，立刻踢下线」的场景，需要在文档里告知使用者「请同时通知对方改密码」，
    或把 `JWT_EXPIRE_MINUTES` 调小。

    本用例把这个窗口写进测试：哪天有人给 accessToken 加上版本校验（让窗口
    归零），这里会失败并提醒同步更新文档里的取舍说明。
    """
    user, _role = await create_admin(db_session)
    _register_gated_probe(application, Permission.MONITOR_VIEW, MONITOR_GATE)

    tokens = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    headers = {
        "Authorization": f"Bearer {tokens['accessToken']}",
    }

    # 安全侧强制下线：版本号 +1（生产里由管理员接口或运维脚本触发）
    version = await token_store.revoke_all(user.id)
    assert version >= 1, "强制下线必须提升令牌版本号"

    # refresh 立即失效
    revoked = await _refresh(client, tokens)
    assert revoked.status_code == 401
    assert revoked.json()["code"] == ErrorCode.TOKEN_REVOKED

    # accessToken 仍在窗口内可用（含受权限保护的关卡）
    assert (await client.get(INFO, headers=headers)).status_code == 200
    assert (await client.get(MONITOR_GATE, headers=headers)).status_code == 200

    # 且新签发的 accessToken 会带上新版本号 —— 说明登录/续期路径确实读到了它
    relogin = (await login(client, "admin", ADMIN_PASSWORD)).json()["data"]
    assert (await client.get(INFO, headers=_bearer(relogin))).status_code == 200
    assert relogin["accessToken"] != tokens["accessToken"]
