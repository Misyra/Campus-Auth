import { extractApiError } from './utils.js';

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
          content: data.content || '',
          _isNew: false,
        };
        this.editingTaskType = 'script';
      } catch (error) {
        this.notify(false, extractApiError(error, '加载脚本失败'));
      }
    } else {
      this.editingTaskType = 'script';
      this.editingTask = {
        id: '',
        name: '',
        description: '',
        content: '#!/usr/bin/env python3\n"""自定义登录脚本"""\nimport httpx\n\n',
        _isNew: true,
      };
    }
  },

  async saveScript() {
    if (!this.editingTask) return;

    const id = this.editingTask.id.trim();
    if (!id) {
      this.notify(false, '脚本ID不能为空');
      return;
    }
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(id)) {
      this.notify(false, '脚本ID必须以字母开头，且只能包含字母、数字和下划线');
      return;
    }
    if (!this.editingTask.content.trim()) {
      this.notify(false, '脚本内容不能为空');
      return;
    }

    const payload = {
      name: this.editingTask.name || id,
      description: this.editingTask.description || '',
      content: this.editingTask.content,
    };

    try {
      const { data } = await this.$api.put(`/api/scripts/${id}`, payload);
      if (data.success) {
        this.editingTask = null;
        await this.fetchScripts();
        this.notify(true, data.message);
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, extractApiError(error, '保存失败'));
    }
  },

  async deleteScript(taskId) {
    if (!confirm(`确定删除脚本「${taskId}」吗？`)) return;
    try {
      const { data } = await this.$api.delete(`/api/scripts/${taskId}`);
      if (data.success) {
        await this.fetchScripts();
        this.notify(true, data.message);
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, extractApiError(error, '删除失败'));
    }
  },

  async runScript(taskId) {
    try {
      const { data } = await this.$api.post(`/api/scripts/${taskId}/run`);
      this.notify(data.success, data.message);
    } catch (error) {
      this.notify(false, extractApiError(error, '执行失败'));
    }
  },

  async exportScript(taskId) {
    try {
      const { data } = await this.$api.get(`/api/scripts/${taskId}`);
      const blob = new Blob([data.content || ''], { type: 'text/x-python' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${taskId}.py`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      this.notify(false, extractApiError(error, '导出失败'));
    }
  },

  importScript() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.py';
    input.onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        const content = ev.target.result;
        const id = file.name.replace(/\.py$/, '').replace(/[^A-Za-z0-9_]/g, '_');
        this.editingTaskType = 'script';
        this.editingTask = {
          id: id,
          name: '',
          description: '',
          content: content,
          _isNew: true,
        };
        this.currentPage = 'scripts';
      };
      reader.readAsText(file);
    };
    input.click();
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
        this.notify(true, `已将「${taskId}」设为活动任务`);
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, extractApiError(error, '设置失败'));
    }
  },
};
