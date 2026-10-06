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

// PUT /tickets/{ticketId}/status 处理工单（只改状态，人工决定）
export function updateTicketStatus(ticketId, data) {
  return bizHttp.put(`/tickets/${ticketId}/status`, data)
}

// POST /tickets/{ticketId}/handle 提交处理结果照片 + AI 核验
//
// 与 updateTicketStatus 的分工（见 backend/app/api/inspection.py 的模块文档）：
//   updateTicketStatus → **人工**决定（到场发现是误报，直接标完成）
//   handleTicket       → **机器**判定（照片经 AI 核验通过才置完成）
//
// 返回 { passed, verifyStatus, verifyReport, status, statusText, handleImageUrl, ... }，
// 其中 `passed` 由后端算好，前端**不要**自己拿 verifyStatus 和字符串比 ——
// 「哪个取值算通过」是业务口径，只应在后端定义一次。
// 返回 { data, message }（passMessage: true）。
// 需要 message 的原因：**核验未通过也是 HTTP 200 + code=200**，
// 而「未通过」这句人话由后端按判定结果拼好（见 inspection.py 的 ticket_handle），
// 只回 data 的话前端还得自己拼一遍，两处口径会漂移。
export function handleTicket(ticketId, file) {
  const formData = new FormData()
  formData.append('file', file)
  return bizHttp.post(`/tickets/${ticketId}/handle`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    passMessage: true,
  })
}
