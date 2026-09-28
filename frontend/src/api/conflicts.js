import { bizHttp } from '@/utils/request'

// 模块 7：AI 冲突预警与智能通知
// GET /conflicts/scan 冲突扫描（data 为数组）
export function scanConflicts() {
  return bizHttp.get('/conflicts/scan')
}

// POST /notify/generate 生成通知文案
export function generateNotify(data) {
  return bizHttp.post('/notify/generate', data)
}
