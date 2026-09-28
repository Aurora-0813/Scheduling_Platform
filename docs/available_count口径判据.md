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

返回**形状不变** —— 仍是 `docs/api.md` 里 `create_order` 冻结的
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

**注意 HTTP 层拿不到 `conflictDetail`**：`docs/api.md` 规定错误响应 `data=null`，
路由层 `_error_for` 只透传 `reason` 作为 `message`。要读结构化冲突详情得直调
`create_order`（Agent 的 `lock_resources` Tool 就是这么调的）。

---

## 5. 代价（不藏）

`device_resource` **没有 `space_id`** —— 设备是**全局资源，不挂在场地**。
所以「某设备在某时段被占了几次」必须**跨场地**统计，`§6.6` 的
`idx_space_time(space_id, start_time, end_time)` **帮不上**（这台设备可能出现在任何场地）。

现状：`_device_conflicts` 只能捞出**全部**活跃重叠订单再在 Python 里数。
数据量上来前可用，但这是**尽力而为的正确性，不做性能承诺**。

已随本轮一并反馈给集成组（对应 `§6.6` 只有 9 个 `idx_*`、没有设备维度的索引）。
真正的解法（设备占用表 / 生成列 / 多值索引）超出模块 3 范围，需要集成组给口径。

---

## 6. 仍未解决的一项：`release_occupancy` 是空 hook

`app/state_machine.py::release_occupancy` 是 `pass`，只在取消「已确认」单时被调用。
按上面的口径，**它本来就不需要做任何事** —— 名额是算出来的，取消单离开
`ACTIVE_ORDER_STATUSES` 即自动释放。但「半死不活的 hook 比没有更糟」这条意见成立：
调用点看起来在释放，实际是空操作。

建议集成组二选一：要么删掉它、把「取消即自动释放」写进口径文档；
要么留作将来接入正式占用表的位置，但补一句注释说明当前为何是空实现。
