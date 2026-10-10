import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

import { tokenStorage } from './auth'
import { stashDurableOperationAsPending } from './pendingAction'

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

// 登录失效的一次性提示。并发 401 可能同时进来，必须去重，否则弹一叠框。
let sessionNoticeShown = false

/**
 * 取当前路径（用于登录后回跳）。
 *
 * 路由是 `createWebHistory`（非 hash 模式），所以 `pathname + search` 就是路由地址。
 * 登录页自己不进回跳（否则会 `redirect=/login` 死循环）。
 */
function currentPathForRedirect() {
  const path = `${window.location.pathname}${window.location.search}`
  if (path.startsWith('/login')) return ''
  return path
}

/**
 * 会话失效时的统一处置：**先告知用户，再清会话回登录页并记住来路**。
 *
 * ⚠️ 2026-10-09 改。原来是静默的：
 *     `tokenStorage.clear()` + `router.push('/login')`
 *   两个问题：
 *     1. **静默被踢**。用户只看到页面突然变成登录页，不知道发生了什么。
 *        更糟的是：如果被踢时正有一个**长任务刚成功**（比如 25 秒的
 *        `/agent/schedule` 已把订单落库），用户完全不知道自己到底成功没有。
 *     2. **不回跳**。登录后一律落到 `/agent`（`router` 的默认 redirect），
 *        之前在看哪个页面就丢了。
 *   现在：告知 + 记住来路；登录页已支持 `?redirect=`，回来后即恢复原页。
 *
 * 返回 Promise：调用方 `await` 它，保证跳转在用户确认之后发生。
 */
async function redirectToLogin(reason) {
  tokenStorage.clear()

  // 先把「被打断的动作」记下来，再跳转。
  // 顺序很重要：跳转之后内存里的在途标记可能已被清掉，
  // 而恢复卡需要的是**持久化后的**那条记录。
  stashDurableOperationAsPending(reason)

  if (!sessionNoticeShown) {
    sessionNoticeShown = true
    try {
      await ElMessageBox.alert(reason || '登录状态已失效，需要重新登录。', '会话已过期', {
        confirmButtonText: '重新登录',
        type: 'warning',
        // 不可点遮罩关闭：这是一次必须处理的跳转，避免用户以为"关掉就没事了"
        closeOnClickModal: false,
        showClose: false,
      })
    } catch {
      // 用户按 ESC 等导致 reject —— 仍然继续跳转，绝不把人留在失效页面上
    }
  }

  const routerModule = await import('@/router')
  const back = currentPathForRedirect()
  await routerModule.default.push({
    path: '/login',
    query: back ? { redirect: back } : {},
  })
  // 跳转完成后再放开去重标记：下次会话失效（新一轮登录之后）仍要提示
  sessionNoticeShown = false
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

// ------------------------------------------------------------------
// 主动预刷新：让长任务不再撞上「令牌中途过期」
// ------------------------------------------------------------------

/**
 * 解出 JWT 的 `exp`（秒级时间戳）。解不出返回 null，**绝不抛异常**。
 *
 * 为什么自己解而不是问后端：accessToken 本来就是 JWT（`tokenStorage` 里存着），
 * `exp` 是标准声明，**本地就能读**——不需要新增接口、不需要改后端、也不占一次网络往返。
 *
 * ⚠️ 只用于「提前续期」这一件事，**不做任何安全判断**：
 * 真正是否有效一律以服务端返回为准（签名校验在服务端）。
 * 前端解出来的 exp 仅是个提示值。
 */
export function decodeJwtExp(token) {
  if (!token || typeof token !== 'string') return null
  const parts = token.split('.')
  if (parts.length !== 3) return null
  try {
    // JWT 用的是 base64url，`atob` 只认标准 base64，先补回 +/ 与 padding
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const json = decodeURIComponent(
      atob(padded)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    )
    const exp = JSON.parse(json).exp
    return typeof exp === 'number' ? exp : null
  } catch {
    return null
  }
}

/** 当前 accessToken 还剩多少秒；解不出或没令牌返回 null（=未知，不干预） */
export function accessTokenRemainingSeconds() {
  const exp = decodeJwtExp(tokenStorage.getAccessToken())
  if (exp === null) return null
  return exp - Math.floor(Date.now() / 1000)
}

/**
 * 长任务之前的**主动续期**。
 *
 * ⚠️ 背景（真实故障，2026-10-09 实测）：`POST /agent/schedule` 跑 **25 秒**
 *    （慢模型可到 105 秒），而 accessToken 只有 30 分钟。令牌若在这期间过期：
 *      1. 调度**成功**返回，订单已按「待确认」落库（后端行为正确）
 *      2. 紧接着的前端调用 401 → 续期也失败 → 用户被踢到登录页
 *      3. 用户重新登录后**上下文全丢**，不知道自己刚才到底成功没有
 *    根因是「长任务与令牌寿命赛跑」，所以修法是**开跑前先把令牌续上**。
 *
 * 判定阈值取 **120 秒**：后端 `AGENT_TIMEOUT=180`，剩余时间必须**大于任务时长**
 * 才有意义。120 秒是「够跑完常规调度（实测 25 秒）、又不至于每次都刷新」的折中。
 *
 * ⚠️ 失败时**只返回 false，不跳登录页**：本函数是「尽力而为的优化」，
 *    不该自己劫持用户会话。真正的 401 仍由 `handleBizError` 按原逻辑处理
 *    （那时才弹提示、才跳登录），口径不重复。
 *
 * @param {number} [minSeconds] 剩余多少秒以内就刷新，默认 120
 * @returns {Promise<boolean>} 是否已处于「足够新鲜」的状态
 */
export async function ensureFreshToken(minSeconds = 120) {
  const remain = accessTokenRemainingSeconds()
  if (remain === null) {
    // 解不出 exp（非 JWT / 无令牌）→ 不干预，让正常流程去处理
    return true
  }
  if (remain > minSeconds) return true

  console.info(
    `[request] accessToken 仅剩 ${remain}s（阈值 ${minSeconds}s），长任务前主动续期`,
  )
  try {
    await doRefresh()
    return true
  } catch {
    return false
  }
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
        // 续期都失败了，只能重登。提示语特意点明「长任务可能已成功」——
        // 见 redirectToLogin 的说明：调度类请求跑几十秒，被踢时用户最需要知道的
        // 就是「我刚才那件事到底成没成」。
        await redirectToLogin(
          '登录状态已过期，且自动续期失败，需要重新登录。\n' +
            '如果你刚提交过耗时的操作（例如 AI 调度，最长可能跑 1~3 分钟），' +
            '它可能已经成功完成 —— 登录后请先查看结果，避免重复提交。\n' +
            '登录后会回到你刚才所在的页面。',
        )
      }
      return Promise.reject(body)
    }
  }

  // 其他认证类错误：登录/刷新接口自己处理，其余清会话回登录页
  if (AUTH_ERROR_CODES.includes(code)) {
    if (!isAuthUrl(config.url)) {
      await redirectToLogin(message || '登录状态已失效，需要重新登录。\n登录后会回到你刚才所在的页面。')
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
