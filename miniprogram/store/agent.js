/**
 * Agent 调度 store
 *
 * 为什么需要它：M2 收集需求 → M3 展示思考链 → M4 确认方案，是三个独立页面。
 * `/agent/schedule` 只应调用一次（后端内部会锁资源），若每个页面各拉一次，
 * 既浪费也会产生重复订单。因此把「原始需求 + 返回结果」放在这里跨页共享。
 *
 * 页面返回值不是流式的：后端一次性返回完整 trace，M3 的分步显现是前端
 * 按真实 steps 逐条播出的动画，不是伪造的进度。
 */
import { reactive } from 'vue'
import { schedule } from '@/api/agent.js'

export const agentStore = reactive({
  /** 用户原始需求（口述文本或规整后的文本） */
  request: '',
  /** 拍照识场带过来的上下文，可为空 */
  imageContext: null,
  /** POST /agent/schedule 的完整返回 */
  payload: null,
  loading: false,
  error: '',
  /**
   * 方案生成失败时 Agent 对用户说的那句话（"请您补充使用时间…"）。
   *
   * 后端返回体里没有独立的消息字段，这句话只躺在 `trace` 最后一步的 `result` 里。
   * 存在这里是为了把它带到语音页当提示 —— 否则用户只看到「还没有生成方案」，
   * 不知道自己该补什么。
   */
  lastQuestion: '',
})

/**
 * 发起调度。已有结果且需求未变时直接复用，避免重复下单。
 * @param {string} text 用户需求
 * @param {object} [imageContext]
 * @param {boolean} [force] 强制重新调度
 */
export async function runSchedule(text, imageContext, force) {
  const sameRequest = text === agentStore.request
  if (!force && sameRequest && agentStore.payload) return agentStore.payload

  agentStore.request = text
  // ⚠️ 2026-09-30 修：只有**显式传了**才覆盖 imageContext。
  // 原写法是 `imageContext = imageContext || null`，而 thinking.vue 调的是
  // runSchedule(agentStore.request) —— **根本不传第二个参数**，
  // 于是 recognize.vue 刚放进去的识别结果被当场抹成 null。
  // 结果就是「拍照识场 → 核心调度 Agent」这条通道三处全断，
  // 后端拿到的 imageContext 永远是 {}，只能从一句话里重新猜场地。
  if (imageContext !== undefined && imageContext !== null) {
    agentStore.imageContext = imageContext
  }
  agentStore.payload = null
  agentStore.error = ''
  // 新一轮调度开始，上一次的追问作废
  agentStore.lastQuestion = ''
  agentStore.loading = true

  try {
    const data = await schedule({ text, imageContext: agentStore.imageContext || {} })
    agentStore.payload = data
    return data
  } catch (e) {
    agentStore.error = e.message || 'AI 调度失败'
    throw e
  } finally {
    agentStore.loading = false
  }
}

/** 方案确认落库后清空，避免下次进入沿用旧方案 */
export function resetAgent() {
  agentStore.request = ''
  agentStore.imageContext = null
  agentStore.payload = null
  agentStore.error = ''
  agentStore.lastQuestion = ''
  agentStore.loading = false
}

export default { agentStore, runSchedule, resetAgent }
