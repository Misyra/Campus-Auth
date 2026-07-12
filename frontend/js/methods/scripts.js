import { extractApiError, safeApiCall, pickFile, downloadBlob } from './utils.js';

export const scriptMethods = {

  async fetchScripts() {
    try {
      const { data } = await this.$api.get('/api/scripts');
      this.scripts = data;
    } catch (error) {
      this.frontendLogger.error('scripts', '获取脚本列表失败', error);
    }
  },

  async showScriptEditor(taskId) {
    if (taskId) {
      try {
        const { data } = await this.$api.get(`/api/scripts/${taskId}`);
        this.editingTask = {
          id: taskId,
          name: data.name || '',
          description: data.description || '',
          type: data.type || 'py',
          content: data.type === 'exe' ? (data.path || '') : (data.content || ''),
          _isNew: false,
        };
        this.editingTaskType = 'script';
      } catch (error) {
        this.toastOnly(false, extractApiError(error, '加载脚本失败'));
      }
    } else {
      this.editingTaskType = 'script';
      this.editingTask = {
        id: '',
        name: '',
        description: '',
        type: 'py',
        content: '#!/usr/bin/env python3\n"""自定义登录脚本"""\nimport httpx\n\n',
        _isNew: true,
      };
    }
  },

  async saveScript() {
    if (!this.editingTask) return;

    const id = this.editingTask.id.trim();
    if (!id) {
      this.toastOnly(false, '脚本ID不能为空');
      return;
    }
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(id)) {
      this.toastOnly(false, '脚本ID必须以字母开头，且只能包含字母、数字和下划线');
      return;
    }
    const isExe = this.editingTask.type === 'exe';
    const value = this.editingTask.content.trim();
    if (!value) {
      this.toastOnly(false, isExe ? '可执行文件路径不能为空' : '脚本内容不能为空');
      return;
    }

    // 脚本内容大小限制（100KB）— 仅文本脚本
    if (!isExe) {
      const maxSize = 100 * 1024;
      if (new TextEncoder().encode(value).length > maxSize) {
        this.toastOnly(false, `脚本内容超过大小限制（最大 ${maxSize / 1024}KB）`);
        return;
      }
    }

    const payload = {
      name: this.editingTask.name || id,
      description: this.editingTask.description || '',
      type: this.editingTask.type || 'py',
      ...(isExe ? { path: value } : { content: value }),
    };

    try {
      const { data } = await this.$api.put(`/api/scripts/${id}`, payload);
      if (data.success) {
        this.editingTask = null;
        await this.fetchScripts();
        this.toastOnly(true, data.message);
      } else {
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      this.toastOnly(false, extractApiError(error, '保存失败'));
    }
  },

  async deleteScript(taskId) {
    if (!confirm(`确定删除脚本「${taskId}」吗？`)) return;
    try {
      const { data } = await this.$api.delete(`/api/scripts/${taskId}`);
      if (data.success) {
        await this.fetchScripts();
        this.toastOnly(true, data.message);
      } else {
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      this.toastOnly(false, extractApiError(error, '删除失败'));
    }
  },

  async runScript(taskId) {
    try {
      const { data } = await this.$api.post(`/api/scripts/${taskId}/run`);
      this.toastOnly(data.success, data.message);
    } catch (error) {
      this.toastOnly(false, extractApiError(error, '执行失败'));
    }
  },

  async exportScript(taskId) {
    const resp = await safeApiCall(this, () => this.$api.get(`/api/scripts/${taskId}`), '导出失败');
    if (!resp) return;
    const data = resp.data;
    if (data.type === 'exe') {
      this.toastOnly(true, `可执行文件路径: ${data.path}`);
      return;
    }
    const ext = { py: '.py', bat: '.bat', ps1: '.ps1', sh: '.sh' }[data.type] || '.txt';
    downloadBlob(data.content || '', `${taskId}${ext}`, 'text/plain');
  },

  async importScript() {
    const file = await pickFile('.py,.sh,.bat,.ps1,.txt');
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const content = ev.target.result;
      let id = file.name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_]/g, '_');
      if (/^[0-9]/.test(id)) {
        id = 'sc_' + id;
      }
      if (this.scripts && this.scripts.some(s => s.id === id)) {
        if (!confirm(`脚本「${id}」已存在，是否覆盖？`)) {
          return;
        }
      }
      const ext = file.name.split('.').pop().toLowerCase();
      const typeMap = { py: 'py', bat: 'bat', ps1: 'ps1', sh: 'sh' };
      this.editingTaskType = 'script';
      this.editingTask = {
        id: id,
        name: '',
        description: '',
        type: typeMap[ext] || 'py',
        content: content,
        _isNew: true,
      };
      this.currentPage = 'scripts';
      this.frontendLogger.info('scripts', '已导入脚本文件，请检查后保存');
    };
  },

  loadScriptTemplate() {
    if (!this.editingTask) return;
    this.editingTask.content = `#!/usr/bin/env python3
"""自定义登录脚本示例

脚本只需发送登录请求，登录是否成功由系统网络检测自动判断。
脚本正常退出（exit 0）= 执行成功，脚本报错退出 = 执行失败。
"""

# ============================================================
# 直接硬编码认证参数（按实际情况修改）
# ============================================================
LOGIN_URL = "http://10.0.0.1/login"
USERNAME = "your_username"
PASSWORD = "your_password"
ISP = "cmcc"  # 运营商：cmcc / unicom / telecom，无则留空

# ============================================================
# 以下三种方式任选其一，按需取消注释
# ============================================================

# ── 方式 1: httpx（已安装，推荐） ──
import httpx
resp = httpx.post(LOGIN_URL, data={
    "username": USERNAME,
    "password": PASSWORD,
    "operator": ISP,
}, timeout=30)
print(f"HTTP {resp.status_code}")

# ── 方式 2: urllib（标准库，无需安装） ──
# import urllib.request, urllib.parse
# data = urllib.parse.urlencode({
#     "username": USERNAME,
#     "password": PASSWORD,
#     "operator": ISP,
# }).encode()
# req = urllib.request.Request(LOGIN_URL, data=data)
# with urllib.request.urlopen(req, timeout=30) as resp:
#     print(f"HTTP {resp.status}")
`;
  },

  async setActiveScript(taskId) {
    try {
      const { data } = await this.$api.post(`/api/tasks/active/${taskId}`);
      if (data.success) {
        this.activeTaskId = taskId;
        this.toastOnly(true, `已将「${taskId}」设为活动任务`);
      } else {
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      this.toastOnly(false, extractApiError(error, '设置失败'));
    }
  },
};
