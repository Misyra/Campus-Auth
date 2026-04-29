import { DEFAULT_PROFILE_SETTINGS } from '../constants.js';

export const profileMethods = {
  async fetchProfiles() {
    try {
      const { data } = await this.$api.get('/api/profiles');
      this.profiles = data.profiles || {};
      this.activeProfileId = data.active_profile || 'default';
      this.autoSwitch = data.auto_switch !== false;
    } catch (error) {
      this.frontendLogger.error('profiles', 'failed to fetch profiles', error);
    }
  },
  async fetchActiveProfile() {
    try {
      const { data } = await this.$api.get('/api/profiles/active');
      this.activeProfileId = data.profile_id;
      this.autoSwitch = data.auto_switch;
      return data;
    } catch (error) {
      this.frontendLogger.error('profiles', 'failed to fetch active profile', error);
      return null;
    }
  },
  showProfileEditor(profileId) {
    if (profileId && this.profiles[profileId]) {
      this.$api.get(`/api/profiles/${profileId}`).then(({ data }) => {
        this.editingProfile = {
          id: profileId,
          ...data.settings,
        };
        this.currentPage = 'profile-edit';
      }).catch(() => {
        this.notify(false, '加载方案失败');
      });
    } else {
      this.editingProfile = {
        id: '',
        ...DEFAULT_PROFILE_SETTINGS,
      };
      this.currentPage = 'profile-edit';
    }
  },
  async saveProfile() {
    if (!this.editingProfile) return;

    const profileId = this.editingProfile.id.trim();
    if (!profileId) {
      this.notify(false, '请输入方案 ID');
      return;
    }
    if (!/^[a-zA-Z0-9_]+$/.test(profileId)) {
      this.notify(false, '方案 ID 只能包含字母、数字和下划线');
      return;
    }

    const { id, ...settings } = this.editingProfile;

    try {
      const { data } = await this.$api.put(`/api/profiles/${profileId}`, settings);
      if (data.success) {
        this.notify(true, data.message || '方案保存成功');
        this.editingProfile = null;
        this.currentPage = 'profiles';
        await this.fetchProfiles();
        // 如果保存的是活动方案，重新加载主配置
        if (profileId === this.activeProfileId) {
          await this.fetchConfig(true);
        }
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, error?.response?.data?.detail || '保存失败');
    }
  },
  async deleteProfile(profileId) {
    if (!confirm('确定要删除这个配置方案吗？')) return;
    try {
      const { data } = await this.$api.delete(`/api/profiles/${profileId}`);
      if (data.success) {
        this.notify(true, '方案删除成功');
        if (this.currentPage === 'profile-edit') {
          this.editingProfile = null;
          this.currentPage = 'profiles';
        }
        await this.fetchProfiles();
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, '删除方案失败');
    }
  },
  async setActiveProfile(profileId) {
    try {
      const { data } = await this.$api.post(`/api/profiles/active/${profileId}`);
      if (data.success) {
        this.activeProfileId = profileId;
        this.frontendLogger.info('profiles', data.message || `已切换到方案 ${profileId}`);
        await this.fetchConfig(true);
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, '切换方案失败');
    }
  },
  async detectNetwork() {
    this.busy.detect = true;
    this.detectResult = null;
    try {
      const { data } = await this.$api.post('/api/profiles/detect');
      this.detectResult = data;
      return data;
    } catch (error) {
      this.detectResult = { gateway_ip: null, ssid: null, matched_profile_id: null };
      this.frontendLogger.error('profiles', 'network detect failed', error);
      return null;
    } finally {
      this.busy.detect = false;
    }
  },
  async toggleAutoSwitch() {
    const newState = !this.autoSwitch;
    try {
      const { data } = await this.$api.post(`/api/profiles/auto-switch?enabled=${newState}`);
      if (data.success) {
        this.autoSwitch = newState;
        this.frontendLogger.info('profiles', data.message);
      } else {
        this.notify(false, data.message);
      }
    } catch (error) {
      this.notify(false, '切换自动切换失败');
    }
  },
};
