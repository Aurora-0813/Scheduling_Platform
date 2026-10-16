/**
 * 预约确认页的预填数据（2026-10-13 新增）
 *
 * 为什么需要它：
 *   拍照识场 / 语音预约 / 手绘草图 三个入口**能识别到的信息各不相同** ——
 *     拍照：能认出**是哪间场地** + 人数（设备只有「看起来有哪些」，不可靠）
 *     语音：可能说了时间/设备/人数，也可能什么都没说
 *     草图：能估人数、场地类型，设备只能靠图上的文字标注
 *   但「选时间 + 选场地 + 选设备 + 下单」这一步是完全一样的。
 *   与其在三处各写一遍，不如统一到一个确认页：
 *   三个入口只负责把「自己识别到的那部分」放进这里，缺的部分交给用户在确认页补齐。
 *
 * ⚠️ 每次进入确认页前都要 `setPrefill(...)`（它内部会先重置），
 *    否则上一次的场地/设备会残留 —— 那正是要解决的「猜错没机会纠正」的翻版。
 */
import { reactive } from 'vue'

function emptyPrefill() {
  return {
    source: '', // image | voice | sketch
    sourceLabel: '', // 「拍照识场」/「语音预约」/「手绘草图」
    spaceId: null, // 已识别到的场地：确认页里置顶并默认选中
    capacity: null, // 已识别到的人数：用于筛可用场地
    spaceType: 0, // 已识别到的场地类型：0 = 不限
    deviceTypes: [], // 已识别到的设备**类型**（如 ['投影仪']），用于预勾选
    slotStart: '', // 已选好的时段（拍照识场选过的），'YYYY-MM-DD HH:mm:ss'
    slotEnd: '',
    text: '', // 原始需求文本（语音识别结果 / 拍照识场拼的那句）
    imageContext: null, // 交给 Agent 的上下文（拍照识场带过来的）
  }
}

export const reservePrefill = reactive(emptyPrefill())

/** 覆盖式写入：没传的字段一律回到空值，杜绝串场 */
export function setPrefill(data) {
  Object.assign(reservePrefill, emptyPrefill(), data || {})
  return reservePrefill
}

export function resetPrefill() {
  Object.assign(reservePrefill, emptyPrefill())
}

export default { reservePrefill, setPrefill, resetPrefill }
