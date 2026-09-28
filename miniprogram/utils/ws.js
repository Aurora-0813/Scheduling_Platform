// WebSocket 封装：断线重连、心跳保活、消息分发
import { BASE_URL } from './request'
import { clearToken, ensureToken } from './auth'
import { useNotifyStore } from '@/store/notify'

const WS_BASE = BASE_URL.replace(/^http/, 'ws')
const MAX_ATTEMPTS = 10

//: 服务端在握手鉴权失败时按「策略违规」关闭（见 backend/app/main.py）。
const WS_POLICY_VIOLATION = 1008

let socketTask = null
let heartbeatTimer = null
let reconnectTimer = null
let manualClose = false
let reconnectAttempts = 0

export async function connectWS() {
  manualClose = false

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
    url: `${WS_BASE}/ws/notify?token=${encodeURIComponent(token)}`,
    success: () => {},
    fail: () => scheduleReconnect(),
  })

  socketTask.onOpen(() => {
    reconnectAttempts = 0
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
  // 更新 Pinia 未读数 + 插入列表
  const store = useNotifyStore()
  store.receive(msg)
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
  socketTask && socketTask.close({})
}
