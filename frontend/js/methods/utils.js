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

/**
 * 从路径中提取程序名称（去掉目录和扩展名）。
 * @param {string} path - 完整路径
 * @returns {string}
 */
export function getBinaryName(path) {
  if (!path) return 'Python';
  const name = path.split(/[/\\]/).pop() || path;
  return name.replace(/\.(exe|cmd|bat|sh)$/i, '') || name;
}

/**
 * 包装 API 调用，统一处理错误 toast。
 * 需要通过 .call(this, ...) 调用以绑定 Vue 实例上下文。
 * @param {Function} fn - 异步 API 调用函数
 * @param {string} fallbackMsg - 失败时的默认消息
 * @returns {Promise<any>} 成功时返回 fn 的结果（axios response），失败时返回 null
 */
export async function safeApiCall(fn, fallbackMsg = '操作失败') {
  try {
    return await fn();
  } catch (error) {
    this.toastOnly(false, extractApiError(error, fallbackMsg));
    return null;
  }
}
