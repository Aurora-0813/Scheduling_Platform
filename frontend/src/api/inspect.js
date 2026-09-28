import { bizHttp } from '@/utils/request'

// 模块 6：AI 智能巡检与维修工单
// POST /inspect/submit 提交巡检（FormData：file + spaceId）
export function submitInspect(file, spaceId) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('spaceId', spaceId)
  return bizHttp.post('/inspect/submit', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// GET /tickets/list 工单列表
export function getTickets(params = {}) {
  return bizHttp.get('/tickets/list', { params })
}

// PUT /tickets/{ticketId}/status 处理工单
export function updateTicketStatus(ticketId, data) {
  return bizHttp.put(`/tickets/${ticketId}/status`, data)
}
