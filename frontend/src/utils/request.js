import axios from 'axios'
import { ElMessage } from 'element-plus'

import { tokenStorage } from './auth'

// 《开发流程》8.8：true 时业务接口走 /api/v1/mock/*，false 走真实接口 /api/v1/*
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

const API_PREFIX = '/api/v1'

// 认证相关错误码（后端 auth.py 契约）
const AUTH_ERROR_CODES = [40100, 40102, 40103, 40104, 40105, 40106, 40108, 40109]

// 单例刷新 Promise（后端明确要求：同一时刻只允许一个刷新请求）
let refreshPromise = null

function isAuthUrl(url = '') {
  return url.includes('/auth/login') || url.includes('/auth/refresh') || url.includes('/auth/info')
}

async function redirectToLogin() {
  tokenStorage.clear()
  const routerModule = await import('@/router')
  await routerModule.default.push('/login')
}

function doRefresh() {
  if (!refreshPromise) {
    refreshPromise = realHttp
      .post('/auth/refresh', { refreshToken: tokenStorage.getRefreshToken() })
      .then((data) => {
        tokenStorage.setTokens(data.accessToken, data.refreshToken)
        return data
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

function createInstance(baseURL) {
  const instance = axios.create({ baseURL, timeout: 20000 })

  // 请求拦截：自动带 Authorization: Bearer {token}
  instance.interceptors.request.use((config) => {
    const token = tokenStorage.getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  // 响应拦截：统一解包 { code, message, data }
  instance.interceptors.response.use(
    (response) => {
      const body = response.data
      if (body === null || typeof body !== 'object' || !('code' in body)) {
        return body
      }
      if (body.code === 200) {
        return body.data
      }
      return handleBizError(body, response, instance)
    },
    (error) => {
      const config = error.config || {}
      const silent = isAuthUrl(config.url) || config._silent
      if (!silent) {
        ElMessage.error('网络请求失败，请确认后端已启动（127.0.0.1:8000）')
      }
      return Promise.reject({ code: -1, message: error.message, error })
    },
  )

  return instance
}

async function handleBizError(body, response, instance) {
  const { code, message } = body
  const config = response.config

  // 40103 令牌过期：刷新一次后重放原请求
  if (code === 40103 && !config._retried) {
    config._retried = true
    try {
      await doRefresh()
      config.headers.Authorization = `Bearer ${tokenStorage.getAccessToken()}`
      return await instance(config)
    } catch {
      if (!isAuthUrl(config.url)) {
        ElMessage.error('登录已过期，请重新登录')
        await redirectToLogin()
      }
      return Promise.reject(body)
    }
  }

  // 其他认证类错误：登录/刷新接口自己处理，其余清会话回登录页
  if (AUTH_ERROR_CODES.includes(code)) {
    if (!isAuthUrl(config.url)) {
      ElMessage.error(message || '认证失败，请重新登录')
      await redirectToLogin()
    }
    return Promise.reject(body)
  }

  // 权限不足及其余业务错误：弹提示
  if (!isAuthUrl(config.url)) {
    ElMessage.error(message || '请求失败')
  }
  return Promise.reject(body)
}

// 真实接口实例（登录/用户信息/监控等真实路由）
export const realHttp = createInstance(API_PREFIX)

// 业务接口实例：mock 开关切换 baseURL，业务代码无需改动
export const bizHttp = createInstance(USE_MOCK ? `${API_PREFIX}/mock` : API_PREFIX)

export default realHttp
