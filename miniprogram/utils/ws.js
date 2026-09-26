// WebSocket 封装：断线重连、心跳保活、消息分发
import { BASE_URL, USER_ID } from './request'
import { useNotifyStore } from '@/store/notify'

const WS_BASE = BASE_URL.replace(/^http/, 'ws')
const MAX_ATTEMPTS = 10

let socketTask = null
let heartbeatTimer = null
let reconnectTimer = null
let manualClose = false
let reconnectAttempts = 0

export function connectWS() {
  manualClose = false
  socketTask = uni.connectSocket({
    url: `${WS_BASE}/ws/notify?user_id=${USER_ID}`,
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

  socketTask.onClose(() => {
    stopHeartbeat()
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
