import axios from 'axios'
import { ElMessage } from 'element-plus'

import { tokenStorage } from './auth'

// 《开发流程》8.8：true 时业务接口走 /api/v1/mock/*，false 走真实接口 /api/v1/*
//
// ⚠️ **2026-09-29 修复：原来这里只有一行 `=== 'true'`，会静默失败。**
//
// `VITE_USE_MOCK` 由 `frontend/.env.development` / `.env.production` 提供，
// 而 `.env.*` 在仓库里是 **gitignore 的**（根 `.gitignore:8`）—— 新克隆的仓库里
// **一个都不存在**，于是 `undefined === 'true'` 恒为 false，实际走的是**真实接口**，
// 而 `frontend/README.md` 的「Mock 开关说明」却写着开发环境走 mock。
// 照 README 做的人会以为自己在用示例数据，其实在打通真库，**且没有任何提示**。
//
// 现在的口径：**行为不变**（没设就是真实接口，不制造行为变更），
// 但开发模式下会把「实际用了哪个」打出来，不再静默。
const RAW_USE_MOCK = import.meta.env.VITE_USE_MOCK
export const USE_MOCK = RAW_USE_MOCK === 'true'

if (import.meta.env.DEV) {
  const mode = USE_MOCK
    ? 'mock（/api/v1/mock/*，写死的示例数据，**不能用于验收**）'
    : 'real（/api/v1/*，真实接口）'
  if (RAW_USE_MOCK === undefined) {
    console.warn(
      `[request] VITE_USE_MOCK 未设置，业务接口当前走 ${mode}。\n` +
        '           要切到 mock：在 frontend/.env.development 里写 VITE_USE_MOCK=true，然后重启 npm run dev。\n' +
        '           该文件被 .gitignore 排除，需要自己建 —— 见 frontend/README.md「Mock 开关说明」。',
    )
  } else {
    console.info(`[request] 业务接口当前走 ${mode}`)
  }
}

// 接口前缀（相对路径 = 走 Vite 的 /api 代理；绝对地址 = 直连后端）。
//
// 默认 `/api/v1` 是**相对路径**，浏览器会打到 dev server（5173），
// 由 `vite.config.js` 的 server.proxy 转发到 http://127.0.0.1:8000 ——
// **这是正常且推荐的做法**：同源、不经 CORS。DevTools 里看到请求 URL 是
// 5173/api/v1/... 并不代表配错了；后端返回的 404/400 同样会以 5173 开头显示。
//
// 要改成直连后端（比如把 dist 部署到别处、或不想依赖 dev server 的代理）：
//   在 frontend/.env.development 里写
//     VITE_API_BASE=http://127.0.0.1:8000/api/v1
//   此时浏览器直连 8000，需要后端 CORS 放行来源（backend/.env 的 CORS_ORIGINS）。
const API_PREFIX = import.meta.env.VITE_API_BASE || '/api/v1'

// 认证相关错误码（后端 auth.py 契约）
// 需要「清会话并回登录页」的认证码。
//
// ⚠️ **2026-09-29 补 40101（TOKEN_MISSING）**：原先漏了它，
// 于是「根本没带令牌」这种情况既不续期、也不回登录页，
// 只弹一句通用提示，用户卡在一个永远刷不出数据的页面上。
//
// 40107（CREDENTIALS_INVALID，密码错误）**刻意不在列表里** ——
// 那是登录页自己要展示的错误，把它也算进来会把用户从登录页再踢回登录页。
const AUTH_ERROR_CODES = [
  40100, // UNAUTHORIZED 未登录
  40101, // TOKEN_MISSING 缺少令牌
  40102, // TOKEN_INVALID
  40103, // TOKEN_EXPIRED
  40104, // TOKEN_TYPE_INVALID
  40105, // TOKEN_REVOKED
  40106, // REFRESH_TOKEN_INVALID
  40108, // USER_DISABLED
  40109, // ACCOUNT_LOCKED
]

// 单例刷新 Promise（后端明确要求：同一时刻只允许一个刷新请求）
let refreshPromise = null

function isAuthUrl(url = '') {
  return url.includes('/auth/login') || url.includes('/auth/refresh') || url.includes('/auth/info')
}

async function redirectToLogin() {
  tokenStorage.clear()
  const routerModule = await import('@/router')
  await routerModule.default.push('/login')
}

function doRefresh() {
  if (!refreshPromise) {
    refreshPromise = realHttp
      .post('/auth/refresh', { refreshToken: tokenStorage.getRefreshToken() })
      .then((data) => {
        tokenStorage.setTokens(data.accessToken, data.refreshToken)
        return data
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

function createInstance(baseURL) {
  // ⚠️ **默认超时 20 秒对「要等大模型」的接口不够（2026-09-29 修）。**
  //
  // 实测：`GET /dashboard/report` 要走一次真模型，**26.7 秒**；
  //       `POST /agent/schedule` 更是 **39 秒**。
  // 20 秒会在中途把请求掐断，浏览器报「请求超时」，
  // **而后端其实还在正常处理、稍后也会正常返回** —— 看起来像后端挂了，
  // 实际是前端等不及。
  //
  // 取 **240 秒**：必须**大于后端**的限制，否则前端会在后端返回前先断开。
  // 后端上限：`AGENT_TIMEOUT=180`（Agent 整轮思考）、`LLM_TIMEOUT=120`（其它 AI 调用）。
  // 取 240 = 180 + 60 秒余量，覆盖最慢的 `/agent/schedule`；
  // 看板报告另按 `LLM_TIMEOUT` 单独放宽，见 `api/dashboard.js`。
  const instance = axios.create({ baseURL, timeout: 240000 })

  // 请求拦截：自动带 Authorization: Bearer {token}
  instance.interceptors.request.use((config) => {
    const token = tokenStorage.getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  // 响应拦截：统一解包 { code, message, data }
  instance.interceptors.response.use(
    (response) => {
      const body = response.data
      if (body === null || typeof body !== 'object' || !('code' in body)) {
        return body
      }
      if (body.code === 200) {
        // ⚠️ **2026-09-30 新增 `passMessage` 开关（默认关闭，行为不变）。**
        //
        // 默认只回 `data` 是**有意**的（绝大多数调用方只关心 data）。
        // 但有一类接口「降级成功」也是 HTTP 200 + code=200，
        // 而**可读原因只存在于 `message` 里**，data 是个空壳：
        //   `POST /agent/schedule` 在「模型没交出方案」「模型输出格式错乱」时
        //   返回 `data.plan = null` + `message = 原因+修改建议`
        //   （见 backend/app/schemas/agent.py 的 ScheduleData 降级口径表）。
        // 只回 data 的话，前端只能渲染一个空白页，用户完全不知道为什么没方案。
        //
        // 所以给需要它的调用方一个**显式**开关，而不是全局改返回值形状 ——
        // 全局改会静默破坏所有既有调用方的取值方式。
        if (response.config && response.config.passMessage) {
          return { data: body.data, message: body.message }
        }
        return body.data
      }
      return handleBizError(body, response, instance)
    },
    (error) => {
      // ⚠️ **2026-09-29 修复：非 2xx 响应不能被当成「连不上」。**
      //
      // 后端**不保证 HTTP 200** —— `docs/api.md` 明写「400/401/403/404/409/500/503
      // 都会真实出现，Pydantic 校验失败还是 400 而非 FastAPI 默认的 422」。
      // 而 axios 默认对非 2xx 走 reject，于是 401 这类**带业务码的正常错误响应**
      // 全部落进这里，被一律报成「网络请求失败，请确认后端已启动」。
      //
      // 实测代价：令牌一失效，除看板（`/dashboard/*` 无需鉴权）之外的所有页面
      // 都显示「后端连接失败」，把「该重新登录」误导成「后端挂了」，排查方向完全跑偏。
      //
      // 现在：响应体只要带 `code`，就说明**后端答了话**，走与成功分支同一套业务处理
      // （40103 自动续期重放、其余认证码清会话回登录页、业务错误弹真实 message）。
      const body = error.response && error.response.data
      if (body && typeof body === 'object' && 'code' in body) {
        return handleBizError(body, error.response, instance)
      }

      // 到这才算**真的连不上**：没有 response（网络断开 / 后端没起），或请求超时。
      const config = error.config || {}
      const silent = isAuthUrl(config.url) || config._silent
      if (!silent) {
        ElMessage.error(
          error.code === 'ECONNABORTED'
            ? '请求超时，后端可能正在处理复杂任务（如 AI 调度），请稍后重试'
            : '网络请求失败，请确认后端已启动（127.0.0.1:8000）',
        )
      }
      return Promise.reject({ code: -1, message: error.message, error })
    },
  )

  return instance
}

async function handleBizError(body, response, instance) {
  const { code, message } = body
  const config = response.config

  // 40103 令牌过期：刷新一次后重放原请求
  if (code === 40103 && !config._retried) {
    config._retried = true
    try {
      await doRefresh()
      config.headers.Authorization = `Bearer ${tokenStorage.getAccessToken()}`
      return await instance(config)
    } catch {
      if (!isAuthUrl(config.url)) {
        ElMessage.error('登录已过期，请重新登录')
        await redirectToLogin()
      }
      return Promise.reject(body)
    }
  }

  // 其他认证类错误：登录/刷新接口自己处理，其余清会话回登录页
  if (AUTH_ERROR_CODES.includes(code)) {
    if (!isAuthUrl(config.url)) {
      ElMessage.error(message || '认证失败，请重新登录')
      await redirectToLogin()
    }
    return Promise.reject(body)
  }

  // 权限不足及其余业务错误：弹提示
  if (!isAuthUrl(config.url)) {
    ElMessage.error(message || '请求失败')
  }
  return Promise.reject(body)
}

// 真实接口实例（登录/用户信息/监控等真实路由）
export const realHttp = createInstance(API_PREFIX)

// 业务接口实例：mock 开关切换 baseURL，业务代码无需改动
export const bizHttp = createInstance(USE_MOCK ? `${API_PREFIX}/mock` : API_PREFIX)

export default realHttp
