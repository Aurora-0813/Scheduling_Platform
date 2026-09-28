# 数据库设计文档 —— 移动端预约与通知模块

> 统一连接云服务器 MySQL（开发流程 §6.1）。本模块只涉及 4 张表，其余表由队友模块负责。
> 驱动统一使用异步驱动 asyncmy（§3.4），连接串固定 `mysql+asyncmy://`。

## 云数据库连接配置

连接信息一律从 `backend/.env` 读取，禁止写入代码或文档（§6.1 / §9.4）。

参数与团队公用 `backend/.env` 完全对齐，两边连同一个云库。

| 配置项   | 值                                 |
| -------- | ---------------------------------- |
| 地址     | 见 `.env` 中 `DB_HOST`（隧道入口 `127.0.0.1`） |
| 端口     | 见 `.env` 中 `DB_PORT`（默认 3308 = SSH 隧道本地端口，转发到服务器 3307） |
| 数据库   | `smart_scheduler_dev`              |
| 用户名   | 见 `.env` 中 `DB_USER`             |
| 密码     | 见 `.env` 中 `DB_PASSWORD`         |
| 字符集   | `utf8mb4`                          |
| 驱动     | `asyncmy`（异步）                  |

本地经 SSH 隧道连服务器 MySQL：

```bash
ssh -L 3308:127.0.0.1:3307 root@<服务器IP> -N
```

后端 `.env`（严禁提交，用 `.env.example` 作模板）：

```env
DB_HOST=127.0.0.1
DB_PORT=3308
DB_USER=<数据库用户名>
DB_PASSWORD=<数据库密码>
DB_NAME=smart_scheduler_dev

APP_NAME=SmartScheduler
APP_ENV=dev
DEBUG=true

JWT_SECRET_KEY=<JWT密钥>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

AGENT_URL=
```

由上述五项自动拼接连接串：`mysql+asyncmy://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?charset=utf8mb4`。

## 表结构

命名规范：表名/字段 `snake_case`，API 字段 `camelCase`（§6.2）。

### 1. space_resource 空间资源表

| 字段名          | 类型            | 说明                             |
| --------------- | --------------- | -------------------------------- |
| id              | BIGINT UNSIGNED | 主键，自增                       |
| space_name      | VARCHAR(128)    | 空间名称                         |
| space_type      | INT             | 1会议室 2展厅 3多功能厅 4户外场地 |
| capacity        | INT             | 容纳人数                         |
| location        | VARCHAR(255)    | 位置                             |
| budget          | DECIMAL(10,2)   | 预算                             |
| open_start_time | TIME            | 开放起始时间                     |
| open_end_time   | TIME            | 开放结束时间                     |
| status          | INT             | 1可用 0停用                      |
| create_time     | DATETIME        | 创建时间                         |
| update_time     | DATETIME        | 更新时间                         |

索引：`idx_space_type(space_type)`、`idx_capacity(capacity)`。

### 2. device_resource 设备资源表

| 字段名          | 类型            | 说明                    |
| --------------- | --------------- | ----------------------- |
| id              | BIGINT UNSIGNED | 主键，自增              |
| device_name     | VARCHAR(128)    | 设备名称                |
| device_type     | VARCHAR(64)     | 设备类型                |
| device_status   | INT             | 1完好，2损坏，3缺失配件 |
| total_count     | INT             | 总数量                  |
| available_count | INT             | 可用数量                |
| create_time     | DATETIME        | 创建时间                |
| update_time     | DATETIME        | 更新时间                |

索引：`idx_device_type(device_type)`。

### 3. reserve_order 预约订单表

| 字段名        | 类型            | 说明                               |
| ------------- | --------------- | ---------------------------------- |
| id            | BIGINT UNSIGNED | 主键，自增                         |
| user_id       | BIGINT UNSIGNED | 预约人ID（FK -> sys_user.id）      |
| space_id      | BIGINT UNSIGNED | 空间ID（FK -> space_resource.id）  |
| device_ids    | JSON            | 设备ID列表                         |
| start_time    | DATETIME        | 开始时间                           |
| end_time      | DATETIME        | 结束时间                           |
| order_status  | INT             | 1待确认，2已确认，3已取消，4已完成 |
| agent_request | VARCHAR(1024)   | 用户原始需求                       |
| agent_trace   | JSON            | AI思考过程追踪                     |
| create_time   | DATETIME        | 创建时间                           |
| update_time   | DATETIME        | 更新时间                           |

索引：`idx_user_id(user_id)`、`idx_space_time(space_id, start_time, end_time)`、`idx_status(order_status)`。

### 4. notify_message 消息通知表

| 字段名      | 类型            | 说明                                    |
| ----------- | --------------- | --------------------------------------- |
| id          | BIGINT UNSIGNED | 主键，自增                              |
| receiver_id | BIGINT UNSIGNED | 接收人ID（FK -> sys_user.id）           |
| notify_type | INT             | 1预约提醒 2变更致歉 3故障告警           |
| order_id    | BIGINT UNSIGNED | 关联订单ID（FK -> reserve_order.id）    |
| title       | VARCHAR(255)    | 通知标题                                |
| content     | TEXT            | 通知内容                                |
| is_read     | INT             | 0未读，1已读                            |
| create_time | DATETIME        | 创建时间                                |

索引：`idx_receiver_read(receiver_id, is_read)`。

## 建表 SQL

表已在云数据库 `smart_scheduler_dev` 中创建完成（§6.5），完整脚本见 `backend/init_db.sql`。

### ⚠️ 上面各节的 `idx_*` 索引并未落到云库（2026-09-26 实测）

上面四张表列出的 `idx_space_type` / `idx_capacity` / `idx_device_type` / `idx_user_id` /
`idx_space_time` / `idx_status` / `idx_receiver_read` —— **云库 `smart_scheduler_dev` 里一个都没有**。

直查 `information_schema.STATISTICS`，库中除主键外的索引全是外键/唯一约束**自动生成、
与外键列同名**的那些（`reserve_order.space_id`、`reserve_order.user_id`、
`notify_message.receiver_id` …）。对照 `开发流程.md`：§6.7 前 6 步的 `ALTER TABLE` 与外键回填
执行过（外键索引在库为证），**唯独第 7 步 `CREATE INDEX` 没跑** —— 而该步注明
「由基础支撑与集成组统一执行」。团队唯一的 Alembic 迁移 `init_tables_single_role.py`
里也没有 `create_index`。

上表按 §6.6 **规范**记述，不是对云库现状的描述；`backend/init_db.sql` 里也仍带着这 7 条
`INDEX` 声明（本模块唯一还声明它们的地方，只在自建库时才会生效）。**索引是否补建属集成组
待办**，详见 `docs/团队仓库合并冲突比对.md` 第 11.1 节。

## 模型与公用后端的对齐说明

2026-09-26 起 `app/models/` **就是团队公用 `backend/app/models/` 的同一份内容**
（字段、外键、`comment`、`server_default=func.now()`、绝对导入均逐字一致），
只有一处必要差异：

**主键类型 `PK_TYPE`**（`app/core/database.py`）定义为
`BigInteger().with_variant(Integer, "sqlite")`。MySQL 下渲染为 `BIGINT`，与公用后端及云库一致；
SQLite 下降级为 `INTEGER`。原因：SQLite 只有 `INTEGER PRIMARY KEY` 是 rowid 别名才会自增，
`BIGINT PRIMARY KEY` 不会，否则 §13.1 应急预案要求的「本地 SQLite 镜像库」无法建表。

**索引**：模型**不声明任何索引**（团队模型也没有）。原因见上文「上面各节的 `idx_*` 索引
并未落到云库」—— 云库、团队模型、团队迁移三处都没有这些索引，模型若单方面声明，等于
声明云库没有的东西，也与「表结构变更由集成组统一执行」的约定冲突。

### 外键：四个都是真外键

`reserve_order` 的 `space_id`、`user_id` 与 `notify_message` 的 `order_id`、`receiver_id`
**均声明为真外键**。云库 `information_schema.STATISTICS` 显示这四列上都有外键自动生成的
索引，证实云库里的约束确实存在。

> 本模块曾把 `user_id` / `receiver_id` 写成软引用，理由是「保持自包含、不引入 `SysUser`
> 实体，否则 `create_all` 抛 `NoReferencedTableError`」。**该顾虑已随本次对齐消失**：
> 团队 `system.py` 带进了 `SysUser`，`sys_user` 进了 metadata，真外键可正常解析。
>
> **连带影响**：写 `reserve_order` / `notify_message` 前必须先有对应的 `sys_user` 行，
> 否则云库会以 1452 拒绝写入。测试夹具因此新增 `_seed_users()`
> （`tests/module3/conftest.py`）。这同时是 `docs/公用后端问题反馈.md` 第四条的另一面。
