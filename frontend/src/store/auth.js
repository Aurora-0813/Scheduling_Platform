import { defineStore } from 'pinia'

import * as authApi from '@/api/auth'
import { tokenStorage } from '@/utils/auth'

// 认证状态（《开发流程》7.2：Pinia 按模块分 store）
export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: tokenStorage.getAccessToken(),
    userInfo: null,
  }),
  getters: {
    isLogin: (state) => Boolean(state.accessToken),
    permissions: (state) => state.userInfo?.permissions || [],
    // ["*"] 或具体权限码包含该权限
    hasPermission: (state) => (permission) => {
      const perms = state.userInfo?.permissions || []
      return perms.includes('*') || perms.includes(permission)
    },
  },
  actions: {
    async login(username, password) {
      const data = await authApi.login(username, password)
      this.accessToken = data.accessToken
      tokenStorage.setTokens(data.accessToken, data.refreshToken)
      return data
    },
    async fetchUserInfo() {
      this.userInfo = await authApi.getInfo()
      return this.userInfo
    },
    async logout() {
      await authApi.logout()
      this.reset()
    },
    reset() {
      this.accessToken = ''
      this.userInfo = null
      tokenStorage.clear()
    },
  },
})
