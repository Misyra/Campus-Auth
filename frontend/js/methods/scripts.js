export const scriptMethods = {
  async fetchScripts() {
    try {
      const { data } = await this.$api.get('/api/scripts');
      this.scripts = data;
    } catch (error) {
      this.frontendLogger.error('scripts', '获取脚本列表失败', error);
    }
  },

  showScriptEditor(taskId) {
    if (taskId) {
      this.$api.get(`/api/scripts/${taskId}`).then(({ data }) => {
        this.editingTask = {
          id: taskId,
          name: data.name || '',
          description: data.description || '',
          content: data.content || '',
          _isNew: false,
        };
        this.editingTaskType = 'script';
      }).catch((error) => {
        this.notify(false, error?.response?.data?.detail || '加载脚本失败');
      });
    } else {
      this.editingTaskType = 'script';
      this.editingTask = {
        id: '',
        name: '',
        description: '',
        content: '#!/usr/bin/env python3\n"""自定义登录脚本"""\nimport os, json\n\n',
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
      this.notify(false, error?.response?.data?.detail || error.message || '保存失败');
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
      this.notify(false, error?.response?.data?.detail || '删除失败');
    }
  },

  async runScript(taskId) {
    try {
      const { data } = await this.$api.post(`/api/scripts/${taskId}/run`);
      this.notify(data.success, data.message);
    } catch (error) {
      this.notify(false, error?.response?.data?.detail || '执行失败');
    }
  },

  exportScript(taskId) {
    this.$api.get(`/api/scripts/${taskId}`).then(({ data }) => {
      const blob = new Blob([data.content || ''], { type: 'text/x-python' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${taskId}.py`;
      a.click();
      URL.revokeObjectURL(url);
    }).catch((error) => {
      this.notify(false, error?.response?.data?.detail || '导出失败');
    });
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
"""自定义登录脚本示例"""
import os
import json

# 从环境变量获取登录参数
username = os.environ["CAMPUS_USERNAME"]
password = os.environ["CAMPUS_PASSWORD"]
isp = os.environ.get("CAMPUS_ISP", "")
login_url = os.environ["CAMPUS_URL"]

# ============================================================
# 以下三种方式任选其一，按需取消注释
# ============================================================

# ── 方式 1: httpx（已安装，推荐） ──
import httpx
resp = httpx.post(login_url, data={
    "username": username,
    "password": password,
    "operator": isp,
}, timeout=30)
if resp.is_success:
    print(json.dumps({"success": True, "message": "登录成功"}))
else:
    print(json.dumps({"success": False, "message": f"HTTP {resp.status_code}"}))

# ── 方式 2: requests（已安装） ──
# import requests
# resp = requests.post(login_url, data={
#     "username": username,
#     "password": password,
#     "operator": isp,
# }, timeout=30)
# if resp.ok:
#     print(json.dumps({"success": True, "message": "登录成功"}))
# else:
#     print(json.dumps({"success": False, "message": f"HTTP {resp.status_code}"}))

# ── 方式 3: urllib（标准库，无需安装） ──
# import urllib.request, urllib.parse
# data = urllib.parse.urlencode({
#     "username": username,
#     "password": password,
#     "operator": isp,
# }).encode()
# req = urllib.request.Request(login_url, data=data)
# with urllib.request.urlopen(req, timeout=30) as resp:
#     print(json.dumps({"success": True, "message": "登录成功"}))
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
      this.notify(false, error?.response?.data?.detail || '设置失败');
    }
  },
};
