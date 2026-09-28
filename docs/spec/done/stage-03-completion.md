# 阶段 03 完成文档：依赖模块就绪度与并行方案

| 项 | 内容 |
| --- | --- |
| 阶段 | 阶段 3 · 依赖模块就绪度与并行方案 |
| 对应文档 | `docs/spec/stage-03-dependency.md` |
| 负责人 | 徐川 |
| 开始日期 | 2026-09-25 |
| 完成日期 | 2026-09-27 |
| 计划工时 | 1.5 人日 |
| **实际工时** | 约 2 人日（估计值，未逐时记录；含 E2 签名返工、asyncmy 方言排障、种子数据与库对齐核对） |
| 验收测试 | `AGENT-STAGE-03` |
| **验收结论** | **有条件通过（桩层）**——4 项完成判定中 3 项全过、1 项部分通过，条件见第 2 节与第 6 节 |

## 1. 本阶段目标与达成情况

目标是把链路从"等别人"变成"不等人"：在 `app/services/` 下写出 4 个符合约定签名的桩函数，**直接查库返回真实数据、但不含业务校验层**，让阶段 4 的 Tool 层与阶段 7 的用例不阻塞于杨睿坤 / 蔡玉礼 / 黄嵩三人的交付进度。

**桩层目标已达成**：4 个桩全部可调用、返回结构正确、在**真实种子数据**上 12/12 断言通过（原始输出见第 3 节）。`create_order` 已按蔡玉礼 2026-09-27 的冻结签名改完，`lock_resources` 与 `create_order` 的命名不对称关系已在 `app/services/__init__.py` 中写死说明。

**未完全达成的一项**是"签名与约定一致，且已书面告知对应负责人"。见第 2 节。

**必须点明的性质**：本阶段验的是"桩函数能通"，**不验业务正确性**。12/12 全绿**不代表**订单能正确创建——桩不落库、不加锁、不扣库存，`orderId` 恒为 `None`。详见第 5、6 节。

## 2. 完成判定逐项核对

> 照抄 `stage-03-dependency.md` §4。**未通过项不得打勾。**

- [x] **4 个桩函数可被 Tool 层调用并返回结构正确的数据** —— 证据：第 3 节原始输出（4 个桩在真实种子数据上 12/12 断言 PASS）；桩源码 `backend/app/services/{space,device,order,notify}_service.py`
- [x] **每个桩函数有 `TODO(负责人)` 注释** —— 证据：`grep -n "TODO(" app/services/*.py`

  ```
  app/services/device_service.py:30:    TODO(杨睿坤): 替换为模块 5 的真实设备查询 service，替换时只换函数体。
  app/services/notify_service.py:32:    TODO(黄嵩): 替换为模块 7 的真实通知生成 service，替换时只换函数体。
  app/services/order_service.py:64:    TODO(蔡玉礼): 若模块 3 对入参格式有强约定，这里应换成对应的单格式校验。
  app/services/order_service.py:99:    TODO(蔡玉礼): 替换为模块 3 的真实实现，**替换时只换函数体，签名不动**。
  app/services/space_service.py:36:    TODO(杨睿坤): 替换为模块 5 的真实资源查询 service，替换时只换函数体。
  ```

- [ ] **签名与约定一致，且已书面告知对应负责人"签名不要再变"** —— ⚠️ **部分通过**，不得整体勾选。拆开看：

  | 侧 | 状态 | 依据 |
  | --- | --- | --- |
  | 与既有约定一致 | ✅ | 4 个桩签名与主文档 5.3 / 阶段 4 §3.1 冻结的 Tool 签名逐参数一致 |
  | 蔡玉礼（`create_order`） | ✅ 已闭环 | 2026-09-27 收到其冻结签名，桩已按 `create_order(*, user_id, space_id, start_time, end_time, device_ids=None, agent_request=None, agent_trace=None, order_status=1)` 改完，`签名未锁定` 注释已从该文件移除 |
  | 杨睿坤（`query_spaces`/`query_devices`） | ⛔ 未闭环 | 两侧均无签名，桩内仍带 `签名未锁定,可能与真实 service 不一致,替换时需核对` |
  | 黄嵩（`generate_notification`） | ⛔ 未闭环 → **2026-09-28 已裁定（选 A），本条闭合** | 同上；且黄嵩侧另给过一份 `(order_id, notify_type, reason) -> str` 的**冲突签名**，未澄清。**补记（2026-09-28）**：冲突已按「选 A」裁定——**Tool 层归模块 4（主文档 5.3 冻结签名）、模块 7 的 service 层保留**，黄嵩不把 `notify_tools.py` 挂进 `AGENT_TOOLS`。裁定只登记口径，**本模块零代码变更**。详见 `stage-04-completion.md` 第 5.1 节。**书面回执另计**（阶段 8 交接清单） |

  证据：`grep -n "签名未锁定" app/services/*.py`

  ```
  app/services/device_service.py:34:    签名未锁定,可能与真实 service 不一致,替换时需核对。
  app/services/notify_service.py:33:    签名未锁定,可能与真实 service 不一致,替换时需核对。
  app/services/space_service.py:32:    签名未锁定,可能与真实 service 不一致,替换时需核对。
  ```

  **E2 是对蔡玉礼闭环了，不是整体闭环。** 阶段 4 的 `query_spaces` / `query_devices` / `generate_notification` 三个 Tool 仍在返工面上。详见第 5 节 E2。

- [x] **替换清单已发项目群** —— 证据：第 4 节替换清单；负责人 2026-09-27 转达项目群

### 未通过项说明

| 条目 | 状态 | 原因 | 处置计划 | 责任人 |
| --- | --- | --- | --- | --- |
| 签名与约定一致（第 3 项）—— 杨睿坤侧 | 未闭环 | 与杨睿坤的签名对齐渠道未通，模块 5 未交付，无约定可依 | 阶段 4 写 `query_spaces`/`query_devices` Tool 时若签名仍未到，先按现桩签名实现并在 Tool 内注释标注返工面；取得签名后只换函数体 | 徐川 → 杨睿坤 |
| 签名与约定一致（第 3 项）—— 黄嵩侧 | 未闭环 → **2026-09-28 已裁定，本条闭合** | 同上；另有一份冲突签名 `(order_id, notify_type, reason) -> str` 与其模块 7 交付物边界（Tool 还是 service）未澄清 | 要求黄嵩明确"交付 Tool 还是 service"；`generate_notification` 维持现桩签名（§5.3 冻结）。**结果（2026-09-28）：黄嵩确认交付 service 层，Tool 层归模块 4（选 A）** —— 处置计划执行完毕，`generate_notification` 维持 §5.3 冻结签名不变 | 徐川 → 黄嵩（**已完成**） |

## 3. 验收测试执行记录

| 项 | 内容 |
| --- | --- |
| 测试编号 | `AGENT-STAGE-03` |
| 执行环境 | conda env `smart_dev` / `F:/conda_envs/envs_dirs/smart_dev/python.exe`（Python 3.11.9、SQLAlchemy 2.0.35）<br>库：`smart_scheduler_dev`，经 SSH 隧道 `127.0.0.1:3308` → 云服务器 MySQL（隧道 PID 13964，LISTENING 已确认）<br>数据：种子数据 `docs/seed.sql` 已导入，行数核对 `space_resource 8 / device_resource 15 / reserve_order 10 / sys_user 3 / sys_role 3`，与种子文件一致<br>编码：`PYTHONUTF8=1 PYTHONIOENCODING=utf-8`（控制台 GBK） |
| 执行命令 | `python - <<'PY' …（内联脚本：依次调用 4 个桩并对结果做断言）… PY` |
| 执行时间 | 2026-09-27 |

**原始输出**（真实输出，未改写、未摘要）：

```
==============================================================================
AGENT-STAGE-03 桩验收 · 真实种子数据
==============================================================================

--- query_spaces(capacity=40, space_type=2, 2026-10-15 13:00~17:00)
    {"count": 1, "spaces": [{"id": 4, "spaceName": "A栋3楼展厅", "spaceType": 2, "capacity": 50, "location": "A栋3楼中庭", "budget": 800.0, "openStartTime": "09:00:00", "openEndTime": "21:00:00", "status": 1}]}
    断言 count==1 且 id==4（展厅仅 id4=50人 达标，id5=35人 被容量滤掉）: PASS

--- query_devices(device_type='投影仪')
    {"count": 4, "devices": [{"id": 1, "deviceName": "投影仪01", "deviceType": "投影仪", "deviceStatus": 1, "totalCount": 1, "availableCount": 1}, {"id": 2, "deviceName": "投影仪02", "deviceType": "投影仪", "deviceStatus": 1, "totalCount": 1, "availableCount": 1}, {"id": 3, "deviceName": "投影仪03", "deviceType": "投影仪", "deviceStatus": 1, "totalCount": 1, "availableCount": 1}, {"id": 4, "deviceName": "投影仪04", "deviceType": "投影仪", "deviceStatus": 1, "totalCount": 1, "availableCount": 1}]}
    断言 count==4 且全为 deviceStatus=1/availableCount=1: PASS

==============================================================================
create_order —— 9 条路径（★ 为 §5.5 口径争议的关键证据）
==============================================================================

--- 正常时段(space7 无任何订单)
    {"ok": true, "orderId": null, "reason": "校验通过（预约人 1、场地 7、设备 [9]、2026-10-20 09:00:00 ~ 2026-10-20 11:00:00、拟落状态 1）。⚠️ 桩未落库、未扣减库存，orderId 为 None。", "conflictType": null, "conflictDetail": null, "stub": true}
    期望 ok=True conflictType=None → PASS

--- 冲突·已确认(space1 撞订单7 status=2)
    {"ok": false, "orderId": null, "reason": "场地 1 在该时段已被占用（订单 7：2026-10-15 13:00:00 ~ 2026-10-15 17:00:00），请改时段或换场地。", "conflictType": "TIME_CONFLICT", "conflictDetail": {"spaceId": 1, "orderId": 7, "startTime": "2026-10-15 13:00:00", "endTime": "2026-10-15 17:00:00"}, "stub": true}
    期望 ok=False conflictType=TIME_CONFLICT → PASS

--- ★冲突·待确认(space2 撞订单6 status=1)
    {"ok": false, "orderId": null, "reason": "场地 2 在该时段已被占用（订单 6：2026-10-15 13:00:00 ~ 2026-10-15 17:00:00），请改时段或换场地。", "conflictType": "TIME_CONFLICT", "conflictDetail": {"spaceId": 2, "orderId": 6, "startTime": "2026-10-15 13:00:00", "endTime": "2026-10-15 17:00:00"}, "stub": true}
    期望 ok=False conflictType=TIME_CONFLICT → PASS

--- ☆不占位·已取消(space4 撞订单3 status=3)
    {"ok": true, "orderId": null, "reason": "校验通过（预约人 1、场地 4、设备 无、2026-10-12 10:00:00 ~ 2026-10-12 12:00:00、拟落状态 1）。⚠️ 桩未落库、未扣减库存，orderId 为 None。", "conflictType": null, "conflictDetail": null, "stub": true}
    期望 ok=True conflictType=None → PASS

--- ☆不占位·已完成(space3 撞订单1 status=4)
    {"ok": true, "orderId": null, "reason": "校验通过（预约人 1、场地 3、设备 无、2026-10-08 09:00:00 ~ 2026-10-08 11:00:00、拟落状态 1）。⚠️ 桩未落库、未扣减库存，orderId 为 None。", "conflictType": null, "conflictDetail": null, "stub": true}
    期望 ok=True conflictType=None → PASS

--- 设备缺失(device_ids=[999])
    {"ok": false, "orderId": null, "reason": "设备不存在：[999]。请从可借设备中选择。", "conflictType": "DEVICE_NOT_FOUND", "conflictDetail": {"deviceIds": [999]}, "stub": true}
    期望 ok=False conflictType=DEVICE_NOT_FOUND → PASS

--- 设备故障(device_ids=[13] 无人机02 status=2)
    {"ok": false, "orderId": null, "reason": "设备不可用（非完好状态）：[13]。请改用替代设备。", "conflictType": "DEVICE_UNAVAILABLE", "conflictDetail": {"deviceIds": [13]}, "stub": true}
    期望 ok=False conflictType=DEVICE_UNAVAILABLE → PASS

--- 库存为0(device_ids=[15] 直播设备02 avail=0)
    {"ok": false, "orderId": null, "reason": "设备库存不足（available_count <= 0）：[15]。请改用替代设备。", "conflictType": "DEVICE_INSUFFICIENT", "conflictDetail": {"deviceIds": [15]}, "stub": true}
    期望 ok=False conflictType=DEVICE_INSUFFICIENT → PASS

--- 时间倒挂(end <= start)
    {"ok": false, "orderId": null, "reason": "结束时间(2026-10-20 13:00:00)不晚于开始时间(2026-10-20 15:00:00)，拒绝锁定。", "conflictType": "INVALID_TIME_RANGE", "conflictDetail": null, "stub": true}
    期望 ok=False conflictType=INVALID_TIME_RANGE → PASS

    create_order: 9/9 PASS

--- generate_notification(order_info)
    {"ok": true, "notifyType": 1, "title": "预约成功提醒", "content": "您预约的「A栋305会议室」已提交，时间 2026-10-15 13:00:00 ~ 2026-10-15 17:00:00。", "reason": null, "stub": true}
    断言 ok==True 且 title/content 非空: PASS
```

**结论**：**通过（桩层）**。4 个桩函数全部可调用、返回结构正确，共 12 项断言（1 + 1 + 9 + 1）全部 PASS，且**均在真实种子数据上执行**（非 mock、非空表）。

**附带的稳定性观察**：本轮 4 个桩共开启 11 次异步 session，加同批次的库核对与 A/B 对照脚本，累计 20+ 次异步入库往返**无一次 `TypeError`**——即 `9ee81fc` 关闭异步引擎 `pool_pre_ping` 的修复在真实数据量下再次成立。

**同时暴露的两项"全绿之下"的问题**（详见第 5、6 节，此处只记事实）：

1. `query_spaces(capacity=40, space_type=2, 2026-10-15 13:00~17:00)` 返回 `count=1`（space 4 "可选"），而**该时段 space 4 正被订单 9 占用**。同一时段 8 个场地中有 5 个（space 1/2/3/4/5）被 status ∈ (1,2) 的订单占用：

   ```
   【query_spaces 时段盲区】10-15 13:00~17:00 实际被占的场地（status 1/2）
      space 1 A栋201会议室     被订单 7（status=2）占用
      space 2 A栋305会议室     被订单 6（status=1）占用
      space 3 B栋102会议室     被订单 8（status=2）占用
      space 4 A栋3楼展厅       被订单 9（status=1）占用
      space 5 C栋1楼展厅       被订单 10（status=2）占用

      而 query_spaces(space_type=2, capacity>=40) 仍把 space 4 判为「可选」
      → 桩的 start_time/end_time 只收不用（space_service.py 已知缺口 #1）
   ```

2. §5.5 口径 A/B 对照（同一时段 `space_id=2, 2026-10-15 13:00~17:00`）：

   ```
   【A/B 对照】space_id=2，2026-10-15 13:00~17:00
     5.5 字面口径 status IN (2)           → 命中 无（=放行，重复预约）
     我方桩口径  status IN (1,2)           → 命中 [(6, 1)]
   ```

   主文档 5.5 第 3 步字面只校验"已确认订单"（status=2），按此口径**订单 6（status=1）不占位**，同一场地会被重复预约。这是第 6 节第 4 条的实测证据。

## 4. 交付物清单

| 交付物 | 计划路径 | 实际路径 | 状态 |
| --- | --- | --- | --- |
| 场地查询桩 | `backend/app/services/` | `backend/app/services/space_service.py` | 已交付（**未提交**，等分支裁定） |
| 设备查询桩 | 同上 | `backend/app/services/device_service.py` | 已交付（**未提交**） |
| 订单创建/资源锁定桩 | 同上 | `backend/app/services/order_service.py` | 已交付（**未提交**，已按蔡玉礼冻结签名） |
| 通知文案桩 | 同上 | `backend/app/services/notify_service.py` | 已交付（**未提交**） |
| 集中导出点 | 未计划 | `backend/app/services/__init__.py`（改动） | 已交付（**未提交**，见下） |
| 替换清单 | 完成文档 + 项目群消息 | 本节 + 项目群 | 已交付 |
| 完成文档 | `docs/spec/done/stage-03-completion.md` | 同 | 已交付 |

### 4.1 替换清单（任务 3-4）

| # | 桩函数 | 替换为 | 负责人 | 就绪后动作 | 签名状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | `query_spaces` | 模块 5 资源查询 | 杨睿坤 | 换函数体，签名不动 | ⛔ 未锁定 |
| 2 | `query_devices` | 模块 5 设备查询 | 杨睿坤 | 同上 | ⛔ 未锁定 |
| 3 | `create_order`（Tool 名 `lock_resources`） | 模块 3 订单创建 + 锁定（含 5.5 事务） | 蔡玉礼 | 同上 | ✅ 已冻结 2026-09-27 |
| 4 | `generate_notification` | 模块 7 通知生成 | 黄嵩 | 同上 | ⛔ 未锁定 → **2026-09-28 已裁定：Tool 层归模块 4（选 A），service 层归模块 7；签名按 §5.3 冻结不动，黄嵩的 `notify_tools.py` 不挂进 `AGENT_TOOLS`**。见 `stage-04-completion.md` 第 5.1 节 |

**`__init__.py` 集中导出的理由**：当前 4 个函数全是桩，替换真实实现时模块名与落点由杨睿坤 / 蔡玉礼 / 黄嵩各自决定，可能与现文件名不一致。把导入点收在 `__init__.py` 一处，替换时只改一行 import，**Tool 层与阶段 7 用例一行都不用动**——这正是"桩函数先行"策略成立的前提。若 Tool 直接导入具体模块，模块名一变就得连 Tool 一起改。

## 5. 偏离计划之处

| # | 计划 | 实际 | 原因 | 影响 | 是否需要同步团队 |
| --- | --- | --- | --- | --- | --- |
| E1 | 取得前端 `TraceStep` 书面回执后再冻结（阶段 2 门槛项） | **仍无回执**，负责人自行按 `app/schemas/agent.py` 冻结，不等回执 | 回执渠道始终未通 | 字段若被推翻：`schemas/agent.py`、阶段 5 `chains/trace.py`、阶段 7 trace 用例**双端返工**；屏 3 渲染可能崩。**此项仍挂着，未闭环** | 是 |
| E2 | 先花半天与 4 个 service 负责人对齐签名，再写桩 | **先写桩、后对齐**。蔡玉礼侧已闭环（其反向给出冻结签名）；**杨睿坤 ×2、黄嵩 ×1 仍未锁定** | 对齐渠道未通（负责人未到齐，模块 5 未交付） | 真实签名若与桩不同：阶段 4 对应 3 个 Tool 与相关用例返工。桩内已标 `签名未锁定,可能与真实 service 不一致,替换时需核对` | 是 |
| 3 | 桩函数未规定是否过滤设备可用性 | **有意不过滤**，`query_devices` 返回该类型全部设备（含 `device_status=2` 与 `available_count=0`） | 阶段 4 §3.2 规定可用性过滤是 Tool 层责任。桩若提前滤掉，`AGENT-U-02` 无法证明 Tool 真的在过滤，用例会变成假绿 | 阶段 4 必须自行实现过滤；种子数据已备两个独立见证者（id=13 只该被"状态"筛掉、id=15 只该被"可用数"筛掉） | 否 |
| 4 | `lock_resources` 冻结签名含 `user_id` 传入方式未定（未决 #1） | `create_order` **新增 `user_id` 参数**，由 Agent 调用上下文注入；Tool 签名保持 §5.3 不变（不含 `user_id`） | 蔡玉礼 2026-09-27 冻结签名时一并解决 | 无（反而闭环了未决 #1） | 是（已在项目群同步） |
| 5 | 桩函数"直接查库返回真实数据" | 查询类两桩符合；**`create_order` / `generate_notification` 只读不写库**，`orderId` 恒为 `None` | 主文档 6.8 红线：测试禁止写 `reserve_order` 正式表；且 `FOR UPDATE` 的并发语义在桩上无法验证，假装能验就是假绿 | 阶段 4/7 不得把 `ok=true` 读作"订单已创建"；防假绿标记为返回体恒带的 `"stub": true` | 否 |
| 6 | 桩返回体形状 = 冻结形状（5 键） | **额外恒带第 6 个键 `"stub": true`** | 桩必须能自证"这不是一次真实预约"；不加该键，全绿的验收输出会被误读为功能已完成 | 真实实现替换进来时该键随之消失；**任何断言 `stub` 的代码都是桩期临时代码，须一并删除** | 否 |
| 7 | 计划工时 1.5 人日 | 约 2 人日 | 签名返工、asyncmy 方言缺陷排障（`9ee81fc`）、种子数据与库对齐核对占用 | 无 | 否 |

**E1 / E2 的性质**：均为**负责人自决、接受风险后推进**，不是认为它们不成问题。明细已记于 `docs/spec/00-overview.md` §4.1，此处不重复。

**E2 的当前状态必须说清楚**：**不是"已闭环"**。蔡玉礼一侧闭环了，其余三处没有。若第 2 节第 3 项被读作"已整体完成"，阶段 4 会在没有签名的情况下写三个 Tool。

## 6. 遗留问题与阻塞

| # | 问题 | 类型 | 影响 | 责任人 | 期望闭环时间 |
| --- | --- | --- | --- | --- | --- |
| 1 | **`query_spaces` 时段盲区**——`start_time`/`end_time` 只收不用，桩不做"该时段是否已被占用"的重叠过滤。实测：`10-15 13:00~17:00` 已占的 space 4 仍被判为"可选"，**Agent 会推荐已占场地** | 阻塞 | 阶段 4 起 Agent 的候选清单会含订不上的场地，到 `lock_resources` 才被拦；用户侧表现为"推荐了一个订不上的场地"。**阶段 5 替换项，不得因本轮全绿勾销** | 杨睿坤（阶段 5 替换） | 阶段 5 替换前 |
| 2 | **`FOR UPDATE` 未验**——桩是普通 SELECT，无行锁 | 阻塞 | 低并发下测不出差别，**演示当天并发上来才翻车**。正确性由 `AGENT-C-01` 把关 | 蔡玉礼（真实实现）+ 徐川（用例） | 阶段 7 `AGENT-C-01` |
| 3 | **扣减 `available_count` 未实现**——主文档 §5.5 六步里**没有这一步**，但字段存在 | 待确认 | 谁扣、何时扣未定则设备数会越用越多 | 蔡玉礼 + 集成组 | 阶段 4 前 |
| 4 | **`conflictType` 五个取值枚举、`conflictDetail` 类型**（暂定 object） | 待确认 | 前端屏 3 要按 `conflictDetail` 渲染；契约全文（`docs/api.md` 模块 3 小节）**尚不存在**，`接口文档` 里模块 3 仍在待补充表 | 蔡玉礼 | 阶段 6 前 |
| 5 | **`update_agent_trace(order_id, trace)` 之类的 service 函数缺失**——`agent_trace` 在 `create_order` 被调用的时刻**注定残缺**（Agent 运行未结束），完整 trace 只有跑完才存在；而 Tool 不能直接改库（主文档 4.3），只能走 service 层。该函数不在冻结签名里 | 阻塞 | **不补则阶段 5 组装 trace 落库时必然撞上** | 蔡玉礼 | 阶段 5 前 |
| 6 | 4 个桩 + `__init__.py` **尚未入库** | 流程 | 分支未定；阶段 4 若从 `main` 起手会拿不到桩 | 徐川 | 阶段 4 开始前 |
| 7 | **未决 #4：`space_resource` 是否补 `tags` 字段** | 待确认 | 4.4 模块 5 的 AI 标签推荐成空转；场景检索精度不足。实测 `SELECT * FROM space_resource` **无 `tags` 列**（字段为 id/space_name/space_type/capacity/location/budget/open_start_time/open_end_time/status） | 杨睿坤 + 集成组 | 阶段 4 前 |
| 8 | **未决 #6：`notify_type` 中文枚举与 INT 字典不一致**，「延期致歉」不在字典内 | 待确认 | 通知落库类型映射错误。桩已以「延期致歉 → `None`」显式暴露，**不猜一个数字顶上** | 黄嵩 + 集成组 | 阶段 4 `generate_notification` 前 |

**第 1、2、5 条为阻塞项，已同步项目群。** 第 3、4 条为需蔡玉礼拍板的口径问题（见 `order_service.py` docstring「待蔡玉礼确认」4 条）。

> **补充（2026-09-27）**：上表第 3、4、5 条已与蔡玉礼拍板关闭，**五项契约对齐结果见
> [`contract-alignment.md`](../contract-alignment.md)**——含 `update_agent_trace` 补签名、
> `OCCUPYING_STATUS = (1, 2)`、`conflictType` 四个 snake_case 取值、`conflictDetail` 类型、
> `available_count` 只读不写。
> 其中 **`conflictType` 枚举与 `conflictDetail` 形状待 §7 全文补全**（蔡玉礼的
> `docs/api.md` §7 尚未入库，两边仓库无共同祖先，只能以文本并进团队版）。
> **本表第 5 条的行文（`update_agent_trace(order_id, trace)`）已过时**，实际签名含 `user_id`。

## 7. 未决事项进展

> 对照 `00-overview.md` §4 的 6 项，只填与本阶段相关的。

| # | 事项 | 本阶段是否已闭环 | 结论 / 当前卡点 |
| --- | --- | --- | --- |
| 1 | `lock_resources` 的 `user_id` 如何传入 | **是** | 蔡玉礼 2026-09-27 把 `user_id` 正式写进 `create_order` 签名，由 Agent 调用上下文注入；Tool 签名（§5.3）不含 `user_id`，保持不变。长期挂账的未决 #1 就此闭环 |
| 2 | `TraceStep` 是否含 `thought`/`action`/`actionInput`/`observation` | 否 | 前端书面回执仍未来。已按 `app/schemas/agent.py` 自行冻结（E1），风险挂账 |
| 4 | `space_resource` 是否补 `tags` 字段 | 否 | **本阶段未取得杨睿坤 / 集成组结论**。实测该表无 `tags` 列。阶段文档 §7 要求"本阶段就要问"，未能问到，转入第 6 节第 7 条 |
| 6 | `notify_type`(INT) 与 §5.3 模块 7 中文枚举不一致 | 否 | 桩以「延期致歉 → `None`」显式暴露，待黄嵩 + 集成组拍板 |
| 3 | 40 秒思考过程回放 vs SSE | 不适用 | 影响阶段 5 → 8，本阶段不涉及 |
| 5 | SQLite 兜底与"禁止本地数据库"冲突 | 不适用 | 影响阶段 8，本阶段不涉及 |

## 8. 下一阶段入口条件确认

> 对照 `stage-04-tools.md` §2。

- [x] **`AGENT-STAGE-03` 通过（桩函数可用）** —— **有条件通过（桩层）**：4 个桩可调用、12/12 断言 PASS；条件为第 2 节第 3 项部分未通过、第 5 节 E1/E2 挂账。桩层本身**不构成阻塞**，阶段 4 可启动
- [x] **未决 #1（`user_id` 传递方式）已与蔡玉礼对齐** —— **已闭环**：`create_order` 含 `user_id`，由 Agent 上下文注入，Tool 签名不变

**阶段 4 可启动**，但须带两条约束：

1. `query_spaces` / `query_devices` / `generate_notification` 三个 Tool 的签名**仍可能与模块 5 / 模块 7 的真实 service 不一致**（E2 未整体闭环），Tool 内不得写死对这些 service 的假设。
2. `AGENT-STAGE-04` 要求"5 个 Tool **无一直接使用 `AsyncSession`**"，而**本阶段的桩全都直接用 `AsyncSession` 查库**——这是**桩的特权**（桩就是 service 层的占位实现，主文档 4.3 禁止的是 **Tool 内**直接用 `AsyncSession`）。阶段 4 必须确认 Tool 只 `from app.services import ...`，不得复制桩里的 session 写法。

## 9. 经验与可复用产出

- **桩必须能自证是假的。** 返回体恒带 `"stub": true`，`orderId` 恒为 `None`——不加这两个标记，12/12 全绿的验收输出会被读成"订单创建功能已完成"。**验收输出的"绿"是最容易被误读的东西**，桩层尤其要主动标假。
- **"签名未锁定"这行注释本身就是证据。** 它把 E2 的返工面钉在代码里而不是留在会议记录里——评审时 `grep` 一下就知道哪几个函数还悬着。凡是"将来要替换"的占位实现，都该在源码里留下一句可 `grep` 的自述。
- **方言缺陷证明：桩能跑通 ≠ 环境没问题。** asyncmy 的 `pool_pre_ping` 缺陷（`TypeError: ping() missing 1 required positional argument`）在空库上表现为"偶发失败"，接上真数据后暴露为**确定性奇偶交替**（奇数次成功、偶数次必炸），影响面是**全后端**而非仅 Agent 模块。真数据接上后链路上的第一颗雷往往不在业务代码里。已修于 `9ee81fc`，同步引擎的 `pool_pre_ping=True` **保留是对的**（走 pymysql 无此缺陷）。
- **种子数据的状态设计让规则第一次可验证。** `reserve_order` 10 条覆盖 status 1/2/3/4，且 `10-15 13:00~17:00` 同一时段 5 个场地全满——"已取消/已完成不占位"这条规则因此第一次有了真实数据上的正反证据（订单 3=已取消、订单 1=已完成均不拦；订单 6=待确认、订单 7=已确认均拦）。
- **可复用产出**：`space_service.py` 的 `_to_dict` / `device_service.py` 的 `_to_dict` 已按主文档 6.2 与 `TraceStep.observation` 统一输出 camelCase，阶段 4 的 Tool 可直接复用该传输结构。

## 10. 确认

| 角色 | 姓名 | 确认日期 | 备注 |
| --- | --- | --- | --- |
| 负责人 | 徐川 | 2026-09-27 | |
| 模块 3 | 蔡玉礼 | **待签** | 冻结签名已到；第 6 节第 3、4、5 条待拍板 |
| 模块 5 | 杨睿坤 | **待签** | 签名未锁定（E2）；第 6 节第 1、7 条 |
| 模块 7 | 黄嵩 | **待签** | 签名未锁定且存在冲突签名（E2）；第 6 节第 8 条。**补记（2026-09-28）**：分叉已裁定**选 A**（Tool 层归模块 4、service 层归模块 7）；另 `notify_type` 映射裁定为**不扩字典、`延期致歉` → 2**。两项均**仅有项目群/口头裁定，书面回执仍缺** |
| 前端 | 待定 | **待签** | `TraceStep` 书面回执（E1，阶段 2 起挂账） |

---

> 归档后，回到 `docs/spec/README.md` 第 5 节的阶段状态表更新状态。
