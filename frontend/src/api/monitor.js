import { bizHttp, realHttp } from '@/utils/request'

// GET /monitor/agent 大模型调用统计（真实路由，不鉴权）
export function getAgentMetrics(detail = true) {
  return realHttp.get('/monitor/agent', { params: { detail } })
}

// POST /agent/schedule 智能调度 + 思考链（**真实接口**）
//
// ⚠️ **2026-09-29 改：原先这里有两个走 `/mock/*` 的函数，都是假数据，已删除。**
//
//   1. `simulateMonitor()` → `POST /mock/monitor/simulate`
//      对应页面上「灌入模拟调用（128 次）」按钮 —— 它向后端的指标存储
//      **注入 128 条凭空捏造的调用记录**，把「大模型调用统计」四个 KPI 变成假数字。
//      删除理由：调用统计由 `app/middlewares/agent_metrics.py` 按**真实请求**自动收集，
//      页面上本来就该是真数据；造一批假的只会让人分不清哪些是真调用。
//
//   2. `agentScheduleMock()` → `POST /mock/agent/schedule`
//      展示写死的示例思考链。删除理由：思考链是模块 4 的核心演示点，
//      展示一份**不是模型这次真的跑出来**的时间线，等于把演示变成演戏。
//
// 现在一律走真实接口。代价要说清楚：`/agent/schedule` 在后端会**真的锁资源、
// 落一条 status=1 的待确认预约**（返回体里的 `orderId` 就是它），
// 所以调用方必须让用户知道、并提供确认/取消入口 —— 见 `views/AgentWorkbench.vue`。
//
// **返回值是 `{ data, message }` 而不是裸 data**（`passMessage: true`）：
// 这个接口的**降级路径也是 HTTP 200 + code=200**，此时 `data.plan === null`，
// 而「为什么没有方案」这句话**只在 message 里**
// （见 backend/app/schemas/agent.py::ScheduleData 的降级口径表）。
// 只回 data 的话，Agent 调度台只能渲染一个空白方案区，用户完全不知道发生了什么。
//
// 历史说明：这里曾同时存在 `agentSchedule`（裸 data）与 `agentScheduleVerbose`
// 两个函数，前者是为了兼容「直接用 `Object.assign(schedule, data)` 的旧调用方」。
// 2026-09-30 调度入口统一收敛到 Agent 调度台后，裸 data 版已无调用方，两函数合并。
export function agentSchedule(data = {}) {
  // ⚠️ 2026-10-13 改：**不再默认发 `fast: true`**。
  //
  // 原实现是 `{ ...data, fast: data.fast !== false }`，即调用方不传就发 true。
  // 这让管理端那对「🧠 深度思考 / ⚡ 快速决策」按钮**永远不起作用**：
  // 后端 /agent/schedule 当时只看请求体里的 fast，压根没读 deepMode 开关。
  // 于是点了「深度思考」高亮会变、后端也真的落盘，但每轮调度还是快速模式 ——
  // 没有多轮思考链、也没有 40~80 秒，用户只会以为「深度思考原来这么快」。
  //
  // 现在的口径（后端 app/core/flags.py::resolve_fast）：
  //   · 不传 fast  → 跟随后端全局开关（**这是本函数的默认行为**）
  //   · fast: true / false → 强制指定，给联调与脚本化调用用
  // 所以这里**原样透传**：data 里没有 fast，请求体里就不会出现这个字段。
  // 不要在客户端替服务端定模式 —— 那正是上面那个缺陷的根因。
  return bizHttp.post(
    '/agent/schedule',
    { ...data },
    { passMessage: true },
  )
}
