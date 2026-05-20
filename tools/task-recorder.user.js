// ==UserScript==
// @name         Campus-Auth 任务录制器
// @namespace    https://github.com/Misyra/Campus-Auth
// @version      3.6.7
// @description  可视化选取校园网登录页面元素，自动生成任务 JSON 或结构化文档
// @author       Misyra
// @match        http://*/*
// @match        https://*/*
// @grant        GM_setClipboard
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_addStyle
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  // ==================== 配置 ====================

  const STEP_TYPES = {
    username: { category: "basic", label: "账号输入框", icon: "👤", color: "#4CAF50", primary: true, hint: "点击页面上真实的账号输入框（不是旁边的文字标签），支持自动检测隐藏输入框" },
    password: { category: "basic", label: "密码输入框", icon: "🔒", color: "#2196F3", primary: true, hint: "点击密码输入框，录制器会自动检测 display:none 的隐藏密码框" },
    carrier: { category: "basic", label: "运营商选择", icon: "📶", color: "#FF9800", primary: true, hint: "点击运营商下拉框：原生 select 一键完成；自定义 div 自动进入两阶段选选项" },
    captcha_img: { category: "basic", label: "验证码图片", icon: "🖼️", color: "#9C27B0", primary: true, hint: "点击验证码图片，录制器会自动提示继续点击验证码输入框" },
    captcha_input: { category: "basic", label: "验证码输入框", icon: "✏️", color: "#9C27B0", primary: false, hint: "点击验证码输入框，自动弹出验证码类型选择（数字/字母/运算等）" },
    submit: { category: "basic", label: "提交按钮", icon: "🚀", color: "#F44336", primary: true, hint: "点击登录/提交按钮，通常放在最后一步" },
    checkbox: { category: "basic", label: "勾选/协议", icon: "☑️", color: "#FF5722", primary: true, hint: "点击复选框、用户协议勾选框，自动录制勾选操作" },
    smart_detect: { category: "basic", label: "智能检测", icon: "🔍", color: "#00BCD4", primary: true, hint: "打字自动识别账号/密码，点击自动识别勾选/提交/下拉框，按 Esc 停止" },
    click: { category: "advanced", label: "点击元素", icon: "👆", color: "#607D8B", primary: false, hint: "点击任意页面元素，仅记录点击操作，不填空" },
    wait: { category: "advanced", label: "等待元素", icon: "⏳", color: "#795548", primary: false, hint: "鼠标悬停在要等待的元素上，然后按 Enter 键记录" },
    eval: { category: "advanced", label: "执行JS", icon: "⚙️", color: "#00BCD4", primary: false, hint: "输入一段要在页面中执行的 JavaScript 代码" },
    custom: { category: "advanced", label: "自定义步骤", icon: "📝", color: "#9E9E9E", primary: false, hint: "手动填写步骤描述、选择器、填写值，自由度高" },
    sleep: { category: "advanced", label: "延时等待", icon: "⏳", color: "#795548", primary: false, hint: "添加一个等待步骤，页面不操作仅等待指定时间" },
    screenshot: { category: "advanced", label: "页面截图", icon: "📸", color: "#607D8B", primary: false, hint: "截取当前页面状态，用于调试" },
    wait_url: { category: "advanced", label: "等待URL", icon: "🔗", color: "#795548", primary: false, hint: "等待浏览器 URL 匹配指定正则表达式" },
  };

  const CAPTCHA_TYPES = [
    { value: "4digit", label: "4位纯数字" },
    { value: "4char", label: "4位字母+数字" },
    { value: "math", label: "数学运算 (如 1+2=?)" },
    { value: "other", label: "其他（请描述）" },
  ];

  // ==================== 状态 ====================

  const state = {
    active: false,
    recording: false,
    multiStepMode: false,
    hiddenDetectionEnabled: true,
    revealEnabled: false,   // 强制显示隐藏输入框开关
    steps: [],
    hoveredEl: null,
    selectedEl: null,
    currentStepType: null,
    panel: null,
    tooltip: null,
    iframeWarning: null,
    carrierClickPhase: null,
  };

  const STORAGE_KEY = "ca_recorder_state";

  function saveState() {
    try {
      // 移除大字段防止超出油猴存储限制（通常 5MB）
      const slimSteps = state.steps.map(s => {
        const copy = { ...s };
        delete copy.elementHTML;
        delete copy.elementParentContext;
        delete copy.elementContainerHTML;
        delete copy.hiddenRealHTML;
        return copy;
      });
      GM_setValue(STORAGE_KEY, {
        steps: slimSteps,
        savedAt: Date.now(),
        url: window.location.href,
      });
    } catch (_) {}
  }

  function loadState() {
    try {
      const data = GM_getValue(STORAGE_KEY, null);
      if (!data || !data.steps || data.steps.length === 0) return false;
      if (Date.now() - (data.savedAt || 0) > 2 * 60 * 60 * 1000) {
        clearSavedState();
        return false;
      }
      if (data.url && data.url !== window.location.href) {
        clearSavedState();
        return false;
      }
      return data;
    } catch (_) {
      return false;
    }
  }

  function clearSavedState() {
    try { GM_deleteValue(STORAGE_KEY); } catch (_) {}
  }

  function restoreFromSaved(saved) {
    state.steps = saved.steps;
    activate();
    updateRecordedList();
  }

  // ==================== 样式注入 ====================

  GM_addStyle(`
    #ca-recorder-panel {
      position: fixed; top: 10px; right: 10px; z-index: 2147483647;
      width: 360px; max-height: 90vh; overflow-y: auto;
      background: #1a1a2e; color: #e0e0e0; border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px; line-height: 1.5;
    }
    #ca-recorder-panel * { box-sizing: border-box; }
    #ca-recorder-panel .ca-header {
      padding: 16px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border-radius: 12px 12px 0 0; cursor: move; user-select: none;
    }
    #ca-recorder-panel .ca-header h3 { margin: 0; font-size: 16px; color: #fff; }
    #ca-recorder-panel .ca-header small { color: rgba(255,255,255,0.7); }
    #ca-recorder-panel .ca-body { padding: 12px 16px; }
    #ca-recorder-panel .ca-section { margin-bottom: 12px; }
    #ca-recorder-panel .ca-section-title {
      font-size: 12px; text-transform: uppercase; color: #888;
      letter-spacing: 1px; margin-bottom: 8px;
    }
    #ca-recorder-panel .ca-btn {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 8px 14px; border: none; border-radius: 8px;
      cursor: pointer; font-size: 13px; font-weight: 500;
      transition: all 0.2s;
    }
    #ca-recorder-panel .ca-btn:hover { transform: translateY(-1px); filter: brightness(1.1); }
    #ca-recorder-panel .ca-btn-primary { background: #667eea; color: #fff; }
    #ca-recorder-panel .ca-btn-success { background: #4CAF50; color: #fff; }
    #ca-recorder-panel .ca-btn-danger { background: #e74c3c; color: #fff; }
    #ca-recorder-panel .ca-btn-secondary { background: #333; color: #ccc; }
    #ca-recorder-panel .ca-btn-sm { padding: 4px 10px; font-size: 12px; }
    #ca-recorder-panel .ca-btn-block { width: 100%; justify-content: center; }
    #ca-recorder-panel .ca-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
    #ca-recorder-panel .ca-step-grid {
      display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px;
    }
    #ca-recorder-panel .ca-step-btn {
      display: flex; align-items: center; gap: 6px;
      padding: 8px 10px; background: #2a2a3e; border: 2px solid transparent;
      border-radius: 8px; cursor: pointer; color: #ddd; font-size: 13px;
      transition: all 0.2s;
    }
    #ca-recorder-panel .ca-step-btn:hover { background: #3a3a4e; }
    #ca-recorder-panel .ca-step-btn.active { border-color: #667eea; background: #2a2a5e; }
    #ca-recorder-panel .ca-more-btn { border-color: #555; }
    #ca-recorder-panel .ca-more-btn:hover { border-color: #667eea; }
    #ca-recorder-panel .ca-step-btn .ca-icon { font-size: 16px; }
    #ca-recorder-panel .ca-recorded-list { list-style: none; padding: 0; margin: 0; }
    #ca-recorder-panel .ca-recorded-item {
      display: flex; align-items: center; gap: 8px;
      padding: 8px 10px; margin-bottom: 4px;
      background: #2a2a3e; border-radius: 8px; font-size: 12px;
    }
    #ca-recorder-panel .ca-recorded-item .ca-idx {
      background: #667eea; color: #fff; border-radius: 50%;
      width: 20px; height: 20px; display: flex; align-items: center;
      justify-content: center; font-size: 11px; flex-shrink: 0;
    }
    #ca-recorder-panel .ca-recorded-item .ca-info { flex: 1; min-width: 0; overflow: hidden; }
    #ca-recorder-panel .ca-recorded-item .ca-info .ca-label {
      font-weight: 600; white-space: nowrap; overflow: hidden;
      text-overflow: ellipsis;
    }
    #ca-recorder-panel .ca-recorded-item .ca-info .ca-selector {
      color: #888; font-size: 11px; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis; max-width: 200px;
    }
    #ca-recorder-panel .ca-footer {
      padding: 12px 16px; border-top: 1px solid #333; text-align: center;
      font-size: 12px; color: #666;
    }
    #ca-recorder-panel .ca-footer a {
      color: #667eea; text-decoration: none; display: inline-flex;
      align-items: center; gap: 4px;
    }
    #ca-recorder-panel .ca-footer a:hover { text-decoration: underline; }
    #ca-recorder-panel .ca-footer svg { width: 14px; height: 14px; }
    #ca-recorder-panel .ca-recorded-item .ca-del {
      background: none; border: none; color: #e74c3c; cursor: pointer;
      font-size: 16px; padding: 0 4px;
    }
    #ca-recorder-panel .ca-actions { display: flex; gap: 6px; margin-top: 8px; }
    #ca-recorder-panel .ca-status {
      padding: 8px 12px; background: #2a2a3e; border-radius: 8px;
      font-size: 12px; text-align: center; margin-top: 8px;
    }
    #ca-recorder-panel .ca-status.recording { background: #3a1a1a; color: #ff6b6b; animation: ca-pulse 1.5s infinite; }
    @keyframes ca-pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
    #ca-recorder-panel .ca-modal-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.6);
      z-index: 2147483646; display: flex; align-items: center; justify-content: center;
    }
    #ca-recorder-panel .ca-modal {
      background: #1a1a2e; border-radius: 12px; padding: 20px;
      width: 400px; max-width: 90vw; color: #e0e0e0;
    }
    #ca-recorder-panel .ca-modal h4 { margin: 0 0 12px; }
    #ca-recorder-panel .ca-modal label { display: block; margin-bottom: 4px; font-size: 13px; color: #aaa; }
    #ca-recorder-panel .ca-modal input, #ca-recorder-panel .ca-modal textarea, #ca-recorder-panel .ca-modal select {
      width: 100%; padding: 8px 10px; background: #2a2a3e; border: 1px solid #444;
      border-radius: 6px; color: #e0e0e0; font-size: 13px; margin-bottom: 10px;
    }
    #ca-recorder-panel .ca-modal textarea { min-height: 60px; resize: vertical; }
    #ca-recorder-panel .ca-modal .ca-modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px; }
    #ca-tooltip {
      position: fixed; z-index: 2147483645; pointer-events: none;
      background: rgba(26,26,46,0.95); color: #e0e0e0;
      padding: 8px 12px; border-radius: 8px; font-size: 12px;
      font-family: monospace; max-width: 400px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.4);
      border-left: 3px solid #667eea;
    }
    #ca-tooltip .ca-tt-tag { color: #667eea; font-weight: bold; }
    #ca-tooltip .ca-tt-id { color: #4CAF50; }
    #ca-tooltip .ca-tt-class { color: #FF9800; }
    #ca-tooltip .ca-tt-hint { color: #888; font-size: 11px; margin-top: 4px; }
    .ca-highlight { outline: 3px solid #667eea !important; outline-offset: 2px !important; background: rgba(102,126,234,0.1) !important; }
    .ca-highlight-selected { outline: 3px solid #4CAF50 !important; outline-offset: 2px !important; background: rgba(76,175,80,0.1) !important; }
    #ca-recorder-panel .ca-recorded-item { cursor: pointer; }
    #ca-recorder-panel .ca-recorded-item:hover { background: #333; }
    #ca-recorder-panel .ca-step-edit-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.5);
      z-index: 2147483646; display: flex; align-items: center; justify-content: center;
    }
    #ca-recorder-panel .ca-step-edit-modal {
      background: #1a1a2e; border-radius: 12px; padding: 20px;
      width: 380px; max-width: 90vw; color: #e0e0e0;
    }
    #ca-recorder-panel .ca-step-edit-modal h4 { margin: 0 0 14px; font-size: 15px; }
    #ca-recorder-panel .ca-step-edit-modal label { display: block; margin-bottom: 4px; font-size: 12px; color: #888; }
    #ca-recorder-panel .ca-step-edit-modal select,
    #ca-recorder-panel .ca-step-edit-modal input,
    #ca-recorder-panel .ca-step-edit-modal textarea {
      width: 100%; padding: 8px 10px; background: #2a2a3e; border: 1px solid #444;
      border-radius: 6px; color: #e0e0e0; font-size: 13px; margin-bottom: 10px;
    }
    #ca-recorder-panel .ca-step-edit-modal textarea { min-height: 50px; resize: vertical; }
    #ca-recorder-panel .ca-step-edit-modal .ca-modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px; }
    #ca-recorder-panel .ca-toolbar { display: flex; gap: 4px; margin-bottom: 8px; }
    #ca-recorder-panel .ca-toggle {
      flex: 1; display: flex; align-items: center; justify-content: center; gap: 4px;
      padding: 6px 8px; background: #2a2a3e; border: 1px solid #444;
      border-radius: 8px; cursor: pointer; color: #888; font-size: 12px;
      transition: all 0.2s; user-select: none;
    }
    #ca-recorder-panel .ca-toggle:hover { background: #333; }
    #ca-recorder-panel .ca-toggle.active {
      background: #2a2a5e; border-color: #667eea; color: #aab; box-shadow: 0 0 6px rgba(102,126,234,0.25);
    }
    /* 隐藏输入框高亮 */
    .ca-revealed-highlight {
      outline: 3px dashed #4CAF50 !important; outline-offset: 3px !important;
      background: rgba(76,175,80,0.1) !important; cursor: pointer !important;
      animation: ca-reveal-pulse 2s infinite;
    }
    @keyframes ca-reveal-pulse {
      0%,100% { outline-color: #4CAF50; } 50% { outline-color: #81C784; }
    }
    .ca-revealed-label {
      position: fixed; background: #4CAF50; color: #fff; padding: 2px 6px;
      border-radius: 3px; font-size: 10px; font-family: monospace;
      white-space: nowrap; z-index: 2147483646; pointer-events: none;
      transform: translateY(-110%);
    }
    /* 揭示面板 */
    #ca-reveal-panel {
      position: fixed; left: 10px; top: 10px; z-index: 2147483646;
      width: 260px; max-height: 60vh; overflow-y: auto;
      background: #1a1a2e; color: #e0e0e0; border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 12px;
    }
    #ca-reveal-panel .ca-rv-header {
      padding: 10px 12px; background: #2e7d32; border-radius: 12px 12px 0 0;
      font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 6px;
    }
    #ca-reveal-panel .ca-rv-item {
      display: flex; align-items: center; gap: 8px; padding: 8px 12px;
      border-bottom: 1px solid #2a2a3e; cursor: pointer; transition: background 0.15s;
    }
    #ca-reveal-panel .ca-rv-item:hover { background: #2a2a4e; }
    #ca-reveal-panel .ca-rv-icon { font-size: 14px; flex-shrink: 0; }
    #ca-reveal-panel .ca-rv-info { flex: 1; min-width: 0; }
    #ca-reveal-panel .ca-rv-sel {
      font-family: monospace; font-size: 11px; color: #81C784; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; max-width: 180px;
    }
    #ca-reveal-panel .ca-rv-type { font-size: 10px; color: #888; }
    #ca-reveal-panel .ca-rv-btn {
      flex-shrink: 0; padding: 2px 8px; border: 1px solid #4CAF50; border-radius: 4px;
      background: transparent; color: #4CAF50; cursor: pointer; font-size: 11px;
      transition: all 0.15s;
    }
    #ca-reveal-panel .ca-rv-btn:hover { background: #4CAF50; color: #fff; }
    /* 高亮输入框点击后的步骤选择弹窗 */
    .ca-reveal-popup {
      position: fixed; z-index: 2147483647;
      background: #1a1a2e; color: #e0e0e0; border-radius: 10px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.6); padding: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 13px; min-width: 200px;
    }
    .ca-reveal-popup .ca-rpop-header {
      margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #333;
      font-size: 12px; word-break: break-all;
    }
    .ca-reveal-popup .ca-rpop-actions { display: flex; flex-wrap: wrap; gap: 6px; }
    .ca-reveal-popup .ca-rpop-actions button {
      padding: 6px 12px; border: 1px solid #444; border-radius: 6px;
      background: #2a2a3e; color: #ddd; cursor: pointer; font-size: 12px;
      transition: all 0.15s;
    }
    .ca-reveal-popup .ca-rpop-actions button:hover { background: #3a3a5e; border-color: #667eea; }
    .ca-reveal-popup .ca-rpop-actions button[data-rpop-type="dismiss"] { color: #888; border-color: transparent; }
    .ca-reveal-popup .ca-rpop-actions button[data-rpop-type="dismiss"]:hover { color: #e74c3c; }
  `);

  // ==================== 选择器生成 ====================

  function getSelectors(el) {
    const selectors = [];

    // 检测 Shadow DOM 上下文：选择器只在 Shadow Root 内有效，外部无法直接查询
    let queryRoot = document;
    let inShadowRoot = false;
    try {
      const root = el.getRootNode?.();
      if (root && root instanceof ShadowRoot) {
        queryRoot = root;
        inShadowRoot = true;
      }
    } catch (_) {}

    function queryCount(sel) {
      try { return queryRoot.querySelectorAll(sel).length; } catch (_) { return 0; }
    }

    // 1. ID 选择器（最可靠 — 但 Shadow DOM 内 ID 只在 Shadow Root 作用域内有效）
    if (el.id && !/^\d/.test(el.id)) {
      selectors.push({
        type: "css",
        value: `#${CSS.escape(el.id)}`,
        reliability: inShadowRoot ? 7 : 10,
        shadowScoped: inShadowRoot || undefined,
      });
    }

    // 2. name 属性（检查唯一性：隐藏表单 f0 可能与可见表单 f1 有同名 input）
    if (el.name) {
      const nameSelector = `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
      const matchCount = queryCount(nameSelector);
      // iframe 内元素：name 唯一性只在当前 document 内有效，降低可靠性
      const inIframe = el.ownerDocument !== document;
      const baseReliability = matchCount === 1 ? 9 : 6;
      selectors.push({
        type: "css",
        value: nameSelector,
        reliability: inShadowRoot ? Math.min(baseReliability, 5) : (inIframe ? 5 : baseReliability),
        shadowScoped: inShadowRoot || undefined,
      });
    }

    // 3. 独特的属性组合
    if (el.type && (el.tagName === "INPUT" || el.tagName === "BUTTON")) {
      const s = `${el.tagName.toLowerCase()}[type="${el.type}"]`;
      if (queryCount(s) === 1) {
        selectors.push({
          type: "css",
          value: s,
          reliability: inShadowRoot ? 5 : 7,
          shadowScoped: inShadowRoot || undefined,
        });
      }
    }

    // 4. placeholder（文案可能因多语言/A/B测试变化，可靠性降低）
    if (el.placeholder) {
      const placeholderSelector = `${el.tagName.toLowerCase()}[placeholder="${CSS.escape(el.placeholder)}"]`;
      const placeholderCount = queryCount(placeholderSelector);
      selectors.push({
        type: "css",
        value: placeholderSelector,
        reliability: placeholderCount === 1 ? (inShadowRoot ? 3 : 4) : 2,
        shadowScoped: inShadowRoot || undefined,
      });
    }

    // 5. data-testid（React/Vue 现代 SPA 最稳定标识）
    const testId = el.getAttribute("data-testid");
    if (testId) {
      selectors.push({
        type: "css",
        value: `[data-testid="${CSS.escape(testId)}"]`,
        reliability: inShadowRoot ? 6 : 9,
        shadowScoped: inShadowRoot || undefined,
      });
    }

    // 6. aria-label
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel) {
      selectors.push({
        type: "css",
        value: `[aria-label="${CSS.escape(ariaLabel)}"]`,
        reliability: inShadowRoot ? 5 : 7,
        shadowScoped: inShadowRoot || undefined,
      });
    }

    // 7. 文本内容（按钮/链接）
    const text = (el.textContent || "").trim();
    if (text && text.length < 30 && ["A", "BUTTON", "SPAN", "DIV"].includes(el.tagName)) {
      selectors.push({ type: "text", value: text, reliability: 5 });
    }

    // 8. 短 CSS 路径
    try {
      const shortCss = buildShortCss(el);
      if (shortCss && queryCount(shortCss) === 1) {
        selectors.push({
          type: "css",
          value: shortCss,
          reliability: inShadowRoot ? 2 : 4,
          shadowScoped: inShadowRoot || undefined,
        });
      }
    } catch (_) {}

    // 9. XPath
    selectors.push({ type: "xpath", value: buildXPath(el), reliability: inShadowRoot ? 1 : 3 });

    // 按可靠性排序
    selectors.sort((a, b) => b.reliability - a.reliability);
    return selectors;
  }

  // 检测 CSS Modules / 动态 hash class（如 login_abc12345__xyz、css-1a2b3c4）
  function isHashedClass(name) {
    return /^[a-z]+-[a-z0-9]{6,}(?:-[a-z0-9]+)?$/.test(name)       // css-1a2b3c4, css-1a2b3c4-d7e8 (Emotion/CSS-in-JS)
      || /^[a-zA-Z]+_\w{6,}(?:__\w+)?$/.test(name)                  // login_abc123 或 login_abc123__xyz (CSS Modules)
      || /^[a-zA-Z]+-[a-f0-9]{6,}$/.test(name)                      // header-abc123
      || /^sc-[a-zA-Z]+$/.test(name)                                 // sc-bdVaJa (styled-components)
      || /^css-[a-z0-9]+$/.test(name)                                // css-1a2b3c (Emotion standalone)
      || /^[a-z][a-z0-9]{5,}$/.test(name)                           // e1d2c3f4 (Emotion v10+ short hash)
      || /^_[a-z0-9]{4,}$/.test(name)                                // _2x3y4 (CSS Modules hash suffix)
      || /^jss-\d+$/.test(name);                                     // jss-123 (JSS)
  }

  // 跨 Shadow Root 边界获取父元素
  function getParentNode(el) {
    if (el.parentElement) return el.parentElement;
    const root = el.getRootNode?.();
    if (root && root !== document && root instanceof ShadowRoot) return root.host;
    return null;
  }

  function buildShortCss(el) {
    const parts = [];
    let current = el;
    while (current && current !== document.body && parts.length < 4) {
      let part = current.tagName.toLowerCase();
      if (current.id) {
        parts.unshift(`#${CSS.escape(current.id)}`);
        break;
      }
      if (current.className && typeof current.className === "string") {
        const classes = current.className.trim().split(/\s+/)
          .filter(c => c && !/^[\d-]/.test(c) && !isHashedClass(c));
        if (classes.length > 0) {
          part += "." + classes.slice(0, 2).map(c => CSS.escape(c)).join(".");
        }
      }
      const parent = getParentNode(current);
      if (parent) {
        const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
        if (siblings.length > 1) {
          const idx = siblings.indexOf(current) + 1;
          part += `:nth-of-type(${idx})`;
        }
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(" > ");
  }

  function buildXPath(el) {
    const parts = [];
    let current = el;
    while (current && current !== document.body && parts.length < 6) {
      let part = current.tagName.toLowerCase();
      if (current.id) {
        parts.unshift(`//*[@id="${current.id}"]`);
        return parts.join("");
      }
      const parent = getParentNode(current);
      if (parent) {
        const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
        if (siblings.length > 1) {
          const idx = siblings.indexOf(current) + 1;
          part += `[${idx}]`;
        }
      }
      parts.unshift(`/${part}`);
      current = parent;
    }
    return parts.join("") || "/";
  }

  // ==================== iframe 检测 ====================

  function detectIframe(el) {
    try {
      // 情况 1: 脚本在主文档运行，元素在 iframe/frame 内
      if (el.ownerDocument !== document) {
        // 修复：跨域 frame 只记录不立刻 return，继续检查后续 frame（避免误判）
        let crossOriginFallback = null;

        function searchFrames(doc, depth) {
          if (depth > 10) return null; // 防止过深递归
          const frames = doc.querySelectorAll("iframe, frame");
          for (const frame of frames) {
            try {
              const contentDoc = frame.contentDocument;
              if (contentDoc === el.ownerDocument) {
                const tag = frame.tagName.toLowerCase();
                return {
                  inIframe: true,
                  frameSrc: frame.src || "",
                  frameName: frame.name || "",
                  frameId: frame.id || "",
                  frameSelector: frame.id
                    ? `#${frame.id}`
                    : frame.name
                      ? `${tag}[name="${frame.name}"]`
                      : buildShortCss(frame),
                };
              }
              if (contentDoc) {
                const nested = searchFrames(contentDoc, depth + 1);
                if (nested) return nested;
              }
            } catch (_) {
              // 跨域 iframe：记录但不 return，继续检查后续 frame
              if (!crossOriginFallback) {
                const tag = frame.tagName.toLowerCase();
                // 兜底：生成 nth-of-type 索引选择器
                let fallbackSelector = frame.id
                  ? `#${frame.id}`
                  : frame.name
                    ? `${tag}[name="${frame.name}"]`
                    : buildShortCss(frame);
                if (!fallbackSelector) {
                  const allFrames = Array.from(document.querySelectorAll("iframe, frame"));
                  const idx = allFrames.indexOf(frame) + 1;
                  fallbackSelector = `${tag}:nth-of-type(${idx})`;
                }
                crossOriginFallback = {
                  inIframe: true,
                  crossOrigin: true,
                  frameSrc: frame.src || "",
                  frameName: frame.name || "",
                  frameId: frame.id || "",
                  frameSelector: fallbackSelector,
                };
              }
            }
          }
          return null;
        }

        const found = searchFrames(document, 0);
        if (found) return found;
        if (crossOriginFallback) return crossOriginFallback;
        return { inIframe: true, crossOrigin: false };
      }

      // 情况 2: 脚本自身运行在 frame 内（如 <frameset> 页面的子 <frame>）
      // 此时 document 就是 frame 的文档，el.ownerDocument === document 恒为 true
      // 需要通过 window.frameElement 找到父文档中的 frame 元素
      if (window.self !== window.top) {
        let frameEl = null;
        try { frameEl = window.frameElement; } catch (_) {}
        if (frameEl) {
          const tag = frameEl.tagName.toLowerCase();
          return {
            inIframe: true,
            frameSrc: frameEl.src || "",
            frameName: frameEl.name || "",
            frameId: frameEl.id || "",
            frameSelector: frameEl.id
              ? `#${frameEl.id}`
              : frameEl.name
                ? `${tag}[name="${frameEl.name}"]`
                : null,
          };
        }
        // 跨域 frame，拿不到 frameElement
        return { inIframe: true, crossOrigin: true, frameSrc: "" };
      }
    } catch (_) {}
    return { inIframe: false };
  }

  // ==================== 元素信息提取 ====================

  function detectShadowRoot(el) {
    try {
      const root = el.getRootNode?.();
      if (root && root instanceof ShadowRoot) {
        const host = root.host;
        const hostInfo = host ? {
          tag: host.tagName.toLowerCase(),
          id: host.id || "",
          class: (host.className || "").substring(0, 100),
          selector: host.id ? `#${CSS.escape(host.id)}` : host.tagName.toLowerCase(),
        } : null;
        return { inShadowRoot: true, host: hostInfo };
      }
    } catch (_) {}
    return { inShadowRoot: false, host: null };
  }

  function getElementInfo(el) {
    const tag = el.tagName.toLowerCase();
    const attrs = {};
    for (const attr of el.attributes) {
      if (["id", "class", "name", "type", "placeholder", "value", "href", "src", "action",
           "data-testid", "aria-label", "aria-describedby", "role"].includes(attr.name)) {
        attrs[attr.name] = attr.value;
      }
      // 收集所有 data-* 属性作为候选
      if (attr.name.startsWith("data-")) {
        attrs[attr.name] = attr.value;
      }
    }

    return {
      tag,
      attrs,
      text: (el.textContent || "").trim().substring(0, 100),
      selectors: getSelectors(el),
      iframe: detectIframe(el),
      shadowRoot: detectShadowRoot(el),
      visible: el.offsetParent !== null,
      rect: el.getBoundingClientRect().toJSON(),
    };
  }

  // ==================== 隐藏输入框检测 ====================
  //
  // 校园网认证页面常见的两种隐藏输入框模式：
  //
  // 模式1 — 深澜/Sangfor：可见的 type=text 假占位 + 隐藏的 type=password (display:none)
  //   <input type="text" name="pwdLabel" placeholder="密码">
  //   <input type="password" id="password" style="display:none;">
  //
  // 模式2 — 杭州康工 HK Posi：可见的 readonly tip + 隐藏的真实输入框
  //   <input class="input_tip" readonly value="用户名Username" style="display:block;">
  //   <input class="input" name="username" id="username" style="display:none;" type="text">
  //
  // detectHiddenRealInput 统一处理两种模式，返回隐藏真实输入框的选择器，或 null。
  //
  // 搜索策略：
  //   1. 如果点击的元素本身隐藏 → 直接返回自身（force 模式填入）
  //   2. 在容器内搜索匹配目标类型的隐藏 input
  //   3. 在父元素内搜索（处理嵌套 div 如 HK Posi 的 userNameDiv）
  //
  // 判断元素是否是验证码相关（防止把验证码输入框误判为 hidden real input）
  function isElementCaptcha(el) {
    const name = (el.name || "").toLowerCase();
    const id = (el.id || "").toLowerCase();
    const cls = (el.className || "").toLowerCase();
    return name.includes("captcha") || id.includes("captcha") || cls.includes("captcha")
      || name.includes("verify") || id.includes("verify");
  }

  function detectHiddenRealInput(el, stepType) {
    // 策略1: 所选元素本身隐藏（理论不可达，但做防御）
    if (isElementHidden(el) && stepType !== "click" && stepType !== "submit") {
      if (el.id) return `#${CSS.escape(el.id)}`;
      if (el.name) return `input[name="${CSS.escape(el.name)}"]`;
    }

    // 确定要搜索的 input type
    const needPassword = stepType === "password";
    let typeSelector;
    if (needPassword) {
      typeSelector = 'input[type="password"]';
    } else {
      // username / captcha_input 等：text 类输入框（含 email/tel 等变体）
      typeSelector = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type])';
    }

    // 搜索范围：从点击元素向上查找
    let container = null;
    // 已知门户模式快速匹配
    if (!container) {
    const knownSelectors = [
      "form",
      ".ant-input-affix-wrapper",
      "div[id$='_posi']",
      ".login_frame_hang_1",
      ".input-group, .form-group",
    ];
      for (const sel of knownSelectors) {
        container = el.closest(sel);
        if (container) break;
      }
    }
    // 动态向上搜索（向上 4 层，找第一个包含隐藏匹配输入框的祖先）
    if (!container) {
      let cur = el.parentElement;
      let depth = 0;
      while (cur && cur !== document.body && cur !== document.documentElement && depth < 6) {
        const candidates = cur.querySelectorAll(typeSelector);
        const hasHidden = Array.from(candidates).some(inp =>
          inp !== el && !inp.readOnly && isElementHidden(inp)
        );
        if (hasHidden) { container = cur; break; }
        cur = cur.parentElement;
        depth++;
      }
    }
    // 兜底父元素
    if (!container) container = el.parentElement;
    if (!container) return null;

    // 在容器及父元素中搜索隐藏的匹配输入框
    const searchRoots = [container];
    // 模式2：比如点了 username_tip，真实 input 在父元素 #userNameDiv 里
    const parent = el.parentElement;
    if (parent && !searchRoots.includes(parent)) {
      searchRoots.push(parent);
    }

    // 深澜/Sangfor 模式：密码步骤点中的是 type="text" 假占位，真实密码框可能被
    // 门户 JS 切换可见性。此时忽略可见性搜索 input[type="password"]。
    // 优先在同一父元素内搜索（避免容器内有多个 password 输入框时选错）
    const clickedIsTextDecoy = needPassword && el.tagName === "INPUT" && el.type === "text";
    if (clickedIsTextDecoy) {
      const immediateParent = el.parentElement;
      if (immediateParent) {
        const siblingPw = immediateParent.querySelectorAll('input[type="password"]');
        for (const input of siblingPw) {
          if (input === el) continue;
          if (input.readOnly) continue;
          if (input.id) return `#${CSS.escape(input.id)}`;
          if (input.name) return `input[name="${CSS.escape(input.name)}"]`;
        }
      }
      // 回退到容器搜索
      for (const root of searchRoots) {
        if (!root) continue;
        const pwInputs = root.querySelectorAll('input[type="password"]');
        for (const input of pwInputs) {
          if (input === el) continue;
          if (input.readOnly) continue;
          if (input.id) return `#${CSS.escape(input.id)}`;
          if (input.name) return `input[name="${CSS.escape(input.name)}"]`;
        }
      }
    }

    // 通用搜索：按类型 + 可见性筛选隐藏输入框，按 DOM 距离排序取最近
    const distanceCandidates = [];
    for (const root of searchRoots) {
      if (!root) continue;
      root.querySelectorAll(typeSelector).forEach(input => {
        if (input === el) return;
        if (input.readOnly) return;
        if (!isElementHidden(input)) return;
        if (stepType !== "captcha_input" && isElementCaptcha(input)) return;
        // 计算 DOM 距离（向上步数直到与 clicked 元素共祖）
        let distance = 0;
        let node = input.parentElement;
        while (node && node !== root) { distance++; node = node.parentElement; }
        distanceCandidates.push({ input, distance });
      });
    }
    distanceCandidates.sort((a, b) => a.distance - b.distance);
    for (const {input} of distanceCandidates) {
      if (input.id) return `#${CSS.escape(input.id)}`;
      if (input.name) return `input[name="${CSS.escape(input.name)}"]`;
    }

    // 兜底：在容器内搜索所有隐藏 input（不限类型），适用于 type 属性缺失的情况
    // 如果用户已经点击了正确类型的 input，不需要兜底（Dr.com 上误判 captcha 的根因）
    const clickedIsCorrectType = el.tagName === "INPUT" && (
      (needPassword && el.type === "password") ||
      (!needPassword && (el.type === "text" || el.type === "" || !el.type))
    );
    if (!clickedIsCorrectType) {
      const fallbackCandidates = [];
      for (const root of searchRoots) {
        if (!root) continue;
        root.querySelectorAll("input").forEach(input => {
          if (input === el) return;
          if (input.readOnly) return;
          if (!isElementHidden(input)) return;
          if (input.type === "submit" || input.type === "button" || input.type === "checkbox" || input.type === "radio") return;
          if (stepType !== "captcha_input" && isElementCaptcha(input)) return;
          let distance = 0;
          let node = input.parentElement;
          while (node && node !== root) { distance++; node = node.parentElement; }
          fallbackCandidates.push({ input, distance });
        });
      }
      fallbackCandidates.sort((a, b) => a.distance - b.distance);
      for (const {input} of fallbackCandidates) {
        if (input.id) return `#${CSS.escape(input.id)}`;
        if (input.name) return `input[name="${CSS.escape(input.name)}"]`;
      }
    }

    return null;
  }

  // 检查元素是否实际隐藏（综合检测：display/visibility/opacity/clip/尺寸/offsetParent）
  // 注意：不把 position:fixed 判为隐藏，它只是 offsetParent 为 null 而已
  function isElementHidden(el) {
    if (!el) return true;
    try {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden") return true;
      if (parseFloat(s.opacity) <= 0) return true;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return true;
      if (s.clip === "rect(0px, 0px, 0px, 0px)" || s.clip === "rect(0, 0, 0, 0)") return true;
      if (typeof s.clipPath === "string" && s.clipPath.includes("inset(100%")) return true;
      if (r.left < -1000 || r.top < -1000) return true;
    } catch (_) {}
    if (el.offsetParent === null) {
      try {
        const s = getComputedStyle(el);
        if (s.position !== "fixed") return true;
      } catch (_) { return true; }
    }
    return false;
  }

  // ==================== UI: 提示框 ====================

  function showTooltip(el, x, y) {
    if (!state.tooltip) {
      state.tooltip = document.createElement("div");
      state.tooltip.id = "ca-tooltip";
      document.body.appendChild(state.tooltip);
    }

    const info = getElementInfo(el);
    const best = info.selectors[0] || {};
    const tag = `<span class="ca-tt-tag">&lt;${info.tag}&gt;</span>`;
    const id = info.attrs.id ? ` <span class="ca-tt-id">#${info.attrs.id}</span>` : "";
    const cls = info.attrs.class
      ? ` <span class="ca-tt-class">.${info.attrs.class.split(/\s+/).slice(0, 2).join(".")}</span>`
      : "";
    const iframeHint = info.iframe.inIframe
      ? `<div class="ca-tt-hint">⚠️ 位于 frame/iframe 内${info.iframe.crossOrigin ? "（跨域）" : ""}</div>`
      : "";

    state.tooltip.innerHTML = `${tag}${id}${cls}${iframeHint}<div class="ca-tt-hint">🖱️ 点击记录  |  ⏎ Enter 无click记录</div>`;
    state.tooltip.style.left = `${Math.min(x + 12, window.innerWidth - 420)}px`;
    state.tooltip.style.top = `${Math.min(y + 12, window.innerHeight - 100)}px`;
    state.tooltip.style.display = "block";
  }

  function hideTooltip() {
    if (state.tooltip) state.tooltip.style.display = "none";
  }

  // ==================== UI: 主面板 ====================

  function createPanel() {
    if (state.panel) return;

    state.panel = document.createElement("div");
    state.panel.id = "ca-recorder-panel";
    state.panel.innerHTML = `
      <div class="ca-header" id="ca-drag-handle">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <div>
            <h3>🎬 Campus-Auth 任务录制器</h3>
            <small>v3.6.7 — 选取元素，生成任务配置</small>
          </div>
          <button id="ca-btn-help" style="width:26px;height:26px;border-radius:50%;border:1px solid rgba(255,255,255,0.3);background:rgba(255,255,255,0.1);color:#fff;cursor:pointer;font-size:14px;font-weight:bold;line-height:1;" title="使用说明">?</button>
        </div>
      </div>
      <div class="ca-body">
        <div class="ca-section">
          <div class="ca-section-title">选择步骤类型后点击页面元素</div>
          <div class="ca-step-grid" id="ca-step-grid"></div>
        </div>
        <div class="ca-section">
          <div class="ca-toolbar">
            <span class="ca-toggle" id="ca-toggle-multistep" title="开启后每次点击记录一步，不会自动停止录制">🔁 多步录制</span>
            <span class="ca-toggle active" id="ca-toggle-detect" title="开启后自动检测容器内 display:none 的隐藏输入框">🔍 隐藏检测</span>
            <span class="ca-toggle" id="ca-toggle-reveal" title="强制显示页面上所有 display:none 的输入框，让你能直接看到并点选">👁️ 显示隐藏</span>
          </div>
          <div style="font-size:11px;color:#666;margin-bottom:4px;">💡 <b>Esc</b> 取消  |  <b>Enter</b> 无 click 记录元素
            <span id="ca-help-toggle" style="cursor:pointer;color:#667eea;margin-left:6px;text-decoration:underline;">详细说明 ▾</span>
          </div>
          <div id="ca-help-detail" style="display:none;font-size:11px;color:#888;background:#1f1f30;border-radius:6px;padding:8px 10px;margin-bottom:8px;line-height:1.6;">
            <b>🖱️ 点击</b> — 记录元素并重放 click 给页面（下拉框会展开/按钮会触发）<br>
            <b>⏎ Enter</b> — 仅记录元素，<b>不</b>发送 click 给页面（悬停菜单、下拉选项不会关闭）<br>
            <b>Esc</b> — 取消当前录制<br>
            <b>🔁 多步录制</b> — 开启后每次点击/Enter 记录一步，不会自动停止，需手动 Esc<br>
            <b>🔍 隐藏检测</b> — 开启后自动扫描容器内 <code style="color:#FF9800;">display:none</code> 的真实输入框<br>
            <b>👁️ 显示隐藏</b> — 强制显示页面上所有隐藏的输入框，让你直接看到并点选真实输入框<br>
            <span style="color:#4CAF50;">👤 账号</span> — 点账号输入框 | <span style="color:#2196F3;">🔒 密码</span> — 点密码框 | <span style="color:#FF9800;">📶 运营商</span> — 点下拉框<br>
            <span style="color:#9C27B0;">🖼️ 验证码</span> — 先点图片再点输入框 | <span style="color:#F44336;">🚀 提交</span> — 点登录按钮<br>
            <span style="color:#FF5722;">☑️ 勾选</span> — 点复选框/协议 | <span style="color:#00BCD4;">🔍 智能检测</span> — 点输入框后打字记录真实元素，点击其他自动识别<br>
            <span style="color:#607D8B;">👆 点击</span> — 任意元素仅点击 | <span style="color:#00BCD4;">⚙️ JS</span> — 执行自定义代码<br>
            <span style="color:#667eea;">💡 点击列表中的步骤可编辑类型和备注</span><br>
          </div>
        </div>
        <div class="ca-section">
          <div class="ca-section-title">已录制步骤</div>
          <ul class="ca-recorded-list" id="ca-recorded-list"></ul>
          <div class="ca-actions">
            <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-btn-undo" disabled>↩ 撤销</button>
            <button class="ca-btn ca-btn-danger ca-btn-sm" id="ca-btn-clear" disabled>🗑 清空</button>
          </div>
        </div>
        <div class="ca-status" id="ca-status">选择步骤类型后点击页面元素</div>
        <div class="ca-actions" style="margin-top:12px;">
          <button class="ca-btn ca-btn-primary" id="ca-btn-copy-prompt">📋 复制 AI 提示词</button>
          <button class="ca-btn ca-btn-danger ca-btn-sm" id="ca-btn-close" style="margin-left:auto;">✕</button>
        </div>
      </div>
      <div class="ca-footer">
        <a href="https://github.com/Misyra/Campus-Auth" target="_blank">
          <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
          Misyra/Campus-Auth
        </a>
        <span style="margin:0 6px;">·</span>
        <span>MIT License</span>
      </div>
    `;
    document.body.appendChild(state.panel);

    const grid = state.panel.querySelector("#ca-step-grid");
    const primaryEntries = Object.entries(STEP_TYPES).filter(([, cfg]) => cfg.primary !== false);
    const secondaryEntries = Object.entries(STEP_TYPES).filter(([, cfg]) => cfg.primary === false);

    function createStepBtn(key, cfg) {
      const btn = document.createElement("div");
      btn.className = "ca-step-btn";
      btn.dataset.type = key;
      btn.innerHTML = `<span class="ca-icon">${cfg.icon}</span><span>${cfg.label}</span>`;
      btn.title = cfg.hint || cfg.label;
      btn.addEventListener("click", () => selectStepType(key));
      return btn;
    }

    let lastCategory = null;
    for (const [key, cfg] of primaryEntries) {
      if (lastCategory && cfg.category !== lastCategory) {
        const sep = document.createElement("div");
        sep.style.cssText = "grid-column:1/-1;height:1px;background:#333;margin:2px 0;";
        grid.appendChild(sep);
      }
      lastCategory = cfg.category;
      grid.appendChild(createStepBtn(key, cfg));
    }

    if (secondaryEntries.length > 0) {
      const moreToggle = document.createElement("div");
      moreToggle.className = "ca-step-btn ca-more-btn";
      moreToggle.dataset.type = "more";
      moreToggle.innerHTML = `<span class="ca-icon">📋</span><span id="ca-more-label">更多<span class="ca-more-arrow"> ▾</span></span>`;
      const moreContainer = document.createElement("div");
      moreContainer.id = "ca-more-container";
      moreContainer.style.display = "none";
      moreContainer.style.gridColumn = "1 / -1";
      moreContainer.style.marginTop = "2px";
      const sep = document.createElement("div");
      sep.style.cssText = "grid-column:1/-1;height:1px;background:#444;margin:2px 0 6px;";
      moreContainer.appendChild(sep);
      for (const [key, cfg] of secondaryEntries) {
        moreContainer.appendChild(createStepBtn(key, cfg));
      }
      moreToggle.addEventListener("click", () => {
        const isOpen = moreContainer.style.display !== "none";
        moreContainer.style.display = isOpen ? "none" : "contents";
        const label = document.getElementById("ca-more-label");
        if (label) {
          label.innerHTML = isOpen ? "更多<span class=\"ca-more-arrow\"> ▾</span>" : "收起<span class=\"ca-more-arrow\"> ▴</span>";
        }
      });
      grid.appendChild(moreToggle);
      grid.appendChild(moreContainer);
    }

    // 多步录制 / 隐藏检测 / 显示隐藏 切换按钮
    const toggleMulti = state.panel.querySelector("#ca-toggle-multistep");
    const toggleHiddenDetect = state.panel.querySelector("#ca-toggle-detect");
    const toggleReveal = state.panel.querySelector("#ca-toggle-reveal");
    const refreshToggles = () => {
      toggleMulti.classList.toggle("active", state.multiStepMode);
      toggleHiddenDetect.classList.toggle("active", state.hiddenDetectionEnabled);
      toggleReveal.classList.toggle("active", state.revealEnabled);
    };
    refreshToggles();
    toggleMulti.addEventListener("click", () => {
      state.multiStepMode = !state.multiStepMode;
      refreshToggles();
      if (state.multiStepMode) {
        setStatus("🔁 多步录制已开启 — 连续点击记录，按 Esc 停止");
      } else {
        setStatus("多步录制已关闭");
      }
    });
    toggleHiddenDetect.addEventListener("click", () => {
      state.hiddenDetectionEnabled = !state.hiddenDetectionEnabled;
      refreshToggles();
      if (state.hiddenDetectionEnabled) {
        setStatus("🔍 隐藏元素检测已开启");
      } else {
        setStatus("隐藏元素检测已关闭");
      }
    });
    toggleReveal.addEventListener("click", () => {
      state.revealEnabled = !state.revealEnabled;
      refreshToggles();
      if (state.revealEnabled) {
        revealHiddenInputsForRecorder();
      } else {
        hideRevealedInputs();
        setStatus("已恢复隐藏输入框");
      }
    });

    // 全局 input 事件监听（手动填写 & 智能检测共用 — capture 阶段确保最先捕获）
    document.addEventListener("input", (e) => {
      const el = e.composedPath()[0];
      if (el.tagName !== "INPUT" && el.tagName !== "TEXTAREA") return;
      if (el.type === "checkbox" || el.type === "radio" || el.type === "submit" || el.type === "button") return;
      if (document.activeElement !== el) return;

      // 智能检测模式：按 input type 自动分类记录
      if (state.currentStepType === "smart_detect") {
        // 区分搜索框和登录输入框：检查是否在 login/auth 相关 form 内
        let inLoginForm = false;
        let cur = el.closest("form");
        if (cur) {
          const action = (cur.action || "").toLowerCase();
          const cls = (cur.className || "").toLowerCase();
          const id = (cur.id || "").toLowerCase();
          inLoginForm = /login|auth|signin|sso/.test(action) || /login|auth|signin/.test(cls) || /login|auth|signin/.test(id);
        }
        // 不在登录表单内的输入框，记录为 click 而非 username/password
        if (!inLoginForm && !el.closest("[role='search'], [role='searchbox']")) {
          const name = (el.name || "").toLowerCase();
          const placeholder = (el.placeholder || "").toLowerCase();
          if (/search|query|find|filter/.test(name) || /search|query|find|filter/.test(placeholder)) {
            return; // 跳过搜索框
          }
        }

        const stepType = el.type === "password" ? "password" : "username";
        const desc = stepType === "password" ? "密码输入框 → {{PASSWORD}}" : "账号输入框 → {{USERNAME}}";
        addManualFillStep(stepType, el, desc);
        setStatus("🔍 已记录。继续点击或输入，按 Esc 停止", "recording");
        return;
      }
    }, true);  // capture phase

    // change 事件监听（智能检测模式：勾选/下拉框变动后记录）
    document.addEventListener("change", (e) => {
      if (state.currentStepType !== "smart_detect") return;
      const el = e.target;
      if (el === state.panel || state.panel?.contains(el)) return;

      const tag = el.tagName.toLowerCase();
      if (tag === "input" && el.type === "checkbox") {
        const desc = "勾选: " + (el.name || el.id || "checkbox");
        addManualFillStep("checkbox", el, desc);
        setStatus("🔍 已记录勾选。继续操作或按 Esc 停止", "recording");
      } else if (tag === "select") {
        const desc = "运营商选择 → {{ISP}}（选项: " + (el.value || "") + "）";
        addManualFillStep("carrier", el, desc);
        setStatus("🔍 已记录运营商选择。继续操作或按 Esc 停止", "recording");
      }
    }, true);  // capture phase

    // 事件绑定
    state.panel.querySelector("#ca-btn-undo").addEventListener("click", undoStep);
    state.panel.querySelector("#ca-btn-clear").addEventListener("click", clearSteps);
    state.panel.querySelector("#ca-btn-copy-prompt").addEventListener("click", () => {
      GM_setClipboard(generatePrompt(window.location.href));
      setStatus("✅ AI 提示词已复制到剪贴板！发送给大模型即可生成任务 JSON");
    });
    state.panel.querySelector("#ca-btn-close").addEventListener("click", deactivate);
    state.panel.querySelector("#ca-btn-help").addEventListener("click", showHelpModal);

    // 帮助详情展开/折叠
    const helpToggle = state.panel.querySelector("#ca-help-toggle");
    const helpDetail = state.panel.querySelector("#ca-help-detail");
    helpToggle.addEventListener("click", () => {
      const open = helpDetail.style.display === "block";
      helpDetail.style.display = open ? "none" : "block";
      helpToggle.textContent = open ? "详细说明 ▾" : "详细说明 ▴";
    });

    // 拖拽
    makeDraggable(state.panel, state.panel.querySelector("#ca-drag-handle"));
  }

  function selectStepType(type) {
    state.currentStepType = type;
    state.carrierClickPhase = null;
    state.panel.querySelectorAll(".ca-step-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.type === type);
    });
    setStatus(`${STEP_TYPES[type]?.icon || "📝"} ${STEP_TYPES[type]?.hint || STEP_TYPES[type]?.label || type}`, "recording");
    state.recording = true;
  }

  function setStatus(msg, cls) {
    const el = state.panel.querySelector("#ca-status");
    el.textContent = msg;
    el.className = "ca-status" + (cls ? ` ${cls}` : "");
  }

  function updateRecordedList() {
    const list = state.panel.querySelector("#ca-recorded-list");
    list.innerHTML = state.steps
      .map(
        (s, i) => {
          const displaySelector = s.hiddenRealSelector
            ? (s.tipSelector ? `${s.tipSelector} 👆 → ${s.hiddenRealSelector}` : `${s.hiddenRealSelector} ⚠️`)
            : (s.bestSelector || "(无选择器)");
          const warningIcon = s.hiddenRealSelector ? (s.tipSelector ? " 👆🔒" : " 🔒") : "";
          return `
      <li class="ca-recorded-item">
        <span class="ca-idx">${i + 1}</span>
        <div class="ca-info">
          <div class="ca-label">${STEP_TYPES[s.type]?.icon || "📝"} ${STEP_TYPES[s.type]?.label || s.type}: ${escHtml(s.description || "")}${warningIcon}</div>
          <div class="ca-selector" title="${escHtml(displaySelector)}">${escHtml(displaySelector)}</div>
        </div>
        <button class="ca-del" data-idx="${i}" title="删除">✕</button>
      </li>
    `;
        }
      )
      .join("");

    list.querySelectorAll(".ca-del").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();  // 防止触发编辑弹窗
        state.steps.splice(parseInt(btn.dataset.idx), 1);
        updateRecordedList();
        saveState();
        updateButtons();
      });
    });

    // 点击步骤项可编辑类型和备注
    list.querySelectorAll(".ca-recorded-item").forEach(item => {
      item.addEventListener("click", () => {
        const idx = parseInt(item.querySelector(".ca-del")?.dataset.idx);
        if (idx >= 0) showStepEditModal(idx);
      });
    });

    updateButtons();
  }

  function showStepEditModal(idx) {
    const step = state.steps[idx];
    if (!step) return;

    const overlay = document.createElement("div");
    overlay.className = "ca-step-edit-overlay";
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

    const typeOptions = Object.entries(STEP_TYPES)
      .map(([k, cfg]) => `<option value="${k}" ${step.type === k ? "selected" : ""}>${cfg.icon} ${cfg.label}</option>`)
      .join("");

    overlay.innerHTML = `
      <div class="ca-step-edit-modal">
        <h4>✏️ 编辑步骤 ${idx + 1}</h4>
        <label>步骤类型</label>
        <select id="ca-edit-type">${typeOptions}</select>
        <label>描述 / 备注</label>
        <input type="text" id="ca-edit-desc" value="${escHtml(step.description || "")}" placeholder="描述这个步骤的作用" />
        <label>选择器</label>
        <input type="text" id="ca-edit-selector" value="${escHtml(step.bestSelector || "")}" placeholder="CSS 选择器" />
        <div id="ca-edit-selector-status" style="font-size:11px;margin-bottom:8px;min-height:16px;"></div>
        <div style="font-size:11px;color:#666;margin-bottom:8px;">${step.hiddenRealSelector ? `⚠️ 隐藏输入框: ${escHtml(step.hiddenRealSelector)}` : `标签: &lt;${step.tag}&gt;`}</div>
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-edit-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-edit-save">保存</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-edit-cancel").addEventListener("click", () => overlay.remove());

    const selectorInput = overlay.querySelector("#ca-edit-selector");
    const statusEl = overlay.querySelector("#ca-edit-selector-status");
    const validateSelector = () => {
      const val = selectorInput.value.trim();
      if (!val) {
        statusEl.textContent = "";
        return;
      }
      try {
        const match = document.querySelector(val);
        if (match) {
          statusEl.innerHTML = `<span style="color:#4CAF50;">✅ 匹配到 &lt;${match.tagName.toLowerCase()}&gt;</span>`;
        } else {
          statusEl.innerHTML = `<span style="color:#e74c3c;">⚠️ 未匹配到任何元素</span>`;
        }
      } catch (e) {
        statusEl.innerHTML = `<span style="color:#e74c3c;">❌ 选择器语法错误: ${escHtml(e.message)}</span>`;
      }
    };
    selectorInput.addEventListener("input", validateSelector);
    validateSelector();
    overlay.querySelector("#ca-edit-save").addEventListener("click", () => {
      const newType = overlay.querySelector("#ca-edit-type").value;
      const newDesc = overlay.querySelector("#ca-edit-desc").value.trim();
      const newSelector = overlay.querySelector("#ca-edit-selector").value.trim();

      step.type = newType;
      step.description = newDesc || STEP_TYPES[newType]?.label || newType;
      if (newSelector) {
        step.bestSelector = newSelector;
        if (!step.selectorCandidates.includes(newSelector)) {
          step.selectorCandidates.unshift(newSelector);
        }
      }

      overlay.remove();
      updateRecordedList();
      saveState();
      setStatus(`✅ 步骤 ${idx + 1} 已更新: ${STEP_TYPES[newType]?.icon || ""} ${step.description}`);
    });
  }

  function updateButtons() {
    const has = state.steps.length > 0;
    state.panel.querySelector("#ca-btn-undo").disabled = !has;
    state.panel.querySelector("#ca-btn-clear").disabled = !has;
    const copyBtn = state.panel.querySelector("#ca-btn-copy-prompt");
    if (copyBtn) {
      copyBtn.style.display = has ? "" : "none";
    }
  }

  function undoStep() {
    state.steps.pop();
    updateRecordedList();
    saveState();
    setStatus("已撤销最后一步");
  }

  function clearSteps() {
    if (state.steps.length === 0) return;
    state.steps = [];
    state.carrierClickPhase = null;
    updateRecordedList();
    clearSavedState();
    setStatus("已清空所有步骤");
  }

  // ==================== 元素点击处理 ====================

  function onHover(e) {
    if (!state.recording) return;
    const el = e.target;
    if (el === state.panel || state.panel?.contains(el)) return;

    if (state.hoveredEl && state.hoveredEl !== state.selectedEl) {
      state.hoveredEl.classList.remove("ca-highlight");
    }
    state.hoveredEl = el;
    if (el !== state.selectedEl) {
      el.classList.add("ca-highlight");
    }
    showTooltip(el, e.clientX, e.clientY);
  }

  function onClick(e) {
    if (!e.isTrusted) return;
    if (!state.recording) return;
    let el = e.target;
    // <select> 的 mousedown 已打开下拉框，用户实际点中的是 <option>，往上找到 <select>
    if (el.tagName === "OPTION") {
      el = el.closest("select") || el.parentElement || el;
    }
    if (el === state.panel || state.panel?.contains(el)) return;
    if (el.closest("#ca-tooltip")) return;

    // 运营商 / 智能检测：需要点击到达页面，不能拦截
    // 运营商第二阶段（选选项）也放行，避免自定义下拉框选项点击被拦截
    const needsClickThrough = state.currentStepType === "smart_detect"
      || (state.currentStepType === "carrier" && (el.tagName !== "SELECT" || state.carrierClickPhase));
    if (!needsClickThrough) {
      e.preventDefault();
      e.stopPropagation();
    }

    el.classList.remove("ca-highlight");
    el.classList.add("ca-highlight-selected");
    if (state.selectedEl && state.selectedEl !== el) {
      state.selectedEl.classList.remove("ca-highlight-selected");
    }
    state.selectedEl = el;

    const info = getElementInfo(el);
    hideTooltip();

    handleElementSelected(el, info);
  }

  function handleElementSelected(el, info) {
    const type = state.currentStepType;

    if (type === "captcha_img") {
      // 验证码图片：记录后提示选输入框
      addStepFromElement(type, el, info, "验证码图片");
      selectStepType("captcha_input");
      setStatus("已记录验证码图片，现在点击验证码输入框", "recording");
      return;
    }

    if (type === "captcha_input") {
      // 弹出验证码类型选择
      showCaptchaModal(el, info);
      return;
    }

    if (type === "username") {
      addStepFromElement(type, el, info, "账号输入框");
      return;
    }
    if (type === "password") {
      addStepFromElement(type, el, info, "密码输入框");
      return;
    }
    if (type === "carrier") {
      handleCarrierClickPhase(el, info);
      return;
    }
    if (type === "submit") {
      addStepFromElement(type, el, info, "提交按钮");
      return;
    }
    if (type === "checkbox") {
      const checkboxDesc = info.text ? `勾选: ${info.text.substring(0, 30)}` : "勾选/用户协议";
      addStepFromElement(type, el, info, checkboxDesc);
      return;
    }
    if (type === "smart_detect") {
      handleSmartDetectClick(el, info);
      return;
    }
    if (type === "sleep") {
      showSleepModal(el, info);
      return;
    }
    if (type === "screenshot") {
      showScreenshotModal(el, info);
      return;
    }
    if (type === "wait") {
      const waitDesc = info.text ? `等待元素出现: ${info.text.substring(0, 30)}` : `等待元素: ${info.tag}`;
      addStepFromElement(type, el, info, waitDesc);
      return;
    }
    if (type === "eval") {
      showEvalModal(el, info);
      return;
    }
    if (type === "wait_url") {
      showWaitUrlModal(el, info);
      return;
    }

    // 通用步骤（click / custom）：弹出自定义描述
    showCustomStepModal(type, el, info);
  }

  // 查找元素所属的最近容器（form/login div 等），用于捕获上下文 HTML
  function findStepContainer(el) {
    let cur = el.parentElement;
    let best = null;
    let depth = 0;
    while (cur && cur !== document.body && cur !== document.documentElement && depth < 5) {
      best = cur;
      const tag = cur.tagName.toLowerCase();
      if (tag === "form" || tag === "fieldset") break;
      const cls = typeof cur.className === "string" ? cur.className : "";
      if (/login|auth|form|panel|container/i.test(cls) || /login|auth|form|panel|container/i.test(cur.id || "")) break;
      cur = cur.parentElement;
      depth++;
    }
    return best;
  }

  function addStepFromElement(type, el, info, description) {
    let tipSelector = null;
    if (el.tagName === "LABEL" && el.htmlFor) {
      const target = document.getElementById(el.htmlFor);
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")) {
        if (isElementHidden(target)) {
          tipSelector = info.selectors[0]?.value || "";
        }
        info = getElementInfo(target);
      }
    }

    const bestSelector = info.selectors[0]?.value || "";
    if (state.steps.some(s => s.type === type && s.bestSelector === bestSelector)) {
      setStatus(`⏭️ 已跳过重复: ${description} (${bestSelector})`, "recording");
      return;
    }

    const selectorCandidates = info.selectors.map(s => s.value);
    let hiddenRealSelector = null;
    let hiddenRealHTML = "";
    let hiddenRealTag = "";
    let hiddenRealRelation = "";
    let hiddenWarning = "";
    const isInputStep = type === "username" || type === "password" || type === "captcha_input";

    if (isInputStep && state.hiddenDetectionEnabled) {
      hiddenRealSelector = detectHiddenRealInput(el, type);
      if (hiddenRealSelector) {
        // 尝试在 DOM 中定位隐藏的真实输入框，获取其 HTML 和与点击元素的关系
        try {
          const hiddenEl = document.querySelector(hiddenRealSelector);
          if (hiddenEl) {
            hiddenRealHTML = hiddenEl.outerHTML.substring(0, 2000);
            hiddenRealTag = hiddenEl.tagName.toLowerCase();
            // 分析关系：是否在同一父元素内
            if (hiddenEl.parentElement === el.parentElement) {
              hiddenRealRelation = `同一 <${el.parentElement.tagName.toLowerCase()}> 内的兄弟元素`;
            } else if (el.parentElement && el.parentElement.contains(hiddenEl)) {
              hiddenRealRelation = `点击元素所在 <${el.parentElement.tagName.toLowerCase()}> 的子元素`;
            } else {
              hiddenRealRelation = `位于容器内，与点击元素不同分支`;
            }
          }
        } catch (_) {}
        hiddenWarning = `⚠️ 检测到隐藏输入框！真实输入框 ${hiddenRealSelector} 已自动识别，导出时将使用 force 模式。`;
      }
    }

    if (!tipSelector && hiddenRealSelector && hiddenRealSelector !== bestSelector) {
      tipSelector = bestSelector;
    }

    const step = {
      type,
      description,
      tag: info.tag,
      bestSelector,
      selectorCandidates,
      iframe: info.iframe,
      shadowRoot: info.shadowRoot,
      attrs: info.attrs,
      text: info.text,
      visible: info.visible,
      hiddenRealSelector,
      hiddenRealHTML,
      hiddenRealTag,
      hiddenRealRelation,
      hiddenWarning,
      tipSelector,
      elementHTML: el.outerHTML,
      elementParentContext: el.parentElement ? el.parentElement.innerHTML.substring(0, 3000) : "",
      elementContainerHTML: findStepContainer(el)?.innerHTML.substring(0, 5000) || "",
    };

    state.steps.push(step);
    state.selectedEl?.classList.remove("ca-highlight-selected");
    state.selectedEl = null;
    updateRecordedList();
    saveState();
    if (hiddenWarning) {
      setStatus(hiddenWarning, "recording");
      setTimeout(() => {
        if (state.panel && state.recording) setStatus(`已添加: ${description}`);
      }, 6000);
    } else {
      setStatus(`已添加: ${description}`);
    }
    const isSmartDetect = state.currentStepType === "smart_detect";
    if (!state.multiStepMode && !isSmartDetect) {
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    }
    if ((state.multiStepMode || isSmartDetect) && state.recording) {
      const nextHint = state.currentStepType
        ? `继续 [${STEP_TYPES[state.currentStepType]?.label || state.currentStepType}] — 点击下一个元素或按 Esc 停止`
        : "点击下一个元素或选择步骤类型，按 Esc 停止";
      setStatus(`🔁 ${nextHint}`, "recording");
    }
  }

  // 从 input 事件记录步骤（智能检测 & 旧版手动填写共用）
  function addManualFillStep(type, el, description) {
    const info = getElementInfo(el);
    const bestSelector = info.selectors[0]?.value || "";

    // 检查重复
    if (state.steps.some(s => s.type === type && s.bestSelector === bestSelector)) {
      setStatus(`⏭️ 已跳过重复: ${description} (${bestSelector})`);
      return;
    }

    const isInputStep = type === "username" || type === "password" || type === "captcha_input";
    let hiddenRealSelector = null;
    let hiddenRealHTML = "";
    let hiddenRealTag = "";
    let hiddenRealRelation = "";
    let hiddenWarning = "";

    if (isInputStep && state.hiddenDetectionEnabled) {
      hiddenRealSelector = detectHiddenRealInput(el, type);
      if (hiddenRealSelector) {
        try {
          const hiddenEl = document.querySelector(hiddenRealSelector);
          if (hiddenEl) {
            hiddenRealHTML = hiddenEl.outerHTML.substring(0, 2000);
            hiddenRealTag = hiddenEl.tagName.toLowerCase();
            if (hiddenEl.parentElement === el.parentElement) {
              hiddenRealRelation = `同一 <${el.parentElement.tagName.toLowerCase()}> 内的兄弟元素`;
            } else if (el.parentElement && el.parentElement.contains(hiddenEl)) {
              hiddenRealRelation = `点击元素所在 <${el.parentElement.tagName.toLowerCase()}> 的子元素`;
            } else {
              hiddenRealRelation = `位于容器内，与点击元素不同分支`;
            }
          }
        } catch (_) {}
        hiddenWarning = `⚠️ 检测到隐藏输入框！真实输入框 ${hiddenRealSelector} 已自动识别`;
      }
    }

    const step = {
      type,
      description,
      tag: info.tag,
      bestSelector,
      selectorCandidates: info.selectors.map(s => s.value),
      iframe: info.iframe,
      shadowRoot: info.shadowRoot,
      attrs: info.attrs,
      text: info.text,
      visible: info.visible,
      hiddenRealSelector,
      hiddenRealHTML,
      hiddenRealTag,
      hiddenRealRelation,
      hiddenWarning,
      elementHTML: el.outerHTML,
      elementParentContext: el.parentElement ? el.parentElement.innerHTML.substring(0, 3000) : "",
      elementContainerHTML: findStepContainer(el)?.innerHTML.substring(0, 5000) || "",
    };

    state.steps.push(step);
    state.selectedEl?.classList.remove("ca-highlight-selected");
    state.selectedEl = null;
    updateRecordedList();
    saveState();
    if (hiddenWarning) {
      setStatus(hiddenWarning, "recording");
      setTimeout(() => {
        if (state.panel && state.recording) setStatus(`已添加: ${description}`);
      }, 5000);
    } else {
      setStatus(`已添加: ${description}`);
    }
  }

  // ==================== 智能检测模式 ====================
  // 核心：不拦截用户操作，监听 input/change 事件捕获真正变动的元素
  // click 仅处理提交按钮、图片和无法归类的点击
  function handleSmartDetectClick(el, info) {
    const tag = el.tagName.toLowerCase();
    const type = (el.type || "").toLowerCase();

    // 提交按钮 → 直接记录
    if (type === "submit" || (tag === "button" && /登录|提交|submit|login/i.test(el.textContent || el.value || ""))) {
      addStepFromElement("submit", el, info, "提交按钮");
      return;
    }
    // 图片 → 验证码
    if (tag === "img") {
      const imgDesc = (el.alt || el.src || "").substring(0, 50);
      addStepFromElement("captcha_img", el, info, "验证码图片" + (imgDesc ? `: ${imgDesc}` : ""));
      selectStepType("captcha_input");
      return;
    }
    // input/select → 不处理 click，留给 input/change 事件捕获变动后的真实元素
    if (tag === "input" || tag === "select" || tag === "textarea") return;
    if (tag === "label" && el.htmlFor) return;
    // 其他可点击元素
    const clickDesc = info.text ? `点击: ${info.text.substring(0, 30)}` : `点击: ${tag}`;
    addStepFromElement("click", el, info, clickDesc);
  }

  function findOptionContainer(el) {
    // 从点击的选项向上查找下拉列表容器，返回其选择器
    let cur = el.parentElement;
    let depth = 0;
    while (cur && cur !== document.body && depth < 6) {
      const tag = cur.tagName.toLowerCase();
      const cls = (cur.className || "").toLowerCase();
      const id = (cur.id || "").toLowerCase();
      // 常见下拉列表容器特征
      if (tag === "ul" || tag === "ol") return cur;
      if (/dropdown|select|menu|list|option|popup|pull-down/i.test(cls + id)) return cur;
      // 包含多个同类子元素（如多个 <li>/<div>/<span>），很可能是选项列表
      if (cur.children.length >= 2) {
        const childTags = Array.from(cur.children).map(c => c.tagName);
        const modeTag = Object.entries(childTags.reduce((acc, t) => { acc[t] = (acc[t] || 0) + 1; return acc; }, {}))
          .sort((a, b) => b[1] - a[1])[0];
        if (modeTag && modeTag[1] >= 2) return cur;
      }
      cur = cur.parentElement;
      depth++;
    }
    return el.parentElement;
  }

  function handleCarrierClickPhase(el, info) {
    // 原生 <select>：直接记录，不走两阶段
    if (!state.carrierClickPhase && info.tag === "select") {
      addStepFromElement("carrier", el, info, "运营商选择 → {{ISP}}");
      return;
    }

    if (!state.carrierClickPhase) {
      const group = detectButtonGroup(el);
      if (group) {
        recordButtonGroupCarrier(el, info, group);
        return;
      }
      state.carrierClickPhase = { triggerEl: el, triggerInfo: info };
      state.selectedEl = null;
      setStatus("🔽 已记录下拉触发器，现在点击任意一个运营商选项（用于展示选项格式，实际值用 {{ISP}} 变量）", "recording");
      return;
    }

    const triggerInfo = state.carrierClickPhase.triggerInfo;
    const triggerSelector = triggerInfo.selectors[0]?.value || "";
    const optionText = (el.textContent || "").trim().substring(0, 50);

    // 找到选项所在的下拉容器，用容器选择器而非选项自身选择器（选项可能在临时弹出层中）
    const optionContainer = findOptionContainer(el);
    const containerInfo = optionContainer ? getElementInfo(optionContainer) : null;
    const optionContainerSelector = containerInfo?.selectors[0]?.value || "";

    const step = {
      type: "carrier",
      description: `运营商选择 → {{ISP}}（示例: ${optionText}）`,
      tag: triggerInfo.tag,
      bestSelector: triggerSelector,
      selectorCandidates: triggerInfo.selectors.map(s => s.value),
      iframe: triggerInfo.iframe,
      shadowRoot: triggerInfo.shadowRoot,
      attrs: triggerInfo.attrs,
      text: triggerInfo.text,
      visible: triggerInfo.visible,
      optionText: optionText,
      optionTag: info.tag,
      optionSelector: optionContainerSelector || info.selectors[0]?.value || "",
      elementHTML: el.outerHTML,
      elementParentContext: el.parentElement ? el.parentElement.innerHTML.substring(0, 3000) : "",
      elementContainerHTML: findStepContainer(el)?.innerHTML.substring(0, 5000) || "",
    };

    state.steps.push(step);
    state.carrierClickPhase = null;
    state.selectedEl?.classList.remove("ca-highlight-selected");
    state.selectedEl = null;
    updateRecordedList();
    saveState();
    setStatus(`已添加: 运营商选择 → {{ISP}}（示例: ${optionText}）`);
    if (!state.multiStepMode) {
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    }
    if (state.multiStepMode && state.recording) {
      setStatus("🔁 点击下一个元素或选择步骤类型，按 Esc 停止", "recording");
    }
  }

  function detectButtonGroup(el) {
    for (let depth = 0; depth < 3; depth++) {
      if (!el || !el.parentElement) break;
      el = el.parentElement;
      if (el.children.length < 2) continue;
      const siblings = Array.from(el.children);
      const textSiblings = siblings.filter(s => {
        const t = (s.textContent || "").trim();
        // Handle nested elements like <button><span>Text</span></button>
        // by checking the first direct text node length
        const firstDirectText = Array.from(s.childNodes)
          .filter(n => n.nodeType === 3)
          .map(n => n.textContent.trim())
          .find(t => t.length > 0);
        const effectiveLength = firstDirectText ? firstDirectText.length : t.length;
        return t.length > 0 && effectiveLength < 40;
      });
      if (textSiblings.length < 2) continue;
      const tagCounts = {};
      for (const s of textSiblings) {
        tagCounts[s.tagName] = (tagCounts[s.tagName] || 0) + 1;
      }
      const modeTag = Object.entries(tagCounts).sort((a, b) => b[1] - a[1])[0][0];
      const similar = textSiblings.filter(s => s.tagName === modeTag);
      if (similar.length >= 2) return similar;
    }
    return null;
  }

  function recordButtonGroupCarrier(el, info, group) {
    const groupContainer = group[0].parentElement;
    const groupContainerInfo = groupContainer ? getElementInfo(groupContainer) : { selectors: [], bestSelector: "" };
    const optionText = (el.textContent || "").trim().substring(0, 50);
    const allOptions = group.map(s => (s.textContent || "").trim().substring(0, 30)).filter(Boolean);

    const step = {
      type: "carrier",
      description: `运营商按钮组 → {{ISP}}（示例: ${optionText}）`,
      tag: info.tag,
      bestSelector: info.selectors[0]?.value || "",
      selectorCandidates: info.selectors.map(s => s.value),
      iframe: info.iframe,
      shadowRoot: info.shadowRoot,
      attrs: info.attrs,
      text: info.text,
      visible: info.visible,
      optionText: optionText,
      optionTag: info.tag,
      optionSelector: groupContainerInfo.bestSelector || "",
      carrierMode: "button_group",
      allOptions: allOptions,
      containerSelector: groupContainerInfo.bestSelector || "",
      elementHTML: el.outerHTML,
      elementParentContext: el.parentElement ? el.parentElement.innerHTML.substring(0, 3000) : "",
      elementContainerHTML: findStepContainer(el)?.innerHTML.substring(0, 5000) || "",
    };

    state.steps.push(step);
    state.selectedEl?.classList.remove("ca-highlight-selected");
    state.selectedEl = null;
    updateRecordedList();
    saveState();
    setStatus(`已添加: 运营商按钮组 → {{ISP}}（检测到 ${allOptions.length} 个选项: ${allOptions.join("、")}）`);
    if (!state.multiStepMode) {
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    }
    if (state.multiStepMode && state.recording) {
      setStatus(" 点击下一个元素或选择步骤类型，按 Esc 停止", "recording");
    }
  }

  // ==================== 弹窗 ====================

  function showCaptchaModal(el, info) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    overlay.innerHTML = `
      <div class="ca-modal">
        <h4>🖼️ 验证码设置</h4>
        <label>验证码类型</label>
        <select id="ca-captcha-type">
          ${CAPTCHA_TYPES.map(t => `<option value="${t.value}">${t.label}</option>`).join("")}
        </select>
        <label>自定义描述（可选）</label>
        <input type="text" id="ca-captcha-desc" placeholder="如：四位数字验证码" />
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-captcha-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-captcha-ok">确定</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-captcha-cancel").addEventListener("click", () => {
      overlay.remove();
      state.recording = false;
      state.currentStepType = null;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
      setStatus("已取消验证码选择");
    });
    overlay.querySelector("#ca-captcha-ok").addEventListener("click", () => {
      const captchaType = overlay.querySelector("#ca-captcha-type").value;
      const customDesc = overlay.querySelector("#ca-captcha-desc").value.trim();
      overlay.remove();

      const desc = customDesc || CAPTCHA_TYPES.find(t => t.value === captchaType)?.label || captchaType;
      addStepFromElement("captcha_input", el, info, `验证码输入: ${desc}`);

      // 记录验证码类型到最近的 captcha_img 步骤
      const imgStep = [...state.steps].reverse().find(s => s.type === "captcha_img");
      if (imgStep) {
        imgStep.captchaType = captchaType;
      }
      const inputStep = state.steps[state.steps.length - 1];
      if (inputStep) {
        inputStep.captchaType = captchaType;
      }
    });
  }

  function showCustomStepModal(type, el, info) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    overlay.innerHTML = `
      <div class="ca-modal">
        <h4>${STEP_TYPES[type]?.icon || "📝"} ${STEP_TYPES[type]?.label || type}</h4>
        <label>步骤描述</label>
        <input type="text" id="ca-custom-desc" placeholder="描述这个步骤的作用" />
        ${type === "click" ? "" : `<label>填入的值（如需要）</label><input type="text" id="ca-custom-value" placeholder="留空则不填入" />`}
        <label>自定义选择器（可选，留空则自动检测）</label>
        <input type="text" id="ca-custom-selector" placeholder="CSS 选择器" value="${escHtml(info.selectors[0]?.value || "")}" />
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-custom-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-custom-ok">确定</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-custom-cancel").addEventListener("click", () => {
      overlay.remove();
      state.recording = true;
    });
    overlay.querySelector("#ca-custom-ok").addEventListener("click", () => {
      const desc = overlay.querySelector("#ca-custom-desc").value.trim() || STEP_TYPES[type]?.label || type;
      const valueEl = overlay.querySelector("#ca-custom-value");
      const value = valueEl ? valueEl.value.trim() : "";
      const customSelector = overlay.querySelector("#ca-custom-selector").value.trim();
      overlay.remove();

      const bestSelector = customSelector || info.selectors[0]?.value || "";
      const step = {
        type,
        description: desc,
        tag: info.tag,
        bestSelector,
        selectorCandidates: customSelector ? [customSelector] : info.selectors.map(s => s.value),
        iframe: info.iframe,
        shadowRoot: info.shadowRoot,
        attrs: info.attrs,
        text: info.text,
        value: value || undefined,
        elementHTML: el.outerHTML,
        elementParentContext: el.parentElement ? el.parentElement.innerHTML.substring(0, 3000) : "",
        elementContainerHTML: findStepContainer(el)?.innerHTML.substring(0, 5000) || "",
      };
      state.steps.push(step);
      state.selectedEl?.classList.remove("ca-highlight-selected");
      state.selectedEl = null;
      updateRecordedList();
      saveState();
      setStatus(`已添加: ${desc}`);
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    });
  }

  function showEvalModal(el, info) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    overlay.innerHTML = `
      <div class="ca-modal">
        <h4>⚙️ 执行 JavaScript</h4>
        <label>JS 代码（在页面上下文中执行）</label>
        <textarea id="ca-eval-code" placeholder="document.querySelector('#btn').click();"></textarea>
        <label>步骤描述（可选）</label>
        <input type="text" id="ca-eval-desc" placeholder="执行自定义脚本" />
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-eval-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-eval-ok">确定</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-eval-cancel").addEventListener("click", () => {
      overlay.remove();
      state.recording = true;
    });
    overlay.querySelector("#ca-eval-ok").addEventListener("click", () => {
      const code = overlay.querySelector("#ca-eval-code").value.trim();
      if (!code) {
        setStatus("⚠️ 请输入要执行的 JavaScript 代码");
        return;
      }
      const desc = overlay.querySelector("#ca-eval-desc").value.trim() || `执行 JS: ${code.substring(0, 40)}`;
      overlay.remove();

      state.steps.push({ type: "eval", description: desc, code });
      updateRecordedList();
      saveState();
      setStatus(`已添加: ${desc}`);
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    });
  }

  function showSleepModal(el, info) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    overlay.innerHTML = `
      <div class="ca-modal">
        <h4>⏳ 延时等待</h4>
        <label>等待时长（毫秒）</label>
        <input type="number" id="ca-sleep-duration" placeholder="1000" value="1000" min="100" />
        <label>描述（可选）</label>
        <input type="text" id="ca-sleep-desc" placeholder="等待页面加载" />
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-sleep-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-sleep-ok">确定</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-sleep-cancel").addEventListener("click", () => {
      overlay.remove();
      state.recording = true;
    });
    overlay.querySelector("#ca-sleep-ok").addEventListener("click", () => {
      const duration = parseInt(overlay.querySelector("#ca-sleep-duration").value) || 1000;
      const desc = overlay.querySelector("#ca-sleep-desc").value.trim() || `等待 ${duration}ms`;
      overlay.remove();

      state.steps.push({ type: "sleep", description: desc, duration });
      updateRecordedList();
      saveState();
      setStatus(`已添加: 延时等待 ${duration}ms`);
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    });
  }

  function showScreenshotModal(el, info) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    overlay.innerHTML = `
      <div class="ca-modal">
        <h4>📸 页面截图</h4>
        <label>截图路径/名称（可选）</label>
        <input type="text" id="ca-screenshot-path" placeholder="debug/screenshot.png" />
        <label>描述（可选）</label>
        <input type="text" id="ca-screenshot-desc" placeholder="页面截图" />
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-screenshot-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-screenshot-ok">确定</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-screenshot-cancel").addEventListener("click", () => {
      overlay.remove();
      state.recording = true;
    });
    overlay.querySelector("#ca-screenshot-ok").addEventListener("click", () => {
      const pathValue = overlay.querySelector("#ca-screenshot-path").value.trim();
      const desc = overlay.querySelector("#ca-screenshot-desc").value.trim() || "页面截图";
      overlay.remove();

      const step = { type: "screenshot", description: desc };
      if (pathValue) step.path = pathValue;
      state.steps.push(step);
      updateRecordedList();
      saveState();
      setStatus(`已添加: 页面截图`);
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    });
  }

  function showWaitUrlModal(el, info) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    overlay.innerHTML = `
      <div class="ca-modal">
        <h4>🔗 等待URL</h4>
        <label>URL 正则表达式</label>
        <input type="text" id="ca-waiturl-pattern" placeholder=".*success.*" />
        <label>超时（毫秒）</label>
        <input type="number" id="ca-waiturl-timeout" placeholder="10000" value="10000" min="1000" />
        <label>描述（可选）</label>
        <input type="text" id="ca-waiturl-desc" placeholder="等待 URL 匹配" />
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-waiturl-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-waiturl-ok">确定</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-waiturl-cancel").addEventListener("click", () => {
      overlay.remove();
      state.recording = true;
    });
    overlay.querySelector("#ca-waiturl-ok").addEventListener("click", () => {
      const pattern = overlay.querySelector("#ca-waiturl-pattern").value.trim();
      if (!pattern) {
        setStatus("⚠️ 请输入 URL 正则表达式");
        return;
      }
      const timeout = parseInt(overlay.querySelector("#ca-waiturl-timeout").value) || 10000;
      const desc = overlay.querySelector("#ca-waiturl-desc").value.trim() || `等待 URL 匹配: ${pattern}`;
      overlay.remove();

      state.steps.push({ type: "wait_url", description: desc, pattern, timeout });
      updateRecordedList();
      saveState();
      setStatus(`已添加: 等待URL匹配`);
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    });
  }

  function generatePrompt(url) {
    let prompt = `请根据以下校园网登录页面的元素信息，生成 Campus-Auth 的任务 JSON 配置。\n\n`;
    prompt += `任务编写规范请参考 Campus-Auth 项目中的 doc/task-writing-guide.md 文档。\n\n`;
    prompt += `页面地址: ${url}\n`;
    prompt += `> **重要：不要填写 url 字段。** 任务 JSON 的 url 字段请留空或使用 "{{LOGIN_URL}}"，由用户自行在 Campus-Auth 系统设置中配置认证地址。硬编码 URL 会导致任务无法通用。\n`;
    prompt += `> **新增配置：** 请在任务 JSON 顶层添加 \`"reveal_hidden": true\`，执行器会在填写前自动显示所有隐藏输入框，无需 force 或 click 占位。\n\n`;
    prompt += `> **version 字段：** 请在任务 JSON 顶层添加 \`"version": "3.6.7"\` 字段，标识此任务适用的 Campus-Auth 版本。\n`;

    // on_success / on_failure 建议
    prompt += `## 建议添加 on_success / on_failure 字段\n\n`;
    prompt += `建议在任务 JSON 顶层添加以下字段以增强可用性：\n\n`;
    prompt += `\`\`\`json\n{\n  "on_success": { "message": "登录成功" },\n  "on_failure": { "message": "登录失败", "screenshot": true }\n}\n\`\`\`\n\n`;
    prompt += `其中 \`on_failure.screenshot: true\` 会在登录失败时自动保存页面截图，便于排查问题。\n\n`;

    // 步骤类型映射表
    prompt += `\n---\n\n**任务分享：** 生成任务 JSON 后，请在最后输出以下内容（不要修改链接）：\n`;
    prompt += `> 本任务已生成，可分享至社区仓库：https://c.wss.pet/s/jww2keupvj8\n\n`;
    prompt += `## 步骤类型映射（录制器 → 任务JSON）\n\n`;
    prompt += `| 录制器类型 | 任务JSON类型 | 说明 |\n`;
    prompt += `|-----------|-------------|------|\n`;
    prompt += `| username | input | value: {{USERNAME}} |\n`;
    prompt += `| password | input | value: {{PASSWORD}}（执行器自动处理隐藏输入框，无需 force 字段） |\n`;
    prompt += `| carrier | select / click_select / click_select(按钮组) | value: {{ISP}}（原生 select → select，自定义 div → click_select，按钮组 → click_select 按文本匹配） |\n`;
    prompt += `| captcha_img + captcha_input | ocr | 合并为一个 ocr 步骤，selector=图片, target_selector=输入框 |\n`;
    prompt += `| submit | click | — |\n`;
    prompt += `| checkbox | click | 勾选复选框/用户协议 |\n`;
    prompt += `| smart_detect | 自动分类 | 智能检测模式：自动识别账号/密码/勾选/提交/点击等 |\n`;
    prompt += `| click | click | — |\n`;
    prompt += `| wait | wait | — |\n`;
    prompt += `| eval | eval | — |\n`;
    prompt += `| sleep | sleep | duration 毫秒 |\n`;
    prompt += `| screenshot | screenshot | — |\n`;
    prompt += `| wait_url | wait_url | pattern 为 URL 正则 |\n`;
    prompt += `\n`;

    // 交叉验证指引 — 提醒 AI 不要盲信录制器选择器
    prompt += `## ⚠️ 重要：请结合上下文 HTML 验证选择器\n\n`;
    prompt += `录制器自动检测的选择器可能不准确。请在编写任务 JSON 前：\n\n`;
    prompt += `1. **阅读上下文 HTML** — 仔细阅读下方的「页面上下文 HTML」，理解页面整体结构和各元素之间的关系\n`;
    prompt += `2. **验证账号输入框** — 确认最佳选择器指向的确实是登录用的账号输入框（type="text"、有对应的 name/id/placeholder），而非搜索框或其他 text 字段\n`;
    prompt += `3. **验证密码输入框** — 优先选择 type="password" 的输入框。如果页面同时存在 text 占位框和 password 真实框，请结合上下文自行判断。\n`;
    prompt += `   - 该输入框的 name/id 是否符合预期（如 name="pwd"、id="password" 等）\n`;
    prompt += `   - 如果有多个相似的输入框，选择器应指向登录用的那个，而非修改密码、确认密码等功能\n`;
    prompt += `4. **验证提交按钮** — 确认是登录/提交按钮（type="submit" 或包含"登录"文字），而非重置或其他按钮\n`;
    prompt += `5. **选择器优先级** — 优先使用 id 选择器，次选 name 属性选择器，避免使用易变的 class 选择器\n`;
    prompt += `6. **隐藏输入框** — 执行器会自动处理隐藏/不可交互的输入框（先尝试普通填充，失败后自动降级为强制输入）。如果隐藏输入框的 selector 看起来不对（比如指向了不相关的 input），请根据上下文 HTML 手动修正。无需在 JSON 中设置 force 字段\n`;
    prompt += `\n`;

    // 隐藏输入框警告汇总
    const hiddenSteps = state.steps.filter(s => s.hiddenRealSelector);
    if (hiddenSteps.length > 0) {
      prompt += `## ⚠️ 隐藏输入框检测\n\n`;
      prompt += `以下步骤的真实输入框是隐藏的。请在任务 JSON 中设置 \`"reveal_hidden": true\`，执行器会自动显示所有隐藏输入框并用普通 fill 填入，无需 click 占位或 force 字段：\n\n`;
      for (const hs of hiddenSteps) {
        prompt += `### ${STEP_TYPES[hs.type]?.label || hs.type}: 真实输入框 \`${hs.hiddenRealSelector}\`\n`;
        if (hs.tipSelector) {
          prompt += `- 占位元素: \`${hs.tipSelector}\`\n`;
        }
        if (hs.hiddenRealHTML) {
          prompt += `- 隐藏输入框 HTML:\n\`\`\`html\n${hs.hiddenRealHTML}\n\`\`\`\n`;
        }
        if (hs.hiddenRealRelation) {
          prompt += `- 位置关系: ${hs.hiddenRealRelation}\n`;
        }
        prompt += `\n`;
      }
    }

    // 如果有验证码，补充说明
    const captchaSteps = state.steps.filter(s => s.type === "captcha_input" && s.captchaType);
    if (captchaSteps.length > 0) {
      prompt += `## 验证码说明\n\n`;
      for (const cs of captchaSteps) {
        const label = CAPTCHA_TYPES.find(t => t.value === cs.captchaType)?.label || cs.captchaType;
        prompt += `- 验证码类型: ${label}\n`;
        if (cs.captchaType === "math") {
          prompt += `- 如果识别率不高，可尝试切换 ocr 步骤的 old 参数（true/false）\n`;
        }
      }
      prompt += `\n`;
    }

    // 从 DOM 找所有步骤元素的公共祖先，生成统一的页面上下文
    const stepEls = [];
    for (const s of state.steps) {
      if (!s.bestSelector) continue;
      try {
        const el = document.querySelector(s.bestSelector);
        if (el && !stepEls.includes(el)) stepEls.push(el);
      } catch (_) {}
    }
    if (stepEls.length > 0) {
      // 求所有元素的最近公共祖先
      let common = stepEls[0];
      for (let i = 1; i < stepEls.length; i++) {
        let a = common, b = stepEls[i];
        const parentsA = [];
        while (a) { parentsA.push(a); a = a.parentElement; }
        while (b && !parentsA.includes(b)) b = b.parentElement;
        if (b) common = b;
      }
      // 往上走一层增加上下文余量（不超过 #edit_body 层级）
      if (common && common.parentElement && common.parentElement.id !== "edit_body" && common.parentElement !== document.body && common.parentElement !== document.documentElement) {
        common = common.parentElement;
      }
      if (common) {
        prompt += `- 页面上下文 HTML:\n\`\`\`html\n${common.innerHTML.substring(0, 12000)}\n\`\`\`\n`;
      }
    }

    prompt += `## 录制到的元素 (${state.steps.length} 个步骤)\n\n`;

    state.steps.forEach((s, i) => {
      const typeLabel = STEP_TYPES[s.type]?.label || s.type;
      prompt += `### 步骤 ${i + 1}: ${typeLabel}\n`;
      prompt += `- 录制器类型: ${s.type}\n`;
      prompt += `- 描述: ${s.description}\n`;
      prompt += `- 标签: <${s.tag}>\n`;
      prompt += `- 最佳选择器: \`${s.bestSelector}\`\n`;
      if (s.selectorCandidates?.length > 1) {
        prompt += `- 候选选择器: ${s.selectorCandidates.map(c => "`" + c + "`").join(", ")}\n`;
      }
      if (s.elementHTML) {
        prompt += `- 元素 HTML:\n\`\`\`html\n${s.elementHTML.substring(0, 3000)}\n\`\`\`\n`;
      }
      if (s.attrs) {
        const extras = [];
        if (s.attrs["data-testid"]) extras.push(`data-testid="${s.attrs["data-testid"]}"`);
        if (s.attrs["aria-label"]) extras.push(`aria-label="${s.attrs["aria-label"]}"`);
        if (extras.length > 0) {
          prompt += `- 稳定属性: ${extras.join(", ")}\n`;
        }
      }
      if (s.hiddenRealSelector) {
        prompt += `- ⚠️ 真实输入框（隐藏）: \`${s.hiddenRealSelector}\`（执行器自动处理，无需 force）\n`;
        if (s.hiddenRealHTML) {
          prompt += `- 📋 隐藏输入框 HTML:\n\`\`\`html\n${s.hiddenRealHTML}\n\`\`\`\n`;
        }
        if (s.hiddenRealRelation) {
          prompt += `- 🔗 与点击元素的关系: ${s.hiddenRealRelation}\n`;
        }
        prompt += `- ✅ 请验证此选择器指向的是正确的登录输入框，而非其他功能字段\n`;
      }
      if (s.tipSelector) {
        prompt += `- 占位元素: \`${s.tipSelector}\`\n`;
      }
      if (s.iframe?.inIframe) {
        if (s.iframe.crossOrigin) {
          const frameParts = [];
          if (s.iframe.frameSrc) frameParts.push(`src="${s.iframe.frameSrc}"`);
          if (s.iframe.frameName) frameParts.push(`name="${s.iframe.frameName}"`);
          if (s.iframe.frameId) frameParts.push(`#${s.iframe.frameId}`);
          prompt += `- ⚠️ 位于跨域 iframe 内（油猴脚本无法直接访问，需后端 Playwright 处理）\n`;
          if (frameParts.length > 0 || s.iframe.frameSelector) {
            prompt += `- iframe 定位: ${s.iframe.frameSelector || frameParts.join(" | ")}\n`;
          }
          prompt += `- 建议在步骤中添加 "frame": "${s.iframe.frameSelector || "请填写iframe选择器"}" 字段\n`;
        } else {
          prompt += `- 在 iframe 内: ${s.iframe.frameSelector || "是"}\n`;
          if (s.iframe.frameSelector) {
            prompt += `- 建议在本步骤及同一 iframe 内的其他步骤中添加 "frame": "${s.iframe.frameSelector}" 字段\n`;
          }
        }
      }
      if (s.shadowRoot?.inShadowRoot) {
        prompt += `- ⚠️ 位于 Shadow DOM 内（Web Components 封装）\n`;
        if (s.shadowRoot.host) {
          prompt += `- Shadow Host: <${s.shadowRoot.host.tag}>${s.shadowRoot.host.selector ? " " + s.shadowRoot.host.selector : ""}\n`;
        }
        prompt += `- ⚠️ CSS 选择器仅在 Shadow Root 内部有效，执行器需要先穿透 Shadow Host 再查询\n`;
      }
      if (s.type === "carrier" && s.carrierMode === "button_group") {
        prompt += `- 按钮组模式 → 映射为 click_select，value 用 {{ISP}}\n`;
        prompt += `- 选项容器选择器: \`${s.optionSelector}\`\n`;
        if (s.allOptions?.length) {
          prompt += `- 检测到的选项: ${s.allOptions.map(o => "`" + o + "`").join("、")}\n`;
        }
        prompt += `- 匹配逻辑: 根据 {{ISP}} 文本匹配按钮组中的对应项并点击\n`;
      } else if (s.type === "carrier" && s.optionText) {
        prompt += `- ⚠️ 自定义下拉框（非原生 select）→ 映射为 click_select，value 用 {{ISP}}\n`;
        prompt += `- 触发器选择器（必须设置为 selector 字段）: \`${s.bestSelector}\`\n`;
        prompt += `- 选项容器选择器（必须设置为 option_selector 字段以限定搜索范围）: \`${s.optionSelector || "（手动指定选项的父容器）"}\`\n`;
        prompt += `- 推荐用法:\n\`\`\`json\n{\n  "type": "click_select",\n  "selector": "${s.bestSelector}",\n  "value": "{{ISP}}",\n  "option_selector": "${s.optionSelector || ""}"\n}\n\`\`\`\n`;
        prompt += `- 选项示例（仅参考格式，实际值取 {{ISP}}）: \`${s.optionText}\`\n`;
      } else if (s.type === "carrier" && !s.optionText) {
        prompt += `- 原生 select 下拉框 → 映射为 select，value 用 {{ISP}}\n`;
      }
      if (s.captchaType) {
        prompt += `- 验证码类型: ${CAPTCHA_TYPES.find(t => t.value === s.captchaType)?.label || s.captchaType}\n`;
      }
      if (s.type === "eval" && s.code) {
        prompt += `- JS 代码:\n\`\`\`js\n${s.code}\n\`\`\`\n`;
      }
      if (s.type === "sleep" && s.duration) {
        prompt += `- 等待时长: ${s.duration}ms\n`;
      }
      if (s.type === "wait_url" && s.pattern) {
        prompt += `- URL 正则: \`${s.pattern}\`\n`;
        if (s.timeout) prompt += `- 超时: ${s.timeout}ms\n`;
      }
      if (s.type === "screenshot" && s.path) {
        prompt += `- 截图路径: ${s.path}\n`;
      }
      prompt += `\n`;
    });

    prompt += `\n---\n\n## 后续反馈\n\n`;
    prompt += `在输出任务 JSON 后，请询问用户：\`"任务是否成功？"\`\n`;
    prompt += `如果用户反馈失败，请提供一套使用 \`eval\` 步骤的备选任务，通过 JavaScript 强制填入账号、密码、运营商并提交。请确保脚本中的选择器根据当前页面 HTML 进行了适配。\n`;

    return prompt;
  }

  // ==================== 拖拽 ====================

  function makeDraggable(panel, handle) {
    let isDragging = false;
    let startX, startY, startLeft, startTop;

    handle.addEventListener("mousedown", (e) => {
      if (e.target.tagName === "BUTTON") return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = panel.getBoundingClientRect();
      startLeft = rect.left;
      startTop = rect.top;
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      panel.style.left = `${startLeft + e.clientX - startX}px`;
      panel.style.top = `${startTop + e.clientY - startY}px`;
      panel.style.right = "auto";
    });

    document.addEventListener("mouseup", () => {
      isDragging = false;
    });
  }

  // ==================== 激活/停用 ====================

  // 对 frame/iframe 文档也绑定事件，使录制器能感知 frame 内的元素
  function attachFrameListeners(doc) {
    try {
      doc.addEventListener("mouseover", onHover, true);
      doc.addEventListener("click", onClick, true);
      doc.addEventListener("keydown", onKeyDown, true);
    } catch (_) {}
  }

  function detachFrameListeners(doc) {
    try {
      doc.removeEventListener("mouseover", onHover, true);
      doc.removeEventListener("click", onClick, true);
      doc.removeEventListener("keydown", onKeyDown, true);
    } catch (_) {}
  }

  // Dynamic iframe MutationObserver — watches for new iframe/frame elements added to DOM
  let _iframeObserver = null;

  function attachAllFrameListeners() {
    document.querySelectorAll("iframe, frame").forEach(frame => {
      try {
        if (frame.contentDocument) {
          attachFrameListeners(frame.contentDocument);
        }
      } catch (_) {}
    });

    // Watch for dynamically added iframes/frames
    if (!_iframeObserver && document.body) {
      _iframeObserver = new MutationObserver((records) => {
        for (const r of records) {
          for (const node of r.addedNodes) {
            if (node.nodeType !== 1) continue;
            if (node.tagName === "IFRAME" || node.tagName === "FRAME") {
              try {
                if (node.contentDocument) {
                  attachFrameListeners(node.contentDocument);
                }
                node.addEventListener("load", () => {
                  try {
                    if (node.contentDocument) {
                      attachFrameListeners(node.contentDocument);
                    }
                  } catch (_) {}
                });
              } catch (_) {}
            }
            // Also check nested iframes within added nodes
            if (node.querySelectorAll) {
              node.querySelectorAll("iframe, frame").forEach(frame => {
                try {
                  if (frame.contentDocument) {
                    attachFrameListeners(frame.contentDocument);
                  }
                  frame.addEventListener("load", () => {
                    try {
                      if (frame.contentDocument) {
                        attachFrameListeners(frame.contentDocument);
                      }
                    } catch (_) {}
                  });
                } catch (_) {}
              });
            }
          }
        }
      });
      try {
        _iframeObserver.observe(document.body, { childList: true, subtree: true });
      } catch (_) {}
    }
  }

  function detachAllFrameListeners() {
    document.querySelectorAll("iframe, frame").forEach(frame => {
      try {
        if (frame.contentDocument) {
          detachFrameListeners(frame.contentDocument);
        }
      } catch (_) {}
    });
    if (_iframeObserver) {
      _iframeObserver.disconnect();
      _iframeObserver = null;
    }
  }

  // SPA 延迟加载表单检测 — 监听主文档中新增的登录表单元素
  let _spaFormObserver = null;

  function startSpaFormWatcher() {
    if (_spaFormObserver || !document.body) return;
    try {
      _spaFormObserver = new MutationObserver((records) => {
        for (const r of records) {
          for (const node of r.addedNodes) {
            if (node.nodeType !== 1) continue;
            // 检测新增的登录表单相关元素
            const isFormLike = node.tagName === "FORM"
              || (node.tagName === "INPUT" && (node.type === "password" || node.type === "text"))
              || (node.tagName === "DIV" && /login|auth|signin|form/i.test((node.className || "") + (node.id || "")));
            // 如果节点本身不像表单元素，检查是否包含表单子元素
            let hasFormChild = false;
            if (!isFormLike && node.querySelectorAll) {
              const formInputs = node.querySelectorAll(
                'form, input[type="password"], input[type="text"], input[type="email"], input[type="tel"]'
              );
              hasFormChild = formInputs.length > 0;
            }
            if (isFormLike || hasFormChild) {
              if (state.active && state.panel) {
                setStatus("🆕 检测到新表单元素出现，可开始录制");
              }
              // 新出现的 iframe 也需要绑定监听器
              if (node.querySelectorAll) {
                node.querySelectorAll("iframe, frame").forEach(frame => {
                  try {
                    frame.addEventListener("load", () => {
                      try {
                        if (frame.contentDocument) attachFrameListeners(frame.contentDocument);
                      } catch (_) {}
                    });
                    if (frame.contentDocument) attachFrameListeners(frame.contentDocument);
                  } catch (_) {}
                });
              }
              break;  // 一次变动只通知一次
            }
          }
        }
      });
      _spaFormObserver.observe(document.body, { childList: true, subtree: true });
    } catch (_) {}
  }

  function stopSpaFormWatcher() {
    if (_spaFormObserver) {
      _spaFormObserver.disconnect();
      _spaFormObserver = null;
    }
  }

  // ==================== 使用说明 ====================

  function showHelpModal() {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    overlay.innerHTML = `
      <div class="ca-modal" style="width:600px;max-height:82vh;overflow-y:auto;padding:24px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <h4 style="margin:0;font-size:18px;">📖 Campus-Auth 任务录制器 — 使用说明</h4>
          <button id="ca-help-close" style="background:none;border:none;color:#888;cursor:pointer;font-size:20px;">✕</button>
        </div>

        <div style="line-height:1.8;color:#ccc;">

          <h5 style="color:#667eea;margin:14px 0 6px;">一、启动与关闭</h5>
          <ul style="margin:4px 0;padding-left:18px;">
            <li>快捷键 <b style="color:#fff;">Ctrl+Shift+E</b> 打开或关闭录制器面板</li>
            <li>页面右下角浮动按钮 🎬 也可点击打开</li>
            <li>面板可拖拽（按住顶部蓝色标题栏移动）</li>
          </ul>

          <h5 style="color:#667eea;margin:14px 0 6px;">二、基本录制流程</h5>
          <ol style="margin:4px 0;padding-left:18px;">
            <li>点击面板中的步骤类型按钮（如「账号输入框」），点击页面目标元素录制</li>
            <li>重复以上步骤，依次录完账号、密码、运营商、提交等所有步骤</li>
            <li>点击 <b style="color:#fff;">📋 复制 AI 提示词</b>，将提示词发送给 AI 即可生成完整的任务 JSON</li>
          </ol>

          <h5 style="color:#667eea;margin:14px 0 6px;">三、步骤类型说明</h5>
          <table style="width:100%;font-size:12px;border-collapse:collapse;margin:4px 0;">
            <tr style="color:#aaa;"><td style="padding:3px 6px;">按钮</td><td style="padding:3px 6px;">用途</td><td style="padding:3px 6px;">导出为</td></tr>
            <tr><td style="padding:3px 6px;">👤 账号输入框</td><td style="padding:3px 6px;">点击用户名输入区域</td><td style="padding:3px 6px;"><code>input</code> + {{USERNAME}}</td></tr>
            <tr><td style="padding:3px 6px;">🔒 密码输入框</td><td style="padding:3px 6px;">点击密码输入区域</td><td style="padding:3px 6px;"><code>input</code> + {{PASSWORD}}</td></tr>
            <tr><td style="padding:3px 6px;"> 运营商选择</td><td style="padding:3px 6px;">点下拉框/按钮组（自动识别原生/自定义/按钮组）</td><td style="padding:3px 6px;"><code>select</code> / <code>click_select</code> + {{ISP}}</td></tr>
            <tr><td style="padding:3px 6px;">🖼️ 验证码图片</td><td style="padding:3px 6px;">点击验证码图片</td><td style="padding:3px 6px;"><code>ocr</code> 步骤（与验证码输入框合并）</td></tr>
            <tr><td style="padding:3px 6px;">✏️ 验证码输入</td><td style="padding:3px 6px;">点击验证码输入框</td><td style="padding:3px 6px;"><code>ocr</code> 识别 + 填入</td></tr>
            <tr><td style="padding:3px 6px;">🚀 提交按钮</td><td style="padding:3px 6px;">点击登录/提交按钮</td><td style="padding:3px 6px;"><code>click</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">☑️ 勾选/协议</td><td style="padding:3px 6px;">点击复选框/用户协议勾选框</td><td style="padding:3px 6px;"><code>click</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">🔍 智能检测</td><td style="padding:3px 6px;">打字自动识别账号/密码，点击自动识别勾选/提交/下拉框/图片等</td><td style="padding:3px 6px;">自动分类为对应步骤类型</td></tr>
            <tr><td style="padding:3px 6px;">👆 点击元素</td><td style="padding:3px 6px;">点击任意元素</td><td style="padding:3px 6px;"><code>click</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">⏳ 等待元素</td><td style="padding:3px 6px;">等待某元素出现</td><td style="padding:3px 6px;"><code>wait</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">🔎 检测变动</td><td style="padding:3px 6px;">检测页面元素变化（动态出现/消失/内容变更）</td><td style="padding:3px 6px;"><code>wait</code> / <code>eval</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">⚙️ 执行JS</td><td style="padding:3px 6px;">输入 JS 代码</td><td style="padding:3px 6px;"><code>eval</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">📝 自定义</td><td style="padding:3px 6px;">自定义描述与选择器</td><td style="padding:3px 6px;">通用步骤</td></tr>
            <tr><td style="padding:3px 6px;">⏳ 延时等待</td><td style="padding:3px 6px;">页面不操作仅等待指定时间</td><td style="padding:3px 6px;"><code>sleep</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">📸 页面截图</td><td style="padding:3px 6px;">截取当前页面状态用于调试</td><td style="padding:3px 6px;"><code>screenshot</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">🔗 等待URL</td><td style="padding:3px 6px;">等待浏览器 URL 匹配正则</td><td style="padding:3px 6px;"><code>wait_url</code> 步骤</td></tr>
          </table>

          <h5 style="color:#667eea;margin:14px 0 6px;">四、功能开关</h5>
          <ul style="margin:4px 0;padding-left:18px;">
            <li><b style="color:#fff;">🔁 多步录制</b> — 开启后每次点击/Enter 记录一步，不会自动停止，适合连续录制多个步骤。关闭后每次只记录一步。</li>
            <li><b style="color:#fff;">🔍 隐藏检测</b> — 开启后，当点击容器 <code>div</code> 或 <code>readonly</code> 占位元素时，自动扫描内部 <code>display:none</code> 的隐藏输入框（常见于深澜/Sangfor 和杭州康工 HK Posi 认证页面）。检测到后导出自动使用真实隐藏输入框 + <code>force</code> 模式。</li>
          </ul>

          <h5 style="color:#667eea;margin:14px 0 6px;">五、键盘快捷键</h5>
          <table style="width:100%;font-size:12px;border-collapse:collapse;margin:4px 0;">
            <tr style="color:#aaa;"><td style="padding:3px 6px;">按键</td><td style="padding:3px 6px;">功能</td><td style="padding:3px 6px;">说明</td></tr>
            <tr><td style="padding:3px 6px;"><b style="color:#fff;">Ctrl+Shift+E</b></td><td style="padding:3px 6px;">打开/关闭面板</td><td style="padding:3px 6px;">全局快捷键</td></tr>
            <tr><td style="padding:3px 6px;"><b style="color:#fff;">Esc</b></td><td style="padding:3px 6px;">取消当前录制</td><td style="padding:3px 6px;">清除选中状态，停止录制</td></tr>
            <tr><td style="padding:3px 6px;"><b style="color:#fff;">Enter</b></td><td style="padding:3px 6px;">无 click 记录</td><td style="padding:3px 6px;">记录悬停元素但不发送 click 给页面（下拉菜单保持打开）</td></tr>
          </table>

          <h5 style="color:#667eea;margin:14px 0 6px;">六、典型场景</h5>

          <p style="margin:4px 0;"><b style="color:#fff;">场景 A：普通账号密码登录</b></p>
          <ol style="margin:0 0 8px;padding-left:18px;font-size:12px;">
            <li>点「账号输入框」→ 点页面上账号框</li>
            <li>点「密码输入框」→ 点页面上密码框</li>
            <li>点「提交按钮」→ 点页面登录按钮</li>
            <li>点「📋 复制 AI 提示词」→ 将提示词发送给 AI 生成任务 JSON</li>
          </ol>

          <p style="margin:4px 0;"><b style="color:#fff;">场景 B：运营商选择</b></p>
          <ol style="margin:0 0 8px;padding-left:18px;font-size:12px;">
            <li>点「运营商选择」→ 点目标元素</li>
            <li>原生 <code>&lt;select&gt;</code> 直接完成</li>
            <li>按钮组（如「中国移动」「中国电信」并排按钮）→ 自动检测所有选项，一次完成</li>
            <li>自定义 div 下拉框 → 自动提示"点运营商选项"，点选项后合并为一步</li>
          </ol>

          <p style="margin:4px 0;"><b style="color:#fff;">场景 C：隐藏输入框模式（深澜/HK Posi）</b></p>
          <ol style="margin:0 0 8px;padding-left:18px;font-size:12px;">
            <li>确保 <b style="color:#fff;">🔍 隐藏检测</b> 已开启</li>
            <li>点「账号输入框」→ 点页面上账号占位区域（div 容器或 readonly tip）</li>
            <li>录制器自动检测隐藏的真实输入框，列表中显示 ⚠️ 标记</li>
            <li>点「密码输入框」→ 同样操作</li>
            <li>录制器自动检测隐藏的真实输入框，提示词中会包含 force 模式和隐藏输入框信息</li>
          </ol>

          <!-- 场景 D 已移除：原「完成登录」+ 框选模式已被 AI 提示词方式取代 -->

          <h5 style="color:#667eea;margin:14px 0 6px;">七、获取任务 JSON</h5>
          <ul style="margin:4px 0;padding-left:18px;">
            <li>录制完成后点击 <b style="color:#fff;">📋 复制 AI 提示词</b>，将录制到的元素信息（选择器、类型、属性等）以结构化提示词形式复制到剪贴板</li>
            <li>将提示词发送给 AI（ChatGPT、Claude 等），AI 会参考 <code>doc/task-writing-guide.md</code> 规范生成完整的任务 JSON</li>
            <li>也可以将提示词粘贴到 Campus-Auth 的 Issue 或社区中，方便其他人帮助创建任务</li>
          </ul>

          <h5 style="color:#667eea;margin:14px 0 6px;">八、选择器优先级</h5>
          <p style="margin:4px 0;font-size:12px;">录制器按以下优先级生成选择器：<code>#id</code> &gt; <code>[name="..."]</code> &gt; <code>[type="..."]</code> &gt; <code>[placeholder="..."]</code> &gt; 文本内容 &gt; CSS 路径 &gt; XPath。多个选择器候选会全部保留在 JSON 中，执行时依次尝试。</p>

          <h5 style="color:#667eea;margin:14px 0 6px;">九、技巧与注意事项</h5>
          <ul style="margin:4px 0;padding-left:18px;font-size:12px;">
            <li>录制状态会<b style="color:#fff;">自动保存</b>到油猴存储，刷新页面后自动恢复（2 小时内有效）</li>
            <li>如果元素在 <b style="color:#fff;">iframe</b> 内部，录制器会自动检测并记录 iframe 信息</li>
            <li>连续录制多个步骤时建议开启 <b style="color:#fff;">🔁 多步录制</b></li>
            <li>下拉菜单内的选项建议用 <b style="color:#fff;">Enter</b> 键选取（点击会关闭菜单）</li>
            <li>如果浮层按钮/面板被页面 JS 冲掉，录制器会<b style="color:#fff;">自动恢复</b>（DOM 守护）</li>
            <li>可在列表中点击 ✕ 删除不需要的步骤</li>
          </ul>

          <p style="margin-top:16px;padding-top:12px;border-top:1px solid #333;font-size:11px;color:#666;text-align:center;">
            Campus-Auth 任务录制器 v3.6.7 · <a href="https://github.com/Misyra/Campus-Auth" target="_blank" style="color:#667eea;">GitHub</a>
          </p>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);
    overlay.querySelector("#ca-help-close").addEventListener("click", () => overlay.remove());
  }

  // ==================== 隐藏输入框强制显示 + 高亮 + 面板 ====================
  // 强制显示隐藏输入框，绿色虚线高亮 + 浮动标签，点击直接记录步骤。
  // 左侧新开独立面板列出所有发现的隐藏输入框。

  let _revealedInputs = []; // { el, selector, type, labelText }

  function revealHiddenInputsForRecorder() {
    if (_revealedInputs.length > 0) return; // 已经显示
    _revealedInputs = [];

    const inputs = document.querySelectorAll('input');
    inputs.forEach(el => {
      try {
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) <= 0) {
          // 排除提交/按钮类
          if (el.type === 'submit' || el.type === 'button' || el.type === 'hidden') return;
          // 强制显示
          el.style.setProperty('display', 'inline-block', 'important');
          el.style.setProperty('visibility', 'visible', 'important');
          el.style.setProperty('opacity', '1', 'important');
          el.dataset.caRevealed = '1';
          // 高亮
          el.classList.add('ca-revealed-highlight');
          // 浮动标签
          addRevealLabel(el);
          // 记录
          const tag = el.tagName.toLowerCase();
          let sel = '';
          if (el.id) sel = '#' + CSS.escape(el.id);
          else if (el.name) sel = tag + '[name="' + CSS.escape(el.name) + '"]';
          else sel = tag + (el.type ? '[type="' + el.type + '"]' : '');
          _revealedInputs.push({
            el,
            selector: sel,
            inputType: el.type || 'text',
            labelText: el.name || el.id || el.placeholder || el.type || 'input',
          });
        }
      } catch (_) {}
    });

    // Also scan inside all iframes/frames
    document.querySelectorAll("iframe, frame").forEach(frame => {
      try {
        if (!frame.contentDocument) return;
        const frameInputs = frame.contentDocument.querySelectorAll("input");
        frameInputs.forEach(el => {
          try {
            const s = getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) <= 0) {
              if (el.type === 'submit' || el.type === 'button' || el.type === 'hidden') return;
              el.style.setProperty('display', 'inline-block', 'important');
              el.style.setProperty('visibility', 'visible', 'important');
              el.style.setProperty('opacity', '1', 'important');
              el.dataset.caRevealed = '1';
              el.classList.add('ca-revealed-highlight');
              addRevealLabel(el);
              const tag = el.tagName.toLowerCase();
              let sel = '';
              if (el.id) sel = '#' + CSS.escape(el.id);
              else if (el.name) sel = tag + '[name="' + CSS.escape(el.name) + '"]';
              else sel = tag + (el.type ? '[type="' + el.type + '"]' : '');
              _revealedInputs.push({
                el,
                selector: sel,
                inputType: el.type || 'text',
                labelText: el.name || el.id || el.placeholder || el.type || 'input',
              });
            }
          } catch (_) {}
        });
      } catch (_) {} // cross-origin iframe, skip
    });

    // 监听滚动/调整更新标签位置
    _revealScrollHandler = updateRevealLabels;
    window.addEventListener('scroll', _revealScrollHandler, true);
    window.addEventListener('resize', _revealScrollHandler);

    createRevealPanel();
    if (_revealedInputs.length > 0) {
      setStatus(`👁️ 已显示 ${_revealedInputs.length} 个隐藏输入框，点击高亮框直接记录`);
    } else {
      setStatus('👁️ 未发现隐藏输入框');
    }
  }

  function hideRevealedInputs() {
    _revealedInputs.forEach(({ el }) => {
      try {
        el.style.removeProperty('display');
        el.style.removeProperty('visibility');
        el.style.removeProperty('opacity');
        el.classList.remove('ca-revealed-highlight');
        delete el.dataset.caRevealed;
      } catch (_) {}
    });
    _revealedInputs = [];
    // 移除浮动标签
    document.querySelectorAll('.ca-revealed-label').forEach(l => l.remove());
    // 移除面板
    const panel = document.getElementById('ca-reveal-panel');
    if (panel) panel.remove();
    // 移除监听
    if (_revealScrollHandler) {
      window.removeEventListener('scroll', _revealScrollHandler, true);
      window.removeEventListener('resize', _revealScrollHandler);
      _revealScrollHandler = null;
    }
  }

  let _revealScrollHandler = null;

  // 浮动标签
  function addRevealLabel(el) {
    const label = document.createElement('div');
    label.className = 'ca-revealed-label';
    const typeIcon = el.type === 'password' ? '🔒' : el.type === 'checkbox' ? '☑️' : '👤';
    label.textContent = typeIcon + ' ' + (el.name || el.id || el.type || '');
    label.dataset.forReveal = '1';
    document.body.appendChild(label);
    positionRevealLabel(label, el);
  }

  function positionRevealLabel(label, el) {
    const rect = el.getBoundingClientRect();
    label.style.left = rect.left + 'px';
    label.style.top = rect.top + 'px';
  }

  function updateRevealLabels() {
    const labels = document.querySelectorAll('.ca-revealed-label');
    _revealedInputs.forEach(({ el }, i) => {
      if (labels[i]) positionRevealLabel(labels[i], el);
    });
  }

  // 点击高亮输入框 → 弹出步骤类型选择
  function onRevealedClick(e) {
    if (!state.revealEnabled) return;
    const el = e.target.closest('.ca-revealed-highlight');
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    showRevealPopup(el, e.clientX, e.clientY);
  }

  function showRevealPopup(el, x, y) {
    // 移除旧弹窗
    document.querySelectorAll('.ca-reveal-popup').forEach(p => p.remove());

    const info = getElementInfo(el);
    const selector = info.selectors[0]?.value || '';
    const typeIcon = el.type === 'password' ? '🔒' : el.type === 'checkbox' ? '☑️' : '👤';

    const popup = document.createElement('div');
    popup.className = 'ca-reveal-popup';
    popup.innerHTML = `
      <div class="ca-rpop-header">${typeIcon} <b>${escHtml(selector)}</b></div>
      <div class="ca-rpop-actions">
        <button data-rpop-type="username">👤 账号</button>
        <button data-rpop-type="password">🔒 密码</button>
        <button data-rpop-type="submit">🚀 提交</button>
        <button data-rpop-type="checkbox">☑️ 勾选</button>
        <button data-rpop-type="click">👆 点击</button>
        <button data-rpop-type="dismiss">✕ 忽略</button>
      </div>
    `;
    // 定位
    popup.style.left = Math.min(x, window.innerWidth - 300) + 'px';
    popup.style.top = Math.min(y, window.innerHeight - 200) + 'px';
    document.body.appendChild(popup);

    // 点击选项
    popup.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const stepType = btn.dataset.rpopType;
        if (stepType === 'dismiss') {
          popup.remove();
          return;
        }
        const descMap = {
          username: '账号输入框 → {{USERNAME}}',
          password: '密码输入框 → {{PASSWORD}}',
          submit: '提交按钮',
          checkbox: '勾选: ' + (el.name || el.id || el.tagName),
          click: '点击: ' + (el.name || el.id || el.tagName),
        };
        const step = {
          type: stepType,
          description: descMap[stepType] || '点击元素',
          tag: info.tag,
          bestSelector: selector,
          selectorCandidates: info.selectors.map(s => s.value),
          iframe: info.iframe,
          shadowRoot: info.shadowRoot,
          attrs: info.attrs,
          text: info.text,
          visible: true,
          elementHTML: el.outerHTML,
          elementParentContext: el.parentElement ? el.parentElement.innerHTML.substring(0, 3000) : '',
          elementContainerHTML: findStepContainer(el)?.innerHTML.substring(0, 5000) || '',
          _revealRecorded: true,
        };
        state.steps.push(step);
        updateRecordedList();
        saveState();

        // 移除高亮
        el.classList.remove('ca-revealed-highlight');
        document.querySelectorAll('.ca-revealed-label').forEach(l => {
          if (l.textContent.includes(el.name || el.id || '')) l.remove();
        });
        _revealedInputs = _revealedInputs.filter(r => r.el !== el);
        refreshRevealPanel();
        popup.remove();
        setStatus(`✅ 已记录: ${descMap[stepType]} (${selector})`);

        if (_revealedInputs.length === 0) {
          state.revealEnabled = false;
          const toggle = document.getElementById('ca-toggle-reveal');
          if (toggle) toggle.classList.remove('active');
          const panel = document.getElementById('ca-reveal-panel');
          if (panel) panel.remove();
          setStatus('✅ 所有隐藏输入框已记录');
        }
      });
    });

    // 点击弹窗外关闭
    setTimeout(() => {
      const closePop = (ev) => {
        if (!popup.contains(ev.target)) {
          popup.remove();
          document.removeEventListener('click', closePop, true);
        }
      };
      document.addEventListener('click', closePop, true);
    }, 0);
  }

  // 揭示面板
  function createRevealPanel() {
    const existing = document.getElementById('ca-reveal-panel');
    if (existing) existing.remove();

    const panel = document.createElement('div');
    panel.id = 'ca-reveal-panel';
    panel.innerHTML = `
      <div class="ca-rv-header">
        <span>👁️</span> 隐藏输入框 <span id="ca-rv-count" style="background:#fff;color:#2e7d32;padding:0 6px;border-radius:10px;font-size:11px;">${_revealedInputs.length}</span>
      </div>
      <div id="ca-rv-list"></div>
    `;
    document.body.appendChild(panel);
    refreshRevealPanel();
  }

  function refreshRevealPanel() {
    const list = document.getElementById('ca-rv-list');
    const countEl = document.getElementById('ca-rv-count');
    if (!list) return;
    if (countEl) countEl.textContent = _revealedInputs.length;

    list.innerHTML = _revealedInputs.map((r, i) => {
      const icon = r.inputType === 'password' ? '🔒' : r.inputType === 'checkbox' ? '☑️' : '👤';
      const btnLabel = r.inputType === 'password' ? '密码' : r.inputType === 'checkbox' ? '点击' : '账号';
      return `<div class="ca-rv-item" data-rv-idx="${i}">
        <span class="ca-rv-icon">${icon}</span>
        <div class="ca-rv-info">
          <div class="ca-rv-sel">${escHtml(r.selector)}</div>
          <div class="ca-rv-type">type=${r.inputType} · ${escHtml(r.labelText)}</div>
        </div>
        <button class="ca-rv-btn">${btnLabel}</button>
      </div>`;
    }).join('');

    // 面板内整行点击 → 弹出步骤选择（按钮点击冒泡到行）
    list.querySelectorAll('.ca-rv-item').forEach(row => {
      row.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(row.dataset.rvIdx);
        const item = _revealedInputs[idx];
        if (!item) return;
        const rect = item.el.getBoundingClientRect();
        showRevealPopup(item.el, rect.left + rect.width / 2, rect.top);
      });
    });
  }

  function escHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function activate() {
    if (state.active) return;
    state.active = true;
    createPanel();
    if (state.steps.length > 0) {
      updateRecordedList();
    }
    document.addEventListener("mouseover", onHover, true);
    document.addEventListener("click", onRevealedClick, true);  // 先于 onClick，拦截高亮输入框点击
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeyDown, true);
    attachAllFrameListeners();
    startSpaFormWatcher();
  }

  function deactivate() {
    state.active = false;
    state.recording = false;
    state.carrierClickPhase = null;
    // 恢复被强制显示的隐藏输入框 + 移除面板和高亮
    hideRevealedInputs();
    state.revealEnabled = false;
    document.removeEventListener("mouseover", onHover, true);
    document.removeEventListener("click", onRevealedClick, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKeyDown, true);
    detachAllFrameListeners();
    stopSpaFormWatcher();
    hideTooltip();
    if (state.hoveredEl) {
      state.hoveredEl.classList.remove("ca-highlight");
      state.hoveredEl = null;
    }
    if (state.selectedEl) {
      state.selectedEl.classList.remove("ca-highlight-selected");
      state.selectedEl = null;
    }
    if (state.panel) {
      state.panel.remove();
      state.panel = null;
    }
  }

  function onKeyDown(e) {
    if (e.key === "Escape") {
      if (state.recording) {
        state.recording = false;
        state.currentStepType = null;
        state.carrierClickPhase = null;
        hideTooltip();
        state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
        if (state.hoveredEl) {
          state.hoveredEl.classList.remove("ca-highlight");
          state.hoveredEl = null;
        }
        setStatus("已取消选择");
        e.preventDefault();
        e.stopPropagation();
      }
    }
    // Enter 键：录制模式下记录悬停元素（不触发 click，避免关闭下拉框/弹出菜单）
    if (e.key === "Enter" && state.recording && state.hoveredEl && state.currentStepType) {
      e.preventDefault();
      e.stopPropagation();

      const el = state.hoveredEl;
      const info = getElementInfo(el);
      const type = state.currentStepType;
      const optText = (el.textContent || "").trim().substring(0, 50);

      if (type === "carrier") {
        handleCarrierClickPhase(el, info);
        // handleCarrierClickPhase 内部已调用 updateRecordedList + saveState + setStatus
      } else {
        addStepFromElement(type, el, info, optText || STEP_TYPES[type]?.label || "");
      }

      if (state.hoveredEl) {
        state.hoveredEl.classList.remove("ca-highlight");
        state.hoveredEl = null;
      }
      if (type !== "carrier") {
        updateRecordedList();
        saveState();
        setStatus(`✅ Enter 记录: ${optText || info.tag}`);
      }
    }
    // Ctrl+Shift+E 切换面板
    if (e.ctrlKey && e.shiftKey && e.key === "E") {
      state.active ? deactivate() : activate();
      e.preventDefault();
    }
  }

  // ==================== DOM 守护：防止页面框架清空注入元素 ====================

  // 深澜/Sangfor 等门户在 document-idle 后仍会操作 body.innerHTML，
  // 导致浮动按钮和面板被移除。用 MutationObserver + 定时轮询双保险守护。
  const domGuard = {
    _elems: new Set(),    // 需要守护的 DOM 元素
    _observer: null,
    _interval: 0,
    _pendingRestore: false,

    register(el) {
      if (!el || el.nodeType !== 1) return;
      el.__caGuard = true;
      this._elems.add(el);
    },

    unregister(el) {
      if (el) { delete el.__caGuard; }
      this._elems.delete(el);
    },

    _restoreAll() {
      if (this._pendingRestore) return;
      this._pendingRestore = true;
      // requestAnimationFrame 避免在一次微任务中反复重挂
      requestAnimationFrame(() => {
        this._pendingRestore = false;
        const body = document.body;
        if (!body) return;
        for (const el of this._elems) {
          if (el && !el.isConnected) {
            try { body.appendChild(el); } catch (_) {}
          }
        }
        // 面板激活状态也检查一下
        if (state.active && state.panel && !state.panel.isConnected && body) {
          try { body.appendChild(state.panel); } catch (_) {}
        }
        // 如果面板还在，重新绑定事件（防止 body 被整体替换后事件代理失效）
        if (state.active && state.panel) {
          ensureGlobalListeners();
        }
      });
    },

    start() {
      // 策略1: MutationObserver 监听 body 子节点变动
      const body = document.body;
      if (body && !this._observer) {
        try {
          this._observer = new MutationObserver((records) => {
            for (const r of records) {
              for (const node of r.removedNodes) {
                if (node.nodeType === 1) {
                  // 直接移除
                  if (node.__caGuard) this._restoreAll();
                  // 子节点中包含守护元素
                  if (node.querySelectorAll) {
                    const lost = node.querySelectorAll("[__caGuard]");
                    if (lost.length > 0) this._restoreAll();
                  }
                }
              }
            }
          });
          this._observer.observe(body, { childList: true, subtree: true });
        } catch (_) {}
      }

      // 策略2: 每 2 秒兜底巡检
      if (!this._interval) {
        this._interval = setInterval(() => {
          let missing = false;
          for (const el of this._elems) {
            if (el && !el.isConnected) { missing = true; break; }
          }
          if (!missing && state.active && state.panel && !state.panel.isConnected) {
            missing = true;
          }
          if (missing) this._restoreAll();
        }, 8000);
      }
    },

    stop() {
      if (this._observer) { this._observer.disconnect(); this._observer = null; }
      if (this._interval) { clearInterval(this._interval); this._interval = 0; }
      this._elems.clear();
    },
  };

  // 全局事件监听可能因 body 替换而失效，统一管理
  let _globalListenersAttached = false;
  function ensureGlobalListeners() {
    if (_globalListenersAttached) return;
    document.addEventListener("mouseover", onHover, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeyDown, true);
    attachAllFrameListeners();
    _globalListenersAttached = true;
  }

  function removeGlobalListeners() {
    document.removeEventListener("mouseover", onHover, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKeyDown, true);
    detachAllFrameListeners();
    _globalListenersAttached = false;
  }

  // ==================== 启动 ====================

  // 修改 activate/deactivate 使用新的监听器管理和 DOM 守护
  const _origActivate = activate;
  const _origDeactivate = deactivate;

  activate = function () {
    if (state.active) return;
    _origActivate();
    _globalListenersAttached = true;  // _origActivate 内部已绑定事件
    if (state.panel) domGuard.register(state.panel);
  };

  deactivate = function () {
    if (!state.active) return;
    if (state.panel) domGuard.unregister(state.panel);
    _origDeactivate();
    _globalListenersAttached = false;
  };

  // 检查是否有保存的录制状态，自动恢复（必须在 activate 重写之后，确保 domGuard 注册）
  const savedData = loadState();
  if (savedData) {
    restoreFromSaved(savedData);
  }

  // 添加浮动入口按钮
  const entryBtn = document.createElement("div");
  entryBtn.innerHTML = "🎬";
  entryBtn.title = "Campus-Auth 任务录制器 (Ctrl+Shift+E)";
  Object.assign(entryBtn.style, {
    position: "fixed",
    bottom: "20px",
    right: "20px",
    width: "48px",
    height: "48px",
    borderRadius: "50%",
    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "24px",
    cursor: "pointer",
    zIndex: "2147483647",
    boxShadow: "0 4px 16px rgba(102,126,234,0.4)",
    transition: "transform 0.2s",
    userSelect: "none",
  });
  entryBtn.addEventListener("mouseenter", () => (entryBtn.style.transform = "scale(1.1)"));
  entryBtn.addEventListener("mouseleave", () => (entryBtn.style.transform = "scale(1)"));
  entryBtn.addEventListener("click", () => (state.active ? deactivate() : activate()));
  document.body.appendChild(entryBtn);

  domGuard.register(entryBtn);
  domGuard.start();
})();
