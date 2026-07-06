import { DEFAULT_PROFILE_SETTINGS } from '../constants.js';
import { extractApiError } from './utils.js';

export const profileMethods = {
  async fetchProfiles() {
    try {
      const data = await this.$apiService.profiles.list();
      this.profiles = data.profiles || {};
      this.activeProfileId = data.active_profile || 'default';
      this.autoSwitch = data.auto_switch !== false;
    } catch (error) {
      this.frontendLogger.error('profiles', '获取方案列表失败', error);
    }
  },
  async showProfileEditor(profileId) {
    this.editorDetectResult = null;
    if (profileId && this.profiles[profileId]) {
      try {
        const data = await this.$apiService.profiles.get(profileId);
        this.editingProfile = {
          id: profileId,
          ...data.settings,
          _isNew: false,
        };
        this.currentPage = 'profile-edit';
      } catch {
        this.frontendLogger.error('profiles', '加载方案失败: ' + profileId);
        this.toastOnly(false, '加载方案失败');
      }
    } else {
      this.editingProfile = {
        id: '',
        ...DEFAULT_PROFILE_SETTINGS,
        _isNew: true,
      };
      this.currentPage = 'profile-edit';
    }
  },
  async saveProfile() {
    if (!this.editingProfile) return;

    const profileId = this.editingProfile.id.trim();
    if (!profileId) {
      this.frontendLogger.warn('profiles', '保存方案被拒绝: 空 ID');
      this.toastOnly(false, '请输入方案 ID');
      return;
    }
    if (!/^[a-zA-Z0-9_]+$/.test(profileId)) {
      this.frontendLogger.warn('profiles', '保存方案被拒绝: ID 格式无效');
      this.toastOnly(false, '方案 ID 只能包含字母、数字和下划线');
      return;
    }

    const { id, _isNew, ...settings } = this.editingProfile;

    try {
      const data = await this.$apiService.profiles.save(profileId, settings);
      if (data.success) {
        this.frontendLogger.info('profiles', '方案保存成功: ' + profileId);
        this.toastOnly(true, data.message || '方案保存成功');
        this.editingProfile = null;
        this.currentPage = 'profiles';
        await this.fetchProfiles();
        // 如果保存的是活动方案，重新加载主配置
        if (profileId === this.activeProfileId) {
          await this.fetchConfig(true);
        }
      } else {
        this.frontendLogger.warn('profiles', '方案保存失败: ' + data.message);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      const msg = extractApiError(error, '保存失败');
      this.frontendLogger.error('profiles', '方案保存异常: ' + msg, error);
      this.toastOnly(false, msg);
    }
  },
  async deleteProfile(profileId) {
    if (!confirm('确定要删除这个配置方案吗？')) return;
    try {
      const data = await this.$apiService.profiles.delete(profileId);
      if (data.success) {
        this.frontendLogger.info('profiles', '方案删除成功: ' + profileId);
        this.toastOnly(true, '方案删除成功');
        if (this.currentPage === 'profile-edit') {
          this.editingProfile = null;
          this.currentPage = 'profiles';
        }
        await this.fetchProfiles();
        // 如果删除的是活动方案，重置 activeProfileId
        if (!this.profiles[this.activeProfileId]) {
          this.activeProfileId = 'default';
        }
      } else {
        this.frontendLogger.warn('profiles', '方案删除失败: ' + data.message);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('profiles', '方案删除异常', error);
      this.toastOnly(false, '删除方案失败');
    }
  },
  async setActiveProfile(profileId) {
    if (this.autoSwitch) return;
    try {
      const data = await this.$apiService.profiles.setActive(profileId);
      if (data.success) {
        this.activeProfileId = profileId;
        this.frontendLogger.info('profiles', data.message || `已切换到方案 ${profileId}`);
        this.toastOnly(true, data.message || `已切换到方案 ${profileId}`);
        await this.fetchConfig(true);
      } else {
        this.frontendLogger.warn('profiles', '切换方案失败: ' + data.message);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('profiles', '切换方案异常', error);
      this.toastOnly(false, '切换方案失败');
    }
  },
  async _detectNetwork(busyParent, busyKey, resultKey, errorLabel, fallback, fullData) {
    busyParent[busyKey] = true;
    this[resultKey] = null;
    try {
      const data = await this.$apiService.profiles.detect();
      this[resultKey] = fullData ? data : { gateway_ip: data.gateway_ip, ssid: data.ssid };
      return fullData ? data : null;
    } catch (error) {
      this[resultKey] = fallback;
      this.frontendLogger.error('profiles', errorLabel, error);
      return null;
    } finally {
      busyParent[busyKey] = false;
    }
  },
  async detectNetworkForEditor() {
    return this._detectNetwork(
      this.busy, 'editorDetect', 'editorDetectResult', '编辑器网络检测失败',
      { gateway_ip: null, ssid: null }, false,
    );
  },
  async detectNetwork() {
    return this._detectNetwork(
      this.busy, 'detect', 'detectResult', '网络检测失败',
      { gateway_ip: null, ssid: null, matched_profile_id: null }, true,
    );
  },
  async toggleAutoSwitch() {
    if (this._autoSwitchInFlight) return;
    this._autoSwitchInFlight = true;
    const newState = !this.autoSwitch;
    try {
      const data = await this.$apiService.profiles.toggleAutoSwitch(newState);
      if (data.success) {
        this.autoSwitch = newState;
        // 更新活动方案（ApiResponse 信封，active_profile 在 data.data 中）
        if (data.data?.active_profile) {
          this.activeProfileId = data.data.active_profile;
        }
        this.frontendLogger.info('profiles', data.message);
        this.toastOnly(true, data.message);
      } else {
        this.frontendLogger.warn('profiles', '自动切换设置失败: ' + data.message);
        this.toastOnly(false, data.message);
      }
    } catch (error) {
      this.frontendLogger.error('profiles', '切换自动切换异常', error);
      this.toastOnly(false, '自动切换设置失败');
    } finally {
      this._autoSwitchInFlight = false;
    }
  },
};
