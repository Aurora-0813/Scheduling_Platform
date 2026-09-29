# AI 全感知 · 智能空间与设备综合调度平台 — uni-app 小程序端

按 `docs/开发流程.md` 锁定的技术栈（uni-app / HBuilderX 4.24 / Vue3）开发，
视觉规范来自 `示例样式.html` 的 6 屏小程序原型（M1–M6）。

**零 npm 依赖、零二进制资源**：不需要 `npm install`，HBuilderX 打开即可编译运行。

---

## 一、快速运行

1. HBuilderX 4.24 打开本目录（`frontend-app/miniprogram`）。
2. `manifest.json` → 基础配置 → 填入你自己的**微信小程序 AppID**
   （仓库里留空，AppID 属于账号信息，不入库）。
3. 运行 → 运行到小程序模拟器 → 微信开发者工具。
4. 后端未启动也能跑通全流程（见下方「三、数据通道」）。

> 微信开发者工具里需勾选「详情 → 本地设置 → 不校验合法域名…」，
> 否则 `http://127.0.0.1:8000` 会被拦。`manifest.json` 已设 `urlCheck: false`，
> 但开发者工具的本地设置优先级更高。

### 真机预览

把 `config/index.js` 的 `BASE_URL` 改成电脑的局域网 IP（手机与电脑同一 WiFi）：

```js
export const BASE_URL = 'http://192.168.1.10:8000'   // 换成你电脑的实际 IP
```

### 正式上线

`BASE_URL` 必须是 **https** 域名，并在小程序后台配置 `request` 与 `uploadFile`
合法域名。`http://127.0.0.1` 只适用于开发者工具。

---

## 二、目录结构

```
miniprogram/
├── App.vue                  # 注入全局样式 + onLaunch 恢复登录态
├── main.js                  # createSSRApp 入口
├── manifest.json            # AppID 留空、scope.record 权限、urlCheck:false
├── pages.json               # 12 个页面；navigationStyle:custom；**无原生 tabBar**
├── styles/theme.css         # 设计变量 + 全部全局工具类
├── config/index.js          # BASE_URL / API_MODE / FALLBACK_TO_LOCAL / 录音与图片限制
├── utils/
│   ├── auth.js              # 令牌读写
│   ├── format.js            # 时间与金额（禁用 toISOString）
│   ├── dict.js              # 枚举 → 文案与标签配色
│   ├── normalize.js         # 契约漂移适配（orderId/id、list/items 等）
│   ├── tabs.js              # 底部导航定义（三处共用一份）
│   └── toast.js             # toast / loading / confirm
├── api/
│   ├── request.js           # 网络层核心（见第四节）
│   ├── auth.js  voice.js  image.js  agent.js  orders.js
│   ├── resources.js  inspect.js  messages.js
│   └── mock/local.js        # 本地兜底数据
├── store/                   # user.js / notify.js / agent.js
├── components/              # mp-nav-bar / mp-tab-bar / mp-empty（easycom）
├── tools/                   # 开发期自检脚本（不进包体，见第十节）
└── pages/                   # 12 个页面，见下
```

### 页面清单

| # | 路径 | 说明 | 原型 |
|---|---|---|---|
| 1 | `pages/index/index` | 首页（tab） | M1 |
| 2 | `pages/order/list` | 我的预约（tab） | — |
| 3 | `pages/inspect/index` | 智能巡检（tab） | — |
| 4 | `pages/message/list` | 消息通知（tab） | M6 |
| 5 | `pages/mine/index` | 我的（tab） | — |
| 6 | `pages/login/index` | 登录 | — |
| 7 | `pages/voice/record` | 语音预约 | M2 |
| 8 | `pages/agent/thinking` | Agent 思考链 | M3 |
| 9 | `pages/agent/plan` | 方案确认 | M4 |
| 10 | `pages/space/recognize` | 拍照识场 | — |
| 11 | `pages/inspect/capture` | 拍照巡检 | M5 |
| 12 | `pages/order/detail` | 预约详情 | — |

---

## 三、数据通道（两条开关）

`config/index.js`：

## 三、数据通道（两条开关）

`config/index.js`：

```js
export const API_MODE = 'real'            // 'mock' → /api/v1/mock/*   |   'real' → /api/v1/*
export const FALLBACK_TO_LOCAL = false    // 连不上后端时是否回落到本地内置假数据
```

| 开关 | 现状 | 说明 |
|---|---|---|
| `API_MODE` | `'real'` | 业务路径**一律走真实接口**。后端所有模块都已落地，不再有「只有 mock 占位」的模块。`/api/v1/mock/*` 仍存在（需后端 `DEBUG=true`），但那是给后端自测用的。 |
| `FALLBACK_TO_LOCAL` | `false` | **2026-09-30 由 true 改为 false**，理由见下。 |

### 为什么把本地兜底关掉（原先开着）

它原本是「答辩现场防翻车」（开发流程.md §13.1）：后端挂了也让你能演示完整链路。
但实测下来**代价大于收益**：

1. **它把故障藏起来。** 后端挂了 / 隧道断了 / 大模型 503 —— 页面不但不报错，
   反而显示一份**编造的数据**，而且没有任何标记。演示时看到的是「一切都好」。
2. **它会让假方案变成真订单。** `/agent/schedule` 的兜底数据**没有 orderId**（真实响应有），
   于是 `pages/agent/plan.vue` 判定「后端没建单」→ 转而调 `POST /orders/create`，
   把**编造出来的场地/时段**真的写进了库。
3. **它掩盖了真实契约错误。** 例如场地列表的主键真实字段是 `spaceId`，而兜底数据给的是 `id`
   —— 页面写 `.id` 在兜底态下能跑通、在真实态下**必失败**，
   于是这类错误被一路掩盖到联调最后一天（`pages/inspect/capture.vue` 就是这么坏的）。

需要临时回退（比如演示前想先录一遍界面）时，把 `FALLBACK_TO_LOCAL` 改回 `true` 即可，
`api/mock/local.js` 仍然保留着。

### `auth` 是唯一的例外

后端没有 `/mock/auth/*`，登录与刷新**恒定**走真实 `/api/v1/auth/*`。

⚠️ 2026-09-30 删除了原先的「本地演示身份」：它在后端完全连不上时写入一个假 token
（`'local-demo-token'`）当成登录成功，但那个串不是 JWT，后端下一次请求就判 40102，
用户马上被弹回登录页 —— **连兜底都做不到，只是制造了一次假成功**。
现在登录只有一个结果：拿到真实 JWT，或者如实报错。

---

## 四、网络层必须知道的坑

`api/request.js` 集中处理了下列实测契约，改这个文件前请先读这节。

| 坑 | 处理方式 |
|---|---|
| **HTTP 状态码不恒为 200**（400/401/403/409/500/503 都会真实返回） | **一律按响应体 `code` 分支**，不看 `statusCode` |
| accessToken 30 分钟过期（`40103`） | **单例 Promise 去重**刷新 `/auth/refresh`（轮换制 + 60s 宽限，并发刷新只有一个能成功），成功后自动重放原请求一次 |
| `50301`（Redis 不可用） | **不跳登录页**，只提示稍后重试 |
| 其余 `401xx` | 清 token → 跳登录（3 秒节流，避免并发请求连环跳） |
| 身份标识 | 一律走 `Authorization: Bearer`，**绝不**从请求体传 `userId`（§5.1 / §9.1 防身份伪造） |
| 上传 | 全部 FormData，字段名固定 `file`；图片 ≤5MB 且仅 jpeg/png/webp/bmp |
| 时间 | 一律 `YYYY-MM-DD HH:mm:ss` **本地时间**，`utils/format.js` 自实现——**禁用 `toISOString()`**（带 `Z`，后端不换算时区，东八区会差 8 小时） |
| iOS 解析时间 | `new Date('2026-10-18 14:00:00')` 在 WKWebView 上是 Invalid Date，`parseDateTime()` 统一把 `-` 换成 `/` |
| 金额 | 后端 `MoneyStr` 输出的是**字符串**（`"980.10"`），只做展示，不参与数值运算 |
| 图片 URL | `image/analyze` 的 `imageUrl` 是 `/uploads/...` 相对路径，展示前用 `absoluteUrl()` 拼域名 |
| ES2020 语法 | 全程**不用 `??` 与 `?.`**（部分小程序构建链不降级），用 `utils/normalize.js` 的 `first()` 代替 |

---

## 五、样式还原要点

原型是 390px 宽的设计稿，按 **1px = 2rpx** 统一换算（等价 375px 稿，390px 机型上偏差约 4%）。
`manifest.json` 里 `"transformPx": false`——**不要改**，否则 rpx 会被二次换算。

平台适配（改回去会直接坏样式）：

- **`*` 通配选择器**：WXSS 不支持 → 用 `page{}` + 元素选择器显式重置。
- **`:root`**：不支持 → 主题变量挂在 `page{}` 上。CSS 自定义属性会沿 DOM 树继承，
  所以自定义组件内部同样能取到 `var(--primary)`。
- **`inset` 简写**：低版本 webview 不认 → 一律展开为 `top/right/bottom/left`。
- **裸标签选择器**：原型里的 `h4 / p / b / i / span / div / a` 在小程序里不是组件，
  样式不会命中 → 全部改写成 class（如 `.ai-hero h4` → `.ai-hero .tt`）。
- **`border-image` 渐变边条**：兼容性不稳 → 首页「即将开始」改用实心渐变块。
- **自定义组件样式隔离**：微信自定义组件默认 `styleIsolation: 'isolated'`，
  **`app.wxss` 里的 class 选择器不会作用到组件内部**（只有标签选择器会穿透）。
  因此 `components/` 下的三个组件样式都写全了，不依赖 `theme.css` 的工具类。

### 为什么是自定义 tabBar

微信原生 tabBar 的 `iconPath` **只接受 PNG**，无法用 emoji，选中态也做不出原型里的
渐变与放大。所以 `pages.json` 里**没有 `tabBar` 字段**，改用 `components/mp-tab-bar`
+ `uni.reLaunch`，视觉 1:1 且不引入任何图片资源。

代价：切换 tab 会重建页面（原生 tabBar 会保留各 tab 状态）。本项目可接受——
各 tab 页在 `onShow` 里重新拉数据，反而保证数据新鲜。

### 为什么是自定义导航栏

`globalStyle.navigationStyle: "custom"`，由 `components/mp-nav-bar` 渲染。
高度用 **px 而非 rpx**：导航栏要与微信胶囊按钮垂直对齐，胶囊是物理像素、不随屏宽缩放，
用 rpx 会在宽屏机型上把标题挤进胶囊区域。右侧内边距用
`uni.getMenuButtonBoundingClientRect()` 实时计算，避让胶囊。

---

## 六、已知契约缺口（**未自行发明接口**）

⚠️ **2026-09-30 重核：下面第 2/3/4 条经查证都是错的**（那些接口后端一直都有），
已用删除线标出并给出更正。第 1 条仍然成立。

以下 4 处曾被认为「前后端不一致」，代码里都留了注释与 TODO，**没有自行编造接口或数据**：

1. **Plan 没有价格字段。**
   `app/schemas/agent.py` 的 `Plan` 只有
   `{ spaceId, spaceName, deviceIds, startTime, endTime, reason }`，金额只出现在 `reason`
   散文里。原型 M4 有个大号 `¥ 860`，这里做成**条件渲染**：后端给了价格字段才显示，
   否则不编数字。→ `pages/agent/plan.vue` 的 `priceText`

2. ~~**没有「标记已读」接口。**~~ **（2026-09-30 更正：这句是错的）**
   `PUT /messages/{messageId}/read` 与 `PUT /messages/read-all` **后端一直都有**
   （`backend/app/api/messages.py`）。原实现照着一句错话，把「全部已读」做成了
   「只改前端状态、刷新后复原」，还把那段假说明渲染给用户看。
   现已改为调真实接口落库。→ `api/messages.js` 的 `read()` / `readAll()`、
   `pages/message/list.vue`

3. ~~**没有 `GET /messages/list`。**~~ **（2026-09-30 更正：这句也是错的）**
   `GET /messages` 存在（**裸数组**，支持 `skip/limit`，上限 100），
   消息页原先只调 `GET /messages/unread` —— 而那个接口**只返回计数** `{count}`，
   经 `listOf()` 解出来恒为空数组，于是真实后端下这一页**永远显示「没有未读消息」**，
   首页角标却有数字。
   另外列表项主键是 **`messageId`** 不是 `id`。

4. ~~**没有 `GET /orders/{orderId}`。**~~ **（2026-09-30 更正：这句也是错的）**
   该路由从合并起就在（`backend/app/api/orders.py` 的 `router.get("/{orderId}")`）。
   详情页原先绕道 `GET /orders/my` 拉全量再按 id 过滤，而后端**不支持分页**、
   `pageSize` 是被静默忽略的。现已改为直接调详情接口。

### 另外两处字段漂移，已在 `utils/` 里吸收

- **枚举值对不上**：`mock_data.py` 的 `ORDER_CREATED` 给的是 `status: 1` 配
  `statusText: "已确认"`，而 `docs/database.md` 定义 `order_status = 1` 是「待确认」。
  → `utils/dict.js` 采取**`statusText` 优先、整型字典兜底**的取值顺序，两边都能显示正确文案。
  真实接口落地后应复核此处，届时可只留整型映射。

- **分页字段矛盾**：`docs/api.md` 与全部 Mock 数据用 `list`，但
  `app/utils/pagination.py` 的 `PageResult` 序列化出来是 `items`。
  → `utils/normalize.js` 的 `listOf()` 同时兼容 `list` / `items` / `records` / 裸数组。

### `trace[].actionInput` 是 snake_case

`space_type` / `start_time` / `device_ids`——它是后端 Tool 函数签名的原样回显，与其余
camelCase 字段不同。前端只做整串 JSON 展示，**不按 camelCase 去解析**。
→ `api/agent.js` 的 `formatActionInput()`

---

## 七、本次未做的事

- 不写后端、未改动 `C:\Users\1\Desktop\backend` 的任何文件。
- 未改动 `docs/开发流程.md` 与 `示例样式.html`。
- 不做 PC Web 管理端（§1.4 的 Vue3 + Element-Plus 部分不在本次范围）。
- 不引入 iconfont / 图片资源 / 任何 npm 依赖。
- 列表分页目前只拉第一页（`pageSize` 给得较大），触底加载等后端分页稳定后再补。

---

## 八、状态管理与脚本风格

- **脚本风格**：全量 `<script setup>`（遵循 §7.2）。
  注意 `语音模块集成说明.md` 里的 `record.vue` 是 Options API，本次按原型重做了该页面，
  但**接口契约原样保留**（见下）。
- **状态管理**：用 Vue `reactive` 手写轻量 store（`store/*.js`），按 Pinia 的
  state/actions 形态组织。§3.2 的 Pinia 属于 Web 前端（Vue3）那一栏，未约束小程序端；
  且 HBuilderX 工程模式下没有 `node_modules`，引入 Pinia 需先 `npm install`，
  会破坏「打开即运行」。日后若统一换 Pinia，只需替换 `store/` 下的实现。

---

## 九、语音模块（与郑宇豪已对齐的契约）

**接口契约一字未改**，页面按原型 M2 重做：

```
POST /voice/asr     FormData 字段名固定 file  → { text }
POST /voice/format  { rawText }               → { formattedText, keywords[] }
```

录音参数取自 `config/index.js` 的 `RECORD_OPTIONS`：
**wav / 16000 采样率 / 单声道 / 最长 60 秒**，与百度 ASR 一致，**勿改**。

相比原 `record.vue` 的差异：

- 页面按原型重做（呼吸圆环 + 波形 + 语义高亮 + 约束 chip）；
- 接口收敛到 `api/voice.js` 统一管理；
- 语义高亮的四种颜色由 `keywords[]` 启发式归类（后端只给关键词，不给类型）；
- 增加了「手动输入」兜底：麦克风权限被拒或不便说话时，直接输入文字走同一个
  `/voice/format`。

---

## 十、自检

`tools/` 下有两个校验脚本，**只给开发期用，不进小程序包体**：

```bash
# 1. 静态校验（零依赖，直接跑）
#    页面声明与文件一一对应、路由目标存在、@/ 导入可解析、
#    easycom 组件齐全、无禁用语法与裸标签选择器、tab 页约定
node tools/check.js

# 2. SFC 编译（首次需装一次依赖，装在 tools/ 下并被 .gitignore 覆盖）
npm i --prefix tools @vue/compiler-sfc@3
node tools/compile.js
```

两项目前均通过（16 个 `.vue` / 12 个页面）。

> 这两个脚本只是**本地自检**，不替代真机验证——
> 自定义导航栏与胶囊的避让、录音权限、`uni.reLaunch` 切 tab 的手感，
> 这些只能在微信开发者工具和真机上确认。


---

## 十一、模块 3 遗留文件说明（2026-09-28 合并后）

合并 `origin/integrate/module3` 时，本目录同时落进了**模块 3 版小程序**的一批文件。
它们与本套实现**不兼容**（鉴权与网络层的函数名都不同），因此**未注册进 `pages.json`**，
当前是死代码，仅为留档保留：

| 文件 | 与本文档实现的冲突点 |
| --- | --- |
| `utils/request.js` | 与 `api/request.js` 是两套网络层；本套页面一律用后者 |
| `utils/ws.js` | `App.vue` 不调用它；且它 import 的是 Pinia 版 `useNotifyStore` |
| `api/notify.js`、`api/reserve.js` | import 的是 `@/utils/request`；本套同名文件用 `@/api/request` |
| `api/agent.js` | **已改**用 `@/api/request.js`（2026-09-28 复核），但仍被未注册的 `pages/agent/schedule.vue` 引用，故留在本表 |
| `pages/reserve/*`、`pages/notify/*`、`pages/agent/schedule.vue` | 6 个页面未注册；功能已由本套 `pages/order/*`、`pages/message/*`、`pages/agent/*` 覆盖 |
| `components/StatusTag.vue`、`uni.scss` | 模块 3 版样式与组件；本套用 `styles/theme.css` |

**处理方式**：合并时以本套（12 页 uni-app 版）为唯一注册实现，逐文件冲突全部取本套版本。
上表文件待模块 3 负责人确认后再删除。

> ⚠️ 维护提醒：由于两套的 `utils/auth.js`、`store/notify.js` 同名而 API 不同，
> **不要**把这些遗留文件逐个"复活"——它们与 `pages.json` 里注册的页面不是同一套。
