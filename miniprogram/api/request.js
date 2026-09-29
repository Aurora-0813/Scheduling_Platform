/**
 * 统一请求层
 *
 * 这一层集中处理后端契约里最容易踩的坑，业务模块只管 path 与出入参：
 *
 *  1. 后端 HTTP 状态码**不恒为 200**（400/401/403/404/409/500/503 都会真实出现，
 *     Pydantic 校验失败还是 400 而非 FastAPI 默认的 422）。因此一律只认
 *     body.code，绝不按 res.statusCode 分支。
 *  2. 成功判定严格为 body.code === 200，业务数据在 body.data 里。
 *  3. accessToken 只有 30 分钟，过期错误码 40103 → 单例 Promise 去重后续期并重放。
 *     后端 refresh 是**轮换制**（旧 token 换新后立即失效，仅 60 秒宽限），
 *     并发刷新时只有一个能成功，所以必须复用同一个在途 Promise。
 *  4. 50301 是 Redis 不可用（refresh/logout 受影响），**不是登录失效**，
 *     不能清 token 也不能跳登录页。
 *  5. 连不上后端时按 FALLBACK_TO_LOCAL 回落到本地内置数据；业务错误不兜底。
 */
import {
  BASE_URL,
  API_PREFIX,
  MOCK_PREFIX,
  API_MODE,
  FALLBACK_TO_LOCAL,
  REQUEST_TIMEOUT,
} from '@/config/index.js'
import { getAccessToken, getRefreshToken, setTokens, clearTokens } from '@/utils/auth.js'
import { toast } from '@/utils/toast.js'

/** 业务错误码 */
const CODE = {
  OK: 200,
  /** accessToken 过期，应触发续期 */
  ACCESS_EXPIRED: 40103,
  /** 用 refreshToken 调业务接口 */
  REFRESH_AS_ACCESS: 40104,
  /** Redis 不可用 —— 服务问题，不是登录问题 */
  REDIS_DOWN: 50301,
}

/** 需要清登录态并跳登录页的错误码 */
const AUTH_FAIL_CODES = [
  40100, // 用户已删除
  40101, // 未携带 token
  40102, // 签名/结构错误
  40104, // 拿 refreshToken 调业务接口
  40108, // 账号被禁用
  40302, // 未分配角色
]

function buildUrl(path, useMock) {
  return BASE_URL + (useMock ? MOCK_PREFIX : API_PREFIX) + path
}

function buildHeader(extra, auth) {
  const header = { 'Content-Type': 'application/json', ...extra }
  if (auth) {
    const token = getAccessToken()
    if (token) header.Authorization = `Bearer ${token}`
  }
  return header
}

/** 后端 5xx / 服务级错误码 → 认为服务不可用，可触发本地兜底 */
function isServerDown(statusCode, code) {
  if (statusCode >= 500) return true
  return typeof code === 'number' && code >= 50000 && code !== CODE.REDIS_DOWN
}

function makeError(message, kind, extra = {}) {
  const err = new Error(message)
  err.kind = kind
  Object.assign(err, extra)
  return err
}

// ------------------------------------------------------------------
// 登录态续期：单例 Promise 去重
// ------------------------------------------------------------------
let refreshPromise = null

function doRefresh() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return Promise.reject(makeError('无 refreshToken', 'AUTH'))

  return new Promise((resolve, reject) => {
    uni.request({
      // refresh 不需要 Authorization 头
      url: BASE_URL + API_PREFIX + '/auth/refresh',
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { refreshToken },
      // 续期是「快进快出」的一次调用，不该跟着主请求的 240 秒一起等 ——
      // 后端不可达时要尽快失败，否则用户会在一个已经失效的页面上干等 4 分钟。
      timeout: 15000,
      success: (res) => {
        const body = res.data
        if (body && body.code === CODE.OK) {
          setTokens(body.data)
          resolve(body.data)
        } else {
          reject(makeError((body && body.message) || '登录已过期', 'AUTH', { code: body && body.code }))
        }
      },
      fail: () => reject(makeError('网络请求失败', 'NETWORK')),
    })
  })
}

/**
 * 续期 accessToken。
 * 并发调用会复用同一个在途请求 —— 后端轮换制下并发刷新只有一个能成功。
 */
function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = doRefresh()
    // 无论成功失败都要释放，否则后续请求会一直复用一个已 settle 的 Promise
    refreshPromise.then(
      () => {
        refreshPromise = null
      },
      () => {
        refreshPromise = null
      },
    )
  }
  return refreshPromise
}

// ------------------------------------------------------------------
// 登录失效跳转（加节流，避免多个并发请求同时跳转）
// ------------------------------------------------------------------
let lastRedirectAt = 0

function redirectToLogin() {
  const now = Date.now()
  if (now - lastRedirectAt < 3000) return
  lastRedirectAt = now
  uni.navigateTo({ url: '/pages/login/index' })
}

// ------------------------------------------------------------------
// 本地兜底
// ------------------------------------------------------------------
/**
 * 取本地内置数据。找不到对应条目时返回 undefined（区别于「找到了但是 null」）。
 * 函数式条目会被调用并传入本次请求参数，便于按参数返回不同结果。
 */
function tryFallback(method, path, data) {
  if (!FALLBACK_TO_LOCAL) return undefined
  // 延迟 require，避免生产路径也把 mock 数据打进包
  let localMock
  try {
    // eslint-disable-next-line global-require
    localMock = require('@/api/mock/local.js')
  } catch (e) {
    return undefined
  }
  const entry = localMock.resolve(method, path, data)
  return entry === undefined ? undefined : localMock.clone(entry)
}

// ------------------------------------------------------------------
// 核心请求
// ------------------------------------------------------------------
function rawRequest(options) {
  return new Promise((resolve, reject) => {
    uni.request({
      // ⚠️ **默认超时必须放在展开之前（2026-09-30 修）。**
      // 原先写的是 `...options` 然后 `timeout: REQUEST_TIMEOUT`，
      // 后者**覆盖**了前者 —— 于是调用方传任何 timeout 都不生效，
      // 全站被钉死在 REQUEST_TIMEOUT 上。现在顺序反过来：默认值先给，
      // 调用方传了就覆盖它（`request()` 的 options.timeout）。
      timeout: REQUEST_TIMEOUT,
      ...options,
      success: resolve,
      fail: reject,
    })
  })
}

/**
 * @param {object}  options
 * @param {string}  options.path    业务路径，如 '/orders/my'（不含 /api/v1 前缀）
 * @param {string}  [options.method='GET']
 * @param {object}  [options.data]
 * @param {object}  [options.header]
 * @param {boolean} [options.auth=true]   是否携带 Authorization
 * @param {boolean} [options.mock]        覆盖全局 API_MODE：true 强制走 mock，false 强制走真实
 * @param {boolean} [options.silent=false] 失败时是否不弹 toast（由调用方自己处理）
 * @returns {Promise<any>} resolve body.data
 */
export async function request(options) {
  const {
    path,
    method = 'GET',
    data,
    header,
    auth = true,
    mock,
    silent = false,
    // 逐请求超时。不传则用 config 的 REQUEST_TIMEOUT（已放宽到 240s）。
    timeout,
    _retried = false,
  } = options

  const useMock = mock === undefined ? API_MODE === 'mock' : !!mock

  // ⚠️ **2026-09-30：没登录就**不要**发这个请求。**
  //
  // 原先「未登录」也会真的打一次接口，拿到 40101 之后才由下面的
  // AUTH_FAIL_CODES 分支清 token + 跳登录页。后果有两个：
  //
  //   1. **首页 / 消息 / 我的 三个 tab 都在 onShow 里无条件拉鉴权接口**，
  //      未登录时每进一次页面就白打一轮 401（开发者工具里刷屏），
  //      然后被**强制弹到登录页** —— 于是页面自己写好的
  //      「未登录 / 去登录」分支（pages/mine/index.vue 等）**永远显示不出来**，
  //      退出登录之后也无法再浏览任何 tab。
  //   2. 40101 的语义是「你**根本没带**令牌」，与「令牌被服务端拒绝」是两回事。
  //      把它当成会话失效去 clearTokens + 跳转，属于过度反应。
  //
  // 这里提前短路，抛一个**独立的 kind**（'NO_TOKEN'）交给页面自己决定展示什么。
  //
  // 注意边界：**带了令牌但被服务端拒绝**（40102 签名错 / 40103 过期 …）
  // 仍然走下面的 AUTH_FAIL_CODES 分支 —— 那才是真正该清会话的情况。
  if (auth && !getAccessToken()) {
    throw makeError('未登录', 'NO_TOKEN')
  }

  let res
  try {
    res = await rawRequest({
      url: buildUrl(path, useMock),
      method,
      data,
      header: buildHeader(header, auth),
      // 仅在调用方显式传入时才覆盖默认超时，避免把 undefined 塞进去
      ...(timeout ? { timeout } : {}),
    })
  } catch (e) {
    // 网络层直接失败：后端没启动 / 断网 / 超时
    const fallback = tryFallback(method, path, data)
    if (fallback !== undefined) return fallback
    throw makeError('网络连接失败，请确认后端服务已启动', 'NETWORK')
  }

  const body = res.data
  const code = body && typeof body === 'object' ? body.code : undefined

  // 1. 成功
  if (code === CODE.OK) return body.data

  // 2. accessToken 过期 → 续期后原样重放一次
  if (code === CODE.ACCESS_EXPIRED && !_retried && auth) {
    try {
      await refreshAccessToken()
    } catch (e) {
      clearTokens()
      redirectToLogin()
      throw makeError('登录已过期，请重新登录', 'AUTH')
    }
    return request({ ...options, _retried: true })
  }

  // 3. Redis 不可用：服务问题，保留登录态
  if (code === CODE.REDIS_DOWN) {
    throw makeError((body && body.message) || '服务暂时不可用，请稍后重试', 'SERVICE', { code })
  }

  // 4. 登录态无效
  if (AUTH_FAIL_CODES.indexOf(code) !== -1) {
    clearTokens()
    redirectToLogin()
    throw makeError((body && body.message) || '登录状态无效，请重新登录', 'AUTH', { code })
  }

  // 5. 服务端不可用 → 本地兜底
  if (isServerDown(res.statusCode, code)) {
    const fallback = tryFallback(method, path, data)
    if (fallback !== undefined) return fallback
  }

  // 6. 其余业务错误：把后端 message 原样交给调用方
  const message = (body && body.message) || `请求失败（HTTP ${res.statusCode}）`
  const err = makeError(message, 'BIZ', { code, data: body && body.data })
  if (!silent) toast(message)
  throw err
}

/**
 * 文件上传（语音、图片、巡检）
 *
 * 契约：一律 multipart/form-data，字段名固定为 `file`。
 * 后端限制了图片 ≤5MB 且仅 jpeg/png/webp/bmp，音频支持 wav/pcm/amr/m4a。
 * 注意不要手动设置 Content-Type —— 要让平台自动带上 multipart boundary。
 */
export function upload(options) {
  const {
    path,
    filePath,
    name = 'file',
    formData = {},
    auth = true,
    mock,
    silent = false,
  } = options
  const useMock = mock === undefined ? API_MODE === 'mock' : !!mock

  return new Promise((resolve, reject) => {
    const header = {}
    if (auth) {
      const token = getAccessToken()
      if (token) header.Authorization = `Bearer ${token}`
    }

    uni.uploadFile({
      url: buildUrl(path, useMock),
      filePath,
      name,
      formData,
      header,
      // 上传确实比普通请求慢，但**不能**跟着 REQUEST_TIMEOUT 一起放大：
      // 后者现在是 240000（为 /agent/schedule 那 39~105 秒留的余量），
      // 乘 2 会变成 480 秒 —— 用户要干等 8 分钟才看到失败。
      // 上传是「传字节 + 一次识别」，120 秒足够（60 秒录音的 base64 约 2.6MB）。
      timeout: options.timeout || 120000,
      success: (res) => {
        let body
        try {
          body = JSON.parse(res.data)
        } catch (e) {
          const fallback = tryFallback('UPLOAD', path, formData)
          if (fallback !== undefined) return resolve(fallback)
          return reject(makeError('返回数据解析失败', 'PARSE'))
        }

        if (body && body.code === CODE.OK) return resolve(body.data)

        const message = (body && body.message) || '上传失败'
        if (!silent) toast(message)
        return reject(makeError(message, 'BIZ', { code: body && body.code }))
      },
      fail: () => {
        const fallback = tryFallback('UPLOAD', path, formData)
        if (fallback !== undefined) return resolve(fallback)
        reject(makeError('网络连接失败，请确认后端服务已启动', 'NETWORK'))
      },
    })
  })
}

/** 把后端返回的相对路径（如 /uploads/xxx.jpg）补成可直接给 <image> 用的地址 */
export function absoluteUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//.test(path)) return path
  return BASE_URL + path
}

export default { request, upload, absoluteUrl }
