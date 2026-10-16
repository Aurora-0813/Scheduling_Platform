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
    // ["*"] 或具体权限码包含该权限；同时支持**模块级通配** `模块:*`
    hasPermission: (state) => (permission) => {
      const perms = state.userInfo?.permissions || []
      if (perms.includes('*') || perms.includes(permission)) return true
      // 云库里「管理员」存的是 `inspect:*` 这种前缀写法（见 sys_role.permissions），
      // 只做精确匹配的话，他会连自己模块的菜单都看不见 ——
      // 判定口径必须与后端 `core/permissions.py::has_permission` 完全一致。
      const module = String(permission || '').split(':')[0]
      return Boolean(module) && perms.includes(`${module}:*`)
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
