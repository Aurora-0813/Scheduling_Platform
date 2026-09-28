# `available_count` 口径判据：用时推导（不扣减）

> 模块 3（蔡玉礼）｜ 2026-09-28
> 起因：模块 4 的 AGENT-C-01/02（并发与库存扣减）需要可验证的口径，
> 而 `§5.3` / `§6.3` 都没写「`available_count` 该不该扣」。
> 结论：**一条都不做 —— 因为不扣减。改为「用时推导」。**
> **状态：已实现**（`app/services/order_service.py::_device_conflicts`）。

---

## 1. 口径：`available_count` 是静态上限，不是实时剩余

`device_resource` 表里同时有 `total_count` 和 `available_count` 两列：

```python
total_count:     Mapped[int] = mapped_column(Integer, nullable=False, comment="总数量")
available_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="可用数量")
```

两列并存，说明它们**不是同义词**。唯一自洽的读法：

| 列 | 含义 | 谁维护 | 变不变 |
|---|---|---|---|
| `total_count` | 物理台账数量（这台设备一共有几台） | 管理员 | 静态 |
| `available_count` | **允许被预约系统占用的上限**（≤ total_count，留出备用机） | 管理员 | 静态 |

**`available_count` 不是「当前还剩几台」。** 剩余量是**算出来的**：

```
某设备在某时段的剩余量
    = available_count
      − 该时段重叠订单中「出现该设备」的订单数
```

**谁扣：没人扣。何时扣：不适用。取消回补：无需回补（因为从没扣过）。§5.5：不新增第 7 步。**

---

## 2. 为什么不能写时扣减：一个整数列表达不了「今天下午还剩 2 个」

这是问题的根，不是实现细节：

- `available_count` 是**设备级的单值**，不带时间维度。
- 而「还剩几台」是 **(设备, 时段)** 的函数。
- 写时扣减 = 用一维的量去记二维的事实，必然串台：

```
周一 14:00 张三借走投影仪 → available_count: 3 → 2
周一 20:00 李四来借       → 看到 2，以为是「现在还剩 2」
                           其实是「周二整天也只剩 2」—— 周二的名额被周一吃掉了
```

一旦某天扣到 0，**不取消就永远借不到**，且没有任何自然事件能把它救回来。

反过来若坚持扣减，就必须一次性把四条规则全定死，缺一条就出漏洞：

| # | 规则 | 取值 |
|---|---|---|
| 1 | 谁扣 | `create_order` 第 5 步（INSERT 之后），**同一事务内** |
| 2 | 何时扣 | INSERT 之后立即 |
| 3 | 何时回补 | **取消(3) 和 完成(4) 两者都要** |
| 4 | §5.5 | 新增第 7 步「回补库存」 |

⚠️ **最大的陷阱是第 3 条**：只回补「取消」、忘了「完成」——

```
订单完成(4) → 占用结束，但库存没回补
    ↓
available_count 单调递减，用一次少一次
    ↓
几周后恒为 0，设备再也借不出去，且现象像是「设备坏了」
```

这个 bug 不会报错、不会进日志，只会在演示前一天被发现。

---

## 3. 实现：`_device_conflicts` 的判据是计数比较

`app/services/order_service.py::_device_conflicts` 从**「只要查到重叠就冲突」**
改为**「`重叠单数 >= available_count` 才拒」**：

```python
used: Counter[int] = Counter()
for row in rows:
    for did in _hit_device_ids(row.device_ids, wanted):
        used[did] += 1          # 一单里同一台设备只算一次

full = {did for did in wanted if used[did] >= caps.get(did, 0)}
```

返回**形状不变** —— 仍是 `docs/模块3-api.md` 里 `create_order` 冻结的
`{"conflicts": [{"orderId", "deviceIds", "startTime", "endTime"}, ...]}`（一单一条）。
改形状要走 `§5.3`，本次只是把**列出来的单**限制为「碰到已约满设备」的那些，
否则「A 满了」会把只用到空闲 B 的单也一并报出来。

`reason` 文案随之从「该时段设备已被占用」改为「该时段设备已约满」：
容量 > 1 时，重叠单数没到上限本来就不算冲突，走到拒绝分支的都是名额用光，
旧文案会让人以为「只要没人用就行」。

---

## 4. AGENT-C-01/02 的判据（可直接写成断言）

设某设备 `available_count = 2`：

| # | 前置 | 动作 | 期望 |
|---|---|---|---|
| 1 | 无重叠订单 | 建第 1 单占用该设备，时段 T | 成功，`order_status=1` |
| 2 | 已有 1 单占用 T | 建第 2 单，同一设备、同一 T | **成功**（2 ≤ cap） |
| 3 | 已有 2 单占用 T | 建第 3 单，同一设备、同一 T | **拒绝**，`409` + `code=40901`（`RESOURCE_CONFLICT`） |
| 4 | 已有 2 单占用 T | 把其中一单 `cancel`(→3) | 成功 |
| 5 | 承上 | 再建第 3 单，同一设备、同一 T | **成功**（回落到 1 < 2） |
| 6 | 已有 2 单占用 T | 与 T **相邻但不重叠**的时段 T' | **成功**（半开区间，相邻不算冲突） |
| 7 | 已有 2 单占用 T | 第 3 单用**不同设备**、同一 T | **成功**（容量按设备各算各的） |

第 5 条是这套口径的**核心价值**：取消后名额自动回来 —— 不需要任何回补代码，
因为名额本来就是算出来的。`ACTIVE_ORDER_STATUSES` 只有 1待确认 / 2已确认，
3已取消 / 4已完成是终态，离开该集合即不再计入。

用例位置（判据 1~3、6、7 在服务层，判据 4、5 另有一条走真实 HTTP 的全链路）：

- `backend/tests/module3/test_order_service.py` —— `test_capacity_allows_up_to_available_count`、
  `test_cancel_frees_a_slot_without_any_refund_code`、`test_adjacent_slot_does_not_consume_capacity`、
  `test_capacity_is_counted_per_device`、`test_successful_order_never_writes_available_count`
- `backend/tests/module3/test_orders.py` —— `test_agent_c01_02_capacity_and_cancel_roundtrip`

**注意 HTTP 层拿不到 `conflictDetail`**：本模块的错误响应按 `docs/模块3-api.md` 的约定
把 `data` 置 `null`，路由层 `_error_for` 只透传 `reason` 作为 `message`。要读结构化冲突
详情得直调 `create_order`（Agent 的 `lock_resources` Tool 就是这么调的）。

> **顺带一条可用的余地**：团队 `docs/api.md` §统一响应体写的是「失败时 `data` 为 `null`
> **或补充信息**」—— 也就是说把 `conflictDetail` 放进失败响应的 `data` 并**不违反**
> 团队约定，只是会改本模块的对外契约（§5.3），本轮不做。前端若需要结构化冲突详情，
> 这是成本最低的一条路，比新增一个查询接口小。

---

## 5. 代价（不藏）

`device_resource` **没有 `space_id`** —— 设备是**全局资源，不挂在场地**。
所以「某设备在某时段被占了几次」必须**跨场地**统计，`§6.6` 的
`idx_space_time(space_id, start_time, end_time)` **帮不上**（这台设备可能出现在任何场地）。

**已部分解决（2026-09-28，main `98c54ea`）**：集成组按这条反馈补了
`idx_status_start (order_status, start_time)`，正对 `_device_conflicts` 的谓词
（`order_status IN (活跃) AND end_time > :start AND start_time < :end`），
第一段「捞重叠活跃单」不再退化成全表扫描。迁移见 `b7f1c4a92e35`，
索引登记在 `tests/module3/test_config_alignment.py::_EXTRA_INDEXES`。

**仍未解决**：按设备计数那一步没有索引可用 —— `device_ids` 是 JSON 列，
普通索引无从下手，多值索引 / 生成列都要先定口径。现状是捞出活跃重叠单后在
Python 里数，**尽力而为的正确性，不做性能承诺**。真正的解法（设备占用表 /
生成列 / 多值索引）超出模块 3 范围，仍需集成组给口径。

---

## 6. `release_occupancy` 已删除（2026-09-28 定：删）

`app/state_machine.py::release_occupancy` 原先是个 `pass` 空函数，只在取消「已确认」
单时被调用。按上面的口径，**它本来就不需要做任何事** —— 名额是算出来的，取消单
离开 `ACTIVE_ORDER_STATUSES` 即自动释放。但「半死不活的 hook 比没有更糟」：调用点
看起来在释放，实际是空操作。

**结论：删函数 + 删调用点 + 删对应的 monkeypatch 用例。** 理由：

- 从不扣减 ⇒ 无回补需求，函数名暗示的「释放占用」在新口径下没有语义
- 留着反而危险：将来有人真往里写 `available_count += 1`，就同时破坏了
  「只读不写」与「不产生第二份真值」两条

已核实它**除了空操作什么都不做**（没有回补、没有改状态、没有释放锁），调用方
**只有 `api/orders.py::cancel_order` 一处**，测试里只有两条 monkeypatch 观测它。
原 TC-11「取消已确认预约触发释放占用」改为断言**可观测结果**：取消后同一时段、
同一设备能再下一单（比断言内部调用更结实，不依赖任何内部实现）。

> **更正（2026-09-28）**：这里原写「`docs/test.md` 的 TC-11 仍写着旧 hook，请集成组同步」，
> **不成立**：`origin/main:docs/test.md` 的 `release_occupancy` 命中数为 0。写着旧 hook
> 的是本模块自己的文档（现 `docs/模块3-test.md`），已改成上面的可观测断言。
> 团队文档无需改动。

---

## 7. 并发缺陷：跨场地共用设备会超卖（已修，云库未验证）

**现象**（模块 4 徐川报的 3b；本地稳定复现 13/13 次）：3 个协程各占一个场地、
抢同一台 `available_count = 2` 的设备，**3 单全成**（应恰好 2 单）。

**根因不是「忘了加设备行锁」，而是「设备行锁加在哪儿」**。

第 4 步是「先读后判再写」：读（数重叠单）与写（第 5 步 INSERT）之间若不排他，
两个事务会各自读到「还差一个名额」然后都插入。场地行锁挡不住 —— 设备是**全局
资源**（`device_resource` 没有 `space_id`），同一台设备可以出现在不同场地的订单里，
跨场地的两个事务在场地行上根本不碰面。

但**只把设备行锁补在第 4 步仍然不够**。云库是 InnoDB 默认的 `REPEATABLE READ`：
非加锁 SELECT 读的是「本事务**第一条非加锁读**」时定下的读视图，`FOR UPDATE`
读的才是最新已提交版本。于是：

```
T2 先做了 db.get(SysUser, ...) / _time_conflicts（都是非加锁读）
    → T2 的读视图在此刻钉死，早于 T1 提交
T2 此刻才去锁设备行 → 确实会等 T1 提交，但读视图不会因此刷新
T2 随后数重叠单（_device_conflicts 也是非加锁 SELECT）
    → 读的是旧视图，看不见 T1 刚插入的那一单 → 少一单 → 放行 → 超卖
```

一句话：**锁了一行、却从另一张表的旧快照里读计数，这把锁是白加的。**

**修法**：设备行锁提前到**第 2b 步**（紧随场地锁，在 `db.get(SysUser, ...)` 与
`_time_conflicts` 之前），并按设备 id **升序**加锁（顺序不定会死锁）。
见 `app/services/order_service.py::_lock_devices_stmt`。这是**扩了 `§5.5` 的锁
足迹**（第 2 步原本只锁场地行），复核时请一并看。

### 哪些性质离线可验证、哪些不可

| 性质 | SQLite 上可验证 | 钉在哪 |
| --- | --- | --- |
| 语句里写了 `with_for_update()` | ✅ 编译两种方言比对 | `test_device_lock_is_emitted_on_mysql_and_compiled_away_on_sqlite` |
| 两条锁都排在第一条非加锁读**之前** | ✅ 语句顺序不受方言影响 | `test_row_locks_are_taken_before_any_non_locking_read` |
| 三方并发下不超卖 | ❌ 永远红 | `test_concurrent_device_creation_does_not_oversell`（`xfail(strict=True)`） |

**为什么第三条在 SQLite 上必然红**：`FOR UPDATE` 被方言编译掉，且 pysqlite 默认
不为 SELECT 开启事务（不持有读锁），三个协程因此必然都读到「还差一个名额」。
`tests/conftest.py` 早已写明「事务并发、行锁、时区这三类行为无法在此验证」。

⚠️ 所以 **3b 的 xfail 不能在 SQLite 上摘**。若在云库上跑通，`strict` 会把 XPASS
转成 FAILED —— 那才是摘标记的信号（这也是选 strict 而非普通 xfail 的原因）。

⚠️ 「读视图由第一条非加锁读建立」这条推演**未在云库实测**（离线推自 InnoDB 行为：
读视图只在一致读时 `trx_assign_read_view`，`FOR UPDATE` 不建立它）。若云库实测仍
超卖，说明行锁这条路不够，得走下面的占用表。

### 仍未解决：根治靠占用表

行锁（无论加在哪一步）都是**把一个本可并行的判定串行化**，代价是同一时段的创建
被排成队；而它保护的其实不是「那一行」，是一个范围谓词。根治办法是把设备占用
物化成行：

- 新增设备占用表（`device_id` / `start_time` / `end_time` / `order_id`），
  在 `(device_id, start_time)` 上加唯一键，或对范围查询加行锁；
- 或让 `device_ids` 走生成列 / 多值索引，使「按设备计数」这一步能走索引。

两者都要改 `§6.3` 表结构或索引口径，**超出模块 3 范围，仍等集成组给口径**。
在此之前：**尽力而为的正确性 + 不做性能承诺**（与第 5 节同一口径）。

### 顺带发现：场地维度的时段判定有同一结构

`_time_conflicts` 也是「锁 A 行、查 B 表」——场地行锁同样不锁 `reserve_order` 的
时段范围。场地路径**目前看起来是安全的**，靠的正是本节的修法：场地行锁是事务里的
**第一条语句**，所以读视图是等锁之后才建立的。

「锁必须早于任何非加锁读」这条纪律对场地锁同样成立，而且比设备那一侧更脆：
日后若有人在场地锁之前插一句非加锁读（哪怕只是查一次配置），同场地的时段冲突
就会一起失效，而现有用例（跑在 SQLite 上）**全都是绿的**。所以
`test_row_locks_are_taken_before_any_non_locking_read` 一次断言两条锁的顺序
（`space_resource` → `device_resource` → `sys_user`），不只断言设备那一侧。
