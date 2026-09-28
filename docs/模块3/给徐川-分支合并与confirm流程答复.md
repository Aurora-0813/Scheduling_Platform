# 给徐川：needConfirm 落地三截的答复

## (a) ⚠️ 口径已变：**不能再 `--ff-only`，也不能直接合**

`feat/module3-caiyuli` 确实已推上 `Aurora-0813/Scheduling_Platform`（4 个提交，tip `693ce0a`，
普通 push、**没用 force**）。

**但 `origin/main` 已经往前走了** —— 从 `6f6f6ff` 到了 `9f30d3a`：

```
9f30d3a  merge(backend): 合并模块1/2（语音输入、摄像头空间感知）并适配集成层约定
6f6f6ff  ← 模块 3 分支的基线（现已不是 main tip）
```

**所以此前给你的 `git merge --ff-only feat/module3-caiyuli` 已经作废，跑了会直接报错**
（`Not possible to fast-forward`）。请**不要**再照那条执行。

原因：集成组在这之间合并了模块 1/2，并适配了集成层约定，新增了
`app/api/v1/*`、`app/services/{auth,monitor,risk}_service.py`、`app/core/error_codes.py`、
`app/middlewares/`、`alembic/versions/b7f1c4a92e35_add_doc66_indexes_idempotent.py`、
`.github/workflows/ci.yml`。两个分支现在有 **21 个文件冲突**。

### 正确的落法：`integrate/module3` 分支 + PR

集成组自己文档（`backend/docs/代码合并冲突说明.md` §10）定的流程就是这条：

```bash
git checkout -b integrate/module3 origin/main
# 把模块 3 的增量重组上去（详见《模块3-重组冲突清单与取舍.md》）
git push origin integrate/module3
# 然后在 GitHub 上开 PR —— 不要直接推 main
```

我正在做这件事：已在一棵**独立工作树**上试合完第一轮，冲突清单与取舍见
`模块3-重组冲突清单与取舍.md`。重组完成后我会推 `integrate/module3` 并开 PR。

**在那之前，模块 3 仍不在 main 上** —— `orderId` 恒 `None` 的只读桩
（`app/api/v1/mock.py` 里的常量 `1001`）还在。

---

## (b) orders 树的挂法（你的 `api_router`）

我合并后的 `main.py` 已挂全，照抄即可：

```python
from .api import agent, conflicts, messages, orders, resources

app.include_router(orders.router, prefix="/api/v1")
app.include_router(resources.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(conflicts.router, prefix="/api/v1")
```

⚠️ **前缀两种写法并存，别加重复**：

| 模块 | router 自带前缀 | 挂载处该写 |
|---|---|---|
| orders / resources / messages / agent / conflicts | `prefix="/orders"` 等 | `prefix="/api/v1"` |
| 模块 1 voice | `prefix="/api/v1/voice"` | **不写 prefix** |
| 模块 2 image | `prefix="/api/v1/image"` | **不写 prefix** |

```python
app.include_router(image_router)   # 自身已是 /api/v1/image
app.include_router(voice_router)   # 自身已是 /api/v1/voice
```

加错会变成 `/api/v1/api/v1/image`。

另：orders 树还带一条 WebSocket **`/ws/notify?user_id=xxx`**，**不走** `/api/v1`。

---

## (c) 不用改冻结契约 —— 因为 `/agent/schedule` 压根不建单

先纠正前提：**不是「响应体没透 orderId」**，而是 `POST /api/v1/agent/schedule`
**根本没调 `create_order`**，它只出方案：

```python
@router.post("/schedule")
async def schedule_plan(...):
    ...
    data_out = schedule(data.text, occupied, space_name=...)  # {plan, backupPlan, trace, needConfirm}
    return ok(data_out)
```

真正建单的是 `POST /api/v1/orders/create`，其响应 `_order_out` 的**第一个键就是 `orderId`**。

所以 **`ScheduleData` 里本来就不该有 `orderId`** —— 方案 ≠ 订单。硬塞进去会让
「出方案」和「占资源」耦合：用户还没点确认，场地就先被锁了。

### needConfirm 流程用现有接口就能走通

| 步 | 调用 | 说明 |
|---|---|---|
| 1 | `POST /api/v1/agent/schedule` | 拿 `plan` + `trace` + `needConfirm` |
| 2 | — | 展示方案给用户 |
| 3 | `POST /api/v1/orders/create` | `spaceId`/`deviceIds`/`startTime`/`endTime` 取 `plan` 的字段；`agentRequest` 填原始需求；**`agentTrace` 直接传第 1 步的 `trace`**（同一个数组落库，前端无需转换） |
| 4 | — | 拿到 `orderId` |
| 5 | `PUT /api/v1/orders/{orderId}/confirm` | 状态机 1→2，并触发「预约已确认」通知 |

`create_order` 的 `order_status` **默认就是 `1`（待确认）**，且 `OrderCreate` 里
**没有** `order_status` 字段 —— 走 create 建出来的单天然是待确认态，正好对应 `needConfirm=true`。

### 结论：本次**不做**任何契约或 schema 改动

上面五步用**现有接口**就能跑通，不需要等任何改动。我原本考虑过给 `OrderCreate` 加一个
`orderStatus` 字段（让 `needConfirm=false` 时一步建成已确认），**已决定不加**：

- 多调一次 `confirm` 没有功能损失，行为完全一致
- 少一份要长期维护的 API 面

所以前端**按上面五步接即可，不用等模块 3 出新字段**。若将来确实需要「一步建成已确认」，
再提 —— 那也只需动 `app/schemas/order.py`（模块 3 自己的 schema），
不涉及模块 4 冻结的 `ScheduleData`，前端点头即可，不必惊动契约评审。

---

## 两点提醒

1. `PUT /{orderId}/confirm` 是**模块内扩展**（不在 §5.3 契约清单里），
   归属校验逐条做，**越权与不存在同报 404**（不泄露存在性）。
2. 身份一律从 **JWT** 解析（§5.1），请求体**不再携带 `userId`**。

---

蔡玉礼
