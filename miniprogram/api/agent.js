/**
 * 模块 4：核心调度 Agent
 *
 * 契约：POST /agent/schedule  { text, imageContext } → { plan, backupPlan, trace[], needConfirm }
 *   trace 每一项含 step / result / timestamp，另带 thought / action / actionInput / observation。
 *
 * ⚠️ 两个已知的字段不一致，页面渲染时必须容忍：
 *   1. `trace[].actionInput` 的键是 **snake_case**（space_type / start_time /
 *      device_ids），因为它是后端 Tool 函数签名的原样回显，与其余 camelCase
 *      字段不同。前端只做 JSON 展示，不要按 camelCase 去取值。
 *   2. 冻结的 Plan schema 里**没有价格字段**，金额只出现在 `plan.reason`
 *      散文里。因此方案卡的大号价格需要可缺省渲染。
 *
 * 真源数据：后端 docs/mock/agent_schedule.json（前端与后端共用同一份）。
 */
import { request } from '@/api/request.js'

/**
 * 提交自然语言需求，生成调度方案
 * @param {object} payload
 * @param {string} payload.text 用户原始需求（口述或文字）
 * @param {object} [payload.imageContext] 来自拍照识场的上下文
 * @returns {Promise<object>} { plan, backupPlan, trace[], needConfirm }
 */
export function schedule(payload) {
  return request({
    path: '/agent/schedule',
    method: 'POST',
    data: {
      text: payload.text || '',
      imageContext: payload.imageContext || {},
    },
  })
}

/**
 * 把一帧思考链的 actionInput 渲染成一行代码回显。
 * actionInput 可能是 null（纯推理步）、对象或字符串。
 */
export function formatActionInput(actionInput) {
  if (actionInput === null || actionInput === undefined) return ''
  if (typeof actionInput === 'string') return actionInput
  try {
    return JSON.stringify(actionInput)
  } catch (e) {
    return ''
  }
}

export default { schedule, formatActionInput }
