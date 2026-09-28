# 部署文档 —— 移动端预约与通知模块

> 部署环境遵循《开发流程》第十二章；本模块为后端 + 小程序双端。

## 一、环境要求（§12.1）

| 组件 | 版本/规格 |
| ---- | --------- |
| 操作系统 | Ubuntu 22.04（阿里云 ECS 2核2G） |
| Python | 3.11.9 |
| MySQL | 8.0.39（云服务器，地址/端口见 `.env`，库 `smart_scheduler_dev`） |
| 反向代理 | Nginx 1.26.2 |
| 小程序 | HBuilderX 4.24+ / 微信开发者工具 |

## 二、配置说明（§3.4 / §3.5 / §6.1）

1. 进入 `backend/`，复制模板：`cp .env.example .env`
2. 在 `.env` 中填写配置。参数与团队公用 `backend/.env` 完全对齐，两边连同一个云库
   （真实值严禁提交，§9.4）：

```env
# 本地经 SSH 隧道连服务器 MySQL：ssh -L 3308:127.0.0.1:3307 root@<服务器IP> -N
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

> 连接串由 DB 五项拼接为 `mysql+asyncmy://...`（§3.4）；`AGENT_URL` 为空时走内置 mock 调度器，接入队友 Agent 服务后填写。
> 注意 `DB_PORT` 为**隧道本地端口 3308**（转发到服务器 3307），与公用后端的 `.env` 保持一致。

## 三、后端启动

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt                     # 版本锁定（§3.1）
python seed.py                                      # 造演示数据（连云库）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 接口文档（Swagger）：`http://<host>:8000/docs`
- 生产建议：`gunicorn -k uvicorn.workers.UvicornWorker -w 2 app.main:app`，Nginx 反代到 8000 端口。

## 四、小程序端部署

1. HBuilderX 打开 `miniprogram/`
2. 修改 `utils/request.js` 中 `BASE_URL` 为后端公网地址（如 `https://api.example.com`）
3. 在微信公众平台配置合法 request 域名与 socket 合法域名（`wss://`）
4. 编译上传、提交审核发布

## 五、验证清单

- [ ] 后端能连云库并 `python seed.py` 成功
- [ ] `GET /api/v1/resources/spaces` 返回统一响应体 `{code, message, data}`
- [ ] 小程序预约/确认/取消/通知全链路跑通
- [ ] WebSocket `/ws/notify` 实时推送正常
