# PR：模块 3（移动端预约与通知）重新集成到新 main

> 分支：`integrate/module3` → `main`（**10 个提交**，72 文件，+8569 / −639）
> 作者：模块 3（蔡玉礼）｜ 日期：2026-09-28
> 基线：`9f30d3a`（merge(backend): 合并模块1/2（语音输入、摄像头空间感知）并适配集成层约定）
> 关联：《docs/本次合并对齐方案.md》《docs/团队仓库合并冲突比对.md》
> 《docs/公用后端问题反馈.md》

> **本节给评审看**：这个 PR 把模块 3 重放到了新 main 上，并按**团队现行约定**改了
> 三类口径（业务码、异常体系、身份来源）。其中**身份来源**和 **`/ws/notify` 的
> 握手方式**是对外契约的变化，需要集成组确认；另有**三处团队侧待办**在第 4 节。

---

## 一、为什么有这个 PR

模块 3 原先是合到**旧 main** 上的（用文件级比对，因为没有共同祖先）。新 main
（`9f30d3a`）合并了模块 1/2 并**建立了团队自己的集成层约定**，其中三处与模块 3
原实现直接冲突，必须重放而不是保留：

| # | 新 main 的约定 | 模块 3 原状态 | 本 PR 的处理 |
|---|---|---|---|
| 1 | 异常体系 = `BizError` 子类 + **5 位业务码**（`docs/api.md` §1.4） | 路由层 `raise HTTPException(404, "预约不存在")` | 全部改走 `BizError` 子类 |
| 2 | **Pydantic 校验失败 → 400 / 40001**（团队把 FastAPI 默认的 422 改掉了） | 断言与线上一律 422 | 422 → 400，测试同步 |
| 3 | 身份**一律从 JWT** 解析（§5.1 / `api.md` §1.6） | 自带 `X-User-Id` 请求头 mock | 改用团队 `get_current_user`，删掉 mock |

第 3 条另有一处**契约变化需要集成组确认**：实时通道 `/ws/notify` 的握手参数
由 `?user_id=` 改为 `?token=<accessToken>`，理由见第 3.3 节。

---

## 二、本 PR 的边界

- ✅ 后端代码与测试、小程序客户端、本模块文档
- ❌ **不改团队权威文档**（`docs/api.md` / `docs/database.md` / `docs/deploy.md` /
  `docs/test.md`）。其中 `api.md` / `test.md` 仍在描述 `X-User-Id`，与本 PR 后的
  代码不一致 —— 属 §5.3 冻结契约，请集成组定稿（第 4.3 节）
- ❌ 不重写 `config.py`（`.env` 权威键集合未定，同上轮）

---

## 三、变更内容

### 3.1 业务码与异常体系对齐（提交 `6adb22e`）

新 main 的异常体系是「真实 HTTP 状态码 + 5 位业务码」。模块 3 重放到该基线后，
`raise HTTPException(404, "预约不存在")` 会落进团队的 `_STATUS_MESSAGES` 分支 ——
`detail` 被通用文案（「接口或资源不存在」）**覆盖**，前端拿不到具体原因。
现在全部改走 `BizError` 子类：

| 情形 | HTTP | code |
|---|---|---|
| 参数类失败 | 400 | `40001` |
| 场地 / 设备 / 用户不存在 | 404 | `40402` / `40403` / `40401` |
| 订单不存在 | 404 | `40404` |
| 时段 / 设备冲突 | 409 | `40901` |
| 状态机不允许 | 409 | `40903` |

顺带修掉两处**真实回归**：

1. `IllegalTransitionError` 原先继承裸 `Exception` —— 一旦前置 `can_transition`
   被绕过就落进 500 兜底，而它本质是「当前状态不允许该操作」，应为 409/40903。
   现继承团队的 `OrderStatusConflictError`。
2. `schemas/order.py` 的 `_check_time` 校验器**移除**：它抛的 `ValueError` 会被
   团队的 `_VALIDATION_MESSAGES["value_error"]` 换成通用文案「取值不合法」，
   「开始时间必须早于结束时间」这条真正有用的提示会消失。校验只留在
   `order_service` 一处（Agent 的 `lock_resources` Tool 直接调 service，
   根本不经过模型，两处校验本来就会漂移）。

### 3.2 身份改走团队 JWT（提交 `1bd9149`）

删除模块 3 自带的 `app/core/deps.py`（读 `X-User-Id`、**兜底演示用户 1**）。那个
头不在契约里，且「没带就兜底」很危险：线上漏配令牌不会报错，只会安静地以 1 号
身份读写数据。现在：

- `app/api/{orders,messages,agent}.py` 用 `app.api.deps.get_current_user`，
  统一取 `current.id`；越权仍按「与不存在同一处理」返回 404。
- 测试改**签真令牌**（`app.core.security.create_token`），因此「令牌无效 / 用户
  不存在 / 账号被禁用 / 未分配角色」这些分支在测试里也真实存在，不是被 mock 掉的。

### 3.3 `/ws/notify` 握手改为 `?token=`（**契约变化，需确认**）

浏览器与小程序都**不允许**给 `WebSocket` 自定义请求头，凭据只能放进 URL。原先传
的是身份本身：

```
ws://host/ws/notify?user_id=2     # 谁都能连，一连上就实时收 2 号的预约通知
```

`user_id` 是自增的，枚举一遍就能收全库通知。现在传**令牌**，服务端自己解出
`user_id`；握手失败按 `1008` 关闭且不区分原因（§9.2）。

> **需要集成组确认**：这是对外契约变化。若团队另有约定（如 `Sec-WebSocket-Protocol`
> 携带令牌），以团队为准，本模块配合改。

**已知残留**：这条路径只校验令牌签名与类型，**不查库**确认用户仍存在 / 未被禁用
（那段逻辑写在 `get_current_user` 里、是为 `Depends` 写的，无法直接复用）。
影响有限：被删用户的令牌最多再活一个有效期（30 分钟），且通知是按 `user_id` 从
库里生成的，删号后不会再生成。已记为待办。

### 3.4 小程序客户端（提交 `c9b0782`）

后端改了身份来源，客户端不同步就是全线 401：

| 文件 | 变更 |
|---|---|
| `miniprogram/utils/auth.js` | **新增**：令牌存取 + 登录 |
| `miniprogram/utils/request.js` | 改发 `Authorization: Bearer`；401 时清本地令牌 |
| `miniprogram/utils/ws.js` | `?user_id=` → `?token=`；服务端 1008 拒绝时清令牌 |
| `miniprogram/api/agent.js` | `uni.uploadFile` 带不了默认头，认证头自己加 |

**已知残留**：真实登录页归模块 1/2，尚未接入。为让演示先跑通，`ensureToken()`
暂以种子账号（`backend/scripts/seed.py` 的 `user01`）**自动登录**兜底。登录页接进
来后删掉该分支即可，调用方不用动。**这一条请在评审时明确**：演示账号的密码出现在
客户端代码里，只对本地/演示库有意义。

`miniprogram/utils/voiceApi.js` 与 `pages/voice/` 是队友语音模块的文件，本次未动。

### 3.5 预约写入下沉与归属校验收紧（提交 `8cad681`、`5320217`）

- 预约写入下沉到 `order_service`（§5.5 六步事务自管会话）。
- 旧路径 `GET /orders/user/{userId}` 收紧为「只返回本人订单」，查他人与被查用户
  不存在**同一处理**（404，响应体不含任何订单字段）—— 原先可被用来枚举全库订单。
- 补 `update_agent_trace` 实现。

### 3.6 设备容量改为**计数比较**（`available_count` 口径 = 用时推导）

模块 4 的 AGENT-C-01/02（并发与库存扣减）需要可验证的口径，而 `§5.3` / `§6.3`
都没写「`available_count` 该不该扣」。模块 3 与模块 4 已就**用时推导**对齐：

```
某设备在某时段的剩余量 = available_count − 该时段重叠单数
```

`available_count` 因此是**可用上限**（管理员维护、静态），**不是**「还剩几台」。
`_device_conflicts` 的判据随之从「查到重叠就拒」改为「**重叠单数 `>=`
`available_count`** 才拒」，`§5.5` 六步**不加第 7 步回补** —— 订单离开
`ACTIVE_ORDER_STATUSES`（取消 / 完成）名额自动回来，**回补不需要代码**。

不选「写时扣减」的理由：`available_count` 是不带时间维度的单值，而剩余量是
**(设备, 时段)** 的函数，一维记二维必然串台；且取消**和**完成两条路径都要回补，
漏一条就单调递减到 0，不报错、不进日志。判据全文（含 7 条对照表与代价）见
`docs/available_count口径判据.md`。

**契约影响**：

- `conflictDetail` 的**形状未变**（仍是 `docs/api.md` 冻结的一单一条
  `{orderId, deviceIds, startTime, endTime}`）；只是列出来的单**都落在已约满的设备上**
- `reason` 文案：「该时段设备已被占用」→「该时段设备已约满」（容量 > 1 时旧文案会误导）
- 新增 7 条用例（服务层 6 条 + 走真实 HTTP 全链路的 1 条，含
  `PUT /orders/{id}/cancel` 后名额回落的端到端验证）

---

## 四、请集成组处理的三件事

详见 `docs/公用后端问题反馈.md` 第六 ~ 八节，摘要：

### 4.1 §13.1 的 SQLite 应急镜像库实际不可用（**建议优先**）

`app/core/database.py` 的 `create_async_engine` 无条件传 `pool_size` 等，而
`sqlite+aiosqlite` 会选中 `NullPool`（`:memory:` 是 `StaticPool`），二者都不接受：

```
TypeError: Invalid argument(s) 'pool_size', 'max_overflow' sent to create_engine(),
using configuration SQLiteDialect_aiosqlite/NullPool/Engine.
```

**触发条件要说准**（我上一版的描述有误，已在 `eba0657` 更正）：团队现有用例
**撞不上**（它们不覆盖 `DATABASE_URL`，且自建引擎不含池参数 —— 已在 `9f30d3a` 上
实测可正常收集）。真正的问题在 **§13.1 是书面承诺的兜底手段**：云库断连时按预案
切 SQLite，服务会**启动即挂**，而那时正是最需要它顶上的时候。修法与实测记录见反馈
文档第六节。

### 4.2 自定义校验器的中文文案会被通用文案吞掉（影响全体模块）

`app/core/response.py::_format_validation_error`：

```python
message = _VALIDATION_MESSAGES.get(err_type) or err.get("msg") or "参数不合法"
```

Pydantic 对校验器里抛的 `ValueError` 一律标 `type="value_error"`，而表里有
`"value_error": "取值不合法"` —— **表命中优先于 `err["msg"]`，自定义中文原因被整句
替换**。本模块踩到时前端拿到的是「body 取值不合法」而不是「开始时间必须早于结束
时间」。两种修法见反馈文档第七节（推荐让 `value_error` 优先取 `err["msg"]`）。

### 4.3 团队权威文档仍在描述 `X-User-Id`，与团队自己的代码不一致

`get_current_user` 只认 `Authorization: Bearer <JWT>`，没有读 `X-User-Id` 的分支。
但以下位置仍写着它：

| 文件 | 位置 |
|---|---|
| `docs/api.md` | §1 请求头说明、第 39 / 59 行、第 209 行（`ws://host/ws/notify?user_id=1`） |
| `docs/test.md` | 第 4 / 80 / 81 行、TC-20 的连接 URL |

照文档实现的前端会拿不到身份（401）。属 §5.3 冻结契约，**本 PR 未擅自改动**，
请集成组定稿；`/ws/notify` 的凭据放法也请一并确认（第 3.3 节）。

---

## 五、保留在模块 3 的两处补丁（**不是团队基线的问题，是模块 3 临时兜住的**）

| 补丁 | 位置 | 何时可删 |
|---|---|---|
| `patch_asyncmy_ping` | `app/core/database.py` | 集成组在公用基线修好 `pool_pre_ping` 与 asyncmy `ping` 的冲突后（反馈文档第五节） |
| SQLite 池参数条件分支 | `app/core/database.py` | 集成组按第 4.1 节修好后 |

两者都由 `tests/module3/test_asyncmy_ping_compat.py` 与
`tests/module3/test_config_alignment.py` 盯着，删早了会红。

---

## 六、验证

| 项 | 结果 |
|---|---|
| 模块 3 用例 | 收集 144 条：**143 passed / 1 skipped**（skip 的是 `test_config_alignment.py:175`，因 `backend/.env` 不在仓库里而条件跳过） |
| 全仓用例 | 收集 **568 条，全部通过**（`pytest` 退出码 0） |
| 运行环境 | `backend/.venv`（Python 3.11.15，§3.1 锁定版本），**全部跑在临时 SQLite 上，未触碰云库**，无需 SSH 隧道 |

**本 PR 未验证的事项**（不要当成已验证）：

- **云库上 §6.6 的 10 个 `idx_*` 是否真的建好了** —— 需要 SSH 隧道直查
  `information_schema`。测试里只断言「模型声明 == §6.6 规范」，不验证云库已建
- **云库种子数据**（行数、`sys_role` 空表等）—— 上轮读数已过期，引用前请重测
- **真实 Agent（模块 4）联调** —— 本模块跑的是 mock 调度器

---

## 七、给评审的一句话

这个 PR 的主体是**对齐**（业务码 / 异常体系 / 身份来源），不是新功能；三处团队侧
待办里 **4.1 值得优先看**（它关系到 §13.1 演示应急预案能否真正生效），
**3.3 需要确认**（实时通道握手方式的契约变化）。
