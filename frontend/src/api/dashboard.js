import { bizHttp } from '@/utils/request'

// 模块 8：AI 数据洞察面板
// GET /dashboard/stats 面板统计
export function getDashboardStats() {
  return bizHttp.get('/dashboard/stats')
}

// GET /dashboard/report 洞察报告
export function getDashboardReport() {
  return bizHttp.get('/dashboard/report')
}
