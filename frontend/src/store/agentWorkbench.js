import { defineStore } from 'pinia'

import { agentParse, getAgentMode, setAgentMode } from '@/api/agent'
import { agentSchedule } from '@/api/monitor'
import { cancelOrder, confirmOrder, getOrder } from '@/api/orders'
import { getDevices } from '@/api/resources'
import { useAuthStore } from '@/store/auth'
import { devicesOf, orderStatusLabel } from '@/utils/normalize'
import { ensureFreshToken } from '@/utils/request'
import {
  attachOrderIdToDurableOperation,
  beginDurableOperation,
  clearPendingAction,
  getPendingAction,
} from '@/utils/pendingAction'

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

/**
 * 场地类型码 → 中文。
 *
 * 与后端 `agent/chains/parse.py::SPACE_TYPE_CN` 逐字一致（1会议室/2展厅/3多功能厅/4户外场地）。
 * 前端另写一份而不是向后端要，是因为 `Plan` 契约里根本没带这个文案
 * （它只给 spaceType 整数），为一行标签多发一次请求不划算。
 */
const SPACE_TYPE_TEXT = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }

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

    /**
     * 解析时一并交给后端的图像/草图上下文。
     *
     * `AgentWorkbench` 页面上没有上传入口，所以这里**始终是空对象**。
     * 声明出来是为了让 `parse()` 的入参口径与小程序端一致
     * （那边语音页会把拍照识场的 `imageContext` 带过来），
     * 将来 Web 端接上拍照入口时也不用改 store 的签名。
     */
    imageContext: {},

    // ---- 运行态（**不持久化**）----
    running: false,
    acting: false,
    /** 计时器归 store 所有：切页时组件卸载，秒数仍要继续走 */
    elapsed: 0,
    timer: null,

    // ---- 「AI 解析条件」态（2026-10-13 新增，**不持久化**）----
    /**
     * 解析在飞。
     *
     * 与 `running` 分开：解析走 `/agent/parse`（**不建单**），
     * 调度走 `/agent/schedule`（**会真落一条待确认预约**）。
     * 两者耗时与后果都不同，共用一个标志会让按钮文案与禁用条件全错。
     */
    parsing: false,
    /** `POST /agent/parse` 的结果：`{ conditions, recommend, confidence, latencyMs }` */
    parseResult: null,
    /** 这份 parseResult 是针对哪段文本解析的（判断还能不能复用，见 parseFresh） */
    parseFrom: '',
    /** 解析失败的可读原因。它与 fallbackMessage 是两件事，不共用一个字段 */
    parseError: '',

    // ---- 调度模式开关（后端全局，读回来只用于**显示**）----
    /** `/agent/mode` 的 flags：`{ deepMode, aiRecommend }` */
    modeFlags: { deepMode: false, aiRecommend: true },
    /** 开关是否已从后端读回来。没读回来之前按钮按禁用渲染，不要显示一个假状态 */
    modeLoaded: false,
    /** 读开关失败的原因。有值时页面显示它，而不是无限「读取中…」 */
    modeError: '',
    /** 有开关请求在飞，两个按钮一起禁用，避免连点造成状态互相覆盖 */
    modeSwitching: false,
    /**
     * 切开关所需的 `user:update` 权限，查得怎么样了（2026-10-13 补）。
     *
     * ⚠️ 为什么需要单独一个字段，而不是组件里直接 `authStore.hasPermission(...)`：
     * 页面**刷新**时 `authStore.userInfo` 还是 null，它由 **MainLayout** 的
     * `onMounted` 去拉（`layouts/MainLayout.vue:126`）。而 Vue 的挂载顺序是
     * 「**子先父后**」—— 本页的 `onMounted` 跑在 MainLayout 拉权限**之前**。
     * 直接判的话，管理员刷新页面那一瞬间会被判成「没有权限」：按钮闪一下禁用态，
     * 还多显示一个「只读：需要 user:update」标签，几百毫秒后才自己纠正。
     * 这是假的否定结论，比不显示更糟。
     *
     * 取值：'loading' | 'ok' | 'denied'。
     * 只有到 'denied' 才允许说「你没有权限」；'loading' 期间按钮同样禁用，
     * 但**不能**打出结论性文案。
     */
    modeAuth: 'loading',
    /** 权限是否已经查过（只用于避免重复请求，不作为判定依据） */
    modeAuthChecked: false,

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

    /**
     * 「上次被打断的动作」。有值就在调度台上显示一张恢复卡。
     *
     * 与上面 `PERSISTED_FIELDS` 的快照**不是一回事**：
     *   · `trace`/`plan`/`orderId` 是「调度结果」，可能是很久以前、早已处理完的；
     *   · 这个 `pendingAction` 是「**中断事件**」，只在会话失效那一瞬间写入，
     *     用户处理掉（`dismissPending`）后就该消失。
     * 分开放，恢复卡才不会因为「历史上有过一次调度」而天天弹。
     */
    pendingAction: getPendingAction(),

    // 上次结果从 sessionStorage 恢复回来（没有就是空对象）。
    // 放在 state 里是为了让 actions 能读到，同时不污染上面的字段声明。
    ...loadPersisted(),
  }),

  getters: {
    /**
     * 是否有「被打断的动作」需要用户处理。
     *
     * 只认 `pendingAction`，**不看 `orderId`** —— 后者是历史快照，
     * 用它来驱动恢复卡会让早已处理完的单子每次都弹一次。
     */
    hasPendingAction: (state) => !!state.pendingAction,

    /**
     * 恢复卡文案：把「哪个动作、动到哪个 id」说清楚。
     *
     * 后端已建单时**必须报出单号** —— 用户最需要知道的就是「它到底成没成」，
     * 含糊的「你可能成功过」等于没帮上忙。
     */
    pendingActionText: (state) => {
      const p = state.pendingAction
      if (!p) return ''
      const what = p.label || p.kind || '操作'
      if (p.orderId != null) {
        return `你在登录过期前跑过一次${what}，订单 #${p.orderId} 已经创建（待确认）。`
      }
      return `你在登录过期前跑过一次${what}，但没能拿到结果。建议先确认是否已经产生预约，再决定要不要重跑。`
    },

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

    /* ---------------- AI 解析条件（POST /agent/parse） ---------------- */

    parsedConditions: (state) => (state.parseResult && state.parseResult.conditions) || null,

    parsedRecommend: (state) => (state.parseResult && state.parseResult.recommend) || null,

    /**
     * 上一次解析的结果，**是否仍然对应当前输入框里的需求**。
     *
     * 为什么要比文本：解析一次 10~32 秒，用户改一个字就要重跑一遍，体验很差；
     * 但反过来，拿「别的话」读出来的条件去预填或展示，比不填更糟 ——
     * 用户会以为那是自己这句话的结果。用文本比对两头都占到，
     * 也天然覆盖了「改了又改回来」这种情况。
     */
    parseFresh: (state) =>
      Boolean(state.parseResult) && state.parseFrom === (state.text || '').trim(),

    /**
     * 「AI 读出了什么」渲染成 `[{ label, value }]`，空字段不占位置。
     *
     * ⚠️ 这里**绝不**给缺省值填充（比如人数为空就写「不限」）：
     * 那会让用户分不清「AI 没读到」和「AI 读到的是不限」。
     * 读不到的字段由 `parsedMissing` 单独说清楚。
     */
    parsedRows: (state) => {
      const c = (state.parseResult && state.parseResult.conditions) || null
      if (!c) return []
      const rows = []
      if (c.capacity) rows.push({ label: '人数', value: `${c.capacity} 人` })
      if (c.spaceType) rows.push({ label: '场地类型', value: SPACE_TYPE_TEXT[c.spaceType] || '—' })
      if (c.startTime) {
        rows.push({
          label: '时间',
          value: c.endTime ? `${c.startTime} ~ ${c.endTime}` : c.startTime,
        })
      }
      if (Array.isArray(c.deviceTypes) && c.deviceTypes.length) {
        rows.push({ label: '设备类型', value: c.deviceTypes.join('、') })
      }
      if (c.budget) rows.push({ label: '预算', value: `¥ ${c.budget}` })
      return rows
    },

    /**
     * 模型自报的「你没说、我按什么默认值处理的」。
     *
     * 这块**必须原样展示**：它是用户唯一能发现「AI 悄悄替他做了决定」的地方
     * （后端 prompt 里明文要求模型把默认值写在这里，见 `agent/chains/parse.py`）。
     */
    parsedMissing: (state) =>
      ((state.parseResult &&
        state.parseResult.conditions &&
        state.parseResult.conditions.missing) ||
        []
      ).slice(),

    /** 解析置信度百分比。后端给的是 0~1 的浮点，前端做展示换算 */
    parsedConfidence: (state) => {
      const v = state.parseResult && state.parseResult.confidence
      return typeof v === 'number' ? Math.round(v * 100) : null
    },

    /* ---------------- 调度模式开关（/agent/mode） ---------------- */

    /**
     * 当前是不是深度思考模式。
     *
     * 语义要写清楚，否则按钮会被理解反：
     *   deepMode = true  → 🧠 深度思考：多轮 Agent，40~80 秒，思考链完整（但会真落单）
     *   deepMode = false → ⚡ 快速决策：全量候选 + 单次调用，约 10~14 秒
     */
    isDeepMode: (state) => Boolean(state.modeFlags.deepMode),

    /** AI 推荐 = 推荐与理由由大模型给（约 32 秒）；false = 规则算（10~15 秒，理由来自真库） */
    isAiRecommend: (state) => Boolean(state.modeFlags.aiRecommend),
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

    /**
     * 用户处理完恢复卡（看了一眼 / 确认了 / 决定忽略）后调用。
     *
     * **只清「中断事件」，不动调度结果**：用户可能还想继续看上次的思考链与方案，
     * 所以这里不调 `onReset()`，否则会把 `trace`/`plan` 一起抹掉。
     */
    dismissPending() {
      this.pendingAction = null
      clearPendingAction()
    },

    onReset() {
      this.trace = []
      this.plan = null
      this.backupPlan = null
      this.orderId = null
      this.orderStatus = null
      this.fallbackMessage = ''
      // AI 解析结果也是「上一次那一轮」的东西，跟着一起清 ——
      // 只清思考链不清条件卡，会留下一张描述旧需求的卡片在「清空」之后的界面上。
      // ⚠️ 但**不动模式开关**（modeFlags）：那是后端的全局设置，不是本轮结果。
      this.parseResult = null
      this.parseFrom = ''
      this.parseError = ''
      // 需求文本也要清：它是 `parseFresh` 的比较基准，
      // 留着的话「清空」之后界面上的输入框仍是上一次那句需求。
      this.text = ''
      // 也清掉持久化的那份，否则刷新一下「清空」的结果又回来了
      clearPersisted()
    },

    /**
     * 跑一次**条件解析**（`POST /agent/parse`）。
     *
     * 与 `run()` 的分工是这个页面的核心区别，必须分清：
     *   · 本函数：一次模型调用，**不锁资源、不建单**，产出「AI 从这句话里读出了什么」。
     *     因此它可以被反复调用，用户改完需求重解析没有任何后果。
     *   · `run()`：多轮 Agent，**会真的落一条待确认预约**，只能跑一次。
     *
     * 返回 `{ ok, data, message }` 或 `{ ok:false, reason }`，**不抛**：
     * 提示分级（弹哪个 toast）交给视图层，和 `run()` 的口径保持一致。
     */
    async parse(text) {
      const value = (text ?? this.text ?? '').trim()
      if (!value) return { ok: false, reason: 'empty' }

      this.parsing = true
      this.parseError = ''
      try {
        // 解析最长约 32 秒（aiRecommend=true 时）。虽然比调度短得多，
        // 但同样跨得过令牌的剩余窗口，所以顺手也续一次 —— 与 run() 同口径。
        await ensureFreshToken()

        const data = await agentParse({ text: value, imageContext: this.imageContext || {} })
        this.parseResult = data || null
        this.parseFrom = value
        return { ok: true, data }
      } catch (e) {
        // ⚠️ 取值方式与 `request.js` 的 reject 形状有关，别看错：
        //     `utils/request.js` 的 `handleBizError` 里 `Promise.reject(body)`，
        //     body 就是后端的**响应体** `{ code, message, data }` ——
        //     所以 message 在 `e.message` 上（不是 `e.data.message`），
        //     而超时/断网那条分支 reject 的是 `{ code: -1, message: error.message }`，
        //     同一个字段名。两种失败都能取到原因。
        //
        // 这里的错误**不能吞**：解析失败时页面上没有任何结果可展示，
        // 一句原因都不给，用户只会看到按钮弹回去。
        // （业务错误 axios 拦截器已经弹过 toast，parseError 是**留在页面上**的那份，
        //   用户滚动或离开再回来时仍然能看到失败原因。）
        this.parseError = (e && e.message) || 'AI 解析失败，请重试或直接填写需求'
        return { ok: false, reason: 'request', message: this.parseError }
      } finally {
        this.parsing = false
      }
    },

    /**
     * 读一次调度模式开关。进页面时调，失败就保持「未读到」——
     * 按钮按禁用渲染，绝不猜一个默认值显示出去（那会让用户以为开关真是那个状态）。
     */
    async loadMode() {
      try {
        const data = await getAgentMode()
        this.modeFlags = (data && data.flags) || {
          deepMode: Boolean(data && data.deepMode),
          aiRecommend: true,
        }
        this.modeLoaded = true
        this.modeError = ''
      } catch (e) {
        // 读不到就**明说读不到**，不要留一个「读取中…」永远转下去，
        // 更不要退回本地默认值当成真状态显示 —— 那会让用户以为开关真是那个值。
        this.modeLoaded = false
        this.modeError = (e && e.message) || '读取调度模式失败'
      }
    },

    /**
     * 查「我能不能切开关」，把结果写进 `modeAuth`。进页面时调一次。
     *
     * 为什么要在这里主动补拉 `userInfo`：见 `modeAuth` 的说明 ——
     * 刷新时它是空的，而填它的是父布局，父布局挂载在本页之后。
     * 所以这里必须自己保证「判定之前权限一定已经拿到」。
     *
     * 拉取失败按 **'denied'** 处理（fail-closed）：拿不到权限就说没权限，
     * 总好过显示一个点下去必定吃 403 的按钮。
     * 注意 `fetchUserInfo` 失败时 axios 拦截器可能已经弹过提示，这里不重复弹。
     */
    async loadModePermission() {
      if (this.modeAuthChecked) return
      this.modeAuthChecked = true
      // 直接实例化另一个 store：Pinia 允许在 action 里拿别的 store。
      // 放在函数内而不是模块顶层，是为了避开「模块求值时就要求 Pinia 已安装」的时序问题。
      const auth = useAuthStore()
      try {
        if (!auth.userInfo) {
          // 刷新时它一定是空的，而填它的是**父布局**、挂载在本页之后 ——
          // 所以这里必须自己补拉一次，否则会把「还没读到」误判成「没有权限」。
          await auth.fetchUserInfo()
        }
        // ⚠️ 判定必须走这个 getter，不能自己解析 permissions 数组。
        //    云库里「系统管理员」存的就是 `['*']`（我实测确认过），
        //    getter 里处理了 `*` 与 `模块:*` 两种通配 —— 自己写会漏掉，
        //    结果会把管理员判成没权限。
        this.modeAuth = auth.hasPermission('user:update') ? 'ok' : 'denied'
      } catch {
        // fail-closed：拿不到权限就当没权限，总好过给一个点下去必定吃 403 的按钮。
        // axios 拦截器此时多半已经弹过提示，这里不重复弹。
        this.modeAuth = 'denied'
      }
    },

    async switchMode(patch) {
      this.modeSwitching = true
      try {
        const res = await setAgentMode(patch)
        // 以**后端回显**为准，而不是拿本地意图直接改 UI：
        // 回显与意图不一致时（写盘失败、并发改动），用户看到的必须是真的那个状态。
        const flags = (res && res.data) || null
        if (flags) this.modeFlags = flags
        this.modeLoaded = true
        this.modeError = ''
        return { ok: true, message: (res && res.message) || '' }
      } catch (e) {
        // 403（无 user:update 权限）等由 axios 拦截器弹出真实原因，这里只回报失败，
        // 让视图层知道**不要**去动按钮的高亮状态。
        return { ok: false, message: (e && e.message) || '切换失败' }
      } finally {
        this.modeSwitching = false
      }
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
      // 标记「这次调度有副作用」：若中途会话失效，请求层会据此写一条「未完成动作」，
      // 供登录后的恢复卡使用。finally 里必须清理，否则标记会一直挂着。
      const endDurable = beginDurableOperation({
        kind: 'agent.schedule',
        label: 'AI 调度',
      })
      try {
        // ⚠️ 调度前先把令牌续上（2026-10-09 加）。
        // 这次调度要跑 25~105 秒，而 accessToken 只有 30 分钟 ——
        // 若令牌在中途过期，调度会**成功**（订单已落库）但紧接着的调用 401，
        // 用户被踢到登录页且上下文全丢。详见 utils/request.js::ensureFreshToken。
        // 失败不阻断：那只是优化，真正的 401 仍由请求层按原逻辑处理。
        await ensureFreshToken()

        const res = await agentSchedule({ text: value })
        const data = (res && res.data) || {}
        const message = (res && res.message) || ''

        // 后端已建单 → 把单号补进在途标记。
        // 这样即便紧接着有别的请求 401 把用户踢出去，恢复卡也能直接报出单号，
        // 而不是含糊地说「你可能成功过」。
        attachOrderIdToDurableOperation(data.orderId)

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
        // 无论成功/失败/被踢，都要清掉在途标记 —— 留着的话，之后任何一个
        // 无关的 401 都会把它误记成「未完成动作」，恢复卡就会乱弹。
        endDurable()
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
