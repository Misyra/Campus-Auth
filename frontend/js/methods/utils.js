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
 * @param {Object} vm - Vue 实例（用于调用 toastOnly）
 * @param {Function} fn - 异步 API 调用函数
 * @param {string} fallbackMsg - 失败时的默认消息
 * @returns {Promise<any>} 成功时返回 fn 的结果（axios response），失败时返回 null
 */
export async function safeApiCall(vm, fn, fallbackMsg = '操作失败') {
  try {
    return await fn();
  } catch (error) {
    vm.toastOnly(false, extractApiError(error, fallbackMsg));
    return null;
  }
}

/**
 * 打开文件选择对话框。
 * @param {string} accept - 文件类型过滤（如 '.json', 'image/*'）
 * @returns {Promise<File|null>} 选择的文件，取消时返回 null
 */
export function pickFile(accept = '') {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.onchange = (e) => {
      resolve(e.target.files[0] || null);
      input.value = '';
      input.onchange = null;
    };
    input.click();
  });
}

/**
 * 触发浏览器下载 Blob 数据。
 * @param {BlobPart} data - 要下载的数据
 * @param {string} filename - 文件名
 * @param {string} mimeType - MIME 类型（默认 'application/octet-stream'）
 */
export function downloadBlob(data, filename, mimeType = 'application/octet-stream') {
  const blob = new Blob([data], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
