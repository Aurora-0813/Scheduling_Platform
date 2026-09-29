/**
 * 小程序端静态校验（只读，不修改任何项目文件）
 *
 * 用法：node tools/check.js
 * 无需任何依赖，只用 Node 内置模块。
 *
 * 校验内容：
 *   1. pages.json / manifest.json 能正确 parse
 *   2. pages[] 里每个 path 都有对应的 .vue 文件
 *   3. 代码里所有 uni.navigateTo/reLaunch/redirectTo 的目标页都已声明
 *   4. utils/tabs.js 的 5 个 tab 路径都在 pages.json 里
 *
 * ⚠️ 只校验**已注册**（在 pages.json 里声明过）的页面。
 *    pages/ 下可能残留别的模块合并进来但未注册的页面（见 README §11），
 *    它们**不参与编译、运行时不存在**，「跳转到未声明页面」「用了 ??」这类
 *    针对包体的规则对它们没有意义；报出来只会淹没真正的回归。
 *    这些文件会**单独列出**（见输出末尾），不是被隐藏。
 *   5. 所有 @/ 导入都能解析到真实文件
 *   6. 模板里用到的 mp-* 组件符合 easycom 目录约定
 *   7. 禁用语法：?? / ?. / toISOString() / inset 简写 / * 通配选择器 / :root
 *   8. 裸标签选择器（h4/p/b/i/span/div/a）——小程序里不是组件，样式不会命中
 *   9. tab 页挂了 <mp-tab-bar>，二级页挂了 <mp-nav-bar back>
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const problems = []
const notes = []

function fail(msg) { problems.push(msg) }
function read(p) { return fs.readFileSync(p, 'utf8') }

// ---------- 1. JSON 可解析 ----------
let pagesJson
try {
  pagesJson = JSON.parse(read(path.join(ROOT, 'pages.json')))
} catch (e) {
  fail(`pages.json 解析失败: ${e.message}`)
}
try {
  JSON.parse(read(path.join(ROOT, 'manifest.json')))
} catch (e) {
  fail(`manifest.json 解析失败: ${e.message}`)
}

// ---------- 2. 每个 page 有对应 .vue ----------
const declared = []
if (pagesJson) {
  for (const p of pagesJson.pages || []) {
    declared.push(p.path)
    if (!fs.existsSync(path.join(ROOT, p.path + '.vue'))) {
      fail(`pages.json 声明了 ${p.path} 但没有 ${p.path}.vue`)
    }
  }
  if (!declared.length) fail('pages.json 的 pages 为空')
  // 原生 tabBar 不应存在（本项目用 mp-tab-bar 自定义组件，两者会重复渲染）
  if (pagesJson.tabBar) fail('pages.json 出现了 tabBar：本项目用 mp-tab-bar 自定义组件')
}

// ---------- 2.5 区分「已注册页面」与「未注册页面」 ----------
//
// uni-app 只把 pages.json 里声明的页面编译进小程序包体。pages/ 下未被声明的
// .vue 一律不参与编译 —— 对它们做「包体规则」校验是错的靶子。
// 这里把它们挑出来，后面所有逐文件检查只跑 checkedFiles，最后单独列一份名单。
function isUnregisteredPage(f) {
  const rel = path.relative(ROOT, f).replace(/\\/g, '/')
  if (!rel.startsWith('pages/') || !rel.endsWith('.vue')) return false
  return declared.indexOf(rel.slice(0, -'.vue'.length)) < 0
}

// ---------- 3. 收集所有 .vue / .js ----------
// tools/ 是校验脚本自身，不属于小程序包体，跳过
// （否则脚本里的正则字面量会被自己的规则误判）
const SKIP_DIRS = ['node_modules', 'unpackage', 'tools']

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name)
    if (fs.statSync(full).isDirectory()) {
      if (SKIP_DIRS.indexOf(name) >= 0) continue
      walk(full, out)
    } else if (/\.(vue|js)$/.test(name)) {
      out.push(full)
    }
  }
  return out
}
const files = walk(ROOT)

const unregisteredPages = files.filter(isUnregisteredPage)
const checkedFiles = files.filter((f) => unregisteredPages.indexOf(f) < 0)
const relOf = (f) => path.relative(ROOT, f).replace(/\\/g, '/')

// ---------- 4. 路由目标都存在 ----------
const navRe = /url:\s*[`'"](\/pages\/[^`'"$]*)[`'"]/g
for (const f of checkedFiles) {
  let m
  const src = read(f)
  while ((m = navRe.exec(src))) {
    const target = m[1].split('?')[0].replace(/^\//, '')
    if (!declared.includes(target)) {
      fail(`${path.relative(ROOT, f)} 跳转到未声明的页面 ${target}`)
    }
  }
}

// ---------- 5. utils/tabs.js 的路径都在 pages.json 里 ----------
const tabsFile = path.join(ROOT, 'utils/tabs.js')
if (!fs.existsSync(tabsFile)) {
  fail('缺少 utils/tabs.js')
} else {
  const re = /path:\s*'(\/pages\/[^']+)'/g
  let m
  let n = 0
  const src = read(tabsFile)
  while ((m = re.exec(src))) {
    n++
    const target = m[1].replace(/^\//, '')
    if (!declared.includes(target)) fail(`utils/tabs.js 的 tab 路径 ${target} 未在 pages.json 声明`)
  }
  if (n !== 5) fail(`utils/tabs.js 期望 5 个 tab，实际 ${n} 个`)
}

// ---------- 6. @/ 导入都能解析 ----------
const impRe = /from\s+['"]@\/([^'"]+)['"]/g
for (const f of checkedFiles) {
  let m
  const src = read(f)
  while ((m = impRe.exec(src))) {
    const base = path.join(ROOT, m[1])
    const cands = [base, base + '.js', base + '.vue',
      path.join(base, 'index.js'), path.join(base, 'index.vue')]
    if (!cands.some((c) => fs.existsSync(c) && fs.statSync(c).isFile())) {
      fail(`${path.relative(ROOT, f)} 导入了不存在的模块 @/${m[1]}`)
    }
  }
}

// ---------- 7. easycom 组件存在 ----------
const compsSeen = new Set()
for (const f of checkedFiles.filter((x) => x.endsWith('.vue'))) {
  const re = /<(mp-[a-z-]+)/g
  let m
  const src = read(f)
  while ((m = re.exec(src))) compsSeen.add(m[1])
}
for (const c of compsSeen) {
  if (!fs.existsSync(path.join(ROOT, 'components', c, c + '.vue'))) {
    fail(`模板用了 <${c}> 但缺少 components/${c}/${c}.vue（easycom 约定）`)
  }
}
notes.push(`easycom 组件: ${[...compsSeen].sort().join(', ') || '(无)'}`)

// ---------- 8. 禁用语法 / 已知坑 ----------
/** 去掉注释再扫，否则文档里「不要用 toISOString()」这类说明会误报 */
function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '')
}

for (const f of checkedFiles) {
  const rel = relOf(f)
  const src = read(f)
  const code = stripComments(src)

  if (/\?\?/.test(code)) fail(`${rel} 使用了 ?? （部分小程序构建链不降级 ES2020）`)
  if (/\?\./.test(code)) fail(`${rel} 使用了 ?. （部分小程序构建链不降级 ES2020）`)
  if (/toISOString\s*\(/.test(code)) fail(`${rel} 使用了 toISOString() （带 Z，后端不换算时区会差 8 小时）`)
  if (/^\s*inset\s*:/m.test(code)) fail(`${rel} 使用了 inset 简写（低版本 webview 不支持）`)

  if (f.endsWith('.vue') || f.endsWith('.css')) {
    const blocks = src.match(/<style[^>]*>[\s\S]*?<\/style>/g) || []
    const css = stripComments(f.endsWith('.css') ? src : blocks.join('\n'))
    if (/(^|[\s,{}])\*\s*\{/.test(css)) fail(`${rel} 使用了 * 通配选择器（WXSS 不支持）`)
    if (/:root\s*\{/.test(css)) fail(`${rel} 使用了 :root（小程序应挂在 page{} 上）`)
  }
}

// ---------- 9. 裸标签选择器 ----------
// 只看「选择器开头」的裸标签：.live.b / .ent.b 这类修饰类不算
const badTags = /(?<![.#:\w-])(h4|p|b|i|span|div|a)\s*(?=[{,])/g
for (const f of checkedFiles.filter((x) => x.endsWith('.vue') || x.endsWith('.css'))) {
  const rel = relOf(f)
  const src = read(f)
  const blocks = src.match(/<style[^>]*>[\s\S]*?<\/style>/g) || []
  const css = stripComments(f.endsWith('.css') ? src : blocks.join('\n'))
  let bm
  while ((bm = badTags.exec(css))) {
    fail(`${rel} 出现裸标签选择器 ${bm[1]}（小程序里不是组件，样式不会命中，请改用 class）`)
  }
}

// ---------- 10. tab 页 / 二级页的导航栏约定 ----------
for (const p of declared.slice(0, 5)) {
  if (!/<mp-tab-bar/.test(read(path.join(ROOT, p + '.vue')))) {
    fail(`${p} 是 tab 页但没有渲染 <mp-tab-bar>`)
  }
}
for (const p of declared.slice(5)) {
  const src = read(path.join(ROOT, p + '.vue'))
  if (/<mp-tab-bar/.test(src)) fail(`${p} 是二级页却渲染了 <mp-tab-bar>`)
  if (!/<mp-nav-bar[^>]*\bback\b/.test(src)) notes.push(`${p} 的导航栏没有 back 属性（二级页通常需要）`)
}

// ---------- 输出 ----------
console.log('检查文件数:', files.length)
console.log('声明页面数:', declared.length)
notes.forEach((n) => console.log('  · ' + n))

// 未注册页面**照实列出来**（不是隐藏）：它们不在包体里，所以上面的逐文件
// 检查对它们没有意义；来历与处置方式见 miniprogram/README.md §11。
if (unregisteredPages.length) {
  console.log(
    '  · 未注册页面 ' + unregisteredPages.length + ' 个（不在 pages.json → 不参与编译，已跳过逐文件检查）:'
  )
  unregisteredPages.forEach((f) => console.log('      - ' + relOf(f)))
}
console.log('')
if (problems.length) {
  console.log(`发现 ${problems.length} 个问题:`)
  problems.forEach((p) => console.log('  ✗ ' + p))
  process.exit(1)
}
console.log('✓ 静态校验全部通过')
