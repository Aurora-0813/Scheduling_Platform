# PR：模块 3（移动端预约与通知）重新集成到新 main

> 分支：`integrate/module3` → `main`（**14 个提交**；71 个文件，**+8837 / −21**，
> **没有任何文件被删除** —— 数字取自 `origin/main...HEAD` 的 diffstat 并**去掉本文档自身**，
> 因为本文档里正写着这些数字；含本文档的 GitHub 显示值会各多约 400 行的增量）
> 作者：模块 3（蔡玉礼）｜ 日期：2026-09-28
> 基线：`9f30d3a`（merge(backend): 合并模块1/2（语音输入、摄像头空间感知）并适配集成层约定）
> 关联：《docs/本次合并对齐方案.md》《docs/团队仓库合并冲突比对.md》
> 《docs/公用后端问题反馈.md》

> **本节给评审看**：这个 PR 把模块 3 重放到了新 main 上，并按**团队现行约定**改了
> 三类口径（业务码、异常体系、身份来源）。其中**身份来源**和 **`/ws/notify` 的
> 握手方式**是对外契约的变化，需要集成组确认。第 4 节列了仍待答复的 4.1 / 4.2，
> 以及两处**本模块自查后已修正**的事项（4.3 一条错误断言已作废、4.5 覆盖团队文档
> 已还原）—— 若只读一条，请读 **4.5**。

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
- ✅ 本模块五份文档落在**模块作用域路径**：`docs/模块3-api.md`、`docs/模块3-database.md`、
  `docs/模块3-test.md`、`docs/模块3-deploy.md`、`docs/模块3-README.md`
- ❌ **不改团队权威文档**：`docs/api.md`、`docs/database.md`、`docs/deploy.md`、
  `docs/test.md`、`README.md` 在本 PR 中与 `main` **逐字节一致、零改动**。
  章节级「并入团队文档对应小节」按《本次合并对齐方案》§六 **顺延到下一轮**（理由见 §4.5）
- ❌ 不重写 `config.py`（`.env` 权威键集合未定，同上轮）

> **本 PR 对 team 文档的净效果是「只增不改」**：相对 `main` 只新增 `docs/模块3-*.md`
> 与若干本模块分析文档，**不修改、不删除**团队任何一份文档。
> （2026-09-28 修正：本轮重放期间曾有 5 份团队文档被本模块的同名文件覆盖 ——
> `docs/api.md`、`docs/database.md`、`docs/test.md`、`docs/deploy.md`、`README.md`。
> 已全部还原为 `main` 版本、本模块内容改为上述模块作用域路径，见 §4.5。）

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

> ⚠️ 这两个提交还**顺带覆盖了 5 份团队文档**（本模块的模块级文档被写到了团队文档
> 的路径上）。已全部还原，见 **§4.5**。

### 3.7 并入 main（`98c54ea`）：`idx_status_start` + 模块 4 mock 真源

分支原基于 `9f30d3a`，main 之后前进了两个提交，本分支已并入（**无冲突**）：

- `98c54ea fix(db): 索引迁移按列判存在、补设备时段索引` —— 给 `reserve_order` 加了
  `idx_status_start (order_status, start_time)`，**正是模块 3 反馈的「设备维度时段统计
  没有可用索引」**（设备是全局资源、不挂场地，`idx_space_time` 的最左前缀用不上；
  `device_ids` 是 JSON 列建不了普通索引）。它不在 `§6.6` 原文里，属集成组确认后的补充，
  已登记进 `tests/module3/test_config_alignment.py::_EXTRA_INDEXES` —— 该用例的
  「不多」断言现在要求**规范外的索引必须登记并写明依据**，否则红。
- `25b3ee3 fix(mock): 模块 4 思考链以 docs/mock/agent_schedule.json 为唯一真源`

并入后 `_device_conflicts` 的注释仍写着「没有可用索引」，已一并更正。

### 3.8 设备行锁提前到事务头部（修跨场地超卖）

模块 4 徐川报的 **3b**：3 个协程各占一个场地、抢同一台 `available_count = 2` 的
设备，**3 单全成**（应恰好 2 单）。本地稳定复现 13/13 次，属实。

值得说清楚的是**归因**：这不是「忘了加设备行锁」那么简单。

- 场地行锁挡不住跨场地的并发 —— 设备是**全局资源**（`device_resource` 没有
  `space_id`），同一台设备可以出现在不同场地的订单里，两个事务在场地行上不碰面。
- 但**只把设备行锁补到第 4 步校验处也仍然不够**。云库是 InnoDB 默认的
  `REPEATABLE READ`：非加锁 SELECT 读的是「本事务第一条非加锁读」时定下的读视图，
  `FOR UPDATE` 读的才是最新已提交版本。第 4 步之前已经有 `db.get(SysUser, ...)`
  与 `_time_conflicts` 两处非加锁读，读视图早就钉死在对方提交之前；此时再等锁，
  锁等到了**视图也不会刷新**，随后数出来的重叠单还是旧值。
  一句话：**锁了一行、却从另一张表的旧快照里读计数，这把锁是白加的。**

**改法**：设备行锁提前到**第 2b 步**（紧随场地锁，在上述两处非加锁读之前），
并按设备 id **升序**加锁（顺序不定会死锁）。`_check_devices` 改为校验**已经加了
锁的那一份**行，不再重新 SELECT（否则「锁的是 A、判的是 A'」）。

**这是扩了 `§5.5` 第 2 步的锁足迹**（原本只锁场地行），复核时请一并看。

**能验证到哪一步**（不夸大）：

| 性质 | 离线（SQLite） | 云库 |
| --- | --- | --- |
| 语句里有 `with_for_update()` | ✅ 断言 | — |
| 两条锁都排在第一条非加锁读之前 | ✅ 断言 | — |
| 三方并发下不超卖 | ❌ 永远红（`xfail(strict=True)`） | **未验证** |

SQLite 上第三条**必然红**：`FOR UPDATE` 被方言编译掉，且 pysqlite 默认不为 SELECT
开启事务（不持有读锁），三个协程因此必然都读到「还差一个名额」。`tests/conftest.py`
本就写明「事务并发、行锁、时区这三类行为无法在此验证」。所以 **3b 的 xfail 不能在
本地摘**；若在云库跑通，`strict` 会把 XPASS 转成 FAILED，那才是摘标记的信号。

⚠️ 「读视图由第一条非加锁读建立」这条推演**未在云库实测**。若云库实测仍超卖，
说明行锁这条路不够，得走**设备占用表**（`§6.3` 变更，仍等集成组口径）。
完整分析见 `docs/available_count口径判据.md` §7。

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

- `conflictDetail` 的**形状未变**（仍是 `docs/模块3-api.md` 冻结的一单一条
  `{orderId, deviceIds, startTime, endTime}`）；只是列出来的单**都落在已约满的设备上**
- `reason` 文案：「该时段设备已被占用」→「该时段设备已约满」（容量 > 1 时旧文案会误导）
- 新增 7 条用例（服务层 6 条 + 走真实 HTTP 全链路的 1 条，含
  `PUT /orders/{id}/cancel` 后名额回落的端到端验证）

---

## 四、请集成组处理的事项

> **2026-09-28 状态更新**：
> - **`release_occupancy` 已定「删」并已执行**（函数 + 调用点 + monkeypatch 用例），
>   不再需要答复。**原先「请集成组同步 `docs/test.md` 的 TC-11」这条请求已撤回**：
>   2026-09-28 复核 `origin/main:docs/test.md`，`release_occupancy` 命中数为 **0** ——
>   写着旧 hook 的 TC-11 在本模块自己的文档里（已改为断言可观测结果：取消后同一时段
>   同一设备能再下一单）。团队文档无需改动。
> - **设备维度索引已由集成组补上**（main `98c54ea` 给 `reserve_order` 加了
>   `idx_status_start (order_status, start_time)`，正对 `_device_conflicts` 的谓词）。
>   本分支已并入 main，并把该索引登记进 `_EXTRA_INDEXES`。
> - **跨场地超卖已修但云库未验证**（第 3.8 节）：设备行锁提前到第 2b 步。
>   **请注意这是 `§5.5` 锁足迹的扩展**，需要复核；3b 的 xfail 不能在 SQLite 上摘。
> - **4.1 / 4.2 仍待答复**（SQLite 池参数、`value_error` 文案）。
>   原「4.3 团队文档里的 `X-User-Id`」**已作废** —— 复核 `origin/main` 的 `docs/api.md`
>   与 `docs/test.md`，命中数均为 **0**；写 `X-User-Id` 的是本模块自己的文档，
>   已一并改正（见 §4.3）。

### 4.4 合并顺序提醒：模块 4 分支的两个符号必须留住（**不是本分支的问题**）

徐川提出两条合并风险，已在**本分支实测核对**，结论与提出的假设**不同**：

| 符号 | `origin/main` | 本分支 | 结论 |
| --- | --- | --- | --- |
| `_BUSINESS_ERROR_HTTP_STATUS` | ✅ 有（`core/exceptions.py:279`） | ✅ 同 | 字典在 main 上，但**里面没有 `RESOURCE_CONFLICT` 这一项** |
| `RESOURCE_CONFLICT = 40901` | ✅ 有（`core/error_codes.py:72`） | ✅ 同 | 常量与文案都在 main 上，模块 3 用的就是它 |
| `CONFLICT_DEVICE_SHORTAGE` | ❌ **没有** | ❌ 没有 | 确认只在模块 4 分支 |

两条实测依据：

- 本分支相对基线 `9f30d3a` **完全没有改过** `core/exceptions.py` 与
  `core/error_codes.py`（`git diff --stat 9f30d3a HEAD -- <这两个文件>` 输出为空）。
  所以**模块 3 合进来不会动到那两个文件**，不可能挤掉模块 4 的追加项。
- 模块 3 不依赖 `_BUSINESS_ERROR_HTTP_STATUS` 的 `RESOURCE_CONFLICT` 项：
  `ResourceConflictError`（`exceptions.py:182`）自带 `http_status = 409`，
  走的是 `BizError` 子类那条路；那张映射表只服务于模块 1/2 的 `BusinessError`
  兼容层。`CONFLICT_DEVICE_SHORTAGE` 在本分支与 main 上都**无人引用**。

**所以真正要提醒的不是「模块 3 会挤掉它们」，而是**：合并模块 4 时，
若有人用「整文件取某一侧」的方式解冲突，`core/error_codes.py` 与
`core/exceptions.py` 会被整体覆盖，`CONFLICT_DEVICE_SHORTAGE` 就此消失 →
收集期 `ImportError`。**这两个文件应当逐 hunk 合并，不要整文件取一侧。**

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

### 4.3 「团队文档仍在描述 `X-User-Id`」这条已作废（**是本模块自己的文档写错了**）

上一版此处断言团队 `docs/api.md` / `docs/test.md` 仍写着 `X-User-Id`。**实测不成立**：

| 文件 | `X-User-Id` 命中数 |
|---|---|
| `origin/main:docs/api.md` | **0** |
| `origin/main:docs/test.md` | **0** |
| 本模块改动前的 `docs/api.md` | 4 |
| 本模块改动前的 `docs/test.md` | 3 |

写 `X-User-Id` 的是**本模块自己的文档**，不是团队的。团队那两份文档早已是
`Authorization: Bearer <JWT>` 口径，所以**不存在需要集成组同步的事**。

本模块文档已按代码现状改正，并移到模块作用域路径 `docs/模块3-api.md` /
`docs/模块3-test.md`：请求头改为 Bearer token、`/ws/notify` 的示例由
`?user_id=1` 改为 `?token=<accessToken>`（并写清为什么不能用 `user_id`：
客户端自报身份 = 可越权收别人的通知）。

> `/ws/notify` 的凭据放法（URL 携带令牌）仍需集成组确认 —— 这是对外契约，
> 见第 3.3 节。

---

### 4.5 本轮重放曾覆盖 5 份团队文档，已还原（**本模块自查发现并修正**）

`8cad681` / `5320217` 两个提交在重放时把本模块的**模块级文档**写到了团队文档的
同一个路径上，于是本 PR 相对 `main` 会**删除/替换**这五份：

| 文件 | `main`（团队） | 本模块同名文件 | 覆盖的后果 |
|---|---|---|---|
| `docs/database.md` | 364 行，全平台 9 张表（§4.1~§4.9）+ DDL 清单 | 167 行，只写本模块 4 张表 | 丢掉其他 **5 张表**的权威表结构 |
| `docs/api.md` | 182 行，模块 4 / 模块 10 契约 + 「待补充模块」表 | 357 行，本模块全部接口 + 服务层冻结契约 | 丢掉模块 4 `POST /agent/schedule` 全文 |
| `docs/test.md` | 169 行，模块 4 的 AGENT-U/S/E/I/C 用例清单 | 148 行，本模块 TC-01~TC-22 | 丢掉模块 4 全部用例 |
| `docs/deploy.md` | 3 行骨架占位 | 68 行，本模块部署说明 | 骨架被换成只讲本模块的部署文档 |
| `README.md` | 2 行骨架占位（指向《项目文档.md》） | 本模块 README | 根 README 变成只讲模块 3 |

这与本 PR 第二节原先的断言「不改团队权威文档」**直接矛盾**，也与
《团队仓库合并冲突比对》§5.3 的结论一致 —— 那里写的是「**直接覆盖任何一方都会
丢信息**」。之所以没在重放时发现：这几份是**修改**而非删除，不在当时处置的
「34 个团队独有文件」之列。

**已修正（2026-09-28）**：五份团队文档全部 `git checkout origin/main --` 还原，
本模块内容改到模块作用域路径 `docs/模块3-api.md`、`docs/模块3-database.md`、
`docs/模块3-test.md`、`docs/模块3-deploy.md`、`docs/模块3-README.md`，**内容一字未丢**。
章节级「并入团队文档对应小节」按《本次合并对齐方案》§六 / 待办 12 **顺延下一轮**，
届时按 `docs/api.md` 现有的「待补充模块」表（其中「模块 3 预约订单｜蔡玉礼」一行）
与 `docs/test.md` 的模块小节结构并入。

> 两点补充：
> - `docs/database.md` 这一份**即使直接还原也不丢本模块内容** —— `main` 版
>   §4.4 `space_resource`、§4.5 `device_resource`、§4.6 `reserve_order`、
>   §4.9 `notify_message` 已经覆盖本模块四张表，是集成组此前某一轮并入的。
>   唯一缺口是 `idx_status_start` 尚未写进该文件的索引节（见第 3.7 节）。
> - `README.md` 还原后仍是 2 行骨架。§11.1 要求 README 是**项目级**说明与快速开始，
>   本模块的 README 是模块级的，故未占用该路径；项目 README 由集成组统稿。

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
| 模块 3 用例 | 收集 147 条：**145 passed / 1 skipped / 1 xfailed**（skip 的是 `test_config_alignment.py:175`，因 `backend/.env` 不在仓库里而条件跳过；xfailed 是第 3.8 节的 3b，原因见该节） |
| 全仓用例 | 收集 582 条：**571 passed / 10 skipped / 1 xfailed，0 failed / 0 error**（`pytest` 退出码 0；另有 4 条 `smoke` 用例按 `pytest.ini` 的 `addopts` 默认不选） |
| 运行环境 | `backend/.venv`（Python 3.11.15，§3.1 锁定版本），**全部跑在临时 SQLite 上，未触碰云库**，无需 SSH 隧道 |

**本 PR 未验证的事项**（不要当成已验证）：

- **云库上 §6.6 的 10 个 `idx_*` 与新增 `idx_status_start` 是否真的建好了** ——
  需要 SSH 隧道直查 `information_schema`。测试里只断言「模型声明 == §6.6 规范」，
  不验证云库已建
- **跨场地超卖的修复在云库上的实际效果**（第 3.8 节）—— 离线只能断言「锁写了」
  与「锁排在非加锁读之前」，并发语义本身未验证
- **云库种子数据**（行数、`sys_role` 空表等）—— 上轮读数已过期，引用前请重测
- **真实 Agent（模块 4）联调** —— 本模块跑的是 mock 调度器

---

## 七、给评审的一句话

这个 PR 的主体是**对齐**（业务码 / 异常体系 / 身份来源），不是新功能。团队侧事项里
**4.1 值得优先看**（它关系到 §13.1 演示应急预案能否真正生效），
**3.3 需要确认**（实时通道握手方式的契约变化）；另外本 PR 相对 `main`
**只新增文件、不修改也不删除团队任何文档**（4.5 记录了曾发生并已修正的一次覆盖）。
