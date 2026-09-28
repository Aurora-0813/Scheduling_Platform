/**
 * 逐个编译 .vue，捕获模板 / 脚本的语法错误。
 *
 * 用法（首次需要装一次依赖，装在 tools/ 下，不会进小程序包体）：
 *   npm i --prefix tools @vue/compiler-sfc@3
 *   node tools/compile.js
 *
 * 注意：这个依赖**只给校验脚本用**，App 本身仍是零 npm 依赖，
 * HBuilderX 打开工程照样即编译即运行。
 */
const fs = require('fs')
const path = require('path')

let sfc
try {
  sfc = require('@vue/compiler-sfc')
} catch (e) {
  console.error('缺少依赖，请先执行：npm i --prefix tools @vue/compiler-sfc@3')
  process.exit(1)
}

const ROOT = path.resolve(__dirname, '..')

const SKIP_DIRS = ['node_modules', 'unpackage', 'tools']

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name)
    if (fs.statSync(full).isDirectory()) {
      if (SKIP_DIRS.indexOf(name) >= 0) continue
      walk(full, out)
    } else if (name.endsWith('.vue')) {
      out.push(full)
    }
  }
  return out
}

const problems = []
let ok = 0

for (const file of walk(ROOT)) {
  const rel = path.relative(ROOT, file).replace(/\\/g, '/')
  const source = fs.readFileSync(file, 'utf8')

  const { descriptor, errors } = sfc.parse(source, { filename: file })
  if (errors.length) {
    errors.forEach((e) => problems.push(`${rel} 解析失败: ${e.message}`))
    continue
  }

  try {
    sfc.compileScript(descriptor, { id: rel })
  } catch (e) {
    problems.push(`${rel} 脚本编译失败: ${e.message}`)
  }

  if (descriptor.template) {
    const r = sfc.compileTemplate({
      source: descriptor.template.content,
      filename: file,
      id: rel,
      // view / text 等小程序标签以及 mp-* 自定义组件，Vue 编译器会当普通元素处理，
      // 这里显式声明 mp-* 为自定义元素，避免「未知组件」类噪声
      compilerOptions: { isCustomElement: (tag) => tag.startsWith('mp-') },
    })
    if (r.errors && r.errors.length) {
      r.errors.forEach((e) =>
        problems.push(`${rel} 模板错误: ${typeof e === 'string' ? e : e.message}`)
      )
    }
  } else if (rel !== 'App.vue') {
    // App.vue 是 uni-app 的根组件，按约定只有 <script> + <style>，不渲染模板
    problems.push(`${rel} 没有 <template>`)
  }

  if (descriptor.scriptSetup && descriptor.script) {
    problems.push(`${rel} 同时存在 <script setup> 与 <script>，请确认是有意为之`)
  }

  ok++
}

console.log(`编译 .vue 文件: ${ok} 个`)
if (problems.length) {
  console.log(`\n发现 ${problems.length} 个问题:`)
  problems.forEach((p) => console.log('  ✗ ' + p))
  process.exit(1)
}
console.log('✓ 全部 .vue 编译通过')
