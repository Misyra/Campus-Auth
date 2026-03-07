const { createApp } = Vue;

const api = axios.create({
  timeout: 10000,
});

createApp({
  data() {
    return {
      config: {
        username: "",
        password: "",
        carrier: "无",
        check_interval_minutes: 5,
        auto_start: false,
        headless: false,
        pause_enabled: true,
        pause_start_hour: 0,
        pause_end_hour: 6,
      },
      status: {
        monitoring: false,
        network_check_count: 0,
        login_attempt_count: 0,
        last_check_time: null,
        runtime_seconds: 0,
      },
      logs: [],
      autostart: {
        platform: "-",
        enabled: false,
        method: "-",
        location: "",
      },
      busy: {
        save: false,
        monitor: false,
        action: false,
        autostart: false,
      },
      toast: {
        success: true,
        message: "",
      },
      timers: [],
    };
  },
  mounted() {
    this.init();
  },
  beforeUnmount() {
    this.timers.forEach((t) => clearInterval(t));
  },
  methods: {
    async init() {
      await Promise.all([this.fetchConfig(), this.fetchStatus(), this.fetchLogs(), this.fetchAutostart()]);
      this.timers.push(setInterval(this.fetchStatus, 4000));
      this.timers.push(setInterval(this.fetchLogs, 3000));
      this.timers.push(setInterval(this.fetchAutostart, 12000));
    },
    notify(success, message) {
      this.toast = { success, message };
      setTimeout(() => {
        this.toast.message = "";
      }, 2400);
    },
    formatDuration(totalSeconds) {
      const sec = Number(totalSeconds || 0);
      const h = String(Math.floor(sec / 3600)).padStart(2, "0");
      const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
      const s = String(sec % 60).padStart(2, "0");
      return `${h}:${m}:${s}`;
    },
    async fetchConfig() {
      const { data } = await api.get("/api/config");
      this.config = data;
    },
    async fetchStatus() {
      const { data } = await api.get("/api/status");
      this.status = data;
    },
    async fetchLogs() {
      const { data } = await api.get("/api/logs", { params: { limit: 250 } });
      this.logs = data;
    },
    async fetchAutostart() {
      try {
        const { data } = await api.get("/api/autostart/status");
        this.autostart = data;
      } catch (error) {
        if (error?.response?.status === 404) {
          this.autostart = {
            platform: "-",
            enabled: false,
            method: "当前后端不支持",
            location: "",
          };
        }
      }
    },
    async saveConfig() {
      this.busy.save = true;
      try {
        const { data } = await api.put("/api/config", this.config);
        this.notify(data.success, data.message);
      } catch (error) {
        const msg = error?.response?.data?.detail || "保存失败";
        this.notify(false, msg);
      } finally {
        this.busy.save = false;
      }
    },
    async toggleMonitor() {
      this.busy.monitor = true;
      try {
        const url = this.status.monitoring ? "/api/monitor/stop" : "/api/monitor/start";
        const { data } = await api.post(url);
        this.notify(data.success, data.message);
        await this.fetchStatus();
      } catch {
        this.notify(false, "操作失败");
      } finally {
        this.busy.monitor = false;
      }
    },
    async manualLogin() {
      this.busy.action = true;
      try {
        const { data } = await api.post("/api/actions/login");
        this.notify(data.success, data.message);
      } catch {
        this.notify(false, "手动登录失败");
      } finally {
        this.busy.action = false;
      }
    },
    async testNetwork() {
      this.busy.action = true;
      try {
        const { data } = await api.post("/api/actions/test-network");
        this.notify(data.success, data.message);
      } catch {
        this.notify(false, "网络测试失败");
      } finally {
        this.busy.action = false;
      }
    },
    async enableAutostart() {
      this.busy.autostart = true;
      try {
        const { data } = await api.post("/api/autostart/enable");
        this.notify(data.success, data.message);
      } catch (error) {
        if (error?.response?.status === 404) {
          this.notify(false, "当前后端版本不支持开机自启动，请重启后端");
        } else {
          this.notify(false, "启用自启动失败");
        }
      } finally {
        await this.fetchAutostart();
        this.busy.autostart = false;
      }
    },
    async disableAutostart() {
      this.busy.autostart = true;
      try {
        const { data } = await api.post("/api/autostart/disable");
        this.notify(data.success, data.message);
      } catch (error) {
        if (error?.response?.status === 404) {
          this.notify(false, "当前后端版本不支持开机自启动，请重启后端");
        } else {
          this.notify(false, "关闭自启动失败");
        }
      } finally {
        await this.fetchAutostart();
        this.busy.autostart = false;
      }
    },
  },
}).mount("#app");
