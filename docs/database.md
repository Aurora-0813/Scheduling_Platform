# 数据库文档

> 依据《项目文档.md》6.1~6.9。**本文件是表结构与 DDL 的唯一权威副本**（主文档 6.5 指定）。
> 表结构与索引的任何变更，必须**先由基础支撑与集成组执行**，再同步更新本文件。

---

## 一、边界说明

| 事项 | 归属 | 说明 |
| --- | --- | --- |
| 建表 / 改表 / 建索引 | **集成组** | 主文档 6.5、6.7。**任何人不得到生产库自行执行 DDL** |
| `docs/seed.sql` 的导入 | **集成组** | 导入前确认目标库为 `smart_scheduler_dev`，禁止误入正式环境 |
| 连接凭据 | **各人本地 `.env`** | 见第二节。**凭据不入本文件、不入代码、不入提交** |
| 本文件的表结构描述 | 集成组维护 | 本文与主文档 6.3 不一致时，以主文档为准并立即修正本文 |

---

## 二、库与连接规范（主文档 6.1）

所有开发人员连接云服务器上的**统一 MySQL 库**，禁止使用本地库。

| 配置项 | 值 |
| --- | --- |
| 云服务器地址 | 见 `.env` 的 `DB_HOST` |
| 端口 | 见 `.env` 的 `DB_PORT`（默认 `3308`，**是本机隧道入口端口，不是云服务器侧 MySQL 的监听端口**） |
| 业务库 | `smart_scheduler_dev` |
| 测试库 | `smart_scheduler_test` |
| 用户名 / 密码 | 见 `.env` 的 `DB_USER` / `DB_PASSWORD` |
| 字符集 | `utf8mb4` |
| 驱动 | `asyncmy`（异步） |

> ⚠️ **关于端口：`3307` 与 `3308` 不是同一个数。** 云服务器侧 MySQL 监听 `3307`，本机经 SSH 隧道接入（`ssh -L 3308:127.0.0.1:3307 <user>@<云服务器IP> -N`），隧道在**本机**的入口是 `3308`。代码连的是本机入口，所以 `.env` 的 `DB_PORT` 填 `3308`；填成 `3307` 会连到本机一个没人监听的端口，报错只有一句「连接被拒绝」，极难定位。同理，走隧道时 `DB_HOST` 恒为 `127.0.0.1`，云服务器 IP 只出现在上面那条 `ssh` 命令里。

`backend/.env.example`（**已提交，仅占位符**）；真实值写进 `backend/.env`（**严禁提交**，用 `.env.example` 作模板）：

```env
DB_HOST=<云服务器IP>
DB_PORT=3307
DB_USER=<数据库用户名>
DB_PASSWORD=<数据库密码>
DB_NAME=smart_scheduler_dev
DATABASE_URL=mysql+asyncmy://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?charset=utf8mb4
```

**注意：不要在这里写 `DATABASE_URL`。** 连接串由 `app/core/config.py` 从上面五项拼出，分两条：

| 用途 | 属性 | 驱动 |
| --- | --- | --- |
| 应用运行时 | `database_url` | `mysql+asyncmy://`（主文档 3.4 固定异步驱动） |
| Alembic 迁移 | `sync_database_url` | `mysql+pymysql://`（仅 `alembic/env.py` 引用） |

多写一个 URL 配置项有两个问题：一是 `Settings` 是 `extra="forbid"`，多出来的键会让服务启动时直接 `ValidationError`；二是 `${VAR}` 这种写法 pydantic-settings 不做变量插值，即使键合法也拼不出预期值。

> 🔴 **`backend/.env` 必须被 `.gitignore` 忽略，`.env.example` 必须提交。**
> 提交前 `git status` 看不到 `.env` 才算安全。凭据一旦进入 git 历史，改密码也不足以清除。

> ⚠️ **2026-09-27 补记（这条红线此前是被破的）**：`backend/.env` 自首次提交
> `589c5ea` 起就在版本控制里，`DB_PASSWORD` 与 `JWT_SECRET_KEY` 均已推到 `origin`。
> 它先于 `backend/.gitignore` 的 `.env` 规则存在——**ignore 规则对已跟踪文件无效**，
> 所以 Rule 一直显示"安全"却实际没生效。已在 `2843b71` 执行 `git rm --cached`（不动历史）。
>
> 两点后果：
> 1. **新加入的成员 clone 后不再自带 `.env`**，需 `cp backend/.env.example backend/.env`
>    再按上面第 25~31 行问集成组要连接信息。已有的本地副本不受影响。
> 2. **凭据需轮换**（库密码 + `JWT_SECRET_KEY`）。不轮换的话，历史里那份仍然可用。
>    轮换由集成组决定并执行。
>
> **2026-09-28 补记（轮换与否的裁定）**：**负责人决定：不轮换**。风险现状照录——
> `git rm --cached` 只摘掉索引，**历史里那份凭据仍然可用**；且 `pre-commit` 的
> `no-secrets-file` 钩子当前**两道防线都不生效**（① `.git/hooks/` 下只有 `*.sample`，
> 钩子从未安装；② 其 `files` 正则 `^\.env(\.|$)|…` 的 `^` 锚定匹配不上
> `backend/.env`，实测 `backend/.env` 不匹配、`.env` 匹配）。因此：
> **`pre-commit` 修好之前，`backend/.env` 下次可能又被提交**——
> `.gitignore` 的 `.env` 规则只对**未跟踪**文件有效，一个 `git add -f`
> 或文件重回索引就绕过去了。修 `files` 正则归集成组（见
> `docs/spec/done/README.md` 的《2026-09-28 裁定通知》#4）。
>
> 教训：判断"安全"要看 `git ls-files` 而不是 `git check-ignore`——
> 后者对已跟踪文件**不报忽略**，两者结论相反时以 `git ls-files` 为准。

Navicat / DBeaver 仅作可视化查询用，连接信息从 `.env` 读取，**不写入任何文档**。

---

## 三、命名规范（主文档 6.2）

- 表名、字段名：`snake_case`，表名用**单数**（`sys_user`、`space_resource`、`reserve_order`）
- API 传输字段：`camelCase`（详见 `docs/api.md`）
- 枚举值一律用 `INT` + `COMMENT` 标注含义，不用 `ENUM` 类型

---

## 四、表结构（主文档 6.3）

> 9 张表。加粗字段为**核心调度 Agent 模块直接依赖**的字段。

### 4.1 `sys_user` 用户表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `username` | VARCHAR(64) | UNIQUE | 是 | 登录名 |
| `password` | VARCHAR(255) | | 是 | 密码哈希（bcrypt） |
| `role_id` | BIGINT UNSIGNED | FK → `sys_role.id` | 否 | 角色ID，单角色 |
| `avatar` | VARCHAR(512) | | 否 | 头像地址 |
| `status` | INT | | 是 | 1正常 0禁用 |
| `create_time` | DATETIME | | 是 | 创建时间 |
| `update_time` | DATETIME | | 是 | 更新时间 |

### 4.2 `sys_role` 角色表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `role_name` | VARCHAR(64) | | 是 | 角色名称 |
| `permissions` | JSON | | 否 | 权限集合，JSON 数组 |
| `create_time` | DATETIME | | 是 | 创建时间 |

### 4.3 `sys_permission` 权限表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `permission_name` | VARCHAR(64) | | 是 | 权限名称 |
| `permission_code` | VARCHAR(128) | UNIQUE | 是 | 权限编码，如 `user:add` |
| `parent_id` | BIGINT UNSIGNED | | 否 | 父权限ID，树形结构 |

### 4.4 `space_resource` 空间资源表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `space_name` | VARCHAR(128) | | 是 | 空间名称 |
| **`space_type`** | INT | | 是 | **1会议室 2展厅 3多功能厅 4户外场地** |
| **`capacity`** | INT | | 是 | 容纳人数 |
| `location` | VARCHAR(255) | | 否 | 位置 |
| **`budget`** | DECIMAL(10,2) | | 否 | 预算 |
| `open_start_time` | TIME | | 否 | 开放起始时间 |
| `open_end_time` | TIME | | 否 | 开放结束时间 |
| **`status`** | INT | | 是 | **1可用 0停用** |
| `create_time` | DATETIME | | 是 | 创建时间 |
| `update_time` | DATETIME | | 是 | 更新时间 |

**Agent 模块的检索维度是 `space_type` + `capacity` + `status`，这三个字段缺失会导致 `query_spaces` 工具直接失效。**

### 4.5 `device_resource` 设备资源表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `device_name` | VARCHAR(128) | | 是 | 设备名称 |
| **`device_type`** | VARCHAR(64) | | 否 | 设备类型 |
| **`device_status`** | INT | | 是 | **1完好 2损坏 3缺失配件** |
| `total_count` | INT | | 是 | 总数量 |
| **`available_count`** | INT | | 是 | 可用数量 |
| `create_time` | DATETIME | | 是 | 创建时间 |
| `update_time` | DATETIME | | 是 | 更新时间 |

**`query_devices` 必须同时过滤 `device_status = 1` 且 `available_count > 0`，两个条件缺一不可。**

### 4.6 `reserve_order` 预约订单表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `user_id` | BIGINT UNSIGNED | FK → `sys_user.id` | 是 | 预约人ID |
| `space_id` | BIGINT UNSIGNED | FK → `space_resource.id` | 是 | 空间ID |
| `device_ids` | JSON | | 否 | 设备ID列表 |
| `start_time` | DATETIME | | 是 | 开始时间 |
| `end_time` | DATETIME | | 是 | 结束时间 |
| **`order_status`** | INT | | 是 | **1待确认 2已确认 3已取消 4已完成** |
| `agent_request` | VARCHAR(1024) | | 否 | 用户原始需求 |
| `agent_trace` | JSON | | 否 | AI 思考过程追踪 |
| `create_time` | DATETIME | | 是 | 创建时间 |
| `update_time` | DATETIME | | 是 | 更新时间 |

**硬冲突判定只认 `order_status IN (1, 2)`**（待确认与已确认占位，已取消与已完成不占位）。

> ⚠️ **两套「有效订单」口径并存，用途不同，不要混用：**
>
> | 场景 | 口径 | 为什么 |
> | --- | --- | --- |
> | 硬冲突占位（并发预约检测，模块 3） | `IN (1, 2)` | 已完成与已取消都不再占用场地 |
> | 软冲突扫描（模块 7） | `IN (1, 2, 4)`，代码中即 `ACTIVE_ORDER_STATUSES`（`app/models/reservation.py`） | 扫描窗口是「前 7 天 ~ 后 7 天」，「已完成」的订单仍在窗口内，它同样构成「连续活动无休息」「单日累计占用超 8 小时」的事实依据；漏掉它会漏报。已取消（3）一律排除 |
>
> 模块 7 的口径见第九节，**与模块 3 对接时需确认双方一致认可**。

### 4.7 `inspect_record` 巡检记录表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `space_id` | BIGINT UNSIGNED | FK → `space_resource.id` | 否 | 巡检关联的空间ID |
| `image_url` | VARCHAR(512) | | 是 | 巡检图片地址 |
| `ai_result` | JSON | | 否 | AI 识别结果 |
| `inspector_id` | BIGINT UNSIGNED | FK → `sys_user.id` | 是 | 巡检人ID |
| `create_time` | DATETIME | | 是 | 创建时间 |

### 4.8 `repair_ticket` 维修工单表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `inspect_id` | BIGINT UNSIGNED | FK → `inspect_record.id` | 否 | 关联巡检记录ID |
| `device_id` | BIGINT UNSIGNED | FK → `device_resource.id` | 否 | 关联设备ID |
| `space_id` | BIGINT UNSIGNED | FK → `space_resource.id` | 否 | 关联空间ID |
| `ticket_status` | INT | | 是 | 1待处理 2处理中 3已完成 |
| `handler_id` | BIGINT UNSIGNED | FK → `sys_user.id` | 否 | 处理人ID |
| `create_time` | DATETIME | | 是 | 创建时间 |
| `update_time` | DATETIME | | 是 | 更新时间 |

### 4.9 `notify_message` 消息通知表

| 字段 | 类型 | 键 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | BIGINT UNSIGNED | PK | 是 | 主键，自增 |
| `receiver_id` | BIGINT UNSIGNED | FK → `sys_user.id` | 是 | 接收人ID |
| `notify_type` | INT | | 是 | 1预约提醒 2变更致歉 3故障告警 |
| `order_id` | BIGINT UNSIGNED | FK → `reserve_order.id` | 否 | 关联订单ID |
| `title` | VARCHAR(255) | | 否 | 通知标题 |
| `content` | TEXT | | 否 | 通知内容 |
| `is_read` | INT | | 是 | 0未读 1已读 |
| `create_time` | DATETIME | | 是 | 创建时间 |

---

## 五、索引（主文档 6.6）

| 表 | 索引名 | 字段 | 类型 | 用途 |
| --- | --- | --- | --- | --- |
| `sys_user` | `uk_username` | `username` | UNIQUE | 登录查询 |
| `space_resource` | `idx_space_type` | `space_type` | NORMAL | **Agent 按类型检索** |
| `space_resource` | `idx_capacity` | `capacity` | NORMAL | **Agent 按容量检索** |
| `device_resource` | `idx_device_type` | `device_type` | NORMAL | **Agent 按类型检索** |
| `reserve_order` | `idx_user_id` | `user_id` | NORMAL | 用户订单查询 |
| `reserve_order` | `idx_space_time` | `space_id, start_time, end_time` | COMPOSITE | **并发预约冲突检测** |
| `reserve_order` | `idx_status` | `order_status` | NORMAL | 状态筛选 |
| `inspect_record` | `idx_space_id` | `space_id` | NORMAL | 空间巡检查询 |
| `repair_ticket` | `idx_device_id` | `device_id` | NORMAL | 设备工单查询 |
| `repair_ticket` | `idx_ticket_status` | `ticket_status` | NORMAL | 工单状态筛选 |
| `notify_message` | `idx_receiver_read` | `receiver_id, is_read` | COMPOSITE | 未读消息查询 |

> **`idx_space_time` 是并发预约能否守住的关键。** 没有这个联合索引，`SELECT ... FOR UPDATE` 在冲突检测时会退化为全表扫描并放大锁范围（主文档 5.5），低并发下测不出问题，演示当天会翻车。

> 🔴 **上表是规范，不等于库里已有。** 见 6.2 —— `backend/alembic/` 的初始迁移脚本**一条索引都没建**，在建表路径上与本表不一致。

---

## 六、表结构变更 DDL 清单（主文档 6.7）

> ⚠️ **以下 `ALTER TABLE` 由基础支撑与集成组统一执行，任何人不得自行在库上执行。**
> 执行前需知会业务中台组（涉及 `inspect_record`、`repair_ticket`）。
>
> **⚠️ 2026-09-27 更正**：本节此前声称整份 DDL 与索引均已执行完毕、仅作留档与变更溯源，
> 该表述与库上实测矛盾，**已删除**。
> §6.7 的 9 条 `CREATE INDEX` 中，**7 条尚未执行，2 条由 MySQL 外键自动覆盖**。
> 详见下方实测对照表。
>
> 表结构变更按主文档 §6.5 归集成组执行。**本模块不得自建索引、不得改表结构**——
> 下表只作状态记录，不含任何处置动作。

### 索引实测对照表（2026-09-27）

口径：以 `docs/database.md` §5 的 11 条规范索引为准，逐条比对 `smart_scheduler_dev`
的 `information_schema.STATISTICS`（只读查询，未做任何变更）。

| # | 规范索引（§5） | 表 | 规范字段 | 库上实测 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | `uk_username` | `sys_user` | `username` UNIQUE | `username` 存在，UNIQUE | ⚠️ 功能等价，索引名不符 |
| 2 | `idx_space_type` | `space_resource` | `space_type` | — | ⛔ **缺失** |
| 3 | `idx_capacity` | `space_resource` | `capacity` | — | ⛔ **缺失** |
| 4 | `idx_device_type` | `device_resource` | `device_type` | — | ⛔ **缺失** |
| 5 | `idx_user_id` | `reserve_order` | `user_id` | `user_id` 存在（外键自动生成） | ⚠️ 功能等价，索引名不符 |
| 6 | `idx_space_time` | `reserve_order` | `space_id, start_time, end_time` | 仅有 `space_id` 单列（外键自动生成） | ⛔ **缺失（关键）** |
| 7 | `idx_status` | `reserve_order` | `order_status` | — | ⛔ **缺失** |
| 8 | `idx_space_id` | `inspect_record` | `space_id` | `space_id` 存在（外键自动生成） | ⚠️ 功能等价，索引名不符 |
| 9 | `idx_device_id` | `repair_ticket` | `device_id` | `device_id` 存在（外键自动生成） | ⚠️ 功能等价，索引名不符 |
| 10 | `idx_ticket_status` | `repair_ticket` | `ticket_status` | — | ⛔ **缺失** |
| 11 | `idx_receiver_read` | `notify_message` | `receiver_id, is_read` | 仅有 `receiver_id` 单列（外键自动生成） | ⛔ **缺失** |

**结论**：11 条规范索引中，**7 条缺失**、4 条由外键自动索引在功能上覆盖（索引名与规范不符）。

§5 的 11 条比 §6.7 的 9 条多出第 1、5 行（`uk_username`、`idx_user_id`）——
这两条不在 `CREATE INDEX` 清单内，库上都已在功能上存在。
§6.7 的 9 条 `CREATE INDEX` 对应本表第 2、3、4、6、7、8、9、10、11 行，
其中 **7 条未执行**（第 2、3、4、6、7、10、11 行），2 条（第 8、9 行）外键已覆盖。

**第 6 行 `idx_space_time` 缺失是本表的重点**：没有这个联合索引，
`SELECT ... FOR UPDATE` 在冲突检测时会退化为全表扫描并放大锁范围（主文档 5.5），
低并发下测不出问题，演示当天会翻车。§6.1 的自检 SQL 至今应报**空结果**。

```sql
-- 1. space_resource 新增字段
ALTER TABLE space_resource
  ADD COLUMN space_type INT NOT NULL DEFAULT 1 COMMENT '1会议室 2展厅 3多功能厅 4户外场地' AFTER space_name,
  ADD COLUMN status INT NOT NULL DEFAULT 1 COMMENT '1可用 0停用' AFTER open_end_time;

-- 2. space_resource 开放时段拆分
ALTER TABLE space_resource
  ADD COLUMN open_start_time TIME NULL AFTER budget,
  ADD COLUMN open_end_time TIME NULL AFTER open_start_time;

UPDATE space_resource
SET open_start_time = '08:00:00', open_end_time = '22:00:00'
WHERE open_time IS NOT NULL;

ALTER TABLE space_resource DROP COLUMN open_time;

-- 3. device_resource 新增数量字段
ALTER TABLE device_resource
  ADD COLUMN total_count INT NOT NULL DEFAULT 1 AFTER device_status,
  ADD COLUMN available_count INT NOT NULL DEFAULT 1 AFTER total_count;

-- 4. inspect_record 新增 space_id
ALTER TABLE inspect_record
  ADD COLUMN space_id BIGINT UNSIGNED NULL AFTER id,
  ADD CONSTRAINT fk_inspect_space FOREIGN KEY (space_id) REFERENCES space_resource(id);

-- 5. repair_ticket 新增设备/空间关联
ALTER TABLE repair_ticket
  ADD COLUMN device_id BIGINT UNSIGNED NULL AFTER inspect_id,
  ADD COLUMN space_id BIGINT UNSIGNED NULL AFTER device_id,
  ADD CONSTRAINT fk_ticket_device FOREIGN KEY (device_id) REFERENCES device_resource(id),
  ADD CONSTRAINT fk_ticket_space FOREIGN KEY (space_id) REFERENCES space_resource(id);

-- 6. notify_message 新增通知类型与关联订单
ALTER TABLE notify_message
  ADD COLUMN notify_type INT NOT NULL DEFAULT 1 COMMENT '1预约提醒 2变更致歉 3故障告警' AFTER receiver_id,
  ADD COLUMN order_id BIGINT UNSIGNED NULL AFTER notify_type,
  ADD CONSTRAINT fk_notify_order FOREIGN KEY (order_id) REFERENCES reserve_order(id);

-- 7. 索引创建
CREATE INDEX idx_space_type ON space_resource(space_type);
CREATE INDEX idx_capacity ON space_resource(capacity);
CREATE INDEX idx_device_type ON device_resource(device_type);
CREATE INDEX idx_space_time ON reserve_order(space_id, start_time, end_time);
CREATE INDEX idx_status ON reserve_order(order_status);
CREATE INDEX idx_space_id ON inspect_record(space_id);
CREATE INDEX idx_device_id ON repair_ticket(device_id);
CREATE INDEX idx_ticket_status ON repair_ticket(ticket_status);
CREATE INDEX idx_receiver_read ON notify_message(receiver_id, is_read);
```

### 6.1 执行后自检

```sql
-- 表结构核对：space_resource 应有 11 个字段，device_resource 应有 8 个
SHOW COLUMNS FROM space_resource;
SHOW COLUMNS FROM device_resource;

-- 索引核对：应列出上面 11 条索引
SHOW INDEX FROM reserve_order;

-- 关键索引必须存在
SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'smart_scheduler_dev'
  AND TABLE_NAME = 'reserve_order'
  AND INDEX_NAME = 'idx_space_time'
ORDER BY SEQ_IN_INDEX;
```

`idx_space_time` 的 `SEQ_IN_INDEX` 必须依次为 `space_id=1`、`start_time=2`、`end_time=3`。**顺序错了索引基本失效。**

### 6.2 与 `backend/alembic/` 迁移脚本的关系（**待集成组定夺**）

仓库里目前存在**两条互不相同的建表路径**：

| 路径 | 内容 | 是否含第五节索引 |
| --- | --- | --- |
| 本节 SQL（`ALTER` + `CREATE INDEX`） | 6.7 清单，逐条变更 | ✅ 全部 11 条 |
| `backend/alembic/versions/8969262c9d0c_init_tables_single_role.py` | 直接 `create_table` 建 9 张表 | ❌ **一条 `op.create_index` 都没有** |

也就是说：**只跑 Alembic 得到的是「有表无索引」的库**，与本文件第五节、以及主文档 6.6 都不一致。后果不是「慢一点」，而是 `idx_space_time` 缺失会让模块 3 的并发预约检测退化为全表扫描并放大锁范围（主文档 5.5）。

此外，Alembic 脚本是**全新 `create_table`**，不包含本节 1~6 条的 `ALTER` 语义，因此它假定的是「空库可直接建全量结构」，与「已有库需增量变更」是两种前提。

**结论：两条路径只能留一条作为权威。** 建议由集成组明确：

1. 以本节 SQL 为准，Alembic 仅作留档；或
2. 以 Alembic 为准，则**必须补齐索引**（`op.create_index` × 11），并把本节 1~6 条的历史变更语义并入迁移链

> 索引缺失已单独登记为待办（见 `docs/test.md` 与本轮合并说明），**不由模块 7 擅自补迁移脚本** —— 建表与索引归集成组，模块 7 全程零 DDL 变更。

---

## 七、测试库（主文档 6.8）

云库中另建 `smart_scheduler_test`，结构与 `smart_scheduler_dev` 一致。测试用例连测试库，**禁止污染正式库**。

集成组若无建库权限，退回备选方案：在 `smart_scheduler_dev` 中给测试用表加前缀 `test_`，测试结束 `TRUNCATE` 清理。

> 🔴 **禁止测试直接写 `reserve_order` 正式表。**

---

## 八、种子数据（主文档 6.9）

脚本：`docs/seed.sql`

| 对象 | 数量 | 明细 |
| --- | --- | --- |
| 用户 `sys_user` | 3 | 普通用户、管理员、系统管理员 |
| 角色 `sys_role` | 3 | 与上表一一对应（种子脚本附带，便于 FK 成立） |
| 场地 `space_resource` | 8 | 会议室 ×3、展厅 ×2、多功能厅 ×2、户外 ×1 |
| 设备 `device_resource` | 15 | 投影仪 ×4、音响 ×4、显示屏 ×3、无人机 ×2、直播设备 ×2 |
| 历史预约 `reserve_order` | 10 | 覆盖 4 种订单状态、不同时段 |

### 8.1 数据设计约束（**写测试前必读**）

种子数据不是随手编的，它被五个评审场景的断言**反向约束**。下表是设计意图，改数据前先看懂它：

| 约束 | 具体值 | 服务于 |
| --- | --- | --- |
| **会议室最大容量必须 < 40** | 会议室容量 12 / 20 / 30 | 场景 B（拆分）：40 人的会议室需求**无单场地可满足**，才会触发"拆成两个会议室"（12+30=42 ≥ 40） |
| **存在容量 ≥40 且预算 >500 的场地** | 展厅 `A栋3楼展厅` 容量 50、预算 800 | 场景 A（预算降级）：800 元预算下场地保得住，**降级的是设备** |
| **不存在"容量 ≥40 且预算 ≤500"的场地** | 容量 ≥40 的场地预算分别为 800 / 1500 / 1000 | 场景 D（需求矛盾）："40 人 + 500 元"必须**真的无解**，否则场景失效 |
| **投影仪共 4 台且全部为完好状态** | `device_status=1`、`available_count=1` | 场景 C（设备替代）：当 4 台都被预约占用时，**只能靠替代品**（LED显示屏）解决，不能靠"还有空闲的投影仪"蒙混过关 |
| **存在「只坏一个条件」的设备各 1 台** | 无人机02（`device_status=2`，但 `available_count=1`）、直播设备02（`device_status=1`，但 `available_count=0`） | 用例 AGENT-U-02：两个见证者必须**互相独立**，否则漏写任一过滤条件的查询会"碰巧"把它们都排除掉，用例抓不到 bug |
| **存在同团队连续两场的历史预约** | 用户 1 在同一日下午连开两场 | 场景 E（活动合并） |
| **投影仪占用集中在演示基准日** | 4 条覆盖全部投影仪的预约，落在 `2026-10-15` | 场景 C 可复现 |

> **演示基准日：`2026-10-15`（周四）。** 针对场景 A/B/C/D/E 的测试用例，请求时间窗应落在该日或其前后 1 日内，否则命不中预设的占用状态。**这个日期是种子数据的一部分，改种子数据必须同步改它。**

### 8.2 演示账号

三个用户的口令统一为演示口令 `Demo@123`，库中存 bcrypt 哈希。

> 🔴 **这是开发库的演示口令，不是任何真实环境的凭据。禁止复用到生产、禁止写入除 `seed.sql` 以外的任何文件。**

### 8.3 导入与自检

```bash
# 导入（凭据从本地 .env 取，不要写进命令行历史）
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p smart_scheduler_dev < docs/seed.sql
```

```sql
-- 自检：条数应为 3 / 3 / 8 / 15 / 10
SELECT 'sys_user' t, COUNT(*) n FROM sys_user
UNION ALL SELECT 'sys_role', COUNT(*) FROM sys_role
UNION ALL SELECT 'space_resource', COUNT(*) FROM space_resource
UNION ALL SELECT 'device_resource', COUNT(*) FROM device_resource
UNION ALL SELECT 'reserve_order', COUNT(*) FROM reserve_order;

-- 自检：场地类型分布应为 3 / 2 / 2 / 1
SELECT space_type, COUNT(*) FROM space_resource GROUP BY space_type ORDER BY space_type;

-- 自检：设备类型分布应为 4 / 4 / 3 / 2 / 2
SELECT device_type, COUNT(*) FROM device_resource GROUP BY device_type;

-- 自检：容量 ≥40 且预算 ≤500 的场地必须为 0 行（场景 D 的前提）
SELECT COUNT(*) FROM space_resource WHERE capacity >= 40 AND budget <= 500;
```

最后一条查询**必须返回 0**。若返回非 0，场景 D（需求矛盾）不再成立，对应用例会假失败。

---

## 九、模块 7：AI 冲突预警与智能通知

### 9.1 ⚠️ 本模块无 DDL 变更

**结论：本模块不新增任何表、字段、索引或约束，不需要集成组执行任何 `ALTER TABLE`。**

主文档 6.7 的「表结构变更 DDL 清单」中与本模块相关的部分（**第 6 条**：`notify_message` 增加 `notify_type`、`order_id` 及外键，**第 7 条**：创建 `idx_receiver_read`）**已包含在集成组的既有清单内（见本文第六节），本模块不需要追加任何条目**。

请集成组按原清单执行即可，**不必等待本模块的迁移脚本** —— 本模块没有迁移脚本。

### 9.2 本模块使用的表

#### 1. `notify_message`（主表，只写）

本模块是本表的主要写入方（AI 冲突预警与智能通知）。

| 字段名 | 类型 | 本模块用法 |
| :--- | :--- | :--- |
| `id` | BIGINT UNSIGNED | 自增主键，不做业务使用 |
| `receiver_id` | BIGINT UNSIGNED | 收件人。由后端按订单与角色解析得出，**绝不取自请求体或事件载荷** |
| `notify_type` | INT | 1 预约提醒（软冲突扫描）／2 变更致歉（取消、改期）／3 故障告警（设备故障事件） |
| `order_id` | BIGINT UNSIGNED | 关联订单。设备故障等无订单上下文的事件写 `NULL` |
| `title` | VARCHAR(255) | 写入前统一截断至 200 字符（留足安全边界） |
| `content` | TEXT | 写入前统一截断至 2000 字符 |
| `is_read` | INT | 新建通知一律写 `0`（未读） |
| `create_time` | DATETIME | 由数据库 `DEFAULT CURRENT_TIMESTAMP` 生成，不显式赋值 |

**写入规范**：一条通知只写一行，同一批次的多条记录在一个事务内提交（`generate_and_dispatch` 内逐条 `flush`，由调用方 `commit`）。

#### 2. `reserve_order`（只读）

软冲突判定的数据来源。本模块**全程只读**，不修改任何预约状态 —— 预约的创建 / 变更 / 取消由预约管理模块的事务与唯一索引负责，本模块只负责发现冲突并生成通知文案（主文档 4.4）。

**有效订单口径 = `order_status IN (1, 2, 4)`**，即排除 `3 已取消`，但**保留 `4 已完成`**。代码中该口径定义为 `ACTIVE_ORDER_STATUSES`（`app/models/reservation.py`），服务层引用常量而非裸数字，避免「两个模块各自写一套状态码」。理由：本模块的扫描窗口是「前 7 天 ~ 后 7 天」，窗口内的「已完成」订单同样是「连续活动无休息」「单日累计占用超 8 小时」的事实依据，排除它会漏报。这与 4.6 节硬冲突占位的 `IN (1, 2)` 口径**不同且各自成立**，详见 4.6 节的对照表。

读取方式：按扫描窗口一次性批量读取，配合 `ORDER BY start_time LIMIT 2000` 保护 2 核 2G 服务器的内存；不使用任何 ORM 惰性加载（异步会话下会抛 `MissingGreenlet`，故模型上的 `relationship()` 一律 `lazy="raise"`，让错误在调用点直接暴露）。

#### 3. `space_resource` / `device_resource` / `sys_user` / `sys_role`（只读）

用于补全文案所需的场地名、容量、设备名与设备类型、预约人姓名与角色名。均为种子数据量级（个位数到十几行），全量读取后在内存中做映射，不做 N+1 查询。

### 9.3 本模块使用的索引

| 表 | 索引 | 用途 |
| :--- | :--- | :--- |
| `notify_message` | `idx_receiver_read` (receiver_id, is_read) | 消息列表与未读数查询 |
| `reserve_order` | `idx_status` (order_status) | 扫描时过滤有效订单（排除已取消） |
| `reserve_order` | `idx_space_time` (space_id, start_time, end_time) | 扫描窗口内的订单范围查询 |

三条均为第五节既有索引，本模块**未新增任何索引**。

> ⚠️ **但「规范列了」不等于「库里有」。** 见 6.2：`backend/alembic/` 的初始迁移脚本没有创建任何索引。其中 `idx_space_time` 的缺失会实打实影响本模块的扫描窗口查询性能，也会影响模块 3 的并发预约正确性。**该项已单独登记待办。**

### 9.4 去重状态为什么不入库

同一冲突需要「24 小时内只提醒一次」，但 `notify_message` 没有去重列，且按 6.7 的流程新增列需由集成组统一执行。

本模块的取法：**去重状态放 Redis，不入库。**

- 主：Redis `SET <指纹> 1 NX EX <TTL>`，原子占位（`CONFLICT_DEDUP_BACKEND=redis` 或默认 `auto`）
- 兜底：Redis 不可用时降级为按 `(receiver_id, title, create_time)` 查库近似判重（`=db`），本地无 Redis 环境再退化为进程内实现（`=memory`）

指纹 = `sha1(source | rule_code | notify_type | order_ids | space_id | receiver_id)`。其中 `title` 取**模板**渲染出的标题而非 AI 标题 —— 模板标题是确定性的、可在调用大模型前算出，而 AI 标题每次都可能不同，无法用于判重。

Redis 键前缀 `conflict:notify:`，TTL 由 `CONFLICT_DEDUP_TTL_SECONDS` 配置（默认 86400 秒）。

### 9.5 验证方式

```sql
-- 确认本模块只写 notify_message，且未产生任何表结构变更
SHOW CREATE TABLE notify_message;
SHOW INDEX FROM notify_message;

-- 验证一轮扫描后确实落库（第二轮不应重复写入）
SELECT id, receiver_id, notify_type, order_id, LEFT(title, 40), is_read, create_time
FROM notify_message
ORDER BY id DESC
LIMIT 20;
```

### 9.6 本模块相关的配置项

均为应用层配置，**不涉及数据库结构**：

| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `CONFLICT_SCAN_ENABLED` | `true` | 是否启用后台周期扫描 |
| `CONFLICT_SCAN_INTERVAL_SECONDS` | `300` | 扫描间隔 |
| `CONFLICT_SCAN_INITIAL_DELAY_SECONDS` | `20` | 启动后首次扫描延迟 |
| `CONFLICT_PAST_WINDOW_DAYS` / `CONFLICT_FUTURE_WINDOW_DAYS` | `7` / `7` | 扫描窗口 |
| `CONFLICT_MAX_ORDERS_IN_SNAPSHOT` | `2000` | 单轮快照订单上限（内存保护） |
| `CONFLICT_DEDUP_BACKEND` | `auto` | 去重后端：`auto` / `redis` / `db` / `memory` |
| `CONFLICT_DEDUP_TTL_SECONDS` | `86400` | 同一冲突的去重窗口（秒） |

阈值类配置（连续活动间隔、容量倍数、高价值设备白名单、单日占用小时数、闲置天数）见 `.env.example`。

---

## 十、变更记录

| 日期 | 变更 | 执行人 | 是否已同步主文档 |
| --- | --- | --- | --- |
| 2026-09-24 | 本文件建立，转录主文档 6.3 / 6.6 / 6.7；新增 `docs/seed.sql` | 徐川（代集成组整理） | 待集成组确认 |
| 2026-09-27 | 修正第二节 `DB_PORT` 口径为隧道入口 `3308`（原写 `3307`）并补充 `3307`/`3308` 差异说明；示例中的 `DB_HOST` 由 `<云服务器IP>` 同步为 `127.0.0.1`，与 `.env.example` 保持一致 | 黄嵩（模块 7） | 待集成组确认 |

> 本文件由核心调度 Agent 模块负责人依主文档 6.5 要求整理成稿。**表结构与 DDL 的最终解释权在基础支撑与集成组**，如与主文档冲突，以主文档为准并立即修正本文。

---

## 十、模块 3 补充说明（2026-09-28 合并时并入）

> 本节由模块 3 版本的 `docs/database.md` 在合并时并入，**只保留合并后仍然成立**的内容。
> 该版本另有两节与当前代码矛盾，未予收录，原因见 §10.4。

### 10.1 连接串由五项拼接

`DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` 五项由 `config.database_url`
自动拼成：

    mysql+asyncmy://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?charset=utf8mb4

另有 `DATABASE_URL` 作为**显式覆盖口**（默认空串，非空时直接返回它，见
`app/core/config.py`）；非 `dev` 环境下它非空会拒绝启动。

### 10.2 自建库脚本

云库中的表已按 §6.5 创建完成。**自建库**时的完整脚本见 `backend/init_db.sql`
（其中仍带 7 条 `INDEX` 声明，只在自建库时生效；云库的索引落实情况见 §6 的实测对照表）。

### 10.3 四个外键都是真外键（及对测试夹具的连带影响）

`reserve_order` 的 `space_id`、`user_id` 与 `notify_message` 的 `order_id`、`receiver_id`
**均为真外键**。云库 `information_schema.STATISTICS` 显示这四列上都有外键自动生成的索引，
证实约束确实存在。

> **连带影响**：写 `reserve_order` / `notify_message` 之前**必须先有对应的 `sys_user` 行**，
> 否则云库以 1452 拒绝写入。测试夹具因此新增 `_seed_users()`
> （`backend/tests/module3/conftest.py`）。

### 10.4 未收录的两节及原因

模块 3 版还有两节，合并后**已与代码不符**，故不收录：

1. **「主键类型 `PK_TYPE`」**：该节称主键用
   `BigInteger().with_variant(Integer, "sqlite")`。而 `app/core/database.py` 的模块
   docstring 已明写「模型一律用裸 `BigInteger`，本模块**不再提供** `PK_TYPE`」——
   SQLite 下的主键自增改由测试进程内的 `SQLiteTypeCompiler` 垫片解决，两法等价。
2. **「模型不声明任何索引」**：该节称模型不声明索引。合并后的 `backend/app/models/`
   实际声明了 11 处 `Index(...)`（`idx_space_type`、`idx_capacity`、`idx_space_time`、
   `idx_status`、`idx_receiver_id` 等，见 `resource.py` / `reservation.py` /
   `notification.py` / `inspection.py`），与 §5 的规范索引一致。

---

## 十一、与 backend/alembic 迁移脚本的关系（模块 7 版原 §6.2，并入）


仓库里目前存在**两条互不相同的建表路径**：

| 路径 | 内容 | 是否含第五节索引 |
| --- | --- | --- |
| 本节 SQL（`ALTER` + `CREATE INDEX`） | 6.7 清单，逐条变更 | ✅ 全部 11 条 |
| `backend/alembic/versions/8969262c9d0c_init_tables_single_role.py` | 直接 `create_table` 建 9 张表 | ❌ **一条 `op.create_index` 都没有** |

也就是说：**只跑 Alembic 得到的是「有表无索引」的库**，与本文件第五节、以及主文档 6.6 都不一致。后果不是「慢一点」，而是 `idx_space_time` 缺失会让模块 3 的并发预约检测退化为全表扫描并放大锁范围（主文档 5.5）。

此外，Alembic 脚本是**全新 `create_table`**，不包含本节 1~6 条的 `ALTER` 语义，因此它假定的是「空库可直接建全量结构」，与「已有库需增量变更」是两种前提。

**结论：两条路径只能留一条作为权威。** 建议由集成组明确：

1. 以本节 SQL 为准，Alembic 仅作留档；或
2. 以 Alembic 为准，则**必须补齐索引**（`op.create_index` × 11），并把本节 1~6 条的历史变更语义并入迁移链

> 索引缺失已单独登记为待办（见 `docs/test.md` 与本轮合并说明），**不由模块 7 擅自补迁移脚本** —— 建表与索引归集成组，模块 7 全程零 DDL 变更。

---


---

## 十二、模块 7：AI 冲突预警与智能通知（并入）


### 9.1 ⚠️ 本模块无 DDL 变更

**结论：本模块不新增任何表、字段、索引或约束，不需要集成组执行任何 `ALTER TABLE`。**

主文档 6.7 的「表结构变更 DDL 清单」中与本模块相关的部分（**第 6 条**：`notify_message` 增加 `notify_type`、`order_id` 及外键，**第 7 条**：创建 `idx_receiver_read`）**已包含在集成组的既有清单内（见本文第六节），本模块不需要追加任何条目**。

请集成组按原清单执行即可，**不必等待本模块的迁移脚本** —— 本模块没有迁移脚本。

### 9.2 本模块使用的表

#### 1. `notify_message`（主表，只写）

本模块是本表的主要写入方（AI 冲突预警与智能通知）。

| 字段名 | 类型 | 本模块用法 |
| :--- | :--- | :--- |
| `id` | BIGINT UNSIGNED | 自增主键，不做业务使用 |
| `receiver_id` | BIGINT UNSIGNED | 收件人。由后端按订单与角色解析得出，**绝不取自请求体或事件载荷** |
| `notify_type` | INT | 1 预约提醒（软冲突扫描）／2 变更致歉（取消、改期）／3 故障告警（设备故障事件） |
| `order_id` | BIGINT UNSIGNED | 关联订单。设备故障等无订单上下文的事件写 `NULL` |
| `title` | VARCHAR(255) | 写入前统一截断至 200 字符（留足安全边界） |
| `content` | TEXT | 写入前统一截断至 2000 字符 |
| `is_read` | INT | 新建通知一律写 `0`（未读） |
| `create_time` | DATETIME | 由数据库 `DEFAULT CURRENT_TIMESTAMP` 生成，不显式赋值 |

**写入规范**：一条通知只写一行，同一批次的多条记录在一个事务内提交（`generate_and_dispatch` 内逐条 `flush`，由调用方 `commit`）。

#### 2. `reserve_order`（只读）

软冲突判定的数据来源。本模块**全程只读**，不修改任何预约状态 —— 预约的创建 / 变更 / 取消由预约管理模块的事务与唯一索引负责，本模块只负责发现冲突并生成通知文案（主文档 4.4）。

**有效订单口径 = `order_status IN (1, 2, 4)`**，即排除 `3 已取消`，但**保留 `4 已完成`**。代码中该口径定义为 `ACTIVE_ORDER_STATUSES`（`app/models/reservation.py`），服务层引用常量而非裸数字，避免「两个模块各自写一套状态码」。理由：本模块的扫描窗口是「前 7 天 ~ 后 7 天」，窗口内的「已完成」订单同样是「连续活动无休息」「单日累计占用超 8 小时」的事实依据，排除它会漏报。这与 4.6 节硬冲突占位的 `IN (1, 2)` 口径**不同且各自成立**，详见 4.6 节的对照表。

读取方式：按扫描窗口一次性批量读取，配合 `ORDER BY start_time LIMIT 2000` 保护 2 核 2G 服务器的内存；不使用任何 ORM 惰性加载（异步会话下会抛 `MissingGreenlet`，故模型上的 `relationship()` 一律 `lazy="raise"`，让错误在调用点直接暴露）。

#### 3. `space_resource` / `device_resource` / `sys_user` / `sys_role`（只读）

用于补全文案所需的场地名、容量、设备名与设备类型、预约人姓名与角色名。均为种子数据量级（个位数到十几行），全量读取后在内存中做映射，不做 N+1 查询。

### 9.3 本模块使用的索引

| 表 | 索引 | 用途 |
| :--- | :--- | :--- |
| `notify_message` | `idx_receiver_read` (receiver_id, is_read) | 消息列表与未读数查询 |
| `reserve_order` | `idx_status` (order_status) | 扫描时过滤有效订单（排除已取消） |
| `reserve_order` | `idx_space_time` (space_id, start_time, end_time) | 扫描窗口内的订单范围查询 |

三条均为第五节既有索引，本模块**未新增任何索引**。

> ⚠️ **但「规范列了」不等于「库里有」。** 见 6.2：`backend/alembic/` 的初始迁移脚本没有创建任何索引。其中 `idx_space_time` 的缺失会实打实影响本模块的扫描窗口查询性能，也会影响模块 3 的并发预约正确性。**该项已单独登记待办。**

### 9.4 去重状态为什么不入库

同一冲突需要「24 小时内只提醒一次」，但 `notify_message` 没有去重列，且按 6.7 的流程新增列需由集成组统一执行。

本模块的取法：**去重状态放 Redis，不入库。**

- 主：Redis `SET <指纹> 1 NX EX <TTL>`，原子占位（`CONFLICT_DEDUP_BACKEND=redis` 或默认 `auto`）
- 兜底：Redis 不可用时降级为按 `(receiver_id, title, create_time)` 查库近似判重（`=db`），本地无 Redis 环境再退化为进程内实现（`=memory`）

指纹 = `sha1(source | rule_code | notify_type | order_ids | space_id | receiver_id)`。其中 `title` 取**模板**渲染出的标题而非 AI 标题 —— 模板标题是确定性的、可在调用大模型前算出，而 AI 标题每次都可能不同，无法用于判重。

Redis 键前缀 `conflict:notify:`，TTL 由 `CONFLICT_DEDUP_TTL_SECONDS` 配置（默认 86400 秒）。

### 9.5 验证方式

```sql
-- 确认本模块只写 notify_message，且未产生任何表结构变更
SHOW CREATE TABLE notify_message;
SHOW INDEX FROM notify_message;

-- 验证一轮扫描后确实落库（第二轮不应重复写入）
SELECT id, receiver_id, notify_type, order_id, LEFT(title, 40), is_read, create_time
FROM notify_message
ORDER BY id DESC
LIMIT 20;
```

### 9.6 本模块相关的配置项

均为应用层配置，**不涉及数据库结构**：

| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `CONFLICT_SCAN_ENABLED` | `true` | 是否启用后台周期扫描 |
| `CONFLICT_SCAN_INTERVAL_SECONDS` | `300` | 扫描间隔 |
| `CONFLICT_SCAN_INITIAL_DELAY_SECONDS` | `20` | 启动后首次扫描延迟 |
| `CONFLICT_PAST_WINDOW_DAYS` / `CONFLICT_FUTURE_WINDOW_DAYS` | `7` / `7` | 扫描窗口 |
| `CONFLICT_MAX_ORDERS_IN_SNAPSHOT` | `2000` | 单轮快照订单上限（内存保护） |
| `CONFLICT_DEDUP_BACKEND` | `auto` | 去重后端：`auto` / `redis` / `db` / `memory` |
| `CONFLICT_DEDUP_TTL_SECONDS` | `86400` | 同一冲突的去重窗口（秒） |

阈值类配置（连续活动间隔、容量倍数、高价值设备白名单、单日占用小时数、闲置天数）见 `.env.example`。

---

## 十、变更记录
