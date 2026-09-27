# 移动端预约与通知模块

「AI 全感知·智能空间与设备综合调度平台」——移动端预约与通知模块（模块3，负责人蔡玉礼）。

双端自包含全栈模块，严格对齐《开发流程》：统一 `/api/v1/` 前缀、`{code, message, data}` 响应体、camelCase 字段、云服务器 MySQL、异步驱动 asyncmy、版本锁定。可演示「创建预约 → 确认/取消 → 实时收通知 → Agent 智能预约」完整闭环。

## 技术栈（§3.2）

| 层 | 选型 |
|---|---|
| 小程序端 | Uni-app 3.0.x（Vue3 组合式 API）+ Pinia |
| 后端 | Python 3.11 + FastAPI 0.115.0 + SQLAlchemy 2.0.35（异步） |
| 数据库 | 云服务器 MySQL 8.0.39（连接信息见 `.env`，驱动 asyncmy） |
| 实时通知 | WebSocket + 微信订阅消息（封装占位） |
| Agent | `agent_client` 服务层（mock + 真实接口占位） |

## 目录结构（§8.5）

```
weix/
├── backend/            # FastAPI 后端（app/api|models|schemas|services|agent|core）
├── miniprogram/        # Uni-app 小程序端（pages|components|store|api|utils）
├── docs/               # api.md / database.md / deploy.md / test.md
├── .gitignore
└── README.md
```

## 运行步骤

### 1. 后端

**必须用 Python 3.11**，用独立 venv（不要装进全局环境）：

```bash
cd backend
python3.11 -m venv .venv                 # 3.13 装不上 asyncmy，见下方说明
.venv/Scripts/activate                   # Windows；macOS/Linux 用 source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                     # 填写配置（§6.1，严禁提交 .env）
python seed.py                           # 造演示数据
uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000/docs 用 Swagger 验证
```

> **为什么锁 3.11**：`asyncmy==0.2.10` 只发到 cp312，**没有 cp313 轮子**。在 Python 3.13 上
> pip 会退化成从源码编译，Windows 无 MSVC 时报
> `Failed to build 'asyncmy' when installing build dependencies`（长得像网络问题，其实是缺编译器）。

> 配置参数与团队公用 `backend/.env` 对齐（同一云库）：本地经 SSH 隧道连接，
> `DB_HOST=127.0.0.1`、`DB_PORT=3308`（隧道本地端口，转发到服务器 3307）。
> 隧道命令：`ssh -L 3308:127.0.0.1:3307 root@<服务器IP> -N`

#### 跑测试

```bash
cd backend
.venv/Scripts/python -m pytest -q                        # 80 个用例
.venv/Scripts/python -m pytest --cov=app                 # 覆盖率（当前 100%）
```

用例跑在临时 SQLite 上，**不会碰云库**。覆盖率依赖 `.coveragerc` 的
`concurrency = thread,greenlet`，原因见 `docs/test.md` 附二 —— 删掉会让数字假性偏低。

### 2. 小程序端

1. HBuilderX 打开 `miniprogram/`
2. 修改 `utils/request.js` 中 `BASE_URL` 指向后端（本地默认 `http://127.0.0.1:8000`，上线改 https 域名）
3. 运行到微信开发者工具

## 完整闭环演示

1. `智能预约` tab 提交需求 → 看 Agent 思考过程 → 确认方案（落库 agentRequest/agentTrace）
2. `预约` tab 出现新单（待确认）→ 确认 / 取消
3. `通知` tab 收到通知推送 + 未读角标

## 关键约定

- 接口前缀 `/api/v1/`，统一响应体 `{code, message, data}`，camelCase 字段，时间 `YYYY-MM-DD HH:mm:ss`（§5）
- 数据库统一云 MySQL，异步驱动 asyncmy（连接串 `mysql+asyncmy://`），连接从 `.env` 读取，禁止硬编码提交（§3.4/§6.1/§9.4）
- 身份一律从 JWT（演示 `X-User-Id`）解析，请求体不传 `userId`（§5.1）
- 预约状态 `order_status` 为 INT（1待确认/2已确认/3已取消/4已完成），变更必须经 `state_machine.py`
- Agent 经 `agent_client` 单一入口，未配置 `AGENT_URL` 走 mock；接入队友模块后设置 `AGENT_URL`
- 语音 ASR / 图像识别：本模块只做「入口 + 上传 + 占位回显」，真实 API 由队友模块接入
