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
export function agentSchedule(data) {
  return bizHttp.post('/agent/schedule', data, { passMessage: true })
}
