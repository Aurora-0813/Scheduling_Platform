# 数据库设计文档

> 适用范围：本项目使用的全部 9 张业务表、索引、迁移流程与种子数据。
> 主管模块：**模块 10 系统集成与联调**（表结构变更由集成组统一执行，`开发流程.md` 6.5）。
>
> 权威来源：仓库根目录 `开发流程.md` 第 6 章（数据库规范）。
> 本文档与 `开发流程.md` 6.3 一致的字段定义**不重复罗列**，只说明差异、索引、迁移与数据。
> 表结构变更请走第 6 节的迁移流程，**不要**手改云库后不同步代码。

---

## 一、连接规范

| 配置项 | 值 |
| --- | --- |
| 云服务器地址 | 见 `.env` 中 `DB_HOST`（开发机上为 **SSH 隧道本端**，非云服务器真实 IP） |
| 端口 | 见 `.env` 中 `DB_PORT`（默认 `3308`，隧道映射端口） |
| 数据库名（dev） | `smart_scheduler_dev` |
| 数据库名（test） | `smart_scheduler_test` |
| 用户名 | 见 `.env` 中 `DB_USER` |
| 密码 | 见 `.env` 中 `DB_PASSWORD` |
| 字符集 | `utf8mb4` |
| 驱动 | `asyncmy`（异步，**禁止** PyMySQL / mysqlclient） |

连接串由 `app/core/config.py` 从 `DB_*` 各项拼接，**不单独配置 `DATABASE_URL`**，避免两处配置漂移：

```
mysql+asyncmy://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4
```

> ⚠️ **项目文档 6.1 要求所有开发人员连接云服务器上的统一 MySQL，禁止使用本地数据库。**
> 开发机通过 SSH 隧道连接，因此 `.env` 里的 `DB_HOST=127.0.0.1` 是隧道本端、`DB_PORT=3308` 是隧道端口，
> 它们**不是**云服务器的真实地址与端口。隧道命令见 `docs/deploy.md`。
>
> Navicat / DBeaver 仅用于可视化查询，连接信息从 `.env` 读取，**不写入任何文档**（`开发流程.md` 6.1 / 9.4）。

**连接超时**：`DB_CONNECT_TIMEOUT`（默认 5 秒）。不设它时，隧道没起 / 云库不可达会让每次连接尝试等到操作系统 TCP 超时
（Windows 上可长达 20 秒以上），表现为进程启动卡住、`/ready` 长时间无响应、迁移前先干等半分多钟。

---

## 二、表清单

9 张表，字段定义见 `开发流程.md` 6.3，命名遵循 6.2（表名与字段名 `snake_case`、表名单数）。

| # | 表名 | 说明 | 主责模块 |
| --- | --- | --- | --- |
| 1 | `sys_user` | 用户表，单角色（`role_id` 单值） | 9 |
| 2 | `sys_role` | 角色表，`permissions` 为 JSON 数组 | 9 |
| 3 | `sys_permission` | 权限字典表（**鉴权不查它**，见第 4 节） | 9 |
| 4 | `space_resource` | 空间资源表 | 5 |
| 5 | `device_resource` | 设备资源表 | 5 |
| 6 | `reserve_order` | 预约订单表 | 3 |
| 7 | `inspect_record` | 巡检记录表 | 6 |
| 8 | `repair_ticket` | 维修工单表 | 6 |
| 9 | `notify_message` | 消息通知表 | 7 |

### 枚举字段取值（数据字典，`开发流程.md` 6.3）

| 表.字段 | 取值 |
| --- | --- |
| `sys_user.status` | `1` 正常 / `0` 禁用 |
| `space_resource.space_type` | `1` 会议室 / `2` 展厅 / `3` 多功能厅 / `4` 户外场地 |
| `space_resource.status` | `1` 可用 / `0` 停用 |
| `device_resource.device_status` | `1` 完好 / `2` 损坏 / `3` 缺失配件 |
| `reserve_order.order_status` | `1` 待确认 / `2` 已确认 / `3` 已取消 / `4` 已完成 |
| `repair_ticket.ticket_status` | `1` 待处理 / `2` 处理中 / `3` 已完成 |
| `notify_message.notify_type` | `1` 预约提醒 / `2` 变更致歉 / `3` 故障告警 |
| `notify_message.is_read` | `0` 未读 / `1` 已读 |

> 上表的 `0`/`1`、`1`/`2`/`3` 是**数据库内部**的整型枚举，与接口无关。
> **API 传输的布尔值必须是 `true`/`false`**（`开发流程.md` 5.1），由各模块的 schema 层负责转换。

### `agent_trace` 字段（`开发流程.md` 6.4）

`reserve_order.agent_trace` 存储 Agent 完整思考过程（Thought-Action-Observation），用于前端可视化展示及答辩溯源。
**其 JSON 结构由模块 4（核心调度 Agent）定义**，模块 10 不预设格式；`docs/seed.sql` 刻意将该字段留空。

---

## 三、索引

先说清两个容易混的数字 —— 它们都等于 11，但**不是同一批**：

| 口径 | 条数 | 说明 |
| --- | --- | --- |
| `开发流程.md` 6.6 的表格**行数** | **11** | 含 `uk_username`（UNIQUE），它**只检查、不创建**（见 3.2） |
| 6.6 里由本迁移**创建**的索引 | **10** | 即上表去掉 `uk_username` |
| 本迁移**实际建出**的索引 | **11** | 上述 10 条 + 1 条 6.6 之外的 `idx_status_start`（见 3.4） |

三者关系一句话：**`uk_username` 不建（模型已 `unique=True`），`idx_status_start` 多建（6.6 没写）**，
一减一加恰好还是 11 —— 所以别用「11 条」相互印证，两批的组成不同。

以下表格列出全部 **12** 行：迁移**建出**的 11 条 + 只**检查**的 `uk_username`。

| 表 | 索引 | 类型 | 列 | 用途 |
| --- | --- | --- | --- | --- |
| `sys_user` | `uk_username` | UNIQUE | `username` | 登录查询 |
| `space_resource` | `idx_space_type` | NORMAL | `space_type` | Agent 按类型检索 |
| `space_resource` | `idx_capacity` | NORMAL | `capacity` | Agent 按容量检索 |
| `device_resource` | `idx_device_type` | NORMAL | `device_type` | Agent 按类型检索 |
| `reserve_order` | `idx_user_id` | NORMAL | `user_id` | 用户订单查询 |
| `reserve_order` | `idx_space_time` | COMPOSITE | `space_id, start_time, end_time` | 并发预约冲突检测 |
| `reserve_order` | `idx_status` | NORMAL | `order_status` | 状态筛选 |
| `reserve_order` | **`idx_status_start`** | COMPOSITE | `order_status, start_time` | **设备维度**的时段占用统计（**6.6 之外**，见 3.4） |
| `inspect_record` | `idx_space_id` | NORMAL | `space_id` | 空间巡检查询 |
| `repair_ticket` | `idx_device_id` | NORMAL | `device_id` | 设备工单查询 |
| `repair_ticket` | `idx_ticket_status` | NORMAL | `ticket_status` | 工单状态筛选 |
| `notify_message` | `idx_receiver_read` | COMPOSITE | `receiver_id, is_read` | 未读消息查询 |

### 3.4 第 11 条索引 `idx_status_start`（**6.6 之外**）

**为什么加**：统计「某台设备在某时段被占用几次」时，6.6 的索引在这一维度**全部失效**：

- 设备是**全局资源**（跨场地共用），`device_resource` 没有 `space_id`，
  所以 `idx_space_time(space_id, ...)` 的**最左前缀**用不上；
- `reserve_order.device_ids` 是 JSON 列，不能直接建索引。

模块 3 的 `_device_conflicts` 因此只在 SQL 里过滤「状态 + 时段重叠」，设备匹配退回 Python。
它的谓词是：

```sql
WHERE order_status IN (活跃) AND end_time > :start AND start_time < :end
```

没有这条索引时只能**全表扫描**。加上后 `order_status` 等值 + `start_time` 范围可走索引，
扫描量降到「该状态在 `:end` 之前开始的订单」。
**注意列序**：`order_status` 是等值列必须在前，反了索引就用不上。

两点如实声明：

- 它的**最左前缀 `order_status` 已覆盖 6.6 里 `idx_status` 的用途**。保留 `idx_status`
  是因为本迁移是**纯增量、不删索引**；等确认线上没有旧版本代码依赖后可合并为一条。
- 这只是**中间档**，不是终局方案。彻底的做法是建 `order_device` 关联表、
  或用 MySQL 8.0.17+ 对 JSON 列的多值索引，两者都超出本轮范围。

> **6.6 的原文并未包含这一条**，是集成组确认后补的。若 §6.6 要收编它，
> 应同步更新 `开发流程.md` 6.6 的清单（本轮未改团队文档）。

### 3.1 为什么迁移是「幂等」的

`开发流程.md` 6.5 说明「所有表已在云服务器创建完成」，也就是说云库里**已经有数据、也可能已经有别人建的索引**。
当前网络不可达，无法核实云库现状，因此直接 `op.create_index` 有风险：

- 索引已存在 → 报 `Duplicate key name` 而**中断迁移**；
- 只看索引名判断也不够 —— `uk_username` 这种索引在库里的实际名字可能是 MySQL 按列名自动生成的 `username`。

所以 `b7f1c4a92e35` 在**创建前逐个检查**，存在则跳过并记日志。**无论云库现状如何，重复执行都安全**
（可以反复 `alembic upgrade head`）。

**存在性按「列」判断，不按「名」判断。** 这是上面第二条的直接后果，也是本迁移最初**踩过的坑**：
MySQL 会为**每个外键自动建索引**，名字形如 `inspect_record_ibfk_1`，与 6.6 点名的
`idx_space_id` / `idx_device_id` 对不上 —— 只比名字就会在 `space_id` / `device_id` 上
**再建一条同列的重复索引**：白占空间、拖慢写入，而且不报错，只会安静地留在云库里。

判定口径是**列序列完全相同**（含顺序），不是「前缀相同」。
刻意不取前缀：前缀判定会让 6.6 点名的索引在 `SHOW INDEX` 里彻底不出现，
这正是本轮「三方复现报索引缺失」那类**误判**的来源。
对应实现见 `alembic/versions/b7f1c4a92e35_*.py` 的 `_index_on_columns`，
护栏是 `tests/integration/test_migrations.py::test_upgrade_skips_columns_already_indexed_under_another_name`
（SQLite 不为外键建索引，该用例**手工造出** `..._ibfk_N` 的现场）。

### 3.2 `uk_username` 只检查、不创建

`sys_user.username` 在 ORM 里已声明 `unique=True`，初始迁移 `8969262c9d0c` 也已在建表时建出唯一索引。
再建一个名为 `uk_username` 的唯一索引会在同一列上留下**两个**唯一索引（纯浪费），
而且若云库里存在重复用户名，建唯一索引会直接失败并中断迁移。

因此迁移只**检查并告警**。若告警提示缺失，说明云库表结构与 `开发流程.md` 不一致，
属数据库结构变更，**必须先与集成组确认**再处理。

### 3.3 防误删：`_include_object` 钩子

MySQL 会为**每个外键自动创建索引**（如 `sys_user.role_id`、各表的 FK 列）。这些索引存在于数据库中，
但不出现在 ORM 模型的索引声明里。若不拦截，`alembic revision --autogenerate` 会把它们当作
「数据库中多余的索引」并生成 `drop_index`，执行后会**连带影响外键约束**。

`alembic/env.py` 的 `_include_object` 对「已存在但模型未声明」的索引一律返回 `False`（不生成删除语句）。

> 取舍：这也意味着「从模型中删除索引声明」**不会**自动生成删除语句，需要人工编写迁移。
> 这是刻意的选择 —— 误删索引的代价远高于多写一条迁移。

因此 ORM 模型侧也补齐了 `__table_args__` 声明（**只加索引声明，字段定义一律未改**）：

| 模型文件 | `__table_args__` |
| --- | --- |
| `app/models/resource.py` `SpaceResource` | `idx_space_type`、`idx_capacity` |
| `app/models/resource.py` `DeviceResource` | `idx_device_type` |
| `app/models/reservation.py` `ReserveOrder` | `idx_user_id`、`idx_space_time`、`idx_status`、`idx_status_start`（6.6 之外，见 3.4） |
| `app/models/inspection.py` `InspectRecord` | `idx_space_id` |
| `app/models/inspection.py` `RepairTicket` | `idx_device_id`、`idx_ticket_status` |
| `app/models/notification.py` `NotifyMessage` | `idx_receiver_read` |
| `app/models/system.py` | 无（`username` 已是 `unique=True`，不需要额外索引声明） |

---

## 四、角色与权限的存储（重要）

### 4.1 鉴权的权威来源是 `sys_role.permissions`

**`sys_role.permissions`（JSON 列）是授权的唯一权威来源**；`sys_permission` 表降级为「前端菜单渲染用的字典」，
**鉴权时不查它**。

| 方案 | 优点 | 缺点 |
| --- | --- | --- |
| 三层 join（user → role → permission） | 规范化，权限可复用 | 每次请求多一次 join；改权限要改关系表 |
| **JSON 数组存权限码（采用）** | 鉴权只需一次 `sys_user` + `sys_role` 查询 | 权限码是字符串，改动需同步代码常量 |

权限码格式为 `模块:动作`，例如 `order:create`。完整清单定义在 `app/core/permissions.py` 的 `Permission` 类。

### 4.2 角色

| `role_name` | 说明 | 权限数 |
| --- | --- | --- |
| `admin` | 系统管理员 | 26 |
| `resource_admin` | 资源管理员 | 19 |
| `user` | 普通用户 | 10 |

结构上保证 **`user` ⊂ `resource_admin` ⊂ `admin`**（层层包含），该关系由 `docs/seed.sql` 的自查查询与
测试共同保证。

### 4.3 容错：`permissions` 列可以是任意形态

`permissions` 是 JSON 列，理论上存字符串数组，但实际（手工建表、中途改结构、别的同学用 Navicat 填数据）可能碰到：

```
NULL
[]
{"order:create": true, "order:view": false}     ← 权限位映射
"[\"order:create\"]"                            ← JSON 文本
"order:create,order:view"                       ← 逗号分隔
"order:create"                                  ← 裸字符串
"order:create;order:view" / 全角逗号 / 空格分隔
```

`app/core/permissions.py` 的 `normalize_permissions()` 把这些形态全部归一成 `set[str]`，鉴权逻辑不关心存储形态。
上述 7 种形态都由 `tests/integration/test_auth_flow_db.py` 的参数化用例逐一到**门禁处**验证过。

**回落规则**：仅当 `permissions` 解析结果为空、而 `role_name` 是已知角色时，才回落到代码里的静态映射
（`ROLE_PERMISSIONS`）。这样即使云库的 `permissions` 列还没填数据，演示也不会整个鉴权失效；
回落时角色名会记入日志。**「解析结果非空就不用静态映射」这条很重要**：
把权限改成 `["order:view"]`（非空但很少）会**立即生效**，不会因为「看起来像没配」而被静态映射覆盖。

### 4.4 `sys_permission` 表当前为空

`docs/seed.sql` **刻意不插入** `sys_permission` 数据：它的内容是前端菜单字典，属于模块 2（前端集成）与菜单设计的一部分，
改动它会牵动前端，因此由前端负责人维护，种子脚本不塞一份可能与页面不同步的副本。

---

## 五、`BIGINT` 与 `BIGINT UNSIGNED` 的差异（必须知道）

| | 云库（`开发流程.md` 6.3） | ORM 模型 |
| --- | --- | --- |
| 主键 / 外键类型 | `BIGINT UNSIGNED` | `BigInteger`（**有符号**） |

这是**已知的、刻意保留的**不一致：

- **不动模型**：改模型字段类型会牵动所有模块的 ORM 定义与全部迁移，风险远大于收益；
- **在迁移层屏蔽**：`alembic/env.py` 的 `_compare_type` 钩子对 `BigInteger ↔ BigInteger` 一律返回「不视为差异」，
  避免每次 `autogenerate` 都生成大量 `MODIFY COLUMN` 噪音，掩盖真正的结构变更。

**影响与边界**：

- 业务层无需关心：Python 的 `int` 无符号/有符号之分，`asyncmy` 读回来的都是整数；
- 真正的风险是**有人真的去改模型**：若有人把 ORM 改成 `UNSIGNED`，`_compare_type` 那条规则会同时失效，
  autogenerate 会开始生成 `MODIFY COLUMN`。改这条规则前请先读完本节。

---

## 六、迁移规范（Alembic）

### 6.1 Alembic 是 schema 的**唯一来源**

项目文档 6.5 / 6.7 描述的是「集成组手工执行 DDL 并同步文档」的流程。本项目已由 Alembic 迁移取代该流程：
**表结构与索引一律通过迁移变更**，不再手工执行 DDL。`docs/database.md`（即本文档）负责记录「当前 schema 是什么」。

当前迁移链：

```
8969262c9d0c  init_tables_single_role      ← 建 9 张表（已有）
      ↓
b7f1c4a92e35  add_doc66_indexes_idempotent ← 幂等补 11 个索引（6.6 的 10 个 + 3.4 的 1 个）
```

### 6.2 常用命令

```bash
# 必须在仓库根目录（backend/）执行
alembic current                  # 查看当前版本
alembic upgrade head             # 升级到最新（幂等，可反复执行）
alembic upgrade head --sql       # 只生成 SQL，不执行（人工评审用）
alembic downgrade -1             # 回滚一步
alembic revision --autogenerate -m "描述"    # 生成迁移（必须人工审查！）
```

### 6.3 四个必须知道的坑

#### ① 只能用 `alembic`，不能用 `python -m alembic`

仓库根目录下有个名为 `alembic/` 的迁移目录（无 `__init__.py`）。从仓库根用 `python -m alembic` 启动时，
它会作为**命名空间包**遮蔽真正的 alembic 包，报：

```
No module named alembic.__main__; 'alembic' is a namespace package
```

`scripts/dev.sh` 与 CI 里都走控制台脚本（`.github/workflows/backend-ci.yml` 同理）。

#### ② 连接串只从 `.env` 来，`alembic.ini` 里保持注释

`alembic.ini` 的 `sqlalchemy.url` **始终是注释状态**，禁止写入真实连接串（`开发流程.md` 9.4）。
`alembic/env.py` 从 `app.core.config` 取配置覆盖它。

编码细节：密码中若含 `%`（例如 URL 编码后的 `%40`），`configparser` 会把 `%` 当作插值语法并抛
`InterpolationSyntaxError`，因此 `env.py` 里做了 `.replace("%", "%%")`。

#### ③ `ALEMBIC_DATABASE_URL` 是**仅供离线测试**的覆盖开关

`tests/integration/test_migrations.py` 用它把迁移指向临时 SQLite 库，以便在云库不可达时验证
「迁移能建出索引」与「重复执行幂等」。

该变量**只接受以 `sqlite` 开头的连接串**，否则直接报错退出。这条限制是刻意的：
它保证这个开关**永远不可能**把迁移重定向到另一个 MySQL，从而排除「误设变量把迁移打到线上库」的风险。

#### ④ 离线模式（`--sql`）不做存在性判断

离线模式拿到的连接是 `MockConnection`，`sa.inspect()` 会抛 `NoInspectionAvailable`，
因此幂等迁移退化为**无条件 `CREATE INDEX`**，并在产物里插入一行醒目注释。

> ⚠️ 离线产出的 SQL **只用于评审与备份参考**，直接重放到已有索引的库上会报 `Duplicate key name`。
> 真正执行请用在线模式（在线分支是幂等的）。

另外，离线模式会把 SQL 写到 stdout。Windows 控制台默认用 cp936，产物会是 GBK 编码、中文注释在 MySQL 客户端里乱码，
因此 `env.py` 强制把 stdout 切到 UTF-8。

### 6.4 `autogenerate` 之后**必须人工审查**

自动生成的迁移可能包含：

- `drop_index`（已被 `_include_object` 拦截，但仍需确认）；
- 把 `positional_args` 写成 `Column(...)` 的旧风格；
- 对 SQLite 等非 MySQL 方言的误判（如果误连了别的库）。

**审查清单**：① 有没有意外的 `drop_*`；② 有没有 `MODIFY COLUMN`；③ 表名/列名拼写；④ `downgrade()` 是否真的可回滚。

### 6.5 迁移的测试覆盖

`tests/integration/test_migrations.py`（`@pytest.mark.migrations`）用 subprocess 在**独立进程**里跑
`alembic upgrade head`，避免与 pytest 的事件循环冲突。覆盖：升级成功、索引真的建出来了、重复执行幂等、`downgrade` 可回滚。

---

## 七、事务与并发控制

`开发流程.md` 5.5 规定 Agent 自动创建预约时必须在**一个事务**中完成资源锁定：

```
1. BEGIN 事务
2. SELECT ... FOR UPDATE 对目标 space_resource 行加锁
3. 校验时间重叠：查询 reserve_order 中该场地在目标时段是否存在已确认订单
4. 校验设备可用性
5. 插入 reserve_order，写入 device_ids
6. COMMIT
```

第 3 或第 4 步失败 → `ROLLBACK` 并返回友好提示。

### 7.1 事务边界的实现约定

- `get_db` **只负责「异常回滚 + 关闭会话」，不负责提交**；
- **提交必须由 `services/` 层在业务结尾显式调用 `await session.commit()`**；
- 忘记 commit 的后果是「接口返回 200、日志无异常、数据没落库」——由
  `tests/integration/test_db_session_contract.py`（`@pytest.mark.db`）用「未提交的写入在**另一个连接**里查不到」钉死。

`SELECT ... FOR UPDATE` 是 MySQL 特性。**离线测试（SQLite）跑不到行锁语义**，因此：

- 并发冲突的正确性**必须在云库上验证**（步骤见 `docs/deploy.md`）；
- 离线测试只覆盖「时间重叠校验」这类业务逻辑，SQLite 下退化为普通查询。

### 7.2 冲突检测依赖的索引

`reserve_order` 的复合索引 `idx_space_time (space_id, start_time, end_time)` 就是为第 3 步的重叠查询建的（`开发流程.md` 6.6）。
重叠判定的标准写法是 `start_time < :end AND end_time > :start`（**开区间比较**，不要用 `BETWEEN`，否则相邻时段的边界会误判为冲突）。

---

## 八、种子数据

`docs/seed.sql`，规格见 `开发流程.md` 6.9。**人工执行，不要交给应用或 CI**。

```bash
mysql --default-character-set=utf8mb4 -h 127.0.0.1 -P 3308 -u <user> -p <db> < docs/seed.sql
```

前置条件：已跑过 `alembic upgrade head`（表与索引都存在）。

### 8.1 内容

| 表 | 行数 | 说明 |
| --- | --- | --- |
| `sys_role` | 3 | `admin` / `resource_admin` / `user`，权限码与 `app/core/permissions.py` 逐字一致 |
| `sys_user` | 5 | 3 个正常账号（`admin` / `resadmin` / `user01`）+ 2 个演示用异常账号 |
| `space_resource` | 8 | 含 1 条 `status=0`（停用），供「停用场地不可预约」演示 |
| `device_resource` | 15 | 含 `device_status` 为 2/3 的行，供巡检与冲突预警演示 |
| `reserve_order` | 10 | 覆盖 4 种 `order_status`、时间相对当天计算、含 1 组**故意时段重叠**的已确认单 |

### 8.2 两个演示用异常账号

| 账号 | 状态 | 用途 |
| --- | --- | --- |
| `user02` | `status=0` | 密码正确仍返回 `40108`（账号已禁用） |
| `user03` | `role_id=NULL` | 密码正确仍返回 `40302`（未分配角色） |

两者的口令与 `user01` 相同（`User@123456`），这样演示时能说明「密码是对的，拦住你的不是密码」。
**不要把它们记进任何「可用账号清单」。**

### 8.3 幂等性

显式写主键 + `ON DUPLICATE KEY UPDATE`，因此可以**重复执行**。
重复执行的副作用是 `create_time` 保留原值、预约时间按当天重算。

> ⚠️ 它是「演示库初始化」脚本，**不是数据迁移脚本**：`ON DUPLICATE KEY UPDATE` 会**覆盖** id 1..N 上的现有行。
> 不要在云库以外的库上随手跑。

### 8.4 时间字段为什么用 `CURDATE()` 计算

预约单写死日期的话，演示时永远是「过去的预约」，看板上一条进行中的都没有。
所有时间都相对**执行当天**计算（`-2 天` ～ `+14 天`），任何一天跑都能得到一批
「已完成 / 进行中 / 待开始」齐全的数据。

### 8.5 口令（安全相关）

脚本里的口令是**显式占位口令**（写死在文件里），因此：

- 首次部署后**必须立即修改**；
- 换口令方式：

```bash
bash scripts/gen_seed_hashes.sh '新口令'
# 得到 bcrypt 哈希后：
# UPDATE sys_user SET password = '<哈希>' WHERE username = 'admin';
```

哈希用 **cost=12** 生成（与 `.env` 的 `BCRYPT_ROUNDS` 一致）；cost 低于 12 时脚本会给出警告。

### 8.6 离线校验（本仓库做过的验证）

云库当前不可达，因此 `docs/seed.sql` 通过**方言翻译后真跑一遍**来验证（脚本为一次性工具，未入库）。
验证方法：把 MySQL 特有语法翻译成 SQLite 能执行的形态后逐条执行，再断言结果。

| 翻译项 | MySQL | SQLite（验证用） |
| --- | --- | --- |
| JSON 数组构造 | `JSON_ARRAY('a','b')` | JSON 文本 `'["a","b"]'` |
| 幂等更新 | `ON DUPLICATE KEY UPDATE ...` | 整段丢弃（用显式主键 + 首次插入验证） |
| 日期运算 | `CURDATE() - INTERVAL 2 DAY + INTERVAL 9 HOUR` | `datetime('now','-2 days','+9 hours')` |
| JSON 长度 | `JSON_LENGTH(...)` | `json_array_length(...)` |

**验证结果（全部通过）**：

| 断言 | 结果 |
| --- | --- |
| **5 条 INSERT 全部可执行**（括号/引号/列名/列数正确） | ✅ |
| 行数 `sys_role` / `sys_user` / `space_resource` / `device_resource` / `reserve_order` = **3 / 5 / 8 / 15 / 10** | ✅ |
| 外键完整性（开启 `PRAGMA foreign_keys=ON`，`user_id` / `space_id` / `device_ids` 均指向真实行） | ✅ |
| 角色权限层层包含 `user(10) ⊂ resource_admin(19) ⊂ admin(26)` | ✅ |
| 5 个账号的占位口令哈希都能通过**生产代码**的 `verify_password` | ✅ |

> ⚠️ 这**不能**代替云库实测：`JSON_ARRAY` / `ON DUPLICATE KEY UPDATE` / `CURDATE()+INTERVAL` 只在这里被翻译后执行过。
> 它拦的是笔误、列错位、外键顺序、以及「口令哈希其实对不上口令」这类问题。
> 真库执行仍按 `docs/deploy.md` 的步骤由人在隧道里完成。

### 8.7 与 `开发流程.md` 6.9 的差异（**待确认**）

规格与实现的行数一致，但**构成分布不同**，已如实记录，需确认按哪一份为准：

| 项 | `开发流程.md` 6.9 | `docs/seed.sql` 实际 | 差异原因 |
| --- | --- | --- | --- |
| 用户 | 3 个 | **5 个** | 额外 2 个是演示 `40108` / `40302` 两个错误分支用的异常账号 |
| 场地类型分布 | 会议室 ×3、展厅 ×2、多功能厅 ×2、户外 ×1 | 会议室 ×4、展厅 ×1、多功能厅 ×1、户外 ×2 | 按真实使用频率铺的数据，并保留 1 条停用场地 |
| 设备类型分布 | 投影仪 ×4、音响 ×4、显示屏 ×3、无人机 ×2、直播设备 ×2 | 投影仪 ×2、麦克风 ×2、音响 ×2、摄像头 ×2、直播设备 ×1、灯光 ×1、无人机 ×2、白板 ×1、对讲机 ×1、会议平板 ×1 | 同上；且避免了「显示屏」这类可被会议平板覆盖的重复项 |
| 场地/设备/预约总数 | 8 / 15 / 10 | 8 / 15 / 10 | **一致** |

> 结论：**总数与规格一致，类型分布做了调整**。
> 若要求严格照 6.9 的分布，请告知——改 `docs/seed.sql` 的类型取值即可（不涉及表结构）。

---

## 九、测试库

`开发流程.md` 6.8：云库中另建 `smart_scheduler_test`，结构与 `smart_scheduler_dev` 一致。
测试用例连接测试库，**禁止污染正式库**。

**本项目当前的做法**：所有自动化测试**离线运行**（SQLite 临时文件库 + 假 Redis），
因此 CI 与本地开发**不需要** `smart_scheduler_test`，也不会碰云库。

| 场景 | 使用的库 |
| --- | --- |
| 本地/CI 自动化测试 | SQLite 临时文件库（`tests/conftest.py` 创建，测试结束删除） |
| 云库联调、并发验证、种子数据 | `smart_scheduler_dev` |
| 需要真库的自动化测试 | 暂不使用独立测试库，改用下述「外层事务 + savepoint 回滚」（见下） |

### 9.1 真库测试的口径（已定）

原先的备用方案是「在 `smart_scheduler_dev` 里给测试用表加 `test_` 前缀，跑完 `TRUNCATE`」。
**该方案已废弃**，原因：`test_` 前缀表要手工建、与 ORM 模型是两份定义，模型一改就悄悄偏离；
且 `TRUNCATE` 在 MySQL 中是隐式提交，回滚不了，清理失败就会把脏数据留在云库里。

现在的做法是**外层事务 + savepoint 回滚**：整个用例包在一个外层事务里，
用例内部用 savepoint 分段，结束时不提交而是整体回滚 —— 不建任何测试表、
不依赖清理语句，异常路径也会被回滚掉。
具体实现与 `_db_readonly_guard` 的收窄方案见模块 3/4 的 stage-07 附录。

若确需真库的**写**权限（含建库权限），由模块负责人**向管理员申请**后再用；
在此之前真库相关用例保持标记为 `integration` 并默认排除。

**禁止测试直接写 `reserve_order` 正式表。**

> 注：`smart_scheduler_test` 是否已建、`smart_dev` 账号有无建库权限，
> 从「阻塞项」降级为「将来若要用独立测试库时才需要核实」，
> 不再是推进的前置条件。

---

## 十、待确认项

| # | 事项 | 影响 |
| --- | --- | --- |
| 1 | 云库时区（`SELECT @@global.time_zone, NOW();`） | 决定是否给连接加 `init_command=SET time_zone`。当前全链路用**本地 naive datetime**，若云库时区不是东八区，写入与读取会出现偏移 |
| 2 | 云库现有索引的真实清单（需在隧道里查 `information_schema.statistics`） | 决定幂等迁移会「创建」还是「跳过」哪些索引；当前无法核实，故做成幂等 |
| 3 | ~~`smart_scheduler_test` 是否已建；`smart_dev` 账号有无建库权限~~ **已闭**：真库测试改用「外层事务 + savepoint 回滚」，不再依赖独立测试库（见 9.1） | —— |
| 4 | 种子数据的类型分布是否按 `开发流程.md` 6.9 调整（见 8.7） | 纯数据，不涉及表结构 |
| 5 | 云库的 `space_resource` / `device_resource` 是否已有存量数据 | 若有，`seed.sql` 的 `ON DUPLICATE KEY UPDATE` 会覆盖 id 1..N 的行 |

---

## 十一、维护约定

| 变更类型 | 流程 |
| --- | --- |
| 新增/修改**表或字段** | ① 与集成组（模块 10）确认；② 写 Alembic 迁移（**不要**手改云库）；③ 更新 `开发流程.md` 6.3 与本文档；④ 在测试库先验证（`开发流程.md` 12.4） |
| 新增索引 | 写幂等迁移（照 `b7f1c4a92e35` 的写法）+ 在模型补 `__table_args__`；同步 `开发流程.md` 6.6 与本文档第三节 |
| 修改权限码 | 改 `app/core/permissions.py`（**唯一权威**）→ 同步 `docs/seed.sql` 的 `sys_role.permissions` → 通知模块 10 与前端 |
| 新增枚举取值 | 更新本文档第二节的数据字典表，并确认相关模块的校验逻辑已同步 |

> **禁止在本文档中写入真实连接信息、密码或连接串**（`开发流程.md` 9.4 / 11.2）。
> 本文档描述的是**结构**，具体值是运维信息，只存在于 `.env`。
