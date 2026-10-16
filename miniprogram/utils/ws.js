// WebSocket 封装：断线重连、心跳保活、消息分发
//
// ⚠️ **2026-10-14 修了一个必崩的导入。**
// 原先这里是 `import { BASE_URL } from './request'`，而 `utils/request.js`
// **根本没有导出 BASE_URL**（真正导出它的曾经是 `config/index.js`）。
// ES 模块下命名导入不存在时，真实打包会直接报「does not provide an export」，
// 于是**整个通知通道在真机上起不来** —— 静态检查（包括 IDE 的自动补全）看不出来，
// 因为路径本身是存在的、只是名字不对。
//
// 现在改从 `api/endpoint.js` 取，并且**在每次连接时现算**地址：
// 登录页可以在运行时改后端地址（内网穿透的公网地址会变），
// 若像原先那样在模块顶层算成一个常量 `WS_BASE`，改完地址后 WS 会一直重连旧地址，
// 页面表现是「登录正常、但通知永远不来」—— 比直接报错难查得多。
import { getBaseUrl } from '@/api/endpoint.js'
import { clearToken, ensureToken } from './auth'
import { refreshUnread } from '@/store/notify.js'

const MAX_ATTEMPTS = 10

//: 服务端在握手鉴权失败时按「策略违规」关闭（见 backend/app/main.py）。
const WS_POLICY_VIOLATION = 1008

let socketTask = null
let heartbeatTimer = null
let reconnectTimer = null
let manualClose = false
let reconnectAttempts = 0
/** 当前这条连接实际用的基地址（http(s)://），用于判断「地址变了没有」 */
let currentBase = null
/** 管理端/登录页改了后端地址后置位：下一次重连要按新地址建 */
let endpointDirty = false

/** 由 `getBaseUrl()` 现算的 ws(s):// 基地址 */
function wsBase() {
  return getBaseUrl().replace(/^http/, 'ws')
}

export async function connectWS() {
  manualClose = false

  // 地址变了就先把旧连接彻底断掉：否则 socketTask 会被下面覆盖，
  // 旧连接**无人关闭**、服务端还挂着一个会话，且新旧两条都在推消息（重复通知）。
  const base = wsBase()
  if (socketTask && currentBase !== base) {
    try { socketTask.close({}) } catch (e) {}
    socketTask = null
    stopHeartbeat()
  }
  currentBase = base

  // 身份走**令牌**，不是 user_id（§5.1）。
  // 浏览器与小程序都不允许给 WebSocket 自定义请求头，凭据只能放进 URL；
  // 但传的必须是令牌 —— 早先的 `?user_id=${USER_ID}` 谁都能改成别人，
  // 一连上就实时收别人的预约通知。
  let token
  try {
    token = await ensureToken()
  } catch (e) {
    scheduleReconnect()
    return
  }

  socketTask = uni.connectSocket({
    url: `${base}/ws/notify?token=${encodeURIComponent(token)}`,
    success: () => {},
    fail: () => scheduleReconnect(),
  })

  socketTask.onOpen(() => {
    reconnectAttempts = 0
    // 连上了说明当前地址可用，清掉「地址已改」标记
    endpointDirty = false
    startHeartbeat()
  })

  socketTask.onMessage((res) => {
    try {
      handleMessage(JSON.parse(res.data))
    } catch (e) {}
  })

  socketTask.onClose((res) => {
    stopHeartbeat()
    // 1008 = 服务端按策略违规拒绝握手：本地令牌已不可用（多半是过期）。
    // 丢掉它，重连时 ensureToken() 会自动重登，否则会拿着废令牌一直重试。
    if (res && res.code === WS_POLICY_VIOLATION) clearToken()
    if (!manualClose) scheduleReconnect()
  })

  socketTask.onError(() => {
    stopHeartbeat()
  })
}

function handleMessage(msg) {
  // ⚠️ 2026-10-14 重写。原先这里是这样的：
  //
  //     import { useNotifyStore } from '@/store/notify'
  //     const store = useNotifyStore(); store.receive(msg)
  //
  // 三处都不成立：
  //   1. store/notify.js **没有** useNotifyStore（它是 Pinia 风格的命名，
  //      而这个项目用的是 `reactive()` 导出的单例 notifyStore）；
  //   2. 更没有 `receive()` 方法 —— 真实 API 只有 notifyStore /
  //      refreshUnread() / setUnreadCount()；
  //   3. WebSocket 推送的消息体里**没有未读数**，想靠它自己算也做不到。
  //
  // 所以改成「收到推送 → 向服务端重新取一次未读数」：
  //   · 未读数的唯一权威来源是 GET /messages/unread（见 api/messages.js 的说明，
  //     那个接口只返回计数），本地猜数迟早会和库里的真实值对不上；
  //   · refreshUnread() 失败时会**保留旧值**、只记错误，
  //     所以这里不需要额外 try/catch，一次网络抖动不会把角标打成 0。
  //
  // 不在这里改动列表：按 store/notify.js 的既定分工，list 只由消息页写入，
  // 否则会把消息页刚拉到的列表覆盖掉（那个坑该文件顶部有记录）。
  refreshUnread()
  uni.showToast({ title: msg.title || '收到新通知', icon: 'none' })
  // 订阅消息授权（封装占位）
  requestSubscribe()
}

function requestSubscribe() {
  // 微信订阅消息需在用户点击事件中调用才有效，此处为占位封装
  // uni.requestSubscribeMessage({ tmplIds: ['xxx'], success() {}, fail() {} })
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeatTimer = setInterval(() => {
    socketTask && socketTask.send({ data: 'ping', fail: () => {} })
  }, 30000)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

function scheduleReconnect() {
  if (reconnectTimer || manualClose) return
  if (reconnectAttempts >= MAX_ATTEMPTS) return
  reconnectAttempts += 1
  const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts))
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectWS()
  }, delay)
}

export function closeWS() {
  manualClose = true
  stopHeartbeat()
  currentBase = null
  endpointDirty = false
  socketTask && socketTask.close({})
}

/**
 * 后端地址被改掉时调用（登录页保存新地址后）。
 *
 * 只是把标记置位并断掉旧连接，**不在这里立刻重连** ——
 * 登录页改地址时用户通常还没登录，此刻连上去只会因拿不到令牌而反复重试。
 * 真正的重连交给下一次 `connectWS()`（登录成功后由页面调用）。
 */
export function notifyEndpointChanged() {
  endpointDirty = true
  try { socketTask && socketTask.close({}) } catch (e) {}
  socketTask = null
  stopHeartbeat()
}

/** 当前 WS 是否正连着（登录页/排查用，不参与业务判断） */
export function isWSConnected() {
  return !!socketTask && !endpointDirty
}
