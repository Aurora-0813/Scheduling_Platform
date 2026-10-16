import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/store/auth'
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
        // 预约日历是**管理视角**（含全库占用的 AI 软冲突雷达），普通用户不展示。
        // `order:approve` 是「能否管理全部预约」的判别码：
        //   管理员库里是 `order:*` → 命中；普通用户只有 order:add/list/cancel → 不命中。
        meta: { title: '日历视图', group: '预约管理', permission: 'order:approve' },
      },
      {
        // 草图预约（2026-10-13 新增）：手绘草图 → AI 识别人数/布局 → 手动补设备 +
        // 15 分钟档选时间 → 查该时段可用场地 → 建单。
        // **不加 meta.permission**：建单是普通用户本来就有的能力（库里是 `order:add`），
        // 加了反而会把普通用户挡在门外。
        path: 'sketch',
        name: 'SketchReserve',
        component: () => import('@/views/SketchReserve.vue'),
        meta: { title: '草图预约', group: '预约管理' },
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
        // 普通用户不展示「AI 数据洞察」。侧栏隐藏只是看不见，直接输 /dashboard
        // 仍然进得来 —— 路由层必须用同一口径再挡一次（与下面 monitor 一致）。
        meta: { title: 'AI 数据洞察', group: '数据中心', permission: 'dashboard:view' },
      },
      {
        path: 'conflicts',
        name: 'Conflicts',
        component: () => import('@/views/Conflicts.vue'),
        // 冲突扫描会遍历**全库活跃订单**、暴露他人的占用情况，普通用户不该看。
        // 它不在侧栏菜单里（见文件头说明），但路由存在 —— 不加这行的话
        // 普通用户直接输 /conflicts 就能进去。
        meta: { title: '冲突预警', group: '预约管理', permission: 'conflict:view' },
      },
      {
        path: 'monitor',
        name: 'Monitor',
        component: () => import('@/views/AgentMonitor.vue'),
        // 同上：普通用户不展示「Agent 监控」，路由层同口径。
        // 库里 monitor:view 归系统管理员（管理员角色本次也补了 monitor:*）。
        meta: { title: 'Agent 调用监控', group: '系统集成', permission: 'monitor:view' },
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
// ⚠️ 必须是 `async`：下面的权限守卫要 `await auth.fetchUserInfo()`。
// 写成同步函数的话 `await` 在非 async 函数里是**语法错误**，整个前端白屏。
router.beforeEach(async (to) => {
  document.title = to.meta.title
    ? `${to.meta.title} - AI全感知调度平台`
    : 'AI全感知·智能空间与设备综合调度平台'

  if (to.path === '/login') {
    return true
  }
  if (!tokenStorage.getAccessToken()) {
    return { path: '/login' }
  }

  // 权限守卫（2026-10-13 加）：路由声明了 `meta.permission` 才校验。
  //
  // ⚠️ 刷新页面时 `authStore.userInfo` **还是空的** —— 它由 MainLayout 挂载后才拉，
  //    而守卫跑在挂载之前。直接判会把**所有人**都挡在门外（包括管理员）。
  //    所以这里按需补拉一次；只对声明了权限的路由生效，不增加普通导航的开销。
  if (to.meta && to.meta.permission) {
    let allowed = false
    try {
      const auth = useAuthStore()
      if (!auth.userInfo) {
        await auth.fetchUserInfo()
      }
      allowed = auth.hasPermission(to.meta.permission)
    } catch (e) {
      allowed = false
    }
    if (!allowed) {
      // 落回调度台：它是所有人的公共落地页，不会二次触发权限判定
      return { path: '/agent' }
    }
  }

  return true
})

export default router
