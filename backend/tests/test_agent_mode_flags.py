"""调度模式开关的**行为**用例（2026-10-13 新增）。

## 这个文件为什么存在

管理端那对「🧠 深度思考 / ⚡ 快速决策」和「AI 推荐 / 规则推荐」按钮，
在 2026-10-13 之前处于两种**不同的**坏状态：

| 开关 | 坏法 | 症状 |
| --- | --- | --- |
| `aiRecommend` | 好的 | 真的接到了 `agent/chains/parse.py`，能改变推荐由谁给 |
| `deepMode` | **没接到任何业务** | 高亮会换、`runtime_flags.json` 会写，但调度永远走快速模式 |

`deepMode` 那种坏法是**静默**的：接口回 200，页面也真的变了，只有结果不对
（没有多轮思考链、没有 40~80 秒）。用户看到按钮亮了，只会以为「深度思考原来这么快」。

成因是三条路都在**客户端**把 `fast` 定成了 `true`：

    · `frontend/src/api/monitor.js::agentSchedule` → `{ ...data, fast: data.fast !== false }`
    · `miniprogram/api/agent.js::schedule`        → `fast: payload.fast !== false`
    · `agentWorkbench.run()` 干脆不传 → 同样落到 `true`

而 `/agent/schedule` 当时只看 `req.fast`。**后端那个开关从来没被读过。**

因此本文件**不测「按钮能不能点」**，只测一条：*开关真的改变了走哪条路吗*。
断言全部落在「调用的是哪个 run 函数」上 —— 那是模式唯一可观察的后果。

## 为什么盯 `resolve_fast`

三态口径（`app/core/flags.py::resolve_fast`）是整个修复的枢纽：

    fast is None  → 跟全局开关 deepMode（默认，服务端说了算）
    fast is True  → 强制快速
    fast is False → 强制深度

只要它成立，客户端「不传」就等于「听服务端的」；一旦它退化成二态，
那个开关又会变回摆设，而且**不会有任何用例变红** —— 所以这里逐档钉住。
"""
from __future__ import annotations

import pytest

from app.agent.chains import builder  # noqa: F401 - 与会话夹具同源，保持导入顺序一致
from app.api.v1 import agent as agent_api
from app.core import flags as runtime_flags

from tests.test_agent_schedule import _stub_outcome


@pytest.fixture
def flags(monkeypatch):
    """把开关换成**纯内存**的一份，不碰 `runtime_flags.json`。

    ⚠️ 必须连 `set_flag` 一起换掉，理由不只是「别写坏文件」：
    真实的 `set_flag` 会把全局 `_cache` 改成新值且**不还原**，
    于是本文件跑完后，后面任何依赖默认模式的用例都会莫名其妙地红/绿。
    `monkeypatch` 不会替我们还原那个模块级变量 —— 它是模块状态，不是参数。
    这里用一份局部 dict 兜住，跑完由 monkeypatch 还原函数、模块状态不受影响。
    """
    state = {"deepMode": False, "aiRecommend": True}

    def _all_flags():
        return dict(state)

    def _set_flag(key, value):
        state[key] = bool(value)
        return dict(state)

    monkeypatch.setattr(runtime_flags, "_cache", None)
    monkeypatch.setattr(runtime_flags, "all_flags", _all_flags)
    monkeypatch.setattr(runtime_flags, "set_flag", _set_flag)
    # deep_mode_enabled / resolve_fast 内部都走 all_flags，因此上面两行就够了
    return state


@pytest.fixture
def routing(monkeypatch):
    """截住两条调度路，只记录「哪条被走了」。返回调用记录列表。

    同时把 `record_call` 换成空实现：`_stub_outcome` 的 `locked_order_id` 是 None，
    trace 本来就不会写；而 `record_call` 会碰指标存储 —— 与「走哪条路」无关的
    依赖不该进本例的失败面。

    ## 为什么手动备份/还原（这不是多余动作，是修一个真实的跨文件污染）

    本模块与 `tests/test_agent_schedule.py` **同处一个 pytest 进程**。
    后者用 `monkeypatch.setattr("app.api.v1.agent.run_schedule", _spy)` 装探针
    （`test_i04_identity_comes_only_from_jwt`）—— 它的前提是那个名字上
    **原本就是真的 `run_schedule`**。

    而 `monkeypatch` 撤销的是**它自己这次**的改动：它把「改动前看到的值」记在
    自己的 undo 栈里。若本夹具先跑、且**没有还原**，那条栈里存下的就是我的桩，
    撤销等于把我的桩又装了回去，且此后不再有任何东西会去动它 ——
    `test_agent_schedule.py` 于是拿到一个假的 `run_schedule`，
    探针为空、断言全红，看起来却像「模块 4 的调度用例坏了」。

    症状还会**随执行顺序变**：单跑任一个文件都绿，合跑才红。
    （本文件刚写出来时就是这样：单跑 13 例全过，与 test_agent_schedule 合跑红 9 例。）
    所以这里显式存一份原值，在 teardown 里放回去。
    """
    calls: list[str] = []

    async def _deep(**_kw):
        calls.append("deep")
        return _stub_outcome()

    async def _fast(**_kw):
        calls.append("fast")
        return _stub_outcome()

    # ⚠️ 必须在 monkeypatch 之前存原值，且 teardown 里写回**模块属性本身**
    #    —— 理由见上面的 docstring：否则会把别的测试文件的真函数永久换掉。
    original = (agent_api.run_schedule, agent_api.run_schedule_fast)
    monkeypatch.setattr(agent_api, "run_schedule", _deep)
    monkeypatch.setattr(agent_api, "run_schedule_fast", _fast)
    monkeypatch.setattr(agent_api, "record_call", lambda _outcome: None)
    try:
        yield calls
    finally:
        agent_api.run_schedule, agent_api.run_schedule_fast = original


# ==========================================================================
# 一、resolve_fast 的三态口径（纯函数，不碰 HTTP）
# ==========================================================================
@pytest.mark.unit
async def test_resolve_fast_defers_to_the_global_switch_when_unset(flags) -> None:
    """**不传** fast 时，全局开关说了算 —— 这是整个修复的核心。"""
    flags["deepMode"] = False
    assert runtime_flags.resolve_fast(None) is True, "开关关着就该走快速模式"
    flags["deepMode"] = True
    assert runtime_flags.resolve_fast(None) is False, "开关开着就该走深度模式"


@pytest.mark.unit
async def test_resolve_fast_explicit_value_wins_over_the_switch(flags) -> None:
    """显式传了就以它为准 —— 联调/脚本要能强制某一档，不该被全局开关改掉。"""
    flags["deepMode"] = True
    assert runtime_flags.resolve_fast(True) is True
    flags["deepMode"] = False
    assert runtime_flags.resolve_fast(False) is False


@pytest.mark.unit
async def test_resolve_fast_returns_real_bools(flags) -> None:
    """返回值必须是 bool：它会进 if 分支，也会进日志。

    三态里 True / False 单独处理，None 走开关 —— 别把 None 透出去，
    否则 `if fast` 与「未指定」就分不开了。
    """
    flags["deepMode"] = False
    assert runtime_flags.resolve_fast(None) is True
    assert runtime_flags.resolve_fast(True) is True
    assert runtime_flags.resolve_fast(False) is False


# ==========================================================================
# 二、开关真的改变了走哪条路（HTTP 全链路）
# ==========================================================================
@pytest.mark.api
@pytest.mark.parametrize(
    ("deep", "expected"),
    [(True, "deep"), (False, "fast")],
    ids=["开关开→深度", "开关关→快速"],
)
async def test_schedule_follows_the_global_switch_when_fast_is_absent(
    flags, routing, dev_client, auth, deep, expected
) -> None:
    """请求体里**没有 fast** 时，路由由后端开关决定。

    这就是「客户端别再替服务端定模式」那条改动的验收点：
    修复前两端默认发 `fast: true`，本例的 deep 那一档**永远不可能成立**。
    """
    flags["deepMode"] = deep
    resp = await dev_client.post(
        "/api/v1/agent/schedule", json={"text": "帮我排个 40 人的会议室"}, headers=auth
    )
    assert resp.status_code == 200
    assert routing == [expected]


@pytest.mark.api
async def test_schedule_honours_an_explicit_fast_true(flags, routing, dev_client, auth) -> None:
    """显式 `fast: true` 压过开关（开关开着也走快速）。"""
    flags["deepMode"] = True
    resp = await dev_client.post(
        "/api/v1/agent/schedule",
        json={"text": "帮我排个会议室", "fast": True},
        headers=auth,
    )
    assert resp.status_code == 200
    assert routing == ["fast"]


@pytest.mark.api
async def test_schedule_honours_an_explicit_fast_false(flags, routing, dev_client, auth) -> None:
    """显式 `fast: false` 压过开关（开关关着也走深度）。"""
    flags["deepMode"] = False
    resp = await dev_client.post(
        "/api/v1/agent/schedule",
        json={"text": "帮我排个会议室", "fast": False},
        headers=auth,
    )
    assert resp.status_code == 200
    assert routing == ["deep"]


@pytest.mark.api
async def test_schedule_never_calls_both_paths(flags, routing, dev_client, auth) -> None:
    """一轮调度**只能走一条路**。

    这条防的是回归成「先试深度、失败再快速」那种写法：那会让一轮请求
    真的落两次库（`lock_resources` 有副作用），也会让耗时与思考链口径全乱。
    """
    flags["deepMode"] = True
    await dev_client.post("/api/v1/agent/schedule", json={"text": "排一下"}, headers=auth)
    assert len(routing) == 1, f"一轮调度走了 {routing} 条路"


@pytest.mark.api
async def test_schedule_without_auth_does_not_pick_a_path(routing, dev_client) -> None:
    """401 发生在选路之前：没令牌就不该有任何 run 调用。

    顺序反过来的话，未登录用户也能让服务端跑一轮大模型 —— 那是白烧额度。
    """
    resp = await dev_client.post("/api/v1/agent/schedule", json={"text": "排一下"})
    assert resp.status_code == 401
    assert routing == []


# ==========================================================================
# 三、PUT /agent/mode 真的改得动开关
# ==========================================================================
@pytest.fixture
def admin_auth() -> dict[str, str]:
    """**系统管理员**的令牌（sys_user.id=3，角色「系统管理员」→ ["*"]）。

    ⚠️ 不能复用 auth（id=1 zhangsan「普通用户」）：PUT /agent/mode 挂的是
    user:update，普通用户**必然 403**。而且权限不是从令牌里的 role 取的
    （见 api/deps.py），是按 userId 回库读 sys_role —— 所以必须真的换一个 userId，
    光把 role 写成 "admin" 没有用。这一点下面有专门的用例钉住。
    """
    from datetime import timedelta

    from app.core.security import TokenType, create_token

    issued, _payload = create_token(
        user_id=3,
        role="admin",
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=30),
    )
    return {"Authorization": f"Bearer {issued}"}


@pytest.mark.api
async def test_put_mode_writes_deep_mode(flags, dev_client, admin_auth) -> None:
    """PUT /agent/mode 的 body 必须被解析成 deepMode。

    这是 2026-10-13 修过的另一个**静默失败**，与本文件主题同源：
    原签名把 deepMode 写成标量参数，FastAPI 按 **query** 参数取；
    而前端发的是 JSON body —— 于是永远取到 None，接口回 200 + 「未做改动」，
    开关纹丝不动，且**不报错**。修法是收一个 Pydantic 模型。
    这条用例钉住「发 body 就真的生效」。
    """
    resp = await dev_client.put("/api/v1/agent/mode", json={"deepMode": True}, headers=admin_auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["deepMode"] is True
    assert flags["deepMode"] is True


@pytest.mark.api
async def test_put_mode_can_toggle_ai_recommend_alone(flags, dev_client, admin_auth) -> None:
    """两个开关可**单独**切：不传的那个保持原样，不能被顺手重置。"""
    flags["deepMode"] = True  # 先造一个「与默认不同」的值，才看得出有没有被顺手改回
    resp = await dev_client.put(
        "/api/v1/agent/mode", json={"aiRecommend": False}, headers=admin_auth
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["aiRecommend"] is False
    assert body["data"]["deepMode"] is True, "只切 aiRecommend 不该动 deepMode"
    assert flags["deepMode"] is True


@pytest.mark.api
async def test_switching_the_button_changes_the_next_schedule(
    flags, routing, dev_client, admin_auth
) -> None:
    """**端到端**：管理员点一下「🧠 深度思考」，下一次调度真的走多轮 Agent。

    这一条是本文件里最贴近用户可见行为的一条 —— 它把三段接起来验：

        1. `PUT /agent/mode` 把开关写进去（body 真的被解析）
        2. `GET /agent/mode` 读回来还是那个值（前端按钮高亮与真实状态一致）
        3. 随后一个**不传 fast** 的 `/agent/schedule` 走 `run_schedule`

    修复前这条必红：第 1、2 步一直是好的，红在第 3 步 —— 请求体里那个
    `fast: true` 是客户端发的，服务端开关再对也没用。
    """
    # 起点：默认（.env 未开深模）应当是快速模式
    before = await dev_client.post(
        "/api/v1/agent/schedule", json={"text": "先跑一轮"}, headers=admin_auth
    )
    assert before.status_code == 200
    assert routing == ["fast"], f"默认应当走快速模式，实际 {routing}"

    # 管理员点「🧠 深度思考」
    put = await dev_client.put(
        "/api/v1/agent/mode", json={"deepMode": True}, headers=admin_auth
    )
    assert put.status_code == 200, put.text

    # 读回来确认（前端进页面读的就是这个）
    got = await dev_client.get("/api/v1/agent/mode", headers=admin_auth)
    assert got.json()["data"]["deepMode"] is True

    # 同一个请求体（依然不传 fast），这次必须走深度
    routing.clear()
    after = await dev_client.post(
        "/api/v1/agent/schedule", json={"text": "再跑一轮"}, headers=admin_auth
    )
    assert after.status_code == 200
    assert routing == ["deep"], f"切了开关仍走 {routing} —— 开关又成了摆设"


@pytest.mark.api
async def test_put_mode_rejects_a_normal_user(flags, dev_client, auth) -> None:
    """普通用户切不动这个开关（user:update）。

    为什么这条属于本文件：开关是**系统级**的，一次点击改变所有人的调度路径。
    如果它变成谁都能点，那「影响所有用户」的文案就成了摆设。
    同时钉住「权限来自数据库而不是令牌里的 role」——auth 的令牌里写的是
    role: "user"，但真正的判据是库里的角色。
    """
    resp = await dev_client.put("/api/v1/agent/mode", json={"deepMode": True}, headers=auth)
    assert resp.status_code == 403
    assert flags["deepMode"] is False, "被拒的请求绝不能改到开关"


@pytest.mark.api
async def test_get_mode_reports_both_switches(flags, dev_client, auth) -> None:
    """读接口对**所有登录用户**开放，且同时给出两个开关 —— 前端靠它渲染按钮。

    读接口不挂 user:update：普通用户也该看到当前处于哪一档，
    否则他只会觉得「今天 AI 怎么这么慢/这么快」，而不知道这是全局设置。
    """
    flags["deepMode"] = True
    flags["aiRecommend"] = False
    resp = await dev_client.get("/api/v1/agent/mode", headers=auth)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["deepMode"] is True
    assert data["flags"] == {"deepMode": True, "aiRecommend": False}
