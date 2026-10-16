<template>
    <div class="login">
        <!-- 左：品牌区（原型 .login-l：点阵 + 光晕 + 徽标 + 能力点） -->
        <div class="login-l">
            <div class="dotgrid"></div>
            <div class="orb a"></div>
            <div class="orb b"></div>

            <div class="inner">
                <div class="ll-badge">
                    <span class="sp-live"></span>
                    LangChain Agent 中台 · 在线
                </div>
                <h2>让空间与设备<br />听懂你的每一句话</h2>
                <p class="sub">
                    多模态感知 → Agent 智能决策 → 业务自动落库<br />
                    全链路异步架构 · 思考过程全程可视化
                </p>
                <div class="ll-feat">
                    <div><i>◈</i>口述一句模糊需求，Agent 自动解析并排冲突</div>
                    <div><i>◈</i>拍照识空间、拍图查故障，多模态直达业务单据</div>
                    <div><i>◈</i>Thought → Action → Observation 推理链实时可见</div>
                </div>
            </div>

            <div class="ll-foot">PC Web 管理端 · AI 全感知调度平台</div>
        </div>

        <!-- 右：登录表单（原型 .login-r：.field / .inputx / .btn.ai.block） -->
        <div class="login-r">
            <div class="login-card">
                <h3>账号登录</h3>

                <el-form ref="formRef" class="login-form" :model="form" :rules="rules" size="large" label-position="top"
                    @keyup.enter="onSubmit">
                    <el-form-item label="账号" prop="username">
                        <el-input v-model="form.username" placeholder="请输入用户名" :prefix-icon="User" clearable :disabled="locked" />
                    </el-form-item>
                    <el-form-item label="密码" prop="password">
                        <el-input v-model="form.password" type="password" placeholder="请输入密码" :prefix-icon="Lock"
                            show-password :disabled="locked" />
                    </el-form-item>
                    <el-button type="primary" size="large" class="sp-btn is-ai is-block login-submit" :loading="loading"
                        :disabled="locked" @click="onSubmit">
                        进入 AI 调度中台
                    </el-button>
                    <div v-if="lockHint" class="lock-hint" :class="{ 'is-locked': locked }">{{ lockHint }}</div>
                </el-form>
            </div>
            <div class="login-copy">© 2026 AI全感知调度平台</div>
        </div>
    </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'

import { useAuthStore } from '@/store/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref()
const loading = ref(false)
// 演示用：密码连续输错 3 次，前端假锁定（不改后端，仅前端状态，刷新页面即重置）
const MAX_LOGIN_ATTEMPTS = 3
const failedCount = ref(0)
const locked = ref(false)
const lockHint = ref('')
// 表单**不预填任何凭据**：原先写死的是 { username: 'admin', password: '123456' }，
// 而 123456 根本不是本项目的账号口令（真实口令见 .env / docs/seed.sql），
// 预填一个错的密码只会让人点一次登录就撞一次「用户名或密码错误」。
// 演示账号请写进 README 或口头告知，不要硬编码进源码。
const form = reactive({ username: '', password: '' })

const rules = {
    username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
    password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
    if (locked.value) return
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) return

    loading.value = true
    try {
        await authStore.login(form.username, form.password)
        failedCount.value = 0
        lockHint.value = ''
        // 兜底落到「Agent 调度台」——它是本平台的主入口，
        // 与 router 里 `redirect: '/agent'` 保持同一个口径。
        // （原先兜底到 /dashboard，于是改路由默认页也没用：这里会把它覆盖掉。）
        const redirect = route.query.redirect || '/agent'
        await router.push(redirect)
    } catch {
        failedCount.value += 1
        const left = MAX_LOGIN_ATTEMPTS - failedCount.value
        if (left <= 0) {
            locked.value = true
            lockHint.value = '连续输错 3 次，账号已锁定'
        } else {
            lockHint.value = `用户名或密码错误，还可尝试 ${left} 次`
        }
    } finally {
        loading.value = false
    }
}
</script>

<style scoped>
/*
 * 登录页背景：蓝色主调的简约科技感（2026-10-14）
 *
 * ## 和上一版的关系
 *
 * 上一版把左栏的装饰**全部删光**（蓝紫大渐变 + 点阵 + 两个 blur 光球），
 * 理由是它们属于「AI 概念稿」语言。但删干净之后页面确实偏平、缺少气质。
 * 这一版按「**蓝色单色 + 极低对比 + 静态**」重做装饰，是刻意的折中：
 *
 *   · 只用品牌蓝一个色系（不再出现紫色）—— 紫蓝渐变才是 AI 感的来源，
 *     单色蓝的细网格是标准的技术界面语言；
 *   · 对比度压到「近处看得出、远处几乎看不见」，不与正文争注意力；
 *   · 一个极慢（16s）的呼吸只作用在角落光晕上，不承载任何信息，
 *     且带 prefers-reduced-motion 降级（见本文件末尾）。
 */
@keyframes ll-glow {
    0%,
    100% {
        opacity: 0.55;
        transform: scale(1);
    }
    50% {
        opacity: 0.95;
        transform: scale(1.06);
    }
}

/* 原型登录区是 1440×900 的缩略画布，这里改为铺满浏览器视口并随宽度自适应 */
.login {
    display: flex;
    min-height: 100vh;
    background: #fff;
}

/*
 * 左栏的角落光晕。
 *
 * 用 `.login-l::after` 而不是再加一个 DOM 节点 —— 模板里已有 .orb 两个空 div，
 * 但它们原先各代表「一个色球」，语义上不该被复用来做别的层次。
 * 伪元素是纯视觉层次，不占结构，也不参与无障碍树。
 */
.login-l::after {
    content: '';
    position: absolute;
    top: -160px;
    right: -160px;
    width: 520px;
    height: 520px;
    border-radius: 50%;
    pointer-events: none;
    /* 光晕提亮到白色系：深蓝底上需要一点「亮」，蓝色光晕会看不出来 */
    background: radial-gradient(circle, rgba(255, 255, 255, 0.72), rgba(255, 255, 255, 0) 68%);
    animation: ll-glow 16s ease-in-out infinite;
}

/*
 * 左：品牌区
 *
 * ## 背景的三个层次（自下而上）
 *
 *   1. `.login-l`         — 竖直方向的极浅蓝渐变（#f7fbff → #eef5ff）
 *   2. `.dotgrid`         — 32px 细网格 + 径向遮罩，靠中心可见、向边缘淡出
 *   3. `.login-l::after`  — 右上角一枚极淡的蓝色光晕（16s 呼吸）
 *
 * ## 为什么是「网格」而不是「点阵 + 光球」
 *
 * 原版是 145deg 蓝紫大渐变 + 点阵 + 两个 blur(60px) 模糊光球（一白一紫），
 * 且都带无限缩放动画 —— 那是「AI 概念稿」的典型排版，也是全站最重的 AI 感来源。
 *
 * 现在换成**单色蓝的细网格**：网格是工程/技术界面的常见语汇（图纸、控制台、
 * 数据面板），既给出「科技感」，又不会像彩色光斑那样制造概念稿观感。
 * 紫色彻底不出现（紫蓝渐变才是 AI 感的真正来源）。
 *
 * 文字仍然压在浅底上，所以层级由字号/字重承担 ——
 * 标题 600、正文 t2、辅助 t3，不靠白色透明度区分。
 */
.login-l {
    flex: 1.15;
    min-width: 0;
    position: relative;
    overflow: hidden;
    padding: clamp(36px, 6vw, 74px) clamp(28px, 5vw, 68px);
    color: var(--sp-text);
    display: flex;
    flex-direction: column;
    justify-content: center;
    /*
     * 底色：加深后的蓝（2026-10-14 按反馈「再深一些」调整）。
     *
     * 上一版是 #f7fbff → #eef5ff，几乎是白底，科技感没立住。
     * 现在加深到 #dce9ff → #c9dcfa —— 明显是蓝，但仍属**浅蓝**区间，
     * 所以正文继续用深色文字（--sp-text / --sp-t2 与 #dce9ff 的对比度都在 7:1 以上，
     * 远高于 AA 的 4.5:1）。这样就避免了「深底 + 白字」那套会带来
     * 大面积反白的观感，也保留了左侧要读的三行特性说明的可读性。
     */
    background: linear-gradient(180deg, #dce9ff 0%, #c9dcfa 100%);
    border-right: 1px solid var(--sp-border-l);
}

/*
 * 网格纹理。
 *
 * ⚠️ 遮罩必须用 `radial-gradient(...)` 让边缘淡出，否则整块是均匀网格，
 *    会在右边界形成一条生硬的截断线。淡出之后它才像「背景氛围」而不是「贴图」。
 *
 * 32px 格距偏密，配 1px 细线得到的是「亚毫米方格纸」的观感 ——
 * 比大网格更克制，2x 屏上也不会糊成灰面。
 */
.dotgrid {
    position: absolute;
    inset: 0;
    pointer-events: none;
    /* 网格改用**白色**半透明：底色变深后，蓝线会糊在蓝底里看不见；
       白线才能浮出来，且与「深蓝底 + 白色网格」的技术图纸观感一致。 */
    background-image:
        linear-gradient(rgba(255, 255, 255, 0.55) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.55) 1px, transparent 1px);
    background-size: 32px 32px;
    /* 遮罩中心左移一点，让网格在标题一侧最清楚，向右逐渐散开 */
    -webkit-mask-image: radial-gradient(115% 90% at 20% 40%, #000 0%, rgba(0, 0, 0, 0.35) 55%, transparent 84%);
    mask-image: radial-gradient(115% 90% at 20% 40%, #000 0%, rgba(0, 0, 0, 0.35) 55%, transparent 84%);
}

/*
 * 原先这里是两个 blur(60px) 的模糊光球（一白一紫）各带无限动画。
 *
 * 紫的去掉了，白的那枚改成**右上角的静态蓝晕**（见 `.login-l::after`）——
 * 用一个伪元素表达，比留两个空 div 更省结构。
 * 这里保留 class 只为不动模板。
 */
.orb {
    display: none;
}

.inner {
    position: relative;
    z-index: 2;
    max-width: 540px;
}

.ll-badge {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-s2);
    font-size: 12.5px;
    padding: 6px 13px;
    border-radius: var(--sp-r-pill);
    margin-bottom: 24px;
    width: fit-content;
    /* 原为半透明白底（配渐变背景）；浅底上改用浅蓝底 + 主色边框 */
    background: var(--sp-accent-bg);
    border: 1px solid var(--sp-accent-line);
    color: var(--sp-accent-h);
}

.login-l h2 {
    font-size: clamp(24px, 2.3vw, 32px);
    line-height: 1.4;
    font-weight: 600;
    letter-spacing: 0;
    margin: 0 0 14px;
    color: var(--sp-text);
}

.login-l .sub {
    font-size: 13.5px;
    color: var(--sp-t2);
    line-height: 1.8;
    margin: 0 0 32px;
}

.ll-feat {
    display: flex;
    flex-direction: column;
    gap: var(--sp-s3);
}

.ll-feat div {
    display: flex;
    align-items: center;
    gap: var(--sp-s3);
    font-size: 13px;
    color: var(--sp-t2);
    line-height: 1.6;
}

.ll-feat i {
    width: 29px;
    height: 29px;
    flex: none;
    border-radius: var(--sp-r-sm);
    font-style: normal;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--sp-accent-bg);
    border: 1px solid var(--sp-accent-line);
    color: var(--sp-accent-h);
}

.ll-foot {
    position: absolute;
    left: clamp(28px, 5vw, 68px);
    bottom: 28px;
    z-index: 2;
    font-size: 12px;
    letter-spacing: 0.2px;
    color: var(--sp-t3);
}

/* ---------- 右：表单区 ----------
 *
 * 底色用「上浅蓝 → 下白」的极弱渐变，与左栏接上，让两屏是同一片空间；
 * 但仍以白为主，保证输入框与文字有最高对比度（表单区不该有装饰干扰）。
 */
.login-r {
    flex: 1;
    min-width: 0;
    position: relative;
    background: linear-gradient(180deg, #eef5ff 0%, #ffffff 46%);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 56px clamp(24px, 6vw, 88px);
}

.login-card {
    width: 100%;
    max-width: 360px;
}

.login-r h3 {
    font-size: 23px;
    color: var(--sp-text);
    margin: 0 0 8px;
}

.login-r .hint {
    font-size: 12.5px;
    color: var(--sp-t3);
    line-height: 1.7;
    margin: 0 0 30px;
}

/* 输入框落到原型的 .inputx：细描边 + 聚焦 3px 光晕 */
.login-form :deep(.el-form-item) {
    margin-bottom: 19px;
}

.login-form :deep(.el-form-item__label) {
    font-size: 12.5px;
    color: var(--sp-t2);
    line-height: 1.2;
    padding-bottom: 8px;
    margin-bottom: 0;
}

.login-form :deep(.el-input__wrapper) {
    border-radius: var(--sp-r-sm);
    padding: 4px 14px;
    box-shadow: 0 0 0 1px var(--sp-border) inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
    box-shadow:
        0 0 0 1px var(--sp-accent) inset,
        0 0 0 3px rgba(64, 158, 255, 0.12);
}

/* Element Plus 的 primary 皮肤改不动渐变阴影，这里显式落到原型的 .btn.ai.block */
.login-form :deep(.el-button.login-submit) {
    /* letter-spacing 由 4px 收到 1px：中文按钮里拉开 4px 会显得松散，
       而且「进入 AI 调度中台」比原型按钮文案长，撑得更明显。 */
    letter-spacing: 1px;
    border: none;
    background: var(--sp-accent);
    box-shadow: none;
}

.lock-hint {
    margin-top: 14px;
    font-size: 12.5px;
    color: var(--sp-warning);
    line-height: 1.6;
    text-align: center;
}

.lock-hint.is-locked {
    color: var(--sp-danger);
    font-weight: 600;
}

.login-crypt {
    margin: 16px 0 0;
    font-size: 12px;
    color: var(--sp-t3);
    text-align: center;
}

.login-copy {
    position: absolute;
    bottom: 24px;
    font-size: 12px;
    color: var(--sp-t3);
}

/* 窄屏：品牌区收起为顶部横条，表单铺满，避免左侧大块留白 */
@media (max-width: 900px) {
    .login {
        flex-direction: column;
    }

    .login-l {
        flex: none;
        padding: 40px 28px;
    }

    .login-l .sub {
        margin-bottom: 22px;
    }

    .ll-foot {
        display: none;
    }

    .login-r {
        flex: 1;
        padding: 40px 22px 64px;
    }

    /* 窄屏（单列）时左栏只占一小段，角落光晕没有足够空间铺开，收起更干净 */
    .login-l::after {
        display: none;
    }
}

/*
 * 可访问性降级：尊重系统「减少动态效果」。
 * 左栏那枚角落光晕是纯装饰，开着 reduce-motion 时应当**完全静止**。
 */
@media (prefers-reduced-motion: reduce) {
    .login-l::after {
        animation: none;
        opacity: 0.75;
    }
}
</style>
