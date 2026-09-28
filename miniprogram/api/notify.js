import request from '@/utils/request'

export const getMessages = (params = {}) =>
  request({ url: '/api/v1/messages', data: params })
export const getUnreadCount = () => request({ url: '/api/v1/messages/unread' })
export const readMessage = (id) =>
  request({ url: `/api/v1/messages/${id}/read`, method: 'PUT' })
export const readAllMessages = () =>
  request({ url: '/api/v1/messages/read-all', method: 'PUT' })
