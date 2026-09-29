import { createRouter, createWebHistory } from 'vue-router'

import { tokenStorage } from '@/utils/auth'

/**
 * 路由表。
 *
 * meta.group 用于顶栏面包屑（"AI 能力中台 / 核心调度 Agent"），
 * meta.title 同时用于 `document.title`。
 *
 * 侧栏导航**不**从这里推导 —— 它显式写在 `layouts/MainLayout.vue` 的
 * `menuItems` 里（顺序对齐原型 `docs/new_web.html`）。所以这里出现
 * 但没有进侧栏的路由（/conflicts、/profile）是有意的，不是漏配。
 */
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
    redirect: '/agent',
    children: [
      {
        path: 'agent',
        name: 'AgentWorkbench',
        component: () => import('@/views/AgentWorkbench.vue'),
        meta: { title: '核心调度 Agent', group: 'AI 能力中台' },
      },
      {
        path: 'calendar',
        name: 'Calendar',
        component: () => import('@/views/Calendar.vue'),
        meta: { title: '日历视图', group: '预约管理' },
      },
      {
        path: 'orders',
        name: 'Orders',
        component: () => import('@/views/Orders.vue'),
        meta: { title: '预约单管理', group: '预约管理' },
      },
      {
        path: 'resources',
        name: 'Resources',
        component: () => import('@/views/Resources.vue'),
        meta: { title: '资源与设备', group: '资源管理' },
      },
      {
        path: 'inspect',
        name: 'Inspect',
        component: () => import('@/views/Inspect.vue'),
        meta: { title: 'AI 智能巡检', group: '运维管理' },
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: 'AI 数据洞察', group: '数据中心' },
      },
      {
        path: 'conflicts',
        name: 'Conflicts',
        component: () => import('@/views/Conflicts.vue'),
        meta: { title: '冲突预警', group: '预约管理' },
      },
      {
        path: 'monitor',
        name: 'Monitor',
        component: () => import('@/views/AgentMonitor.vue'),
        meta: { title: 'Agent 调用监控', group: '系统集成' },
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('@/views/Profile.vue'),
        meta: { title: '个人中心' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/agent' },
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
