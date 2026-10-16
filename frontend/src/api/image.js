import { bizHttp } from '@/utils/request'

// 模块 2：摄像头空间感知（2026-10-13 补 —— Web 端此前**完全没有**这个模块）
//
// POST /image/sketch 手绘草图识别（multipart：file）
//
// 返回 data（app/schemas/image.py::SketchAnalyzeData）：
//   { type:'sketch', capacity, layout, requirements[], spaceType,
//     confidence, needConfirm, question, imageUrl }
//
// ⚠️ `spaceType`（2026-10-13 新增）是从草图布局推断的场地类型 1/2/3/4，
//    可直接作为 GET /resources/spaces/available?spaceType= 的入参；
//    为 null 时**不要传**该参数（退化为「不限类型」）。
// ⚠️ 本接口**不做候选场地匹配**（草图解读的是「需求」而不是「身份」），
//    所以回包里没有 candidates —— 场地要另外查「时段可用场地」。
export function analyzeSketch(file) {
  const formData = new FormData()
  formData.append('file', file)
  return bizHttp.post('/image/sketch', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
