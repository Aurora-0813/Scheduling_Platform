import { realHttp } from '@/utils/request'
import { tokenStorage } from '@/utils/auth'

// 认证接口。
//
// ⚠️ **2026-09-30 删除了「演示兜底会话」（`DEMO_USER` + `makeDemoToken`）。**
//
// 原行为：`USE_MOCK=true` 且 `/auth/login` 请求失败时，**完全忽略用户名与口令**，
// 直接在浏览器本地塞一个假 token 和 `permissions: ['*']` 的超级管理员对象，
// 页头挂一个「演示模式」标签。**后端全程不知道这个会话存在** ——
// 那个 `demo.<base64>.sig` 令牌从没被任何服务端校验过。
//
// 删除理由：
//   1. 它是一条**免密登录**路径：开关一开，随便填什么都能进管理端且拿满权限。
//   2. 它的触发条件（后端不可达）恰恰是最不该放行的时刻 —— 数据库挂了、隧道断了
//      的时候，它反而会让人以为「系统是好的」，把故障藏起来。
//   3. 已有可用的真实测试账号（见 `docs/seed.sql`），兜底会话没有存在必要。
//
// 现在登录只有一个结果：拿到真实 JWT，或者失败并如实报错。

// 登录：POST /auth/login
export function login(username, password) {
    return realHttp.post('/auth/login', { username, password })
}

// 当前用户信息：GET /auth/info
export function getInfo() {
    return realHttp.get('/auth/info')
}

// 登出：POST /auth/logout
//
// 失败一律吞掉：登出是「尽力而为」的收尾动作，后端不可达时不该把用户卡在页面上。
export function logout() {
    return realHttp
        .post('/auth/logout', { refreshToken: tokenStorage.getRefreshToken() })
        .catch(() => { })
}
