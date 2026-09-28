# 给徐川：`available_count` 扣减/回补口径 —— 判据与结论

> 你问的四点（谁扣 / 何时扣 / 取消回补 / §5.5 是否补第 7 步），结论先给：
> **一条都不做 —— 因为不扣减。改为「用时推导」。**

---

## 1. 先把口径定死：`available_count` 是静态上限，不是实时剩余

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

## 3. 你要改的地方（仅一处）

`app/services/order_service.py` 的 `_device_conflicts`，现在的判据是
**「只要查到重叠就冲突」**：

```python
for row in result.all():
    hit = _hit_device_ids(row.device_ids, wanted)
    if hit:
        conflicts.append(...)      # ← 一个重叠就拒
```

改为**计数比较**：

```python
# 按 device_id 分组累计重叠次数，count >= available_count 才拒
per_device = collections.Counter()
for row in result.all():
    for did in _hit_device_ids(row.device_ids, wanted):
        per_device[did] += 1
for did in wanted:
    cap = caps[did]                    # 取自 device_resource.available_count
    if per_device[did] >= cap:
        conflicts.append({"deviceId": did, "used": per_device[did], "cap": cap})
```

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
因为名额本来就是算出来的。

---

## 5. 需要你知道的代价（我不藏）

`device_resource` **没有 `space_id`** —— 设备是**全局资源，不挂在场地**。
所以「某设备在某时段被占了几次」必须**跨场地**统计，`§6.6` 的
`idx_space_time(space_id, start_time, end_time)` **帮不上**（这台设备可能出现在任何场地）。

现状：`_device_conflicts` 只能捞出**全部**活跃重叠订单再在 Python 里数。
数据量上来前可用，但这是**尽力而为的正确性，不做性能承诺**。

已随本轮一并反馈给集成组（对应 `§6.6` 只有 9 个 `idx_*`、没有设备维度的索引）。
真正的解法（设备占用表 / 生成列 / 多值索引）超出模块 3 范围，需要集成组给口径。

---

蔡玉礼
2026-09-28
