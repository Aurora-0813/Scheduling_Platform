# 部署与联调文档

> 适用范围：开发机本地启动、云服务器部署、以及**云库在隧道里的人工验证步骤**。
> 主管模块：**模块 10 系统集成与联调**。
>
> 权威来源：仓库根目录 `开发流程.md` 第 12 章（部署与运维规范）。
> 文档要求（`开发流程.md` 11.2）：**必须包含环境要求、配置说明、启动步骤**，且**禁止出现真实密码/密钥/连接串**。

---

## 一、环境要求

### 1.1 云服务器（`开发流程.md` 12.1）

| 项目 | 值 |
| --- | --- |
| 主机 | 阿里云 ECS，2 核 2G，Ubuntu 22.04 |
| MySQL | 8.0.39，`utf8mb4`，字符集与排序规则见 `docs/database.md` |
| Redis | 7.2.5，需开启持久化（`appendonly yes`） |
| Nginx | 1.26.2，反向代理 |
| 可选 | Docker 26.1.4 + Docker Compose 2.29.7 |

> ⚠️ **2 核 2G 同时跑 MySQL + Redis + Nginx + Uvicorn 会 OOM**。
> 必须配置 **2G swap**，并给各服务设内存上限（见 5.3 的 `systemd` 片段与 5.4）。
> 这不是「建议」：MySQL 8 默认 `innodb_buffer_pool_size` 为 128M，
> 加上 Redis（默认无上限）与 Python 进程，2G 物理内存的实际余量只有几百 MB。

### 1.2 开发机

| 项目 | 值 | 说明 |
| --- | --- | --- |
| OS | Windows 10 / 11 + Git Bash，或 Linux / macOS | 本项目在 Windows + Git Bash 下完成全部开发与测试 |
| Python | **3.11.9** | 3.12+ 下 `asyncmy 0.2.10` 与 `bcrypt 4.0.1` 的轮子匹配情况未验证 |
| 环境管理 | conda，环境名 **`smart_dev`** | 与 `开发流程.md` 3.6 一致 |
| 依赖 | `pip install -r requirements.lock` | **用 lock 不用 `requirements.txt`**：间接依赖也必须一致 |
| 数据库 | 通过 **SSH 隧道**访问云库 | 见第二节 |
| 测试 | 无需任何外部依赖 | 见 `docs/test.md`，349 个用例离线全绿 |

### 1.3 网络可达性（当前实测）

| 目标 | 状态 | 影响 |
| --- | --- | --- |
| 云库真实端口（云服务器上） | 未直连，需隧道 | — |
| 隧道本端 `127.0.0.1:3308` | 隧道未启动时 CLOSED | 启动服务前必须先起隧道 |
| Redis 隧道本端 `127.0.0.1:6380` | 同上 | 同上 |
| SSH 部署机 `192.168.88.100:22` | CLOSED（非当前网段） | 见 7.1 |

---

## 二、SSH 隧道（开发机连云库的唯一方式）

### 2.1 为什么必须走隧道

`开发流程.md` 6.1 规定「所有开发人员连接云服务器上的统一 MySQL，禁止使用本地数据库」。
云库**不对公网开放端口**（这是正确的安全姿态 —— 3306 暴露在公网上几小时内就会开始被扫描爆破），
因此开发机通过 SSH 隧道把云服务器的端口映射到本机。

### 2.2 端口对应关系（**最容易搞混的一点**）

同一个服务有**两个端口号**，`.env` 里填的是**本机这一端**：

| 服务 | 云服务器上的端口 | 本机隧道端口 | `.env` 里填哪个 |
| --- | --- | --- | --- |
| MySQL | 见云服务商/运维实际配置 | **3308** | `DB_PORT=3308` ✅ 本机端 |
| Redis | 6379（默认） | **6380** | `REDIS_PORT=6380` ✅ 本机端 |

> `开发流程.md` 466 行的示例写的是 `DB_PORT=3307`，那是**示例值**。
> 本项目实际使用 **3308**（见 `.env.example`）。
> 关键在于：`.env` 的 `DB_HOST=127.0.0.1` 说明它写的是隧道**本端**，
> 所以 `DB_PORT` 也必须是隧道本端端口 —— 这两项必须属于同一端，否则连不上或连错服务。

### 2.3 启动命令

```bash
ssh -N \
  -L 3308:<云库真实端口>:<云库真实主机或容器名> \
  -L 6380:127.0.0.1:6379 \
  <用户名>@<云服务器IP>
```

参数说明：

- `-N`：只做端口转发，不执行远程命令；这样窗口里不会有 shell 提示符，**看着像卡住，其实是正常的**。
- `-L 3308:...`：把本机 `3308` 转到「从云服务器视角看」的目标。
  若 MySQL 直接跑在宿主机上，目标写 `127.0.0.1:3306` 或云服务商配置的端口；
  若跑在 Docker 容器里，目标写 `<容器名>:3306`（**容器名由云服务器解析**，因为 `-L` 的目标是从服务器那端连的）。
- `-L 6380:127.0.0.1:6379`：Redis 通常直接跑在宿主机，故写 `127.0.0.1:6379`。
- 加 `-o ServerAliveInterval=30` 可防止 SSH 空闲被网络设备掐断。

### 2.4 隧道是否已通的判据

```bash
# 隧道起来后，下面两条命令不应报「连接被拒绝」
python -c "import socket; s=socket.create_connection(('127.0.0.1',3308),3); print('3308 OK')"
python -c "import socket; s=socket.create_connection(('127.0.0.1',6380),3); print('6380 OK')"
```

更省事的办法是直接问服务本身 —— 起好服务后打 `/api/v1/ready`（见 3.4），
它会分别报 `db` 与 `redis` 的状态。

> ⚠️ **`<云服务器IP>` 当前未知**：`.env` 里只有隧道本端的 `127.0.0.1`，
> 云服务器真实地址需由你补充（已列入 `docs/汇报文档.md` 待确认项）。
> 同理，云库的**真实端口**也需确认（`开发流程.md` 只给了示例 `3307`）。

---

## 三、本地启动

### 3.1 首次准备

```bash
# 1) 建环境（环境名必须与文档一致）
conda create -n smart_dev python=3.11.9 -y
conda activate smart_dev

# 2) 装依赖（用 lock 文件）
pip install -r requirements.lock

# 3) 建 .env
cp .env.example .env
#    然后编辑 .env，至少填 DB_PASSWORD 与 JWT_SECRET_KEY
```

生成 `JWT_SECRET_KEY`：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> ⚠️ **不要手写短密钥**。`app/core/config.py` 的 `MIN_JWT_SECRET_LENGTH = 32`：
> **非 dev 环境**下长度不足**直接拒绝启动**；**dev 环境**下只打 WARNING。
> 当前 `.env` 里的值只有 6 个字符 —— 在 dev 下能跑起来，但这是个真实的安全弱点：
> HS256 的密钥一旦被猜到，任何人都能伪造任意用户的令牌。
> **本仓库的 `.env` 未被修改**（敏感文件，改动需你确认）；加固建议见 `docs/汇报文档.md`。

`.env` 里的关键项：

| 变量 | 本项目取值 | 说明 |
| --- | --- | --- |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3308` | 隧道本端 |
| `DB_NAME` | `smart_scheduler_dev` | `开发流程.md` 12.2：dev 环境库 |
| `REDIS_ENABLED` | `true` | `.env` 里**没有** `REDIS_*` 项时默认为 `true` |
| `REDIS_PORT` | `6380`（若补上） | 隧道本端 |
| `JWT_EXPIRE_MINUTES` | `1440`（当前 `.env`） | ⚠️ 24 小时。`ACCESS_TOKEN_WARN_MINUTES=120`，超了打警告 |
| `BCRYPT_ROUNDS` | 未设 → `12` | 与 `docs/seed.sql` 的哈希 cost 一致，**不要为了「快」调低演示库** |
| `DEBUG` | `true` | ⚠️ 控制 Mock 路由是否注册（见 6.1） |
| `SQL_ECHO` | `false` | 与 `DEBUG` **刻意解耦**：开启会把 bcrypt 哈希打进日志 |

### 3.2 一键启动（推荐）

```bash
bash scripts/dev.sh
```

脚本做的事（`开发流程.md` 8.9）：检查 `.env` → 载入 conda → `pip install -r requirements.lock` → 可选迁移 → `uvicorn`。

可用环境变量：

| 变量 | 默认 | 用途 |
| --- | --- | --- |
| `ENV_NAME` | `smart_dev` | conda 环境名 |
| `HOST` | `0.0.0.0` | `0.0.0.0` 允许局域网内的手机 / 小程序真机调试 |
| `PORT` | `8000` | 监听端口 |
| `RELOAD` | `1` | `1`=代码改动自动重启 |
| `MIGRATE` | `0` | `1`=启动前先跑 `alembic upgrade head` |
| `SKIP_INSTALL` | `0` | `1`=跳过装依赖（日常重启不必每次装） |

**演示 / 联调时用这一条**：

```bash
SKIP_INSTALL=1 RELOAD=0 bash scripts/dev.sh
```

原因见 6.2：`RELOAD=1` 下每次代码改动都会重启进程，若 `REDIS_ENABLED=false`，
刷新令牌白名单存在进程内存里，**重启即让所有已登录用户掉线**。

### 3.3 手工启动（不用脚本时）

```bash
conda activate smart_dev
export PYTHONIOENCODING=utf-8     # 日志含中文，Windows 控制台需要
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3.4 启动成功的判据（M1 验收点）

启动后依次访问：

| 地址 | 期望 |
| --- | --- |
| <http://127.0.0.1:8000/api/v1/health> | `{"code":200,"message":"success","data":{"status":"ok",...}}` —— 进程活着 |
| <http://127.0.0.1:8000/api/v1/ready> | `data.db = "ok"`（**M1「库能连上」的验收点**）；`data.redis` 为 `"ok"` 或 `"disabled"` 或 `"degraded"` |
| <http://127.0.0.1:8000/docs> | Swagger UI（中文标题），可见四个 `/auth/*` 接口 |

**`/ready` 的三种 `db` 状态及含义**：

| 值 | 含义 | 处理 |
| --- | --- | --- |
| `ok` | 库连上了，且能执行查询 | 正常 |
| `error` | 连不上或查询失败 | 检查隧道是否还在；检查 `.env` 的 `DB_*`；看服务日志里 `_probe_database` 的告警 |
| `degraded` | 同上，但整体状态标为 degraded | 同上 |

> `/ready` **永远返回 HTTP 200**（`docs/api.md` 3.3）：它是诊断工具，
> 若在依赖故障时返回 503，人反而拿不到「哪个依赖坏了」的信息。
> **不要**把 `/ready` 挂到 Nginx 的负载均衡健康检查上（那样故障实例会被误判为健康）。

**登录冒烟**：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<docs/seed.sql 里的占位口令>"}'
```

期望返回统一信封，`data` 含 `accessToken` / `refreshToken` / `role`。

---

## 四、数据库：迁移与种子数据

### 4.1 执行迁移（唯一的 schema 来源）

```bash
conda activate smart_dev
cd <仓库根>                       # 必须在仓库根执行：alembic.ini 的 script_location 是 %(here)s/alembic
alembic upgrade head
```

**四个必须知道的坑**（详见 `docs/database.md` 6.4 与 `docs/开发流程说明文档.md`）：

| 坑 | 现象 | 做法 |
| --- | --- | --- |
| 用 `python -m alembic` | `No module named alembic.__main__` | **必须用 `alembic` 控制台脚本**。仓库根有个同名 `alembic/` 目录，从根用 `-m` 启动时它会作为命名空间包遮蔽真正的 alembic 包 |
| 口令里有 `%` | `InterpolationSyntaxError` | `env.py` 已把 `%` 转义为 `%%`；改连接串拼装逻辑时**别把这一步丢了** |
| Windows 事件循环 | `asyncmy` 相关报错 | `env.py` 在任何 `asyncio.run` 之前设置 `WindowsSelectorEventLoopPolicy`；这也意味着**不能用 `-m` 的某些启动方式绕开它** |
| 中文输出乱码 | `UnicodeEncodeError: 'gbk' codec` | `export PYTHONIOENCODING=utf-8`；`env.py` 也会强制 stdout 为 UTF-8 |

**当前迁移链**：

```
8969262c9d0c  init_tables_single_role         ← 已存在（9 张表）
b7f1c4a92e35  add_doc66_indexes_idempotent    ← 本次新增（补 11 个索引：6.6 的 10 个 + database.md 3.4 的 1 个）
```

第二条是**幂等**的：先查 `information_schema.statistics`，索引已存在就跳过。
因此**无论云库现状如何，执行它都安全**（这正是把它写成幂等版的原因 —— 云库现在是什么状态无法确认）。

**哪些建表语句属于谁**：`开发流程.md` 6.5/6.7 说建表由集成组跑手工 DDL，
但本项目的实际做法是 **Alembic 作为 schema 唯一来源**（决策 1）。
原因：两套机制并存时，`autogenerate` 会把手工 DDL 建出的对象当成「多余」而生成 `drop_index`。
`docs/database.md` 第四节记录了这件事。

### 4.2 执行前的备份（`开发流程.md` 12.4）

```bash
mysqldump -u <DB_USER> -p smart_scheduler_dev > backup_$(date +%Y%m%d_%H%M%S).sql
```

> 迁移**在云库上是写操作**。本仓库的迁移只在 `ALEMBIC_DATABASE_URL` 指向的
> **SQLite 临时库**上被自动验证过（`tests/integration/test_migrations.py`，8 个用例），
> 云库上的执行**必须由你在场**，且先备份。
>
> `ALEMBIC_DATABASE_URL` 这个开关**只接受 `sqlite` 开头的连接串**：`env.py` 里有硬校验，
> 非 sqlite 直接抛错。这是刻意设计的安全护栏 —— 防止有人以为它在设测试库，
> 结果把迁移打到了线上库。

### 4.3 执行种子数据

`docs/seed.sql` 提供了演示数据：**3 个用户 / 8 个场地 / 15 个设备 / 10 条预约**，
外加两份**刻意的异常账号**（已禁用、未分配角色）用于演示 40108 / 40302。

```bash
mysql -h 127.0.0.1 -P 3308 -u <DB_USER> -p smart_scheduler_dev < docs/seed.sql
```

> ⚠️ **占位口令必须改**：`docs/seed.sql` 里的 bcrypt 哈希对应的是
> **公开的占位口令**（写在脚本注释里）。首次部署后**立即**修改：
>
> ```bash
> bash scripts/gen_seed_hashes.sh '你的新口令'
> ```
>
> 该脚本调用**生产代码**的 `app.core.security.hash_password` 生成哈希
> （所以格式与登录校验完全一致，不会出现「哈希格式对但算法不对」），
> **只打印 SQL 不执行任何写操作** —— 种子数据属于数据库写操作，由人执行。

种子脚本的执行顺序与 FK 依赖、幂等性（`INSERT ... ON DUPLICATE KEY UPDATE`）、
以及**离线验证结果**（在 SQLite 上跑通全部 8 条 DML，行数 3/5/8/15/10，
`PRAGMA foreign_keys=ON` 下 FK 完整，角色权限层次 `user(10) ⊂ resource_admin(19) ⊂ admin(26)`，
5 个占位哈希都能通过生产的 `verify_password`）见 `docs/database.md` 第八节。

### 4.4 环境区分（`开发流程.md` 12.2）

| 环境 | 数据库 | 用途 | 如何切换 |
| --- | --- | --- | --- |
| dev | `smart_scheduler_dev` | 日常开发联调 | `.env` 的 `DB_NAME` |
| test | `smart_scheduler_test` | 自动化测试 | 同上（**禁止在代码里硬编码**） |
| prod | `smart_scheduler_prod` | 演示与验收 | 同上，部署时创建 |

> 本项目当前**全部测试离线运行**（SQLite 临时库 + 假 Redis），
> 因此 `smart_scheduler_test` **未被使用**。真库测试的口径已定：不建 `test_` 前缀表，
> 改用「外层事务 + savepoint 回滚」（见 `docs/database.md` 9.1）；
> 确需真库写权限时由模块负责人向管理员申请。
> `test` 这一行**保留在表里是为了对照 `开发流程.md` 12.2 的三环境定义**，
> 不是当下有库在用；`DB_NAME` 仍然只从 `.env` 读，不硬编码。
> 真实 MySQL 的行锁语义（`SELECT ... FOR UPDATE`）与方言差异**必须在真库上验证**，见 4.5。

### 4.5 云库上的人工验证清单（**必须由人执行**）

自动化测试覆盖不到的项，逐条在隧道里验证：

| # | 验证项 | 命令 | 期望 |
| --- | --- | --- | --- |
| 1 | 索引已建齐 | `SHOW INDEX FROM sys_user;` 等 9 张表 | 出现 `docs/database.md` 三节的 **11** 个索引（6.6 的 10 个 + 3.4 的 `idx_status_start`）。注意 `inspect_record.space_id` / `repair_ticket.device_id` 上可能只有 MySQL 外键自动索引（`..._ibfk_N`），**同列即等效**，不算缺失 |
| 2 | 迁移版本 | `SELECT * FROM alembic_version;` | `b7f1c4a92e35` |
| 3 | 种子数据行数 | `SELECT (SELECT COUNT(*) FROM sys_user), (SELECT COUNT(*) FROM space_resource), (SELECT COUNT(*) FROM device_resource), (SELECT COUNT(*) FROM reserve_order);` | `5, 8, 15, 10`（用户 5 个：3 正常 + 2 个演示异常账号，见 `docs/database.md` 8.7） |
| 4 | 角色权限层次 | `SELECT role_name, JSON_LENGTH(permissions) FROM sys_role;` | `admin=26, resource_admin=19, user=10`（**用 `JSON_LENGTH` 而非 `LENGTH`**：后者是字节数） |
| 5 | 云库时区 | `SELECT @@global.time_zone, @@session.time_zone, NOW();` | 决定是否给连接加 `init_command=SET time_zone`（待确认项） |
| 6 | 字符集 | `SELECT @@character_set_database, @@collation_database;` | `utf8mb4` / `utf8mb4_0900_ai_ci` |
| 7 | **行锁语义** | 开两个会话，对同一行 `SELECT ... FOR UPDATE` 后各自尝试 UPDATE | 第二个会话阻塞至第一个提交（`docs/database.md` 七节要求的并发控制，SQLite 测不到） |
| 8 | 登录冒烟 | `docs/seed.sql` 的 3 个账号各登录一次 | 200；异常账号分别得 40108 / 40302 |

---

## 五、部署到云服务器

> 本节是**参考方案**。`开发流程.md` 12.3 只规定了后端用 Uvicorn + `.env`、前端 `npm ci` 构建后交给 Nginx，
> 未规定进程管理方式。本仓库**不含** Docker/Nginx 部署产物（`开发流程.md` 第 12 章不在本轮交付范围）。

### 5.1 后端（systemd 方式，最省内存）

```bash
# 云服务器上
cd /opt/smart-scheduler/backend          # 或 monorepo 下的 backend/
conda activate smart_dev
pip install -r requirements.lock
cp .env.example .env                     # 填真实值；.env 不进仓库
```

`/etc/systemd/system/smart-backend.service`：

```ini
[Unit]
Description=Smart Scheduler Backend
After=network.target mysql.service redis.service

[Service]
Type=simple
User=appuser
WorkingDirectory=/opt/smart-scheduler/backend
Environment=PYTHONIOENCODING=utf-8
ExecStart=/home/appuser/miniconda3/envs/smart_dev/bin/uvicorn \
          app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

# 2 核 2G 上必须设上限，否则 OOM killer 会随机杀进程
MemoryMax=700M

[Install]
WantedBy=multi-user.target
```

> **`--host 127.0.0.1`**：只监听本机，外部流量一律经 Nginx。
> 直接把 Uvicorn 暴露到公网会绕过 Nginx 的超时/限流/HTTPS 配置。
>
> **`--workers 2` 是本项目的上限**：2 核，且 MySQL 与 Redis 也在同一台机器上。
> 更要注意的是 **`REDIS_ENABLED=false` 时 `--workers 2` 会出问题**：
> 两个进程各有一份内存白名单，用户在 A 进程登录、请求被负载到 B 进程就会 401。
> 因此**生产必须启用 Redis**（内存降级方案只适用于单 worker 的演示）。

### 5.2 数据库迁移（部署时）

```bash
cd /opt/smart-scheduler/backend
conda activate smart_dev
mysqldump -u <DB_USER> -p smart_scheduler_prod > backup_$(date +%Y%m%d_%H%M%S).sql   # 先备份
alembic upgrade head
```

> 在云服务器上**不需要 SSH 隧道**（本机连本机），此时 `.env` 的 `DB_HOST` 应为
> `127.0.0.1` 且 `DB_PORT` 为 MySQL 真实端口。**同一份 `.env` 在开发机与服务器上的含义不同**
> （开发机是本端隧道端口，服务器是真实端口）—— 这也是 `.env` 不进仓库的原因之一。

### 5.3 Nginx

```nginx
server {
    listen 80;
    server_name <你的域名或公网IP>;

    client_max_body_size 10m;        # 与 MAX_UPLOAD_SIZE_MB=10 对齐

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;     # 模块 4 的 Agent 调用可能较慢
    }

    # 前端静态资源
    location / {
        root /var/www/smart-scheduler;
        try_files $uri $uri/ /index.html;
    }
}
```

> ⚠️ **`client_max_body_size` 必须与后端的上传上限一致**。若 Nginx 默认的 1m 生效，
> 大文件会在 Nginx 层被 413 拒掉，**后端的 `MAX_UPLOAD_SIZE_MB` 根本执行不到** ——
> 前端会收到一个不带统一信封的 413 错误页，而所有错误处理都在后端。
>
> ⚠️ `proxy_set_header X-Forwarded-For` 是 `app/api/v1/auth.py` 的 `_client_ip()`
> **风控日志**用的。已注明：该值**可伪造**，只用于日志，**绝不用于鉴权**。

### 5.4 Redis 持久化（`开发流程.md` 12.3）

```
# redis.conf
appendonly yes
appendfsync everysec
maxmemory 256mb
maxmemory-policy allkeys-lru
```

> `maxmemory-policy` 用 `allkeys-lru` 而非 `noeviction`：
> 认证白名单的键本身带 TTL，但指标计数器会持续增长。
> `noeviction` 下内存打满会让**所有写入失败**（包括登录），直接把系统打死。

### 5.5 安全清单（部署前逐项确认）

| 项 | 要求 |
| --- | --- |
| `APP_ENV` | **必须非 `dev`**：`config.py` 在非 dev 下会对短 `JWT_SECRET_KEY` **直接拒绝启动** |
| `DEBUG` | **必须 `false`**：否则 `/mock/*` 的 21 个接口会注册到生产（见 6.1） |
| `SQL_ECHO` | `false`：否则 bcrypt 哈希进日志 |
| `JWT_SECRET_KEY` | ≥32 字符随机值，且**与 dev 环境不同** |
| `BCRYPT_ROUNDS` | `12` |
| `.env` 权限 | `chmod 600 .env` |
| 种子占位口令 | **已修改**（`scripts/gen_seed_hashes.sh`） |
| MySQL 端口 | **不对公网开放** |
| Redis | 设密码（若监听非回环地址）、不对公网开放 |
| HTTPS | Nginx 上配 TLS |

> ⚠️ `DEBUG=true` 时 `/mock/*` 会注册 —— 这不是理论风险，见 6.1。

---

## 六、常见问题

### 6.1 `DEBUG=true` 会把 21 个 Mock 接口带进生产 ⚠️

`app/main.py` 里：

```python
if settings.DEBUG:
    application.include_router(mock.router, prefix=settings.API_V1_PREFIX)
```

- ✅ **收益**：模块 1～8 尚未实现时，前端与小程序能并行开发（`docs/api.md` 3.4 有 21 个 `/mock/*` 接口表）。
- ⚠️ **代价**：`DEBUG=true` 的生产环境会**对外暴露** `POST /mock/simulate`（可灌入任意指标数据）
  和 `POST /mock/*` 等一系列写接口。**没有任何鉴权**。
- **护栏**：`tests/api/test_mock_routes.py` 用 3 个用例钉住注册行为
  （`DEBUG` 开时路径与表完全一致、关时整体不注册、HTTP 层确认 404）——
  改动注册条件会被测试拦下。
- **部署检查**：确认 `DEBUG=false`，然后访问 `/api/v1/mock/health` 应得 404。

### 6.2 `REDIS_ENABLED=false` 下的重启掉线

内存白名单随进程消失，因此：

| 场景 | 后果 |
| --- | --- |
| `uvicorn --reload` 下改一次代码 | 所有已登录用户掉线（续期得 40106） |
| 单 worker 重启 | 同上 |
| **多 worker** | **登录后请求被负载到别的 worker 就 401**（各进程白名单不共享） |

对策：演示/联调用 `SKIP_INSTALL=1 RELOAD=0 bash scripts/dev.sh`；生产启用 Redis。
`docs/api.md` 2.6 有完整的降级行为表。

### 6.3 排查表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 启动即 `ModuleNotFoundError: pydantic_settings` | 装到了别的环境 | `conda activate smart_dev`；确认 `python -c "import sys; print(sys.executable)"` |
| `/ready` 报 `db: error` | 隧道没起 / `.env` 的 `DB_*` 错 | 起隧道；核对 `DB_PORT` 是**本端**端口（2.2） |
| `alembic` 报 `No module named alembic.__main__` | 用了 `python -m alembic` | 改用 `alembic upgrade head`（4.1） |
| `alembic` 报 `InterpolationSyntaxError` | 口令含 `%` 且转义被去掉 | `env.py` 里 `.replace("%", "%%")` 必须在 |
| 日志中文乱码 / `UnicodeEncodeError: 'gbk'` | Windows 控制台编码 | `export PYTHONIOENCODING=utf-8` |
| 登录 500 | 库连不上（`/ready` 会提前暴露） | 先修 `/ready` |
| 登录 403 / 40302 | 账号 `role_id` 为空 | 跑 `docs/seed.sql`，或给账号分配角色 |
| 登录 403 / 40108 | 账号 `status=0` | 种子数据里有刻意准备的禁用账号，换用正常账号 |
| 续期 40106 | 白名单里没有该 jti | 已登出/已轮换过；前端应重新登录 |
| 续期 503 / 50301 | Redis 不可用 | **预期行为**（决策 7）：续期与登出严格失败。修 Redis 或启用降级 |
| 登录成功但业务接口 401 | `REDIS_ENABLED=false` + 多 worker / 重启过 | 见 6.2 |
| 响应字段是 `access_token` 而非 `accessToken` | 某处 `model_dump()` 漏了 `by_alias=True` | 见 `docs/api.md` 1.3；`test_response_envelope.py` 会拦下这类回归 |
| 跨域报错 | `CORS_ORIGINS` 没含你的前端来源 | 改 `.env`；**不要**改成 `*` |
| 上传被 413 拒且响应不是统一信封 | Nginx 的 `client_max_body_size` 小于后端上限 | 见 5.3 |

---

## 七、待确认 / 已知风险

### 7.1 待你确认的部署相关信息

| # | 事项 | 影响 |
| --- | --- | --- |
| 1 | **云服务器真实 IP** | 隧道命令必需（`.env` 里没有） |
| 2 | **云库真实端口** | 隧道目标必需（`开发流程.md` 只给示例 3307） |
| 3 | **Redis 实例/端口/密码/DB index** | 决策 6 依赖它；未配置时降级为内存实现 |
| 4 | ~~`smart_scheduler_test` 是否已建、账号有无建库权限~~ **已闭**：真库测试改用「外层事务 + savepoint 回滚」，不依赖独立测试库（`docs/database.md` 9.1）。若确需真库写权限，找管理员申请 | —— |
| 5 | **云库时区**（`SELECT @@global.time_zone, NOW()`） | 决定是否给连接加 `init_command=SET time_zone`。相关：tz-aware 输入目前**不换算**，见 7.2 |
| 6 | 云服务器上 MySQL 是否跑在 Docker 里 | 若是，隧道目标要写容器名而非 `127.0.0.1`（2.3） |
| 7 | `.idea/deployment.xml` 的 SSH 目标是 `root@192.168.88.100:22` → 部署路径 `/` | **直接部署到服务器根目录，风险高**。建议改为普通用户 + `/opt/...`。该文件属 IDE 配置，不在本轮改动范围 |

### 7.2 已知风险

| 风险 | 触发条件 | 应对 |
| --- | --- | --- |
| 种子占位口令未改 | 部署后忘记 | `docs/seed.sql` 注释 + 本文件 4.3 双重标注；`scripts/gen_seed_hashes.sh` 提供改法 |
| `DEBUG=true` 带上 Mock 接口 | 部署时漏改 | 5.5 清单 + 6.1；测试已钉住行为 |
| Nginx 上传上限与后端不一致 | 两处配置未对齐 | 5.3 的 ⚠️；部署检查 |
| 2G 内存 OOM | 未配 swap / 未限内存 | 1.1 与 5.1；`MemoryMax=700M` |
| 短 `JWT_SECRET_KEY` | `.env` 当前 6 字符 | 非 dev 下会拒绝启动（**意外地成了护栏**）；dev 下仅警告 —— 建议立即更换 |
| `--workers > 1` + 内存白名单 | 未启用 Redis | 5.1 的 ⚠️；生产必须启用 Redis |
| 云服务器上 `.env` 语义与开发机不同 | 照抄开发机配置 | 5.2 的 ⚠️（隧道端口 vs 真实端口） |
| 时区不换算 | 前端传带时区的 ISO 时间 | `docs/api.md` 1.5 要求前端传 `YYYY-MM-DD HH:mm:ss`；后端接收层**照抄不换算**（已有测试钉住） |
| 未处理异常的 500 无 CORS 头与 `X-Request-Id` | 应用外的框架级 500 | `tests/api/test_cors.py` 已钉住；前端对该类错误拿不到任何上下文，需看服务端日志 |

---

## 八、演示前检查清单

```
[ ] SSH 隧道已起，3308 / 6380 均通（2.4）
[ ] SKIP_INSTALL=1 RELOAD=0 bash scripts/dev.sh 已启动
[ ] /api/v1/ready 显示 db=ok
[ ] 三个种子账号都能登录（4.5 第 8 项）
[ ] 异常账号分别得到 40108 / 40302（演示异常分支用）
[ ] GET /api/v1/monitor/agent 返回三个契约字段（模块 10 演示）
[ ] DEBUG 与 REDIS_ENABLED 的取值符合本次演示形式（6.1 / 6.2）
[ ] 前端来源在 CORS_ORIGINS 中
[ ] 若演示降级：`/agent/schedule?degraded=true` 会带 X-Agent-Degraded（见 docs/api.md 3.4）
```
