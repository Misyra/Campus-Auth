// ==UserScript==
// @name         Campus-Auth 任务录制器
// @namespace    https://github.com/Misyra/Campus-Auth
// @version      1.0.0
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
    username: { label: "账号输入框", icon: "👤", color: "#4CAF50" },
    password: { label: "密码输入框", icon: "🔒", color: "#2196F3" },
    carrier: { label: "运营商选择", icon: "📶", color: "#FF9800" },
    captcha_img: { label: "验证码图片", icon: "🖼️", color: "#9C27B0" },
    captcha_input: { label: "验证码输入框", icon: "✏️", color: "#9C27B0" },
    submit: { label: "提交按钮", icon: "🚀", color: "#F44336" },
    click: { label: "点击元素", icon: "👆", color: "#607D8B" },
    wait: { label: "等待元素", icon: "⏳", color: "#795548" },
    eval: { label: "执行JS", icon: "⚙️", color: "#00BCD4" },
    custom: { label: "自定义步骤", icon: "📝", color: "#9E9E9E" },
  };

  const CAPTCHA_TYPES = [
    { value: "4digit", label: "4位纯数字" },
    { value: "4char", label: "4位字母+数字" },
    { value: "math", label: "数学运算 (如 1+2=?)" },
    { value: "other", label: "其他（请描述）" },
  ];

  const CONDITION_TYPES = [
    { value: "url_change", label: "页面跳转（URL 变化）", icon: "🔗", hint: "登录成功后 URL 会改变" },
    { value: "text", label: "页面出现特定文字", icon: "📝", hint: "页面上出现「成功」「已连接」等文字" },
    { value: "element", label: "页面出现特定元素", icon: "🎯", hint: "出现某个表示成功的页面元素" },
    { value: "skip", label: "跳过（仅靠步骤完成判断）", icon: "⏭️", hint: "不设置额外条件，步骤全部完成即为成功" },
  ];

  // ==================== 状态 ====================

  const state = {
    active: false,
    recording: false,
    multiStepMode: false,       // 多步录制：开启后每次点击记录一个步骤，不自动停止
    hiddenDetectionEnabled: true, // 隐藏元素检测：自动扫描容器内 display:none 的真实输入框
    steps: [],
    hoveredEl: null,
    selectedEl: null,
    currentStepType: null,
    panel: null,
    tooltip: null,
    iframeWarning: null,
    loginCompleted: false,
    successConditions: [],
  };

  const STORAGE_KEY = "ca_recorder_state";

  function saveState() {
    try {
      GM_setValue(STORAGE_KEY, {
        steps: state.steps,
        loginCompleted: state.loginCompleted,
        successConditions: state.successConditions,
        savedAt: Date.now(),
        url: window.location.href,
      });
    } catch (_) {}
  }

  function loadState() {
    try {
      const data = GM_getValue(STORAGE_KEY, null);
      if (!data || !data.steps || data.steps.length === 0) return false;
      // 超过 2 小时自动过期
      if (Date.now() - (data.savedAt || 0) > 2 * 60 * 60 * 1000) {
        clearSavedState();
        return false;
      }
      // URL 变化说明已跳转，保存的选择器失效
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
    state.loginCompleted = saved.loginCompleted;
    state.successConditions = saved.successConditions || [];
    activate();
    updateRecordedList();
    if (state.loginCompleted) {
      completeLoginUI();
      updateSuccessConditionsList();
      if (state.successConditions.length > 0) showCopyPromptButton();
    }
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
    #ca-recorder-panel .ca-cond-grid {
      display: grid; grid-template-columns: 1fr 1fr; gap: 6px;
    }
    #ca-recorder-panel .ca-cond-btn {
      display: flex; align-items: center; gap: 6px;
      padding: 8px 10px; background: #2a2a3e; border: 1px solid #444;
      border-radius: 8px; cursor: pointer; color: #ddd; font-size: 12px;
      transition: all 0.2s; text-align: left;
    }
    #ca-recorder-panel .ca-cond-btn:hover { background: #3a3a4e; border-color: #667eea; }
    #ca-recorder-panel .ca-cond-btn .ca-cond-icon { font-size: 16px; flex-shrink: 0; }
    #ca-recorder-panel .ca-cond-btn .ca-cond-hint { font-size: 11px; color: #888; }
    #ca-recorder-panel .ca-cond-tag {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 6px 10px; background: #2a2a4e; border-radius: 8px;
      font-size: 12px; border: 1px solid #667eea;
    }
    #ca-recorder-panel .ca-cond-del {
      background: none; border: none; color: #e74c3c; cursor: pointer;
      font-size: 14px; padding: 0 2px;
    }
    #ca-recorder-panel .ca-highlight-phase {
      background: linear-gradient(135deg, #2a1a4e 0%, #1a2a4e 100%);
      border: 1px solid #667eea; border-radius: 8px; padding: 10px 12px;
    }
    #ca-recorder-panel .ca-toolbar { display: flex; gap: 6px; margin-bottom: 8px; }
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
  `);

  // ==================== 选择器生成 ====================

  function getSelectors(el) {
    const selectors = [];

    // 1. ID 选择器（最可靠）
    if (el.id && !/^\d/.test(el.id)) {
      selectors.push({ type: "css", value: `#${CSS.escape(el.id)}`, reliability: 10 });
    }

    // 2. name 属性
    if (el.name) {
      selectors.push({
        type: "css",
        value: `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`,
        reliability: 9,
      });
    }

    // 3. 独特的属性组合
    if (el.type && (el.tagName === "INPUT" || el.tagName === "BUTTON")) {
      const s = `${el.tagName.toLowerCase()}[type="${el.type}"]`;
      if (document.querySelectorAll(s).length === 1) {
        selectors.push({ type: "css", value: s, reliability: 7 });
      }
    }

    // 4. placeholder
    if (el.placeholder) {
      selectors.push({
        type: "css",
        value: `${el.tagName.toLowerCase()}[placeholder="${CSS.escape(el.placeholder)}"]`,
        reliability: 6,
      });
    }

    // 5. 文本内容（按钮/链接）
    const text = (el.textContent || "").trim();
    if (text && text.length < 30 && ["A", "BUTTON", "SPAN", "DIV"].includes(el.tagName)) {
      selectors.push({ type: "text", value: text, reliability: 5 });
    }

    // 6. 短 CSS 路径
    try {
      const shortCss = buildShortCss(el);
      if (shortCss && document.querySelectorAll(shortCss).length === 1) {
        selectors.push({ type: "css", value: shortCss, reliability: 4 });
      }
    } catch (_) {}

    // 7. XPath
    selectors.push({ type: "xpath", value: buildXPath(el), reliability: 3 });

    // 按可靠性排序
    selectors.sort((a, b) => b.reliability - a.reliability);
    return selectors;
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
        const classes = current.className.trim().split(/\s+/).filter(c => c && !/^[\d-]/.test(c));
        if (classes.length > 0) {
          part += "." + classes.slice(0, 2).map(c => CSS.escape(c)).join(".");
        }
      }
      // 加 nth-child 消歧
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
        if (siblings.length > 1) {
          const idx = siblings.indexOf(current) + 1;
          part += `:nth-of-type(${idx})`;
        }
      }
      parts.unshift(part);
      current = current.parentElement;
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
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
        if (siblings.length > 1) {
          const idx = siblings.indexOf(current) + 1;
          part += `[${idx}]`;
        }
      }
      parts.unshift(`/${part}`);
      current = current.parentElement;
    }
    return parts.join("") || "/";
  }

  // ==================== iframe 检测 ====================

  function detectIframe(el) {
    try {
      // 情况 1: 脚本在主文档运行，元素在 iframe/frame 内
      if (el.ownerDocument !== document) {
        const frames = document.querySelectorAll("iframe, frame");
        for (const frame of frames) {
          try {
            if (frame.contentDocument === el.ownerDocument) {
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
          } catch (_) {
            return { inIframe: true, crossOrigin: true, frameSrc: frame.src || "" };
          }
        }
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

  function getElementInfo(el) {
    const tag = el.tagName.toLowerCase();
    const attrs = {};
    for (const attr of el.attributes) {
      if (["id", "class", "name", "type", "placeholder", "value", "href", "src", "action"].includes(attr.name)) {
        attrs[attr.name] = attr.value;
      }
    }

    return {
      tag,
      attrs,
      text: (el.textContent || "").trim().substring(0, 100),
      selectors: getSelectors(el),
      iframe: detectIframe(el),
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
      // username / captcha_input 等：text 类输入框
      typeSelector = 'input[type="text"], input:not([type])';
    }

    // 搜索范围：从特定容器类名到通用父元素
    const containerSelectors = [
      "li, form",
      ".ant-input-affix-wrapper",       // 模式1: 深澜
      "div[id$='_posi']",              // 模式2: HK Posi 的 username_hk_posi
      ".login_frame_hang_1",           // 模式2: HK Posi 容器类
      ".input-group, .form-group",
    ];
    let container = null;
    for (const sel of containerSelectors) {
      container = el.closest(sel);
      if (container) break;
    }
    if (!container) container = el.parentElement;
    if (!container) return null;

    // 在容器及父元素中搜索隐藏的匹配输入框
    const searchRoots = [container];
    // 模式2：比如点了 username_tip，真实 input 在父元素 #userNameDiv 里
    const parent = el.parentElement;
    if (parent && !searchRoots.includes(parent)) {
      searchRoots.push(parent);
    }

    for (const root of searchRoots) {
      if (!root) continue;
      const candidates = root.querySelectorAll(typeSelector);
      for (const input of candidates) {
        if (input === el) continue;
        if (input.readOnly) continue;  // 跳过 tip 本身
        if (!isElementHidden(input)) continue;

        if (input.id) return `#${CSS.escape(input.id)}`;
        if (input.name) return `input[name="${CSS.escape(input.name)}"]`;
      }
    }

    // 兜底：在容器内搜索所有隐藏 input（不限类型），适用于 type 属性缺失的情况
    for (const root of searchRoots) {
      if (!root) continue;
      const allHidden = root.querySelectorAll("input");
      for (const input of allHidden) {
        if (input === el) continue;
        if (input.readOnly) continue;
        if (!isElementHidden(input)) continue;
        // 排除明显不对的类型
        if (input.type === "submit" || input.type === "button" || input.type === "checkbox" || input.type === "radio") continue;

        if (input.id) return `#${CSS.escape(input.id)}`;
        if (input.name) return `input[name="${CSS.escape(input.name)}"]`;
      }
    }

    return null;
  }

  // 检查元素是否实际隐藏（综合考虑 display:none / visibility:hidden / offsetParent）
  function isElementHidden(el) {
    if (!el) return true;
    if (el.offsetParent === null) return true;
    try {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden") return true;
    } catch (_) {}
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
            <small>v1.0 — 选取元素，生成任务配置</small>
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
            <span style="color:#667eea;">💡 运营商下拉框建议：打开多步录制 → 点下拉框 → 切「点击元素」→ 点选项</span>
          </div>
        </div>
        <div class="ca-section">
          <div class="ca-section-title">已录制步骤</div>
          <ul class="ca-recorded-list" id="ca-recorded-list"></ul>
          <div class="ca-actions">
            <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-btn-undo" disabled>↩ 撤销</button>
            <button class="ca-btn ca-btn-danger ca-btn-sm" id="ca-btn-clear" disabled>🗑 清空</button>
            <button class="ca-btn ca-btn-success ca-btn-sm" id="ca-btn-complete" style="margin-left:auto;" disabled>✅ 完成登录</button>
          </div>
        </div>
        <div class="ca-section" id="ca-success-section" style="display:none;">
          <div class="ca-highlight-phase">
            <div class="ca-section-title" style="color:#aaa;">登录成功后页面会怎样？</div>
            <div id="ca-cond-list" style="margin-bottom:8px;"></div>
            <div class="ca-cond-grid" id="ca-cond-grid"></div>
          </div>
        </div>
        <div class="ca-status" id="ca-status">选择步骤类型后点击页面元素</div>
        <div class="ca-actions" style="margin-top:12px;">
          <button class="ca-btn ca-btn-primary" id="ca-btn-copy-prompt" style="display:none;">📋 复制 AI 提示词</button>
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

    // 生成步骤按钮
    const grid = state.panel.querySelector("#ca-step-grid");
    for (const [key, cfg] of Object.entries(STEP_TYPES)) {
      const btn = document.createElement("div");
      btn.className = "ca-step-btn";
      btn.dataset.type = key;
      btn.innerHTML = `<span class="ca-icon">${cfg.icon}</span><span>${cfg.label}</span>`;
      btn.addEventListener("click", () => selectStepType(key));
      grid.appendChild(btn);
    }

    // 多步录制 / 隐藏检测 切换按钮
    const toggleMulti = state.panel.querySelector("#ca-toggle-multistep");
    const toggleDetect = state.panel.querySelector("#ca-toggle-detect");
    const refreshToggles = () => {
      toggleMulti.classList.toggle("active", state.multiStepMode);
      toggleDetect.classList.toggle("active", state.hiddenDetectionEnabled);
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
    toggleDetect.addEventListener("click", () => {
      state.hiddenDetectionEnabled = !state.hiddenDetectionEnabled;
      refreshToggles();
      if (state.hiddenDetectionEnabled) {
        setStatus("🔍 隐藏元素检测已开启");
      } else {
        setStatus("隐藏元素检测已关闭");
      }
    });

    // 生成条件类型按钮
    const condGrid = state.panel.querySelector("#ca-cond-grid");
    for (const ct of CONDITION_TYPES) {
      const btn = document.createElement("div");
      btn.className = "ca-cond-btn";
      btn.innerHTML = `<span class="ca-cond-icon">${ct.icon}</span><div><div>${ct.label}</div><div class="ca-cond-hint">${ct.hint}</div></div>`;
      btn.addEventListener("click", () => handleConditionType(ct.value));
      condGrid.appendChild(btn);
    }

    // 事件绑定
    state.panel.querySelector("#ca-btn-undo").addEventListener("click", undoStep);
    state.panel.querySelector("#ca-btn-clear").addEventListener("click", clearSteps);
    state.panel.querySelector("#ca-btn-complete").addEventListener("click", completeLogin);
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
    state.panel.querySelectorAll(".ca-step-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.type === type);
    });
    setStatus(`已选择 [${STEP_TYPES[type].label}]，点击页面元素  |  Enter=无click记录  Esc=取消`, "recording");
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
          <div class="ca-label">${STEP_TYPES[s.type]?.icon || "📝"} ${STEP_TYPES[s.type]?.label || s.type}: ${s.description || ""}${warningIcon}</div>
          <div class="ca-selector" title="${displaySelector}">${displaySelector}</div>
        </div>
        <button class="ca-del" data-idx="${i}" title="删除">✕</button>
      </li>
    `;
        }
      )
      .join("");

    list.querySelectorAll(".ca-del").forEach(btn => {
      btn.addEventListener("click", () => {
        state.steps.splice(parseInt(btn.dataset.idx), 1);
        updateRecordedList();
        saveState();
        updateButtons();
      });
    });

    updateButtons();
  }

  function updateButtons() {
    const has = state.steps.length > 0;
    const completed = state.loginCompleted;
    state.panel.querySelector("#ca-btn-undo").disabled = !has || completed;
    state.panel.querySelector("#ca-btn-clear").disabled = !has || completed;
    state.panel.querySelector("#ca-btn-complete").disabled = !has;

    // 登录完成后隐藏撤销/清空/完成按钮
    if (completed) {
      state.panel.querySelector("#ca-btn-undo").style.display = "none";
      state.panel.querySelector("#ca-btn-clear").style.display = "none";
      state.panel.querySelector("#ca-btn-complete").style.display = "none";
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
    state.loginCompleted = false;
    state.successConditions = [];
    updateRecordedList();
    clearSavedState();
    setStatus("已清空所有步骤");
  }

  // ==================== 成功条件流程 ====================

  function completeLogin() {
    state.loginCompleted = true;
    state.recording = false;
    completeLoginUI();
    saveState();
    setStatus("录制完成！请选择登录成功的判断方式");
  }

  function completeLoginUI() {
    state.panel.querySelectorAll(".ca-step-btn").forEach(b => {
      b.classList.remove("active");
      b.style.opacity = "0.3";
      b.style.pointerEvents = "none";
    });
    updateButtons();
    state.panel.querySelector("#ca-success-section").style.display = "block";
  }

  function handleConditionType(type) {
    if (type === "skip") {
      addSuccessCondition({ type: "skip" });
      return;
    }
    if (type === "url_change") {
      showConditionModal("url_change");
      return;
    }
    if (type === "text") {
      showConditionModal("text");
      return;
    }
    if (type === "element") {
      // 进入元素选择模式
      state.currentStepType = "success_condition";
      state.recording = true;
      setStatus("请点击表示登录成功的页面元素", "recording");
    }
  }

  function showConditionModal(type) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";

    let content = "";
    if (type === "url_change") {
      content = `
        <h4>🔗 页面跳转条件</h4>
        <label>登录成功后 URL 会包含的关键词（正则表达式）</label>
        <input type="text" id="ca-cond-pattern" placeholder="如: success|welcome|home|portal" />
        <div style="font-size:12px;color:#888;margin-bottom:10px;">多个关键词用 | 分隔，匹配登录成功后跳转的 URL</div>
      `;
    } else if (type === "text") {
      content = `
        <h4>📝 页面文字条件</h4>
        <label>登录成功后页面上会出现的文字</label>
        <input type="text" id="ca-cond-text" placeholder="如: 登录成功、已连接、欢迎" />
        <div style="font-size:12px;color:#888;margin-bottom:10px;">如果登录后页面显示这些文字，即判断为成功</div>
      `;
    }

    overlay.innerHTML = `
      <div class="ca-modal">
        ${content}
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-cond-cancel">取消</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-cond-confirm">确定</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-cond-cancel").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#ca-cond-confirm").addEventListener("click", () => {
      if (type === "url_change") {
        const pattern = overlay.querySelector("#ca-cond-pattern").value.trim();
        if (!pattern) return;
        overlay.remove();
        addSuccessCondition({ type: "url_matches", pattern, label: `URL 匹配: ${pattern}` });
      } else if (type === "text") {
        const text = overlay.querySelector("#ca-cond-text").value.trim();
        if (!text) return;
        overlay.remove();
        addSuccessCondition({ type: "js_expression", script: `document.body.innerText.includes('${text.replace(/'/g, "\\'")}')`, label: `页面包含: ${text}` });
      }
    });
  }

  function addSuccessCondition(condition) {
    state.successConditions.push(condition);
    updateSuccessConditionsList();
    saveState();
    showCopyPromptButton();
    const label = condition.label || CONDITION_TYPES.find(c => c.value === condition.type)?.label || condition.type;
    setStatus(`✅ 已添加条件: ${label}`);
  }

  function updateSuccessConditionsList() {
    const list = state.panel.querySelector("#ca-cond-list");
    list.innerHTML = state.successConditions
      .map(
        (c, i) => `
      <span class="ca-cond-tag">
        ${c.label || c.type}
        <button class="ca-cond-del" data-idx="${i}" title="删除">✕</button>
      </span>
    `
      )
      .join("");

    list.querySelectorAll(".ca-cond-del").forEach(btn => {
      btn.addEventListener("click", () => {
        state.successConditions.splice(parseInt(btn.dataset.idx), 1);
        updateSuccessConditionsList();
        saveState();
        if (state.successConditions.length === 0) hideCopyPromptButton();
      });
    });
  }

  function showCopyPromptButton() {
    state.panel.querySelector("#ca-btn-copy-prompt").style.display = "";
  }

  function hideCopyPromptButton() {
    state.panel.querySelector("#ca-btn-copy-prompt").style.display = "none";
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
    if (!state.recording) return;
    const el = e.target;
    if (el === state.panel || state.panel?.contains(el)) return;
    if (el.closest("#ca-tooltip")) return;

    e.preventDefault();
    e.stopPropagation();

    el.classList.remove("ca-highlight");
    el.classList.add("ca-highlight-selected");
    if (state.selectedEl && state.selectedEl !== el) {
      state.selectedEl.classList.remove("ca-highlight-selected");
    }
    state.selectedEl = el;

    const info = getElementInfo(el);
    hideTooltip();

    // 调用处理函数（carrier 可能保持录制状态）
    handleElementSelected(el, info);

    // 如果录制仍开启（carrier 两阶段第一阶段），重放点击触发页面行为（打开下拉框）
    if (state.recording) {
      const newEvt = new MouseEvent("click", {
        bubbles: true, cancelable: true, view: window,
        clientX: e.clientX, clientY: e.clientY,
      });
      el.dispatchEvent(newEvt);
    }
  }

  function handleElementSelected(el, info) {
    const type = state.currentStepType;

    if (type === "success_condition") {
      const bestSelector = info.selectors[0]?.value || "";
      const desc = info.text ? `元素: ${info.text.substring(0, 20)}` : `元素: ${info.tag}`;
      addSuccessCondition({
        type: "element_exists",
        selector: bestSelector,
        label: `存在元素: ${bestSelector}`,
      });
      state.recording = false;
      state.selectedEl?.classList.remove("ca-highlight-selected");
      state.selectedEl = null;
      return;
    }

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
      addStepFromElement(type, el, info, "运营商选择");
      return;
    }
    if (type === "submit") {
      addStepFromElement(type, el, info, "提交按钮");
      return;
    }

    // 通用步骤：弹出自定义描述
    showCustomStepModal(type, el, info);
  }

  function addStepFromElement(type, el, info, description) {
    const bestSelector = info.selectors[0]?.value || "";
    const selectorCandidates = info.selectors.map(s => s.value);

    // 检测隐藏输入框模式（深澜 / 杭州康工 HK Posi 等）
    let hiddenRealSelector = null;
    let hiddenWarning = "";
    const isInputStep = type === "username" || type === "password" || type === "captcha_input";

    if (isInputStep && state.hiddenDetectionEnabled) {
      // 触发条件：
      //   1. 元素本身 display:none
      //   2. 密码步骤但点中的是 type="text"（深澜/Sangfor）
      //   3. 选中元素是 readonly/disabled 占位（HK Posi 的 input_tip）
      //   4. 选中元素是容器 div/span（HK Posi 的 _hk_posi 外层容器）
      const typeWrong = (type === "password" && info.attrs.type !== "password");
      const isTip = el.readOnly || el.disabled;
      const isContainer = el.tagName !== "INPUT" && el.tagName !== "TEXTAREA";
      if (isElementHidden(el) || typeWrong || isTip || isContainer) {
        hiddenRealSelector = detectHiddenRealInput(el, type);
        if (hiddenRealSelector) {
          const reasons = [];
          if (isElementHidden(el)) reasons.push("所选元素 display:none");
          if (typeWrong) reasons.push(`所选元素 type="${info.attrs.type || "text"}" 非预期`);
          if (isTip) reasons.push("所选元素为 readonly 占位");
          if (isContainer && !isTip && !isElementHidden(el)) reasons.push("所选元素为容器 div，自动扫描内部隐藏输入框");
          hiddenWarning = `⚠️ 检测到隐藏输入框！${reasons.join("；")}。真实输入框 ${hiddenRealSelector} 已自动识别，导出时将使用 force 模式。`;
        }
      }
    }

    // 如果真实输入框和点击元素不同，记录 tip 选择器（用于生成点击步骤触发门户 JS）
    const tipSelector = hiddenRealSelector && hiddenRealSelector !== bestSelector ? bestSelector : null;

    const step = {
      type,
      description,
      tag: info.tag,
      bestSelector,
      selectorCandidates,
      iframe: info.iframe,
      attrs: info.attrs,
      text: info.text,
      visible: info.visible,
      hiddenRealSelector,
      hiddenWarning,
      tipSelector,
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
    if (!state.multiStepMode) {
      state.recording = false;
      state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
    }
    // 多步模式下保持录制，状态提示
    if (state.multiStepMode && state.recording) {
      const nextHint = state.currentStepType
        ? `继续 [${STEP_TYPES[state.currentStepType]?.label || state.currentStepType}] — 点击下一个元素或按 Esc 停止`
        : "点击下一个元素或选择步骤类型，按 Esc 停止";
      setStatus(`🔁 ${nextHint}`, "recording");
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
      state.recording = true;
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
        <input type="text" id="ca-custom-selector" placeholder="CSS 选择器" value="${info.selectors[0]?.value || ""}" />
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
        attrs: info.attrs,
        text: info.text,
        value: value || undefined,
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

  function generatePrompt(url) {
    let prompt = `请根据以下校园网登录页面的元素信息，生成 Campus-Auth 的任务 JSON 配置。\n\n`;
    prompt += `任务编写规范请参考 Campus-Auth 项目中的 doc/task-writing-guide.md 文档。\n\n`;
    prompt += `页面地址: ${url}\n`;
    prompt += `> **重要：不要填写 url 字段。** 任务 JSON 的 url 字段请留空或使用 "{{LOGIN_URL}}"，由用户自行在 Campus-Auth 系统设置中配置认证地址。硬编码 URL 会导致任务无法通用。\n\n`;

    // 步骤类型映射表
    prompt += `## 步骤类型映射（录制器 → 任务JSON）\n\n`;
    prompt += `| 录制器类型 | 任务JSON类型 | 说明 |\n`;
    prompt += `|-----------|-------------|------|\n`;
    prompt += `| username | input | value: {{USERNAME}} |\n`;
    prompt += `| password | input | value: {{PASSWORD}}，隐藏输入框需 force:true |\n`;
    prompt += `| carrier | select | value: {{ISP}} |\n`;
    prompt += `| captcha_img + captcha_input | ocr | 合并为一个 ocr 步骤，selector=图片, target_selector=输入框 |\n`;
    prompt += `| submit | click | — |\n`;
    prompt += `| click | click | — |\n`;
    prompt += `| wait | wait | — |\n`;
    prompt += `| eval | eval | — |\n`;
    prompt += `\n`;

    // 隐藏输入框警告汇总
    const hiddenSteps = state.steps.filter(s => s.hiddenRealSelector);
    if (hiddenSteps.length > 0) {
      prompt += `## ⚠️ 隐藏输入框检测\n\n`;
      prompt += `以下步骤的真实输入框是 display:none，必须使用 force:true 模式：\n\n`;
      for (const hs of hiddenSteps) {
        prompt += `- ${STEP_TYPES[hs.type]?.label || hs.type}: 真实输入框 \`${hs.hiddenRealSelector}\``;
        if (hs.tipSelector) {
          prompt += `，占位元素 \`${hs.tipSelector}\`（建议先 click 占位元素触发门户 JS）`;
        }
        prompt += `\n`;
      }
      prompt += `\n`;
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

    // 成功条件
    if (state.successConditions.length > 0) {
      prompt += `## 登录成功条件\n\n`;
      for (const sc of state.successConditions) {
        if (sc.type === "skip") {
          prompt += `- 跳过（不设置条件）→ success_conditions 应为空数组 []\n`;
        } else if (sc.type === "url_matches") {
          prompt += `- URL 匹配: \`${sc.pattern}\`\n`;
        } else if (sc.type === "js_expression") {
          prompt += `- 页面包含文字: ${sc.label || sc.script}\n`;
        } else if (sc.type === "element_exists") {
          prompt += `- 页面存在元素: \`${sc.selector}\`\n`;
        }
      }
      prompt += `\n`;
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
      if (s.hiddenRealSelector) {
        prompt += `- ⚠️ 真实输入框（隐藏）: \`${s.hiddenRealSelector}\` → 需 force:true\n`;
      }
      if (s.tipSelector) {
        prompt += `- 占位元素: \`${s.tipSelector}\` → 需先 click 触发显示\n`;
      }
      if (s.iframe?.inIframe) {
        prompt += `- 在 iframe 内: ${s.iframe.crossOrigin ? "跨域" : s.iframe.frameSelector || "是"}\n`;
      }
      if (s.captchaType) {
        prompt += `- 验证码类型: ${CAPTCHA_TYPES.find(t => t.value === s.captchaType)?.label || s.captchaType}\n`;
      }
      prompt += `\n`;
    });

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

  function attachAllFrameListeners() {
    document.querySelectorAll("iframe, frame").forEach(frame => {
      try {
        if (frame.contentDocument) {
          attachFrameListeners(frame.contentDocument);
        }
      } catch (_) {}
    });
  }

  function detachAllFrameListeners() {
    document.querySelectorAll("iframe, frame").forEach(frame => {
      try {
        if (frame.contentDocument) {
          detachFrameListeners(frame.contentDocument);
        }
      } catch (_) {}
    });
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
            <li>点击面板中的步骤类型按钮（如「账号输入框」）</li>
            <li>鼠标移到页面目标元素上，会显示蓝色高亮 + 选择器信息</li>
            <li><b style="color:#fff;">点击</b>元素 → 记录步骤 → 显示在「已录制步骤」列表中</li>
            <li>重复以上步骤，依次录完所有步骤</li>
            <li>录完后点击 <b style="color:#fff;">✅ 完成登录</b>，设置登录成功条件</li>
            <li>点击 <b style="color:#fff;">📋 复制 AI 提示词</b>，将提示词发送给 AI（ChatGPT/Claude 等）即可生成完整的任务 JSON</li>
          </ol>

          <h5 style="color:#667eea;margin:14px 0 6px;">三、步骤类型说明</h5>
          <table style="width:100%;font-size:12px;border-collapse:collapse;margin:4px 0;">
            <tr style="color:#aaa;"><td style="padding:3px 6px;">按钮</td><td style="padding:3px 6px;">用途</td><td style="padding:3px 6px;">导出为</td></tr>
            <tr><td style="padding:3px 6px;">👤 账号输入框</td><td style="padding:3px 6px;">点击用户名输入区域</td><td style="padding:3px 6px;"><code>input</code> + {{USERNAME}}</td></tr>
            <tr><td style="padding:3px 6px;">🔒 密码输入框</td><td style="padding:3px 6px;">点击密码输入区域</td><td style="padding:3px 6px;"><code>input</code> + {{PASSWORD}}</td></tr>
            <tr><td style="padding:3px 6px;">📶 运营商选择</td><td style="padding:3px 6px;">点击运营商下拉框</td><td style="padding:3px 6px;"><code>select</code> + {{ISP}}</td></tr>
            <tr><td style="padding:3px 6px;">🖼️ 验证码图片</td><td style="padding:3px 6px;">点击验证码图片</td><td style="padding:3px 6px;"><code>ocr</code> 步骤（与验证码输入框合并）</td></tr>
            <tr><td style="padding:3px 6px;">✏️ 验证码输入</td><td style="padding:3px 6px;">点击验证码输入框</td><td style="padding:3px 6px;"><code>ocr</code> 识别 + 填入</td></tr>
            <tr><td style="padding:3px 6px;">🚀 提交按钮</td><td style="padding:3px 6px;">点击登录/提交按钮</td><td style="padding:3px 6px;"><code>click</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">👆 点击元素</td><td style="padding:3px 6px;">点击任意元素</td><td style="padding:3px 6px;"><code>click</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">⏳ 等待元素</td><td style="padding:3px 6px;">等待某元素出现</td><td style="padding:3px 6px;"><code>wait</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">⚙️ 执行JS</td><td style="padding:3px 6px;">输入 JS 代码</td><td style="padding:3px 6px;"><code>eval</code> 步骤</td></tr>
            <tr><td style="padding:3px 6px;">📝 自定义</td><td style="padding:3px 6px;">自定义描述与选择器</td><td style="padding:3px 6px;">通用步骤</td></tr>
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
            <li>点「✅ 完成登录」→ 设置成功条件 → 复制 AI 提示词</li>
          </ol>

          <p style="margin:4px 0;"><b style="color:#fff;">场景 B：运营商下拉框（自定义 UI，非原生 select）</b></p>
          <ol style="margin:0 0 8px;padding-left:18px;font-size:12px;">
            <li>点「运营商选择」→ 点下拉框触发器</li>
            <li>下拉框弹出后，切到「点击元素」→ <b style="color:#fff;">用 Enter 键</b>点选项（避免点击关掉下拉框）</li>
            <li>点「提交按钮」→ 点登录按钮</li>
            <li>完成 → 复制 AI 提示词</li>
          </ol>

          <p style="margin:4px 0;"><b style="color:#fff;">场景 C：隐藏输入框模式（深澜/HK Posi）</b></p>
          <ol style="margin:0 0 8px;padding-left:18px;font-size:12px;">
            <li>确保 <b style="color:#fff;">🔍 隐藏检测</b> 已开启</li>
            <li>点「账号输入框」→ 点页面上账号占位区域（div 容器或 readonly tip）</li>
            <li>录制器自动检测隐藏的真实输入框，列表中显示 ⚠️ 标记</li>
            <li>点「密码输入框」→ 同样操作</li>
            <li>录制器自动检测隐藏的真实输入框，提示词中会包含 force 模式和隐藏输入框信息</li>
          </ol>

          <h5 style="color:#667eea;margin:14px 0 6px;">七、登录成功条件</h5>
          <ul style="margin:4px 0;padding-left:18px;">
            <li><b style="color:#fff;">页面跳转</b> — 登录后 URL 包含的关键词（如 <code>success|welcome</code>）</li>
            <li><b style="color:#fff;">页面文字</b> — 登录后页面出现的文字（如「登录成功」）</li>
            <li><b style="color:#fff;">页面元素</b> — 登录后出现的特定元素（点击即可记录其选择器）</li>
            <li><b style="color:#fff;">跳过</b> — 不设置条件，步骤全执行完即视为成功</li>
          </ul>

          <h5 style="color:#667eea;margin:14px 0 6px;">八、获取任务 JSON</h5>
          <ul style="margin:4px 0;padding-left:18px;">
            <li>录制完成后点击 <b style="color:#fff;">📋 复制 AI 提示词</b>，将录制到的元素信息（选择器、类型、属性等）以结构化提示词形式复制到剪贴板</li>
            <li>将提示词发送给 AI（ChatGPT、Claude 等），AI 会参考 <code>doc/task-writing-guide.md</code> 规范生成完整的任务 JSON</li>
            <li>也可以将提示词粘贴到 Campus-Auth 的 Issue 或社区中，方便其他人帮助创建任务</li>
          </ul>

          <h5 style="color:#667eea;margin:14px 0 6px;">九、选择器优先级</h5>
          <p style="margin:4px 0;font-size:12px;">录制器按以下优先级生成选择器：<code>#id</code> &gt; <code>[name="..."]</code> &gt; <code>[type="..."]</code> &gt; <code>[placeholder="..."]</code> &gt; 文本内容 &gt; CSS 路径 &gt; XPath。多个选择器候选会全部保留在 JSON 中，执行时依次尝试。</p>

          <h5 style="color:#667eea;margin:14px 0 6px;">十、技巧与注意事项</h5>
          <ul style="margin:4px 0;padding-left:18px;font-size:12px;">
            <li>录制状态会<b style="color:#fff;">自动保存</b>到油猴存储，刷新页面后自动恢复（2 小时内有效）</li>
            <li>如果元素在 <b style="color:#fff;">iframe</b> 内部，录制器会自动检测并记录 iframe 信息</li>
            <li>连续录制多个步骤时建议开启 <b style="color:#fff;">🔁 多步录制</b></li>
            <li>下拉菜单内的选项建议用 <b style="color:#fff;">Enter</b> 键选取（点击会关闭菜单）</li>
            <li>如果浮层按钮/面板被页面 JS 冲掉，录制器会<b style="color:#fff;">自动恢复</b>（DOM 守护）</li>
            <li>可在列表中点击 ✕ 删除不需要的步骤</li>
          </ul>

          <p style="margin-top:16px;padding-top:12px;border-top:1px solid #333;font-size:11px;color:#666;text-align:center;">
            Campus-Auth 任务录制器 v1.0 · <a href="https://github.com/Misyra/Campus-Auth" target="_blank" style="color:#667eea;">GitHub</a>
          </p>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);
    overlay.querySelector("#ca-help-close").addEventListener("click", () => overlay.remove());
  }

  function activate() {
    if (state.active) return;
    state.active = true;
    createPanel();
    document.addEventListener("mouseover", onHover, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeyDown, true);
    // 对已加载的 frame 也绑定事件
    attachAllFrameListeners();
  }

  function deactivate() {
    state.active = false;
    state.recording = false;
    state.loginCompleted = false;
    state.successConditions = [];
    clearSavedState();
    document.removeEventListener("mouseover", onHover, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKeyDown, true);
    detachAllFrameListeners();
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
    // Esc 取消当前选择
    if (e.key === "Escape") {
      if (state.recording) {
        state.recording = false;
        state.currentStepType = null;
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

      addStepFromElement(type, el, info, optText || STEP_TYPES[type]?.label || "");

      if (state.hoveredEl) {
        state.hoveredEl.classList.remove("ca-highlight");
        state.hoveredEl = null;
      }
      updateRecordedList();
      saveState();
      setStatus(`✅ Enter 记录: ${optText || info.tag}`);
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
        }, 2000);
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

  // 检查是否有保存的录制状态，自动恢复
  const savedData = loadState();
  if (savedData) {
    restoreFromSaved(savedData);
  }

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
