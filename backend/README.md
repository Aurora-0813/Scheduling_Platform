# AI 全感知·智能空间与设备综合调度平台 — 后端服务

面向企业的空间硬件资源智能调度系统后端。AI 为核心决策引擎，支持口语、拍照、手绘草图等模糊且带冲突约束的业务需求，由 LangChain Agent 完成解析、冲突校验、权衡决策、生成方案并写入业务数据库。

- **技术栈**：FastAPI 0.115.0 + SQLAlchemy 2.0.35（异步）+ asyncmy + Alembic + LangChain 1.3.11
- **数据库**：云服务器统一 MySQL 8.0.39（`smart_scheduler_dev`），禁止使用本地数据库
- **完整规范**：见仓库根目录 `开发流程.md`

> 本仓库当前定位为 `Scheduling_Platform/backend/` 子目录，后续并入 monorepo。
> 因此 `frontend/`、`miniprogram/`、根级 `.github/`、根级 `docs/`、`scripts/` 均不在此处创建。

---

## 一、快速开始

### 1. 创建并激活环境

项目文档 8.9 / 12.3 要求使用名为 `smart_dev` 的 conda 环境，Python 3.11.9。

```bash
conda create -n smart_dev python=3.11.9 -y
conda activate smart_dev
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

复现他人已验证的环境（推荐，含全部间接依赖）：

```bash
pip install -r requirements.lock
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

然后填写 `.env` 中的真实值。**`.env` 已被 `.gitignore` 忽略，严禁提交**（项目文档 8.6 / 9.4）。

需要留意的两项：

| 项 | 说明 |
| --- | --- |
| `JWT_SECRET_KEY` | 必须用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成。非 `dev` 环境下长度不足 32 字符将拒绝启动 |
| `DB_HOST` / `DB_PORT` | 开发机通过 SSH 隧道连云库，填写的是**隧道本端地址与映射端口**，不是云服务器真实地址 |

### 4. 启动 SSH 隧道

数据库与 Redis 均在云服务器上，需先建立隧道：

```bash
ssh -N \
    -L 3308:127.0.0.1:3307 \
    -L 6380:127.0.0.1:6379 \
    <用户名>@<云服务器IP>
```

隧道端口需与 `.env` 中的 `DB_PORT`（默认 3308）与 `REDIS_PORT`（默认 6380）一致。

### 5. 执行数据库迁移

```bash
# 必须在仓库根目录执行
alembic upgrade head

# 查看当前版本
alembic current

# 查看待执行迁移（不实际执行）
alembic upgrade head --sql
```

### 6. 启动服务

```bash
bash scripts/dev.sh
```

或手动启动：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：

- 接口文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health （恒 200，仅表示进程存活）
- 依赖就绪：http://localhost:8000/api/v1/ready （数据库与 Redis 的真实连通状态）

---

## 二、目录结构

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口：lifespan / CORS / 路由注册 / 全局异常处理
│   ├── core/                # 配置、数据库、Redis、安全、权限、响应体、异常、日志等基础能力
│   ├── middlewares/         # 纯 ASGI 中间件：请求上下文、Agent 调用埋点
│   ├── models/              # SQLAlchemy ORM 模型（与数据库表一一对应）
│   ├── schemas/             # Pydantic 请求/响应模型（负责 snake_case ↔ camelCase 转换）
│   ├── services/            # 业务逻辑层，事务边界在此显式控制
│   ├── api/
│   │   ├── deps.py          # 依赖注入：当前用户、角色与权限校验
│   │   └── v1/              # 各模块路由
│   ├── agent/               # LangChain 相关代码：tools / prompts / chains
│   └── utils/               # 分页、时间、上传等通用工具
├── alembic/                 # 数据库迁移（schema 唯一来源）
├── tests/                   # pytest 测试用例
├── docs/                    # 项目文档
├── scripts/                 # 开发脚本
├── requirements.txt         # 顶层依赖（精确锁定）
├── requirements.lock        # 全量依赖锁文件
├── pytest.ini
└── .env.example
```

---

## 三、开发约定（摘要）

完整规范见 `docs/开发流程说明文档.md`。

| 约定 | 说明 |
| --- | --- |
| 接口前缀 | 所有接口以 `/api/v1/` 开头 |
| 响应体 | 统一 `{"code": 200, "message": "操作成功", "data": {}}` |
| 字段命名 | 数据库 `snake_case`，API 传输 `camelCase`（由 `app/core/camel.py` 自动转换） |
| 时间格式 | 统一 `YYYY-MM-DD HH:mm:ss`，全链路本地时间 naive datetime |
| 布尔值 | 统一 `true` / `false`，禁止 0/1 |
| 身份来源 | `userId` / `inspectorId` / `handlerId` 一律从 JWT 解析，**禁止**从请求体或 FormData 传入 |
| 事务边界 | `get_db` 只负责关闭会话；`commit` 由 `services/` 层**显式调用**，忘记 commit 会静默丢数据 |
| 数据库驱动 | 只用异步 `asyncmy`，连接串固定 `mysql+asyncmy://`，禁止 PyMySQL / mysqlclient |
| 迁移 | 必须在本目录执行；连接串从 `.env` 读取，禁止写入 `alembic.ini` |

⚠️ **`services/` 层必须显式 `await session.commit()`**。依赖注入不再自动提交，未提交的写入不会报错但也不会落库。

---

## 四、运行测试

```bash
# 全量测试 + 覆盖率
pytest --cov=app

# 只跑单元与接口测试（默认行为，不需要云库与 Redis）
pytest

# 只跑需要真实外部依赖的集成测试（默认跳过）
pytest -m integration
```

测试默认使用 **SQLite 内存库 + 假 Redis**，无需连接云库即可离线运行，CI 同样如此。

---

## 五、接口清单（本项目负责的模块）

### 模块 9：用户认证与权限

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | 登录，返回 `accessToken` / `refreshToken` / `role` |
| GET | `/api/v1/auth/info` | 获取当前登录用户信息与权限集合 |
| POST | `/api/v1/auth/refresh` | 刷新令牌（轮换旧 refreshToken） |
| POST | `/api/v1/auth/logout` | 登出，使当前 refreshToken 立即失效 |

### 模块 10：系统集成与联调

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/monitor/agent` | Agent 调用监控：总调用数、成功率、平均耗时 |
| GET | `/api/v1/health` | 存活探针 |
| GET | `/api/v1/ready` | 就绪探针（数据库 / Redis 连通状态） |
| — | `/api/v1/mock/*` | Mock 路由，仅在 `DEBUG=true` 时注册，供前端并行开发 |

完整接口契约见 `docs/api.md`。

---

## 六、相关文档

| 文档 | 内容 |
| --- | --- |
| `docs/开发流程说明文档.md` | 环境搭建、目录结构、分层规范、认证与权限设计、Alembic 迁移规范、常见问题 |
| `docs/汇报文档.md` | 模块完成度对照、技术亮点、技术决策与取舍、待确认项、风险登记 |
| `docs/api.md` | API 接口文档 |
| `docs/database.md` | 数据库设计：表结构、索引、DDL 变更 |
| `docs/test.md` | 测试用例文档 |
| `docs/deploy.md` | 部署与联调步骤 |
| `docs/seed.sql` | 种子数据脚本 |
| `开发流程.md` | 项目总规范（仓库根目录） |
