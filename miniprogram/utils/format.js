// 时间显示格式化：`YYYY-MM-DD HH:mm:ss` -> `YYYY-MM-DD HH:mm`（§5.1）
export function formatDateTime(t) {
  return (t || '').slice(0, 16)
}
