import { createRouter, createWebHistory } from 'vue-router'

import { tokenStorage } from '@/utils/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: 'AI 数据洞察', icon: 'DataAnalysis' },
      },
      {
        path: 'calendar',
        name: 'Calendar',
        component: () => import('@/views/Calendar.vue'),
        meta: { title: '预约日历', icon: 'Calendar' },
      },
      {
        path: 'resources',
        name: 'Resources',
        component: () => import('@/views/Resources.vue'),
        meta: { title: '资源与设备', icon: 'Files' },
      },
      {
        path: 'inspect',
        name: 'Inspect',
        component: () => import('@/views/Inspect.vue'),
        meta: { title: '巡检与工单', icon: 'Tools' },
      },
      {
        path: 'conflicts',
        name: 'Conflicts',
        component: () => import('@/views/Conflicts.vue'),
        meta: { title: '冲突预警', icon: 'Warning' },
      },
      {
        path: 'monitor',
        name: 'Monitor',
        component: () => import('@/views/AgentMonitor.vue'),
        meta: { title: 'Agent 监控', icon: 'Monitor' },
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/Profile.vue'),
        meta: { title: '用户权限', icon: 'User' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 登录守卫：没 token 一律回登录页
router.beforeEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} - AI全感知调度平台`
    : 'AI全感知·智能空间与设备综合调度平台'

  if (to.path === '/login') {
    return true
  }
  if (!tokenStorage.getAccessToken()) {
    return { path: '/login' }
  }
  return true
})

export default router
