<template>
  <div class="sp-layout">
    <!-- ==================== 侧栏 ==================== -->
    <aside class="sp-side">
      <div class="sp-logo">
        <i>◈</i>
        <span class="sp-logo-tx">AI 调度中台</span>
      </div>

      <nav class="sp-nav">
        <router-link v-for="item in menuItems" :key="item.path" :to="item.path" class="sp-si">
          <el-icon class="sp-si-ic"><component :is="item.icon" /></el-icon>
          <span class="sp-si-tx">{{ item.title }}</span>
        </router-link>
      </nav>

      <div class="sp-side-foot">
        <div class="sp-aibox">
          <b><span class="sp-live"></span> {{ statusTitle }}</b>
          {{ statusLine1 }}<br />{{ statusLine2 }}
        </div>
      </div>
    </aside>

    <!-- ==================== 右侧主体 ==================== -->
    <div class="sp-body">
      <header class="sp-head">
        <span class="sp-crumb">{{ crumb }}</span>
        <span class="sp-grow"></span>
        <span class="sp-tag is-purple">LangChain 1.x</span>
        <span class="sp-tag is-green"><span class="sp-live"></span> 服务正常</span>
        <el-dropdown @command="onCommand">
          <span class="sp-user">
            <span class="sp-avatar">{{ avatarText }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">
                <el-icon><User /></el-icon>个人中心
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>

      <main class="sp-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
// 侧栏图标（2026-10-14 由 emoji 换成线性图标集）
//
// ⚠️ 为什么不再用 emoji：emoji 是「AI 概念稿」最直观的签名之一，
//    而且各平台渲染不一致（Windows 的彩色 emoji 与 macOS 差别很大，
//    同一排图标里风格也难统一）。换成单色线性图标后，
//    图标只承担「这是什么入口」的信息职责，不再抢注意力。
import {
  Calendar,
  Crop,
  DataAnalysis,
  DataBoard,
  Monitor,
  OfficeBuilding,
  Tickets,
  VideoCameraFilled,
} from '@element-plus/icons-vue'

import { getAgentMetrics } from '@/api/monitor'
import { useAuthStore } from '@/store/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

/**
 * 侧栏导航 —— **显式列出**，不再从 router 自动推导。
 *
 * 原型 `docs/new_web.html` 定义了 6 项主导航；本平台在此基础上**多一项
 * 「预约单」**：原型的预约单入口只在 Agent 工作台的「确认并创建预约」按钮里，
 * 建完单之后没有任何地方能再看到/确认/取消它，这是本轮要补的缺口。
 *
 * 「冲突预警」「用户权限」不在主导航里（前者已并入预约日历右侧的 AI 软冲突雷达，
 * 后者在右上角头像菜单），但路由与页面都保留，没有删任何功能。
 */
const ALL_MENU_ITEMS = [
  { path: '/agent', title: 'Agent 调度台', icon: DataBoard },
  // 预约日历是管理视角（含全库占用的软冲突雷达），普通用户不显示；口径同 router 的 meta.permission
  { path: '/calendar', title: '预约日历', icon: Calendar, permission: 'order:approve' },
  { path: '/orders', title: '预约单', icon: Tickets },
  // 草图预约：所有人可用（建单是普通用户的固有能力，故不挂 permission）
  { path: '/sketch', title: '草图预约', icon: Crop },
  { path: '/resources', title: '资源与设备', icon: OfficeBuilding },
  // 巡检是「工作人员」的活：普通用户没有 inspect:view，这一项对他就该不显示。
  // 后端已给 4 个巡检接口挂 require_permission（同一口径）——
  // 前端多显示一个入口 = 点进去直接吃 403，比不显示更糟。
  { path: '/inspect', title: 'AI 智能巡检', icon: VideoCameraFilled, permission: 'inspect:view' },
  // AI 数据洞察 / Agent 监控是**管理与运维视角**，普通用户不显示（应用户要求，2026-10-14）。
  //
  // 权限码用的是库/代码里**已有**的定义，没有发明新码：
  //   · 数据洞察 → dashboard:view（管理员有 dashboard:*）
  //   · 调用监控 → monitor:view（系统管理员有 *）
  // ⚠️ 云库 sys_role.permissions 原先**没有** dashboard:* / monitor:*，
  //    只挂权限码的话会连管理员一起挡掉，所以本次同步补齐了角色权限（见下）。
  { path: '/dashboard', title: 'AI 数据洞察', icon: DataAnalysis, permission: 'dashboard:view' },
  { path: '/monitor', title: 'Agent 监控', icon: Monitor, permission: 'monitor:view' },
]

// 只对**声明了 permission 的**项做过滤：其余项的口径尚未与云库权限码对齐
// （库里是 `space:query`/`order:add`，代码常量是 `resource:view`/`order:create`），
// 贸然给它们全加上过滤会让用户凭空丢菜单。
const menuItems = computed(() =>
  ALL_MENU_ITEMS.filter((item) => !item.permission || authStore.hasPermission(item.permission)),
)

const crumb = computed(() => {
  const group = route.meta?.group
  const title = route.meta?.title
  return group && title ? `${group} / ${title}` : title || ''
})

const avatarText = computed(() => (authStore.userInfo?.username || '管').slice(0, 1).toUpperCase())

/* ---------------------------------------------------------------
   侧栏底部状态盒：数字来自真实的 GET /monitor/agent。
   刻意**不写死**任何数字 —— 拿不到就退回一句纯状态描述，不编数据。
   --------------------------------------------------------------- */
const metrics = ref(null)

const statusTitle = computed(() => (metrics.value ? 'Agent 运行中' : '服务正常'))

const statusLine1 = computed(() =>
  metrics.value ? `累计调用 ${metrics.value.totalCalls ?? 0} 次` : 'FastAPI · LangChain · MySQL',
)

const statusLine2 = computed(() => {
  if (!metrics.value) return '实时指标加载中…'
  const rate = metrics.value.successRate
  return rate === undefined || rate === null ? '成功率 —' : `成功率 ${rate}%`
})

onMounted(async () => {
  if (!authStore.userInfo) {
    try {
      await authStore.fetchUserInfo()
    } catch {
      // 守卫之外的兜底，忽略
    }
  }
  try {
    metrics.value = await getAgentMetrics()
  } catch {
    // 侧栏指标拿不到不该影响主流程
    metrics.value = null
  }
})

async function onCommand(command) {
  if (command === 'profile') {
    await router.push('/profile')
  } else if (command === 'logout') {
    await authStore.logout()
    await router.push('/login')
  }
}
</script>

<style scoped>
.sp-layout {
  display: flex;
  /* 不设 height：布局高度由内容决定，页面因此获得**文档级滚动**（见 styles/index.css 说明） */
  align-items: stretch;
}

/* ---------------- 侧栏 ---------------- */
.sp-side {
  width: var(--sp-side-w);
  flex: none;
  background: #fff;
  border-right: 1px solid var(--sp-border-l);
  display: flex;
  flex-direction: column;
  /*
   * 贴顶。父级 .sp-layout 已不再限高，侧栏如果什么都不做就会跟着内容滚走；
   * sticky 让它留在视口内，同时**不改动布局流**（不会像 fixed 那样需要补偏移）。
   * height: 100vh 是为了让底部的状态盒贴在视口下沿，而不是飘在长页面的中间。
   */
  position: sticky;
  top: 0;
  height: 100vh;
}

.sp-logo .sp-logo-tx {
  white-space: nowrap;
}

.sp-si .sp-si-tx {
  white-space: nowrap;
}

.sp-logo {
  display: flex;
  align-items: center;
  gap: var(--sp-s2);
  padding: 16px 18px;
  border-bottom: 1px solid var(--sp-border-l);
  font-size: 14.5px;
  font-weight: 700;
  color: var(--sp-text);
}

.sp-logo i {
  width: 27px;
  height: 27px;
  border-radius: var(--sp-r-sm);
  font-style: normal;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  /* 原为 var(--sp-ai-gradient)（蓝紫渐变）+ 蓝色发光阴影；
     改为单一主色实底、去发光 —— 与全局「轻阴影」口径一致。 */
  background: var(--sp-accent);
}

.sp-nav {
  flex: 1;
  padding-top: 8px;
  overflow-y: auto;
}

.sp-si {
  display: flex;
  align-items: center;
  gap: var(--sp-s2);
  padding: 10px 18px;
  /* 触控/点击区域高度 ≥40px：侧栏项是主要导航，太矮不好点 */
  min-height: 40px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--sp-t2);
  text-decoration: none;
  transition:
    background-color var(--sp-dur) var(--sp-ease),
    color var(--sp-dur) var(--sp-ease);
}

.sp-si:hover {
  background: var(--sp-bg-hover);
  color: var(--sp-text);
}

/* 键盘可达：路由项本是 <a>，必须有可见焦点 */
.sp-si:focus-visible {
  outline: none;
  box-shadow: var(--sp-focus);
  border-radius: var(--sp-r-sm);
}

.sp-si.router-link-active {
  color: var(--sp-accent);
  font-weight: 600;
  background: var(--sp-sidebar-active);
  box-shadow: inset 3px 0 0 var(--sp-accent);
}

/*
 * 侧栏图标。
 *
 * 原先是「一个字符宽 16px + font-size 14px」—— 因为那时用的是 emoji，
 * 只能靠字号控制视觉大小。现在换成 SVG 图标组件，改为固定方格 +
 * 统一描边色：图标大小与基线才能和中文标题严格对齐（emoji 做不到这点，
 * 不同字形的高度差异会让标题看起来参差不齐）。
 */
.sp-si-ic {
  width: 18px;
  height: 18px;
  flex: none;
  font-size: 16px;
  color: var(--sp-t3);
  transition: color var(--sp-dur) var(--sp-ease);
}

.sp-si:hover .sp-si-ic {
  color: var(--sp-t2);
}

.sp-si.router-link-active .sp-si-ic {
  color: var(--sp-accent);
}

.sp-side-foot {
  padding: 12px 14px;
  border-top: 1px solid var(--sp-border-l);
}

.sp-aibox {
  /* 原为 135deg 浅蓝→浅紫渐变（配 --sp-ai-line）；
     改为单一浅蓝实底 —— 该处只是侧栏的一段说明文字，不需要装饰。 */
  background: var(--sp-accent-bg);
  border: 1px solid var(--sp-accent-line);
  border-radius: var(--sp-r-md);
  padding: 10px 12px;
  font-size: 12px;
  color: var(--sp-t2);
  line-height: 1.6;
}

.sp-aibox b {
  display: flex;
  align-items: center;
  gap: var(--sp-s1);
  font-size: 12px;
  color: var(--sp-text);
  margin-bottom: 5px;
}

/* ---------------- 主体 ---------------- */
.sp-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--sp-bg);
}

.sp-head {
  height: var(--sp-head-h);
  flex: none;
  background: #fff;
  border-bottom: 1px solid var(--sp-border-l);
  display: flex;
  align-items: center;
  gap: var(--sp-s3);
  padding: 0 var(--sp-s5);
  font-size: 13px;
  color: var(--sp-t3);
}

.sp-crumb {
  font-size: 13px;
  color: var(--sp-t3);
}

.sp-user {
  display: flex;
  align-items: center;
  cursor: pointer;
  outline: none;
}

.sp-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: #fff;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 原为渐变；头像用单一主色即可。 */
  background: var(--sp-accent);
}

/*
 * 主内容列。
 *
 * ⚠️ 两条关键约定（都是 2026-10-14 按使用反馈定的）：
 *
 * 1. **不限宽**，跟屏幕自适应。
 *    中间版本曾限到 1200px 居中，出发点是「超宽屏下一行字太长」。但实际很别扭：
 *    本端是后台系统，页面主体是「左筛选/输入 + 右台账表格/思考链」这类多列密集布局，
 *    限宽之后两侧留白很大、中间列反而被压窄，表格更容易挤到换行，
 *    留白并没换来可读性。管理端要**把屏幕用满**，与「文章页控制阅读行宽」目标相反。
 *    将来要做长文类页面，用 styles/index.css 的 `.sp-container` 局部包一层即可。
 *
 * 2. **不设 overflow**，滚动交给文档。
 *    之前它是全站唯一的滚动容器（实测内容 895 > 容器 644），于是顶栏与侧栏永远不动、
 *    滚动条看着像贴在整块右侧、跟实际内容对不上。现在页面按内容自然增高，
 *    滚动条由浏览器加在文档上随内容总高走（侧栏用 sticky 留在视口内，见 .sp-side）。
 */
.sp-main {
  /*
   * ⚠️ 这里**不用 flex: 1**（2026-10-14 修）。
   *
   * `.sp-body` 是 flex 列，给 .sp-main 加 flex:1 会让它**被拉伸到填满视口**。
   * 后果不是「更好看」，而是把页面垫高到视口以上：实测资源页在 820 视口下
   * `.sp-main` 的 clientHeight 是 877（超出视口 57px），页面因此照样出现滚动条 ——
   * 而表格容器明明已经收在 max-height 之内。
   *
   * 去掉拉伸后高度由内容决定：内容少时页面就矮（.sp-body 有背景，不会露白），
   * 内容多时由各块自己的 max-height 兜住。
   */
  flex: 0 0 auto;
  padding: var(--sp-s3) var(--sp-s5);
  width: 100%;
  max-width: none;
  margin: 0;
}

/* ============================================================
 * 响应式断点
 * ------------------------------------------------------------
 * 加这一段之前，本 Web 端**没有任何骨架级断点**：侧栏固定 216px，
 * 页面内的多列又都是固定宽（如 AgentWorkbench 的 .agcol.is-side 326px）。
 * 于是窄屏下侧栏吃掉大半宽度、内容被挤成「一个字一行」，
 * 文档还会横向溢出（390px 视口下实测 documentElement.scrollWidth 远超视口）。
 *
 * 处理原则：**只改布局，不动信息架构**。
 *   · 侧栏在窄屏收成「图标竖栏」，不是隐藏 —— 页面里没有汉堡菜单，
 *     真隐藏会让导航彻底点不到。图标本身带 title（见模板），悬停可读。
 *   · 多列改单列，顺序不变。
 * ============================================================ */

@media (max-width: 1200px) {
  /* 顶栏面包屑在窄屏最先该让位（它是位置提示，不是操作） */
  .sp-crumb {
    display: none;
  }
}

@media (max-width: 900px) {
  :root,
  .sp-layout {
    --sp-side-w: 64px;
  }

  .sp-logo {
    justify-content: center;
    padding: 0;
  }

  /*
   * ⚠️ 侧栏项在模板里是「图标 + 一个**裸文本节点**」（没有独立的包裹元素），
   *    所以无法单独给文本加 display:none。
   *    用 font-size:0 让裸文本零尺寸，再把图标字号显式设回来 —— 这是
   *    处理「无法改结构的裸文本」的标准做法，比为了样式去动模板结构稳。
   */
  .sp-si {
    font-size: 0;
    justify-content: center;
    padding: 10px 0;
    gap: 0;
  }

  .sp-si .sp-si-ic {
    font-size: 18px;
  }

  .sp-logo .sp-logo-tx,
  .sp-si .sp-si-tx {
    display: none;
  }

  .sp-side-foot {
    padding: 10px 8px;
  }

  .sp-aibox {
    font-size: 0;
    padding: 8px;
    text-align: center;
  }

  .sp-aibox b {
    font-size: 0;
    margin-bottom: 0;
    justify-content: center;
  }

  .sp-main {
    padding: var(--sp-s3);
  }
}

@media (max-width: 640px) {
  .sp-head {
    padding: 0 var(--sp-s3);
    gap: var(--sp-s2);
  }

  /* 顶栏的版本号标签在手机宽度下没有信息价值，优先让位给状态与头像 */
  .sp-head .sp-tag.is-purple {
    display: none;
  }
}
</style>
