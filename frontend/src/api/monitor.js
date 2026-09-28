import { bizHttp, realHttp } from '@/utils/request'

// GET /monitor/agent 大模型调用统计（真实路由，不鉴权）
export function getAgentMetrics(detail = true) {
  return realHttp.get('/monitor/agent', { params: { detail } })
}

// POST /mock/monitor/simulate 灌入模拟调用数据（仅 DEBUG）
export function simulateMonitor(params) {
  return realHttp.post('/mock/monitor/simulate', null, { params })
}

// POST /agent/schedule 智能调度 + 思考链（mock 模式走 /mock/agent/schedule）
export function agentSchedule(data = {}) {
  return bizHttp.post('/agent/schedule', data)
}
