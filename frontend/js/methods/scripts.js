import { extractApiError, getBinaryName, safeApiCall, pickFile, downloadBlob } from './utils.js';

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
        this.toastOnly(false, extractApiError(error, '加载脚本失败'));
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
      this.toastOnly(false, '脚本ID不能为空');
      return;
    }
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(id)) {
      this.toastOnly(false, '脚本ID必须以字母开头，且只能包含字母、数字和下划线');
      return;
    }
    if (!this.editingTask.content.trim()) {
      this.toastOnly(false, '脚本内容不能为空');
      return;
    }

    // 脚本内容大小限制（100KB）
    const maxSize = 100 * 1024;
    if (new TextEncoder().encode(this.editingTask.content).length > maxSize) {
      this.toastOnly(false, `脚本内容超过大小限制（最大 ${maxSize / 1024}KB）`);
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
    const resp = await safeApiCall.call(this, () => this.$api.get(`/api/scripts/${taskId}`), '导出失败');
    if (!resp) return;
    const data = resp.data;
    const ext = this._inferScriptExtension(data.binary_path, data.content);
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
      this.frontendLogger.info('scripts', '已导入脚本文件，请检查后保存');
    };
    reader.readAsText(file);
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

  // 根据 binary_path 和脚本内容推断导出文件扩展名
  _inferScriptExtension(binaryPath, content) {
    if (binaryPath) {
      const base = binaryPath.split(/[/\\]/).pop().toLowerCase();
      if (base.startsWith('python') || base === 'py' || (base.endsWith('.exe') && base.includes('python'))) return '.py';
      if (base === 'bash' || base === 'sh' || base === 'zsh') return '.sh';
      if (base === 'cmd' || base === 'cmd.exe' || base === 'bat') return '.bat';
      if (base === 'powershell' || base === 'pwsh') return '.ps1';
    }
    // 从 shebang 推断
    if (content) {
      const firstLine = content.split('\n')[0];
      if (firstLine.includes('python')) return '.py';
      if (firstLine.includes('bash') || firstLine.includes('sh')) return '.sh';
      if (firstLine.includes('powershell') || firstLine.includes('pwsh')) return '.ps1';
    }
    return '.py';
  },
};
