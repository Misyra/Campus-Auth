import { extractApiError, getBinaryName } from './utils.js';

export const scriptMethods = {
  getBinaryName,

  async fetchScripts() {
    try {
      const { data } = await this.$api.get('/api/scripts');
      this.scripts = data;
    } catch (error) {
      this.frontendLogger.error('scripts', '获取脚本列表失败', error);
    }
  },

  async fetchAvailableBinaries() {
    try {
      const { data } = await this.$api.get('/api/scripts/binaries');
      this.availableBinaries = data;
    } catch (error) {
      this.frontendLogger.error('scripts', '获取可用二进制列表失败', error);
    }
  },

  async showScriptEditor(taskId) {
    // 确保二进制列表已加载
    if (!this.availableBinaries.length) {
      await this.fetchAvailableBinaries();
    }

    if (taskId) {
      try {
        const { data } = await this.$api.get(`/api/scripts/${taskId}`);
        const binaryPath = data.binary_path || '';
        const realBinaries = this.availableBinaries.filter(b => b.path !== '__custom_python__');
        const isKnownBinary = binaryPath && realBinaries.some(b => b.path === binaryPath);

        let selectValue = binaryPath;
        let customBinary = '';
        let customPythonBinary = '';

        if (!isKnownBinary && binaryPath) {
          if (binaryPath.toLowerCase().includes('python')) {
            selectValue = '__custom_python__';
            customPythonBinary = binaryPath;
          } else {
            selectValue = '__custom__';
            customBinary = binaryPath;
          }
        }

        this.editingTask = {
          id: taskId,
          name: data.name || '',
          description: data.description || '',
          content: data.content || '',
          binary_path: selectValue,
          _customBinary: customBinary,
          _customPythonBinary: customPythonBinary,
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
        binary_path: '',
        _customBinary: '',
        _customPythonBinary: '',
        _isNew: true,
      };
    }
  },

  onBinarySelectChange() {
    if (this.editingTask.binary_path === '__custom__') {
      this.editingTask._customBinary = this.editingTask._customBinary || '';
    } else {
      this.editingTask._customBinary = '';
    }
    if (this.editingTask.binary_path === '__custom_python__') {
      this.editingTask._customPythonBinary = this.editingTask._customPythonBinary || '';
    } else {
      this.editingTask._customPythonBinary = '';
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

    // 处理二进制路径
    let binaryPath = this.editingTask.binary_path;
    if (binaryPath === '__custom__') {
      binaryPath = this.editingTask._customBinary || '';
    } else if (binaryPath === '__custom_python__') {
      binaryPath = this.editingTask._customPythonBinary || '';
    }

    const payload = {
      name: this.editingTask.name || id,
      description: this.editingTask.description || '',
      content: this.editingTask.content,
      binary_path: binaryPath,
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
      const blob = new Blob([data.content || ''], { type: 'text/plain' });
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
    input.accept = '.py,.sh,.bat,.exe,.txt';
    input.onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        const content = ev.target.result;
        let id = file.name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_]/g, '_');
        // 确保 ID 以字母开头（HTML ID 规范）
        if (/^[0-9]/.test(id)) {
          id = 'sc_' + id;
        }
        this.editingTaskType = 'script';
        this.editingTask = {
          id: id,
          name: '',
          description: '',
          content: content,
          binary_path: '',
          _customBinary: '',
          _customPythonBinary: '',
          _isNew: true,
        };
        this.currentPage = 'scripts';
        input.value = '';
        input.onchange = null;
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
