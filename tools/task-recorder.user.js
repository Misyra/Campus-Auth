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
    steps: [],
    hoveredEl: null,
    selectedEl: null,
    currentStepType: null,
    panel: null,
    tooltip: null,
    overlay: null,
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
      if (state.successConditions.length > 0) showExportButtons();
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
    #ca-recorded-item .ca-info { flex: 1; min-width: 0; overflow: hidden; }
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
      if (el.ownerDocument !== document) {
        // 元素在 iframe 内
        const frames = document.querySelectorAll("iframe");
        for (const frame of frames) {
          try {
            if (frame.contentDocument === el.ownerDocument) {
              return {
                inIframe: true,
                frameSrc: frame.src || "",
                frameName: frame.name || "",
                frameId: frame.id || "",
                frameSelector: frame.id
                  ? `#${frame.id}`
                  : frame.name
                    ? `iframe[name="${frame.name}"]`
                    : buildShortCss(frame),
              };
            }
          } catch (_) {
            // 跨域 iframe
            return { inIframe: true, crossOrigin: true, frameSrc: frame.src || "" };
          }
        }
        return { inIframe: true, crossOrigin: false };
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
      ? `<div class="ca-tt-hint">⚠️ 位于 iframe 内${info.iframe.crossOrigin ? "（跨域）" : ""}</div>`
      : "";

    state.tooltip.innerHTML = `${tag}${id}${cls}${iframeHint}`;
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
        <h3>🎬 Campus-Auth 任务录制器</h3>
        <small>v1.0 — 选取元素，生成任务配置</small>
      </div>
      <div class="ca-body">
        <div class="ca-section">
          <div class="ca-section-title">选择步骤类型后点击页面元素</div>
          <div class="ca-step-grid" id="ca-step-grid"></div>
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
          <button class="ca-btn ca-btn-success" id="ca-btn-export-json" style="display:none;">📋 导出 JSON</button>
          <button class="ca-btn ca-btn-primary" id="ca-btn-export-md" style="display:none;">📄 导出文档</button>
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
    state.panel.querySelector("#ca-btn-export-json").addEventListener("click", () => exportJSON());
    state.panel.querySelector("#ca-btn-export-md").addEventListener("click", () => exportMarkdown());
    state.panel.querySelector("#ca-btn-close").addEventListener("click", deactivate);

    // 拖拽
    makeDraggable(state.panel, state.panel.querySelector("#ca-drag-handle"));
  }

  function selectStepType(type) {
    state.currentStepType = type;
    // 高亮按钮
    state.panel.querySelectorAll(".ca-step-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.type === type);
    });
    setStatus(`已选择 [${STEP_TYPES[type].label}]，点击页面元素`, "recording");
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
        (s, i) => `
      <li class="ca-recorded-item">
        <span class="ca-idx">${i + 1}</span>
        <div class="ca-info">
          <div class="ca-label">${STEP_TYPES[s.type]?.icon || "📝"} ${STEP_TYPES[s.type]?.label || s.type}: ${s.description || ""}</div>
          <div class="ca-selector" title="${s.bestSelector || ""}">${s.bestSelector || "(无选择器)"}</div>
        </div>
        <button class="ca-del" data-idx="${i}" title="删除">✕</button>
      </li>
    `
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
    showExportButtons();
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
        if (state.successConditions.length === 0) hideExportButtons();
      });
    });
  }

  function showExportButtons() {
    state.panel.querySelector("#ca-btn-export-json").style.display = "";
    state.panel.querySelector("#ca-btn-export-md").style.display = "";
  }

  function hideExportButtons() {
    state.panel.querySelector("#ca-btn-export-json").style.display = "none";
    state.panel.querySelector("#ca-btn-export-md").style.display = "none";
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
    state.recording = false;
    hideTooltip();

    // 根据步骤类型走不同流程
    handleElementSelected(el, info);
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

    const step = {
      type,
      description,
      tag: info.tag,
      bestSelector,
      selectorCandidates,
      iframe: info.iframe,
      attrs: info.attrs,
      text: info.text,
    };

    state.steps.push(step);
    state.selectedEl?.classList.remove("ca-highlight-selected");
    state.selectedEl = null;
    updateRecordedList();
    saveState();
    setStatus(`已添加: ${description}`);
    state.recording = false;
    state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
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

  // ==================== 导出: 任务 JSON ====================

  function exportJSON() {
    const url = window.location.href;
    const steps = [];
    let stepIdx = 1;

    // 检查是否有验证码
    const hasCaptchaImg = state.steps.some(s => s.type === "captcha_img");
    const hasCaptchaInput = state.steps.some(s => s.type === "captcha_input");
    const captchaType = state.steps.find(s => s.captchaType)?.captchaType || "4digit";

    for (const s of state.steps) {
      const stepId = `s${stepIdx++}`;

      if (s.type === "username") {
        steps.push({
          id: stepId,
          type: "input",
          description: "输入账号",
          selector: s.bestSelector,
          value: "{{USERNAME}}",
          clear: true,
        });
      } else if (s.type === "password") {
        steps.push({
          id: stepId,
          type: "input",
          description: "输入密码",
          selector: s.bestSelector,
          value: "{{PASSWORD}}",
          clear: true,
        });
      } else if (s.type === "carrier") {
        steps.push({
          id: stepId,
          type: "select",
          description: "选择运营商",
          selector: s.bestSelector,
          value: "{{ISP}}",
        });
      } else if (s.type === "captcha_img") {
        steps.push({
          id: stepId,
          type: "screenshot",
          description: "截图验证码区域",
        });
      } else if (s.type === "captcha_input") {
        steps.push({
          id: stepId,
          type: "ocr",
          description: `识别验证码 (${CAPTCHA_TYPES.find(t => t.value === captchaType)?.label || captchaType})`,
          selector: s.bestSelector,  // 验证码图片选择器（从 img 步骤获取）
          target_selector: s.bestSelector,
          store_as: "captcha_code",
          old: captchaType === "math",
        });
        // 修正：ocr 的 selector 是图片，target_selector 是输入框
        const imgStep = [...state.steps].reverse().find(ss => ss.type === "captcha_img");
        if (imgStep) {
          steps[steps.length - 1].selector = imgStep.bestSelector;
          steps[steps.length - 1].target_selector = s.bestSelector;
        }
      } else if (s.type === "submit") {
        steps.push({
          id: stepId,
          type: "click",
          description: "点击提交",
          selector: s.bestSelector,
        });
      } else if (s.type === "click") {
        steps.push({
          id: stepId,
          type: "click",
          description: s.description,
          selector: s.bestSelector,
        });
      } else if (s.type === "wait") {
        steps.push({
          id: stepId,
          type: "wait",
          description: s.description,
          selector: s.bestSelector,
        });
      } else if (s.type === "eval") {
        steps.push({
          id: stepId,
          type: "eval",
          description: s.description,
          script: s.value || "",
        });
      } else if (s.type === "custom") {
        steps.push({
          id: stepId,
          type: "click",
          description: s.description,
          selector: s.bestSelector,
        });
      }
    }

    // 构建成功条件
    const successConditions = [];
    for (const sc of state.successConditions) {
      if (sc.type === "skip") continue;
      const cond = { type: sc.type };
      if (sc.pattern) cond.pattern = sc.pattern;
      if (sc.selector) cond.selector = sc.selector;
      if (sc.script) cond.script = sc.script;
      successConditions.push(cond);
    }

    const task = {
      name: "自动生成的登录任务",
      description: `从 ${url} 录制`,
      metadata: {},
      url: url,
      timeout: 30000,
      steps,
      success_conditions: successConditions,
    };

    const json = JSON.stringify(task, null, 2);
    GM_setClipboard(json);
    setStatus("✅ 任务 JSON 已复制到剪贴板！");
    showExportModal("任务 JSON", json, "json");
  }

  // ==================== 导出: Markdown 文档 ====================

  function exportMarkdown() {
    const url = window.location.href;
    const ts = new Date().toISOString().replace("T", " ").substring(0, 19);

    let md = `# Campus-Auth 任务配置文档\n\n`;
    md += `> 生成时间: ${ts}\n`;
    md += `> 页面地址: ${url}\n\n`;
    md += `## 页面信息\n\n`;
    md += `- **URL**: ${url}\n`;
    md += `- **标题**: ${document.title}\n\n`;

    md += `## 录制步骤\n\n`;

    state.steps.forEach((s, i) => {
      const typeLabel = STEP_TYPES[s.type]?.label || s.type;
      md += `### 步骤 ${i + 1}: ${typeLabel}\n\n`;
      md += `| 属性 | 值 |\n|------|----|\n`;
      md += `| 类型 | ${s.type} |\n`;
      md += `| 描述 | ${s.description} |\n`;
      md += `| 标签 | \`${s.tag}\` |\n`;
      md += `| 最佳选择器 | \`${s.bestSelector}\` |\n`;

      if (s.selectorCandidates?.length > 1) {
        md += `| 候选选择器 | ${s.selectorCandidates.map(c => `\`${c}\``).join(", ")} |\n`;
      }

      if (s.iframe?.inIframe) {
        md += `| iframe | ${s.iframe.crossOrigin ? "跨域" : s.iframe.frameSelector || "是"} |\n`;
      }

      if (s.value) {
        md += `| 值 | ${s.value} |\n`;
      }

      if (s.captchaType) {
        md += `| 验证码类型 | ${CAPTCHA_TYPES.find(t => t.value === s.captchaType)?.label || s.captchaType} |\n`;
      }

      if (s.attrs) {
        const attrStr = Object.entries(s.attrs).map(([k, v]) => `${k}="${v}"`).join(" ");
        if (attrStr) md += `| 属性 | ${attrStr} |\n`;
      }

      md += `\n`;
    });

    md += `## 登录成功条件\n\n`;
    if (state.successConditions.length > 0) {
      for (const sc of state.successConditions) {
        if (sc.type === "skip") {
          md += `- 跳过（步骤全部完成即为成功）\n`;
        } else if (sc.type === "url_matches") {
          md += `- URL 匹配: \`${sc.pattern}\`\n`;
        } else if (sc.type === "js_expression") {
          md += `- 页面包含文字: ${sc.label || ""}\n`;
        } else if (sc.type === "element_exists") {
          md += `- 页面存在元素: \`${sc.selector}\`\n`;
        }
      }
    } else {
      md += `- 未设置\n`;
    }
    md += `\n`;

    md += `## 元素详细信息\n\n`;
    md += `<details>\n<summary>展开查看原始元素数据</summary>\n\n`;
    md += "```json\n";
    md += JSON.stringify(
      state.steps.map(s => ({
        type: s.type,
        description: s.description,
        tag: s.tag,
        selectors: s.selectorCandidates,
        iframe: s.iframe,
        attrs: s.attrs,
        captchaType: s.captchaType,
      })),
      null,
      2
    );
    md += "\n```\n\n</details>\n\n";

    md += `## 任务编写提示词\n\n`;
    md += `将以下提示词和上方的步骤信息一起发送给 AI，即可生成完整的任务 JSON：\n\n`;
    md += "```\n";
    md += generatePrompt(url);
    md += "\n```\n";

    GM_setClipboard(md);
    setStatus("✅ 文档已复制到剪贴板！");
    showExportModal("任务文档 (Markdown)", md, "md");
  }

  function generatePrompt(url) {
    let prompt = `请根据以下校园网登录页面的元素信息，生成 Campus-Auth 的任务 JSON 配置。\n\n`;
    prompt += `任务编写规范请参考 Campus-Auth 项目中的 doc/task-writing-guide.md 文档。\n\n`;
    prompt += `页面地址: ${url}\n\n`;

    // 如果有验证码，补充说明
    const captchaSteps = state.steps.filter(s => s.type === "captcha_input" && s.captchaType);
    if (captchaSteps.length > 0) {
      prompt += `## 验证码说明\n\n`;
      for (const cs of captchaSteps) {
        const label = CAPTCHA_TYPES.find(t => t.value === cs.captchaType)?.label || cs.captchaType;
        prompt += `- 验证码类型: ${label}\n`;
        if (cs.captchaType === "math") {
          prompt += `- 需要使用 ocr 步骤的 old=true 参数来识别数学运算\n`;
        }
      }
      prompt += `\n`;
    }

    // 成功条件
    if (state.successConditions.length > 0) {
      prompt += `## 登录成功条件\n\n`;
      for (const sc of state.successConditions) {
        if (sc.type === "skip") {
          prompt += `- 跳过（步骤全部完成即为成功）\n`;
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
      prompt += `- 类型: ${s.type}\n`;
      prompt += `- 描述: ${s.description}\n`;
      prompt += `- 标签: <${s.tag}>\n`;
      prompt += `- 最佳选择器: \`${s.bestSelector}\`\n`;
      if (s.selectorCandidates?.length > 1) {
        prompt += `- 候选选择器: ${s.selectorCandidates.map(c => "`" + c + "`").join(", ")}\n`;
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

  // ==================== 导出弹窗 ====================

  function showExportModal(title, content, ext) {
    const overlay = document.createElement("div");
    overlay.className = "ca-modal-overlay";
    const preview = content.length > 3000 ? content.substring(0, 3000) + "\n\n... (已截断，完整内容已复制到剪贴板)" : content;
    overlay.innerHTML = `
      <div class="ca-modal" style="width:600px;max-height:80vh;overflow-y:auto;">
        <h4>${title}</h4>
        <textarea style="min-height:300px;font-family:monospace;font-size:12px;" readonly>${escapeHtml(preview)}</textarea>
        <div class="ca-modal-actions">
          <button class="ca-btn ca-btn-secondary ca-btn-sm" id="ca-export-copy">📋 复制</button>
          <button class="ca-btn ca-btn-primary ca-btn-sm" id="ca-export-close">关闭</button>
        </div>
      </div>
    `;
    state.panel.appendChild(overlay);

    overlay.querySelector("#ca-export-copy").addEventListener("click", () => {
      GM_setClipboard(content);
      setStatus("✅ 已复制到剪贴板");
    });
    overlay.querySelector("#ca-export-close").addEventListener("click", () => overlay.remove());
  }

  function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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

  function activate() {
    if (state.active) return;
    state.active = true;
    createPanel();
    document.addEventListener("mouseover", onHover, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeyDown, true);
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
        hideTooltip();
        state.panel.querySelectorAll(".ca-step-btn").forEach(b => b.classList.remove("active"));
        setStatus("已取消选择");
        e.preventDefault();
        e.stopPropagation();
      }
    }
    // Ctrl+Shift+R 切换面板
    if (e.ctrlKey && e.shiftKey && e.key === "R") {
      state.active ? deactivate() : activate();
      e.preventDefault();
    }
  }

  // ==================== 启动 ====================

  // 检查是否有保存的录制状态，自动恢复
  const savedData = loadState();
  if (savedData) {
    restoreFromSaved(savedData);
  }

  // 添加浮动入口按钮
  const entryBtn = document.createElement("div");
  entryBtn.innerHTML = "🎬";
  entryBtn.title = "Campus-Auth 任务录制器 (Ctrl+Shift+R)";
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
})();
