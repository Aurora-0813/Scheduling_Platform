import { defineStore } from 'pinia'

import { agentSchedule } from '@/api/monitor'
import { cancelOrder, confirmOrder, getOrder } from '@/api/orders'
import { getDevices } from '@/api/resources'
import { devicesOf, orderStatusLabel } from '@/utils/normalize'

/**
 * 核心调度 Agent 的状态（Agent 调度台 `/agent`）。
 *
 * ⚠️ **为什么这些状态必须放在 store 而不是页面组件里**
 * ---------------------------------------------------
 * 一次真实调度要跑 6~7 轮「模型 ↔ 工具」往返，实测 **40~105 秒**，
 * 而 `AGENT_TIMEOUT` 还是 180 秒。原先这些状态全是 `AgentWorkbench.vue` 的
 * 局部 `ref`，于是有一个必然踩到的坑：
 *
 *   请求发出后切到别的页面 → `<router-view>` 卸载该组件 → 组件局部状态全丢 →
 *   **调用过程与结果全部消失**，用户回来看到的是一个空白的调度台。
 *
 * 而后端其实把这次调度跑完了、订单也落库了 —— 消失的只有「给人看的那份」。
 * 也就是说这不是「后台运行」的问题（HTTP 请求本来就不随组件卸载而中止，
 * `request.js` 也没有配 AbortController），纯粹是**状态的生命周期挂错了地方**。
 *
 * 放进 store 之后：组件卸载不影响它，切页回来还能看到完整的思考链与方案。
 *
 * 为什么不是给 `<router-view>` 加 `<KeepAlive>`
 * -------------------------------------------
 * KeepAlive 解决不了刷新页面（F5）丢状态，而且它会把**所有**页面都缓存下来，
 * 为了这一个页面的一个问题去改全局布局，代价与风险都不对等。
 * 这个页面的状态本来就该独立于视图存在。
 */
/**
 * 需要**跨页面刷新**存活的那部分状态。
 *
 * 为什么不整份 state 都存：`running` / `timer` 是**进程内**的东西 ——
 * 刷新之后那次请求早就不在跑了，把 `running=true` 恢复回来会让界面永远
 * 卡在「Agent 思考中」，而且没有任何东西会把它复位。所以只存「结果」。
 */
const PERSIST_KEY = 'dsh.agentWorkbench.result'

const PERSISTED_FIELDS = [
  'trace',
  'plan',
  'backupPlan',
  'orderId',
  'needConfirm',
  'orderStatus',
  'fallbackMessage',
]

/** 从 sessionStorage 读回上次的结果。读不到 / 坏了都返回空对象，绝不抛。 */
function loadPersisted() {
  try {
    const raw = sessionStorage.getItem(PERSIST_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const out = {}
    for (const key of PERSISTED_FIELDS) {
      if (key in parsed) out[key] = parsed[key]
    }
    return out
  } catch {
    // 隐私模式 / 超出配额 / 存的内容坏了 —— 都退回「没有持久化」，不影响功能
    return {}
  }
}

/** 把结果写进 sessionStorage。任何异常都吞掉：存不下不该影响调度本身。 */
function savePersisted(state) {
  try {
    const slim = {}
    for (const key of PERSISTED_FIELDS) slim[key] = state[key]
    sessionStorage.setItem(PERSIST_KEY, JSON.stringify(slim))
  } catch {
    /* 忽略 */
  }
}

export function clearPersisted() {
  try {
    sessionStorage.removeItem(PERSIST_KEY)
  } catch {
    /* 忽略 */
  }
}

export const useAgentWorkbenchStore = defineStore('agentWorkbench', {
  state: () => ({
    // ---- 输入 ----
    text: '',

    // ---- 运行态（**不持久化**）----
    running: false,
    acting: false,
    /** 计时器归 store 所有：切页时组件卸载，秒数仍要继续走 */
    elapsed: 0,
    timer: null,

    // ---- 最近一次调度的结果（持久化，见 PERSISTED_FIELDS）----
    trace: [],
    plan: null,
    backupPlan: null,
    orderId: null,
    needConfirm: true,
    orderStatus: null,
    /** 降级路径的可读原因。它来自响应体的 `message`，不在 `data` 里 */
    fallbackMessage: '',

    /** deviceId -> deviceName。Agent 只返回设备 ID，名字得自己查真库补上 */
    deviceMap: new Map(),

    // 上次结果从 sessionStorage 恢复回来（没有就是空对象）。
    // 放在 state 里是为了让 actions 能读到，同时不污染上面的字段声明。
    ...loadPersisted(),
  }),

  getters: {
    /**
     * Tool 调用统计：`[{ name, count }]`。
     * **完全由真实思考链推导** —— 没有真实的 action 就不显示，不编造。
     */
    toolCalls: (state) => {
      const byName = new Map()
      for (const step of state.trace) {
        if (!step.action) continue
        const entry = byName.get(step.action) || { name: step.action, count: 0 }
        entry.count += 1
        byName.set(step.action, entry)
      }
      return [...byName.values()]
    },

    totalToolCalls() {
      return this.toolCalls.reduce((sum, t) => sum + t.count, 0)
    },

    orderStatusText: (state) =>
      state.orderStatus === null || state.orderStatus === undefined
        ? ''
        : orderStatusLabel(state.orderStatus),

    statusTagClass: (state) => {
      switch (state.orderStatus) {
        case 2:
          return 'is-green'
        case 3:
          return 'is-gray'
        case 4:
          return 'is-blue'
        default:
          return 'is-orange'
      }
    },

    /**
     * 方案要素完整度 —— 由 Plan 契约里那 5 个字段的真实有无算出来。
     *
     * 原型画的是「AI 方案置信度 88%」，但**后端不返回置信度**
     * （backend/app/schemas/agent.py::Plan 只有 5 个要素字段），
     * 与其编一个 88%，不如算一个用户能自己核对的东西。
     */
    planFields: (state) => {
      const p = state.plan
      if (!p) return []
      return [
        { label: '场地', ok: p.spaceId !== null && p.spaceId !== undefined },
        { label: '开始时间', ok: Boolean(p.startTime) },
        { label: '结束时间', ok: Boolean(p.endTime) },
        { label: '设备', ok: Array.isArray(p.deviceIds) && p.deviceIds.length > 0 },
        { label: '理由', ok: Boolean(p.reason) },
      ]
    },

    planFilled() {
      return this.planFields.filter((f) => f.ok).length
    },

    planScore() {
      return this.planFields.length
        ? Math.round((this.planFilled / this.planFields.length) * 100)
        : 0
    },
  },

  actions: {
    startTimer() {
      this.stopTimer()
      this.elapsed = 0
      this.timer = setInterval(() => {
        this.elapsed += 1
      }, 1000)
    },

    stopTimer() {
      if (this.timer) {
        clearInterval(this.timer)
        this.timer = null
      }
    },

    onReset() {
      this.trace = []
      this.plan = null
      this.backupPlan = null
      this.orderId = null
      this.orderStatus = null
      this.fallbackMessage = ''
      // 也清掉持久化的那份，否则刷新一下「清空」的结果又回来了
      clearPersisted()
    },

    /**
     * 跑一次真实调度。
     *
     * 返回响应体 `{ data, message, ok }`，**提示分级交给调用方**（组件）——
     * store 不该决定弹哪个 toast，那是视图层的选择。
     * 失败时返回 `{ ok: false }` 且不抛：`request.js` 已经弹过后端真实 message，
     * 这里再抛一次只会让组件多写一个空 catch。
     */
    async run(text) {
      const value = (text ?? this.text ?? '').trim()
      if (!value) return { ok: false, reason: 'empty' }

      this.running = true
      this.startTimer()
      try {
        const res = await agentSchedule({ text: value })
        const data = (res && res.data) || {}
        const message = (res && res.message) || ''

        this.trace = Array.isArray(data.trace) ? data.trace : []
        this.plan = data.plan || null
        this.backupPlan = data.backupPlan || null
        this.orderId = data.orderId || null
        this.needConfirm = data.needConfirm !== false
        // 「操作成功」是正常路径的固定文案，拿它当降级原因显示会很怪
        this.fallbackMessage =
          !data.plan && message && message !== '操作成功' ? message : ''

        if (this.orderId) await this.refreshOrderStatus()
        // 结果落进 sessionStorage：**刷新页面后还能看到上一次的思考链与方案**。
        // 只存结果、不存 running（理由见 PERSISTED_FIELDS 的说明）。
        savePersisted(this)
        return { ok: true, data, message }
      } catch {
        // request.js 已经弹过后端的真实 message，这里不重复打扰
        return { ok: false, reason: 'request' }
      } finally {
        this.running = false
        this.stopTimer()
      }
    },

    async refreshOrderStatus() {
      if (!this.orderId) return
      try {
        const order = await getOrder(this.orderId)
        this.orderStatus = order && order.orderStatus
      } catch {
        // 拿不到状态不影响主流程，按钮仍可用
      }
      // 状态也会被持久化：确认 / 取消之后刷新页面，状态标签不该退回旧值
      savePersisted(this)
    },

    async confirm() {
      if (!this.orderId) return
      this.acting = true
      try {
        await confirmOrder(this.orderId)
        return true
      } catch {
        // 409（当前状态不允许确认）等由 request.js 弹出真实原因
        return false
      } finally {
        this.acting = false
        await this.refreshOrderStatus()
      }
    },

    async cancel() {
      if (!this.orderId) return
      this.acting = true
      try {
        await cancelOrder(this.orderId)
        return true
      } catch {
        return false
      } finally {
        this.acting = false
        await this.refreshOrderStatus()
      }
    },

    /** 拉设备名映射。补不到就退化成显示 ID，不影响调度。 */
    async loadDeviceMap() {
      try {
        this.deviceMap = new Map(
          devicesOf(await getDevices()).map((d) => [Number(d.deviceId), d.deviceName]),
        )
      } catch {
        this.deviceMap = new Map()
      }
    },
  },
})
