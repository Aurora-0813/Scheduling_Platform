/**
 * 后端地址（Endpoint）解析 —— 运行时可改，不必重新打包（2026-10-14 新增）。
 *
 * ## 为什么需要它
 *
 * 原先后端地址是 `config/index.js` 里的一个**编译期常量`BASE_URL`**，
 * 注释写着「打 APK 前必改」（见该文件 10-19 行）。这带来三个现实问题：
 *
 *   1. **换个网络就得重打包**。内网穿透（frp / ngrok / cpolar …）的公网地址
 *      每次重启隧道都可能变，每变一次就要重新打一次 APK 再装一次。
 *   2. **演示时没法现场切**。答辩现场若局域网不通，只能眼睁睁看着 ——
 *      没有地方能把这个地址改掉。
 *   3. **排查断连时看不到真实地址**。用户报「连不上」，你无法确认
 *      他手机上装的包到底在打哪个地址。
 *
 * 所以这里把地址做成**运行时可写**的：登录页有一个输入框，写进本地存储，
 * 之后每次发请求都从这里取。与后端那两个调度开关（`core/flags.py`）是同一种思路 ——
 * **演示前改一下，不必重新打包**。
 *
 * ## 取址优先级
 *
 *     本地存储里的覆盖值  →  `config/index.js` 的 DEFAULT_BASE_URL
 *
 * 存储里**没有**时才回落默认值，所以：
 *   · 没配过的人，行为与改动前**完全一致**（默认值仍是那个局域网 IP）；
 *   · 配过的人，重启小程序/APP 后依然生效（本地存储是持久的）。
 *
 * ⚠️ 地址在**每次请求时**才解析，不是在模块加载时定死。
 *    这是本条需求的关键：`api/request.js` 里原先 `import { BASE_URL }` 是
 *    模块级常量绑定，登录页改了它也不会变 —— 请求会继续打旧地址。
 */
import { DEFAULT_BASE_URL, STORAGE_KEYS, API_PREFIX } from '@/config/index.js'

/** 存储读写都包一层：小程序存储 API 在极少数情况下会抛（配额/隐私模式），不该让整个请求层挂掉 */
function readStored() {
  try {
    const v = uni.getStorageSync(STORAGE_KEYS.ENDPOINT)
    return typeof v === 'string' ? v : ''
  } catch (e) {
    return ''
  }
}

function writeStored(value) {
  try {
    if (value) uni.setStorageSync(STORAGE_KEYS.ENDPOINT, value)
    else uni.removeStorageSync(STORAGE_KEYS.ENDPOINT)
    return true
  } catch (e) {
    return false
  }
}

/**
 * 把用户输入**归一化**成可以直接拼路径的基地址。
 *
 * 用户从浏览器地址栏复制过来的东西五花八门，这里要能吃掉常见的那几种：
 *
 *     "  192.168.1.10:8000  "            → http://192.168.1.10:8000
 *     "https://abc.frp.io/"              → https://abc.frp.io
 *     "https://abc.frp.io/api/v1"        → https://abc.frp.io     ← 见下
 *     "https://abc.frp.io/api/v1/health" → https://abc.frp.io
 *     "http://user:pw@host:8000"         → 抛错（凭据不能写进地址）
 *
 * ⚠️ **为什么要主动剥掉结尾的 `/api/v1`**：请求层自己会拼
 *    `base + API_PREFIX + path`（见 api/request.js::buildUrl）。用户若照着
 *    「后端接口地址」把 `.../api/v1` 或某个具体接口粘进来，不剥就会拼成
 *    `.../api/v1/api/v1/auth/login` —— 404，而报错**看起来像服务端问题**，
 *    极难自查。这类输入在答辩现场几乎一定会出现，所以在这里吃掉它。
 *
 * 前缀最多剥两层：`/api/v1/api/v1/health` 这种粘贴事故也一并容忍。
 *
 * @param {string} raw 用户输入
 * @returns {string} 归一化后的基地址（形如 http(s)://host[:port][/path]）
 * @throws {Error} 输入为空或不合法时抛出，message 可直接展示给用户
 */
export function normalizeBaseUrl(raw) {
  let s = String(raw == null ? '' : raw).trim()
  if (!s) throw new Error('请填写后端地址')

  // 容忍「只写了 host:port」的输入（内网 IP 最常见），自动补 http://
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s

  // 凭据不能写进地址：一来会随每次请求明文发出，二来日志/截图里会泄露
  if (/^https?:\/\/[^/@]*@/i.test(s)) {
    throw new Error('地址里不能包含账号密码')
  }

  const m = /^https?:\/\/[^\s/?#]+/i.exec(s)
  if (!m) throw new Error('地址格式不对，示例：http://192.168.1.10:8000')

  const origin = m[0]
  let rest = s.slice(origin.length)

  // 丢掉 query / hash：基地址里带上它们没有意义
  rest = rest.split('?')[0].split('#')[0]

  // ⚠️ 顺序要紧（2026-10-14 实测踩到）：必须先剥 `/api/v1`，再剥 `/health`，
  // 而且剥完 `/health` 之后要**再剥一轮**。反过来的话 `/api/v1/health`
  // 会先匹配到末尾的 `/health` 并把它去掉，`/api/v1` 就永远轮不到 ——
  // 最终拼成 `.../api/v1/api/v1/health`；而输入框回填的结果
  // **看起来是对的**（https://host/api/v1），用户根本不会怀疑，极难自查。
  const stripTrailing = (s, re) => {
    let cur = s.replace(/\/+$/, '')
    for (let i = 0; i < 3; i += 1) {
      const next = cur.replace(re, '').replace(/\/+$/, '')
      if (next === cur) break
      cur = next
    }
    return cur
  }
  rest = stripTrailing(rest, /\/api\/v1$/i)
  rest = stripTrailing(rest, /\/health$/i)
  rest = stripTrailing(rest, /\/api\/v1$/i)

  const base = origin + rest

  // host 部分必须像样：至少一个点、或 localhost、或纯 IP —— 否则多半是手滑
  const hostPart = origin.replace(/^https?:\/\//i, '').split(':')[0]
  if (!/^([\w-]+\.)+[\w-]+$/.test(hostPart) && !/^localhost$/i.test(hostPart) && !/^\d{1,3}(\.\d{1,3}){3}$/.test(hostPart)) {
    throw new Error('地址里的主机名不像合法域名或 IP')
  }

  return base
}

/**
 * 校验 + 归一化，一次调用完成。
 *
 * @returns {{ ok: true, baseUrl: string, warnings: string[] } | { ok: false, message: string }}
 *
 * 返回 warnings 而不是直接拒绝：`http://` 在微信开发者工具（勾了「不校验合法域名」）
 * 与 APK 真机上是**可用**的，只有正式小程序才强制 https。直接拒绝会把
 * 「本地/局域网调试」这条路一起堵死，而它恰恰是这个项目最常用的场景。
 */
export function validateBaseUrl(raw) {
  let baseUrl
  try {
    baseUrl = normalizeBaseUrl(raw)
  } catch (e) {
    return { ok: false, message: e.message || '地址不合法' }
  }

  const warnings = []
  if (/^http:\/\//i.test(baseUrl)) {
    warnings.push('当前用 http（明文）。正式小程序只允许 https，真机上也需在后台配置合法域名。')
  }
  return { ok: true, baseUrl, warnings }
}

/**
 * 当前后端地址。**每次请求都要调它**，不要在模块顶层缓存结果。
 * @returns {string}
 */
export function getBaseUrl() {
  return readStored() || DEFAULT_BASE_URL
}

/** 当前是否用了存储里的覆盖值（登录页据此显示「已自定义」） */
export function isCustomBaseUrl() {
  return !!readStored()
}

/**
 * 保存后端地址（先校验归一化）。
 * @returns {{ ok: true, baseUrl: string, warnings: string[] } | { ok: false, message: string }}
 */
export function setBaseUrl(raw) {
  const res = validateBaseUrl(raw)
  if (!res.ok) return res
  if (!writeStored(res.baseUrl)) {
    return { ok: false, message: '保存失败：本地存储不可用' }
  }
  return res
}

/** 清除覆盖值，回到 config 里的默认地址 */
export function resetBaseUrl() {
  writeStored('')
  return DEFAULT_BASE_URL
}

/** 默认地址（登录页的「重置」按钮与提示文案要用） */
export function getDefaultBaseUrl() {
  return DEFAULT_BASE_URL
}

/**
 * 探测某个地址上的后端**是否可达**。
 *
 * 打的是 `GET {base}/api/v1/health` —— 选它有三个理由：
 *   1. **不需要登录**，所以能在登录页上直接测；
 *   2. **不查数据库**（见 backend/app/api/v1/health.py 的说明），
 *      所以「隧道通了但云库没连上」时它照样回 200，测的就是**隧道通不通**这一件事；
 *   3. 它回的是统一响应体 `{code:200,...}`，能顺带确认「这个地址后面确实是我们这个后端」，
 *      而不只是「某台机器在监听 8000」。
 *
 * ⚠️ 超时**故意给得很短**（默认 8 秒）：这是给人当场点的按钮。
 *    若沿用主请求那 240 秒，隧道不通时用户要盯着转圈 4 分钟才知道错了。
 *
 * @param {string} raw 待测地址（未归一化，内部会先校验收敛）
 * @param {number} [timeout=8000]
 * @returns {Promise<{ ok: boolean, message: string, baseUrl?: string, latencyMs?: number, detail?: object }>}
 */
export function probeBaseUrl(raw, timeout = 8000) {
  const res = validateBaseUrl(raw)
  if (!res.ok) return Promise.resolve({ ok: false, message: res.message })

  const baseUrl = res.baseUrl
  const started = Date.now()

  return new Promise((resolve) => {
    uni.request({
      url: baseUrl + API_PREFIX + '/health',
      method: 'GET',
      timeout,
      success: (r) => {
        const body = r.data
        const latencyMs = Date.now() - started
        // 后端统一响应体：成功恒为 code === 200（见 docs/api.md 5.2）
        if (body && body.code === 200) {
          resolve({
            ok: true,
            baseUrl,
            latencyMs,
            detail: body.data || {},
            message: `连接成功（${latencyMs} ms）`,
          })
          return
        }
        // 能连上、但回来的不是我们的统一响应体 —— 多半是打到了别的服务
        resolve({
          ok: false,
          baseUrl,
          latencyMs,
          message: `已连上，但返回的不是本平台后端（code=${body && body.code}）`,
        })
      },
      fail: (err) => {
        const msg = (err && err.errMsg) || ''
        resolve({
          ok: false,
          baseUrl,
          message: /timeout/i.test(msg)
            ? '连接超时：地址或端口不通，或被防火墙拦了'
            : '连接失败：地址不可达（隧道是否已启动？）',
        })
      },
    })
  })
}

export default {
  getBaseUrl,
  setBaseUrl,
  resetBaseUrl,
  getDefaultBaseUrl,
  isCustomBaseUrl,
  normalizeBaseUrl,
  validateBaseUrl,
  probeBaseUrl,
}
