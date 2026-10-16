/**
 * 模块 4：核心调度 Agent
 *
 * 契约：POST /agent/schedule  { text, imageContext } → { plan, backupPlan, trace[], needConfirm }
 *   trace 每一项含 step / result / timestamp，另带 thought / action / actionInput / observation。
 * 契约：POST /agent/parse     { text, imageContext } → { conditions, recommend, confidence, latencyMs }
 *   一次模型调用，**不建单**；产出「AI 读出了什么」，供确认页预填 —— 见下方 parseRequest()。
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
export function schedule(payload = {}) {
  return request({
    path: '/agent/schedule',
    method: 'POST',
    data: {
      text: payload.text || '',
      imageContext: payload.imageContext || {},
      // ⚠️ 2026-10-13 改：**不再默认发 `fast: true`**（原为 `payload.fast !== false`）。
      // 那个默认值让后端的「🧠 深度思考 / ⚡ 快速决策」全局开关彻底失效 ——
      // 小程序在客户端就把模式定死了，后端没机会按开关选路。
      //
      // 现在**不传 fast**（请求体里没有这个字段）→ 后端跟全局开关走；
      // 确实需要强制某一档时（联调、脚本）才显式传 `{ fast: true/false }`。
      ...(payload.fast === undefined ? {} : { fast: payload.fast }),
    },
  })
}

/**
 * 把自然语言需求**解析成可编辑的条件清单 + 推荐**（2026-10-13 新增）。
 *
 * 契约：POST /agent/parse  { text, imageContext } → {
 *   conditions: { capacity, spaceType, startTime, endTime, deviceTypes[], budget, missing[] },
 *   recommend:  { spaceId, spaceName, reason, alternatives:[{ spaceId, spaceName, tradeoff }] },
 *   confidence, latencyMs,
 * }
 *
 * ⚠️ 与 `schedule()` 的分工，调用方必须分清：
 *   · `parseRequest` —— **一次模型调用**（实测 10~32 秒，取决于后端 aiRecommend 开关），
 *     **不建单、不锁资源、没有 side effect**。产出是「AI 从我这句话里读出了什么」，
 *     用户改完再走确认页建单。所以它可以被反复调用。
 *   · `schedule` —— 多轮 Agent，**会真的落一条待确认预约**，只能跑一次。
 *
 * 这也正是语音页要它的原因：用户说完话，先把 AI 读出的时间/人数/设备/预算摆出来，
 * 猜错的当场能改；而不是把这句话丢给 Agent 让它直接锁资源下单一轮。
 *
 * @param {object} payload
 * @param {string} payload.text 用户原始需求（口述或文字）
 * @param {object} [payload.imageContext] 来自拍照识场的上下文
 * @returns {Promise<object>} { conditions, recommend, confidence, latencyMs }
 */
export function parseRequest(payload = {}) {
  return request({
    path: '/agent/parse',
    method: 'POST',
    data: {
      text: payload.text || '',
      imageContext: payload.imageContext || {},
    },
    // 这个接口最快也要 10 秒（一次真模型调用），失败原因必须让页面自己说清楚 ——
    // 交给 request.js 弹一句通用 toast，用户看到的只是「请求失败」。
    silent: true,
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

export default { schedule, parseRequest, formatActionInput }
