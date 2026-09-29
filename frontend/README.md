# PC Web 管理端（frontend）

「AI全感知·智能空间与设备综合调度平台」的 **PC Web 管理端**，负责人：郑宇豪。

## 技术栈（版本按《开发流程》3.2 锁定，精确版本，无 `^`/`~`）

- Vue 3.4.38 + Vite 5.4.8
- Element-Plus 2.8.4（UI 组件库）
- ECharts 5.5.1（图表）
- FullCalendar 6.1.15（预约日历）
- Axios 1.7.7（HTTP 请求）
- Pinia 2.2.2（状态管理）+ Vue Router 4.4.5（路由）

## 页面清单（对应原型 1.html 的 PC 端 6 屏）

| 路由 | 页面 | 数据来源 |
|---|---|---|
| `/login` | 登录页 | `POST /auth/login` |
| `/dashboard` | AI 数据洞察（KPI、图表、AI 报告） | `/dashboard/stats`、`/dashboard/report` |
| `/calendar` | 预约日历 + AI 软冲突侧栏 | `/orders/my`、`/conflicts/scan` |
| `/resources` | 资源与设备管理（场地/设备两个标签页） | `/resources/spaces`、`/resources/devices` |
| `/inspect` | AI 巡检与维修工单 | `/inspect/submit`、`/tickets/list` |
| `/conflicts` | 冲突预警 + 智能通知文案 | `/conflicts/scan`、`/notify/generate` |
| `/monitor` | Agent 监控 + 思考链可视化 | `/monitor/agent`、`/agent/schedule` |
| `/profile` | 当前用户与权限 | `GET /auth/info` |

## 怎么跑起来（大白话步骤）

1. **先启动后端**（mock 数据由后端提供，需要后端 `.env` 里 `DEBUG=true`）：

   ```
   cd backend
   conda run -n smart_dev uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. **再启动前端**（本目录）：

   ```
   cd frontend
   npm install      # 第一次需要，以后不用
   npm run dev
   ```

3. 浏览器打开终端里显示的地址（默认 http://127.0.0.1:5173）。

## Mock 开关说明

开关是 `VITE_USE_MOCK`，由 `frontend/.env.development`（开发）与
`frontend/.env.production`（构建）提供。

> ⚠️ **这两个文件仓库里没有。** 根 `.gitignore:8` 的 `.env.*` 把它们排除了，
> 需要**各自在本地建**。建之前 `VITE_USE_MOCK` 是 `undefined`。

| `VITE_USE_MOCK` | 业务接口实际走的 baseURL | 什么时候用 |
| --- | --- | --- |
| `true` | `/api/v1/mock/*`（写死的示例数据） | 后端某模块还没做完时先开工 |
| `false` | `/api/v1/*`（真实接口） | 联调、验收、演示 |
| **未设置** | `/api/v1/*`（真实接口）—— 与 `false` 完全相同 | ⚠️ **这是默认值，最容易误判** |

**未设置时走的是真实接口，不是 mock。** 开发模式下 `src/utils/request.js` 会在
控制台打一条告警说明当前模式，不会静默。

要切 mock：

```bash
echo "VITE_USE_MOCK=true" > frontend/.env.development   # Windows: 用编辑器新建同名文件
# 改完需重启 npm run dev 才生效
```

- 切换只改这一个常量，业务代码不用动。
- mock 数据是写死的常量，不能增删改，**不能用于验收**。
- `/monitor` 页的「查看智能调度思考链」**永远走 mock**（`/mock/agent/schedule`），
  与这个开关无关 —— 因为真实接口有副作用（会在后端锁资源、落一条待确认订单），
  监控页不该调它。见 `src/api/monitor.js` 的 `agentScheduleMock`。

## 目录结构

```
frontend/
├── index.html
├── vite.config.js          # Vite 配置 + /api 代理到 8000
├── src/
│   ├── main.js             # 入口（注册 ElementPlus、Pinia、路由）
│   ├── App.vue
│   ├── api/                # 所有后端请求统一放这里
│   ├── layouts/            # 主框架（侧边栏 + 顶栏）
│   ├── router/             # 路由 + 登录守卫
│   ├── store/              # Pinia 状态
│   ├── styles/             # 全局样式与主题
│   ├── utils/              # axios 封装、token 存储
│   └── views/              # 各业务页面
└── public/
```

## 已知说明

- 真实登录需要后端连通 MySQL（SSH 隧道 + 数据库账号）。数据库未连通时，
  mock 模式下点击登录会自动进入演示会话，方便浏览全部页面。
- `package-lock.json` 必须提交；`node_modules/`、`dist/` 已在 `.gitignore`。
