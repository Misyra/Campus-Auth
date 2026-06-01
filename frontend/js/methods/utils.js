/**
 * 从 API 错误中提取用户友好的错误消息。
 * @param {Error} error - axios 错误对象
 * @param {string} fallback - 默认回退消息
 * @returns {string}
 */
export function extractApiError(error, fallback = '操作失败') {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map(d => d.msg || d.detail || String(d)).join('; ') || fallback;
  }
  return detail || error?.message || fallback;
}
