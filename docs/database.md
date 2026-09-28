# 数据库文档

> 依据《项目文档.md》6.1~6.9。**本文件是表结构与 DDL 的唯一权威副本**（主文档 6.5 指定）。
> 表结构与索引的任何变更，必须**先由基础支撑与集成组执行**，再同步更新本文件。

---

## 一、边界说明

| 事项 | 归属 | 说明 |
| --- | --- | --- |
| 建表 / 改表 / 建索引 | **集成组** | 主文档 6.5、6.7。**任何人不得到生产库自行执行 DDL** |
| `docs/seed.sql` 的导入 | **集成组** | 导入前确认目标库为 `smart_scheduler_dev`，禁止误入正式环境 |
| 连接凭据 | **各人本地 `.env`** | 见第三节。**凭据不入本文件、不入代码、不入提交** |
| 本文件的表结构描述 | 集成组维护 | 本文与主文档 6.3 不一致时，以主文档为准并立即修正本文 |

---

## 二、库与连接规范（主文档 6.1）

所有开发人员连接云服务器上的**统一 MySQL 库**，禁止使用本地库。

| 配置项 | 值 |
| --- | --- |
| 云服务器地址 | 见 `.env` 的 `DB_HOST` |
| 端口 | 见 `.env` 的 `DB_PORT`（默认 `3307`） |
| 业务库 | `smart_scheduler_dev` |
| 测试库 | `smart_scheduler_test` |
| 用户名 / 密码 | 见 `.env` 的 `DB_USER` / `DB_PASSWORD` |
| 字符集 | `utf8mb4` |
| 驱动 | `asyncmy`（异步） |

`backend/.env.example`（**已提交，仅占位符**）：

```env
DB_HOST=<云服务器IP>
DB_PORT=3307
DB_USER=<数据库用户名>
DB_PASSWORD=<数据库密码>
DB_NAME=smart_scheduler_dev
DATABASE_URL=mysql+asyncmy://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?charset=utf8mb4
```

> 🔴 **`backend/.env` 必须被 `.gitignore` 忽略，`.env.example` 必须提交。**
> 提交前 `git status` 看不到 `.env` 才算安全。凭据一旦进入 git 历史，改密码也不足以清除。

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

**冲突判定只认 `order_status IN (1, 2)`**（待确认与已确认占位，已取消与已完成不占位）。

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

---

## 六、表结构变更 DDL 清单（主文档 6.7）

> ⚠️ **以下 `ALTER TABLE` 由基础支撑与集成组统一执行，任何人不得自行在库上执行。**
> 执行前需知会业务中台组（涉及 `inspect_record`、`repair_ticket`）。
> 已全部执行完毕，此处仅作留档与变更溯源。

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

## 九、变更记录

| 日期 | 变更 | 执行人 | 是否已同步主文档 |
| --- | --- | --- | --- |
| 2026-09-24 | 本文件建立，转录主文档 6.3 / 6.6 / 6.7；新增 `docs/seed.sql` | 徐川（代集成组整理） | 待集成组确认 |

> 本文件由核心调度 Agent 模块负责人依主文档 6.5 要求整理成稿。**表结构与 DDL 的最终解释权在基础支撑与集成组**，如与主文档冲突，以主文档为准并立即修正本文。
