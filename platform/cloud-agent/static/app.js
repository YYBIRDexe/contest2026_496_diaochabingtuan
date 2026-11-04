(function () {
  "use strict";

  var Demo = window.VelaDemo;

  var PAGE_LABELS = {
    tasks: "任务中心",
    inbox: "待我处理",
    field: "现场",
    review: "实训复盘"
  };

  var TOOL_LABELS = {
    get_capabilities: "查询能力与登记",
    get_fleet_snapshot: "查询车辆登记",
    validate_mission: "校验计划条件",
    create_plan_proposal: "创建待确认计划"
  };

  var FRIENDLY_ERRORS = {
    llm_not_configured: "模型服务尚未配置，聊天暂不可用。登记信息仍可查看；请联系维护者完成配置后重试。",
    llm_auth_failed: "模型服务认证未通过，请联系维护者检查配置。",
    llm_unreachable: "模型服务暂时不可达，请检查网络或稍后重试。",
    llm_endpoint_not_found: "模型服务端点配置不正确，请联系维护者。",
    llm_rate_limited: "模型服务繁忙，请稍后重试。",
    llm_timeout: "模型服务响应超时，请稍后重试。",
    llm_upstream_error: "模型服务暂时出错，请稍后重试或联系维护者。",
    llm_http_error: "模型服务返回错误，请联系维护者。",
    llm_invalid_response: "模型服务返回了无法识别的结果，请联系维护者。",
    llm_response_too_large: "模型服务响应过大，请联系维护者。",
    rate_limited: "请求过于频繁，请稍后重试。",
    request_too_large: "请求内容过长，请缩短后重试。",
    message_too_long: "消息过长，请缩短到 2000 字以内再发送。",
    tool_loop_limit: "本轮工具调用次数达到上限，没有生成最终答复；请缩小问题范围后重试。",
    unauthorized: "需要访问口令。请在“连接设置”中填入维护者提供的口令。",
    proposal_already_decided: "这条计划已经被处理过，请刷新计划列表查看最新状态。",
    proposal_not_found: "没有找到这条计划，可能已被清理；请刷新计划列表。",
    unknown_route: "这条路线还没有登记，不能生成计划。请先确认路线名称或联系维护者登记。",
    unknown_check: "所选检查项不在该路线的登记范围内，需要维护者补充登记。",
    route_disabled: "这条路线当前未启用，不能生成计划。",
    unknown_robot: "这辆车还没有登记，不能分配计划。",
    robot_unavailable: "这辆车当前不可用，不能分配计划。",
    robot_capability_missing: "这辆车缺少巡检或导航能力，不能分配巡检计划。",
    invalid_scheduled_for: "计划时间格式不正确，请补上日期、时间和时区。",
    scheduled_in_past: "计划时间早于当前时间，请改到未来。",
    not_found: "请求的资源不存在。",
    internal_error: "服务暂时出错，请稍后重试或联系维护者。"
  };

  var TEMPLATE_DRAFTS = {
    lab: "巡查实训室 A 区：通道无占用、灭火器在位、设备状态人工复核，明早 9 点前完成。",
    dam: "安排大坝坝顶与下游观察点巡查，重点看防浪墙内侧积水、警示牌倾斜和岸坡冲刷痕迹；不确定时转人工复查。",
    river: "沿河岸步道巡查，记录岸坡冲刷、垃圾堆积和临水边界；分不清是否安全时标注需要人工判断，不要下水。",
    recheck: "复查上次未闭环的点位：回到同一位置、同一角度拍照，说明处理结果，提交后等待人工复查。"
  };

  var DEMO_NODES = [
    {
      id: "forebay",
      stage: "水库侧",
      name: "坝前水域",
      desc: "仅作逻辑起点，不显示水位、流速或天气。",
      area: null
    },
    {
      id: "gate",
      stage: "通行边界",
      name: "坝顶入口",
      desc: "进入坝顶前的通行检查点；示例不读取门禁与定位。",
      area: null
    },
    {
      id: "crest",
      stage: "坝顶",
      name: "坝顶巡查段",
      desc: "防浪墙、路面积水与警示设施；工单只描述人工观察目标。",
      area: "crest"
    },
    {
      id: "downstream",
      stage: "下游",
      name: "下游观察点",
      desc: "岸坡、步道与临水边界；不自动给出岸坡安全结论。",
      area: "downstream"
    }
  ];

  var state = {
    page: "tasks",
    mode: "real",
    token: "",
    health: null,
    healthError: "",
    healthLoading: true,
    healthCheckedAt: "",
    routes: null,
    routesError: "",
    routesLoading: true,
    routesLoadedAt: "",
    fleet: null,
    fleetError: "",
    fleetLoading: true,
    fleetLoadedAt: "",
    capabilities: null,
    capabilitiesError: "",
    capabilitiesLoading: true,
    capabilitiesLoadedAt: "",
    proposals: [],
    proposalsError: "",
    proposalsLoading: true,
    proposalsLoadedAt: "",
    deciding: "",
    refreshing: false,
    real: {
      messages: [],
      conversationId: null,
      sending: false,
      sessionVerified: false,
      lastError: "",
      draft: ""
    },
    demo: Demo.createState(),
    confirmAction: null,
    confirmOpener: null,
    settingsOpener: null,
    toastTimer: null
  };

  state.demo.sending = false;
  state.demo.draft = "";

  var els = {};

  function byId(id) {
    return document.getElementById(id);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function clear(node) {
    if (!node) {
      return;
    }
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function show(node, visible) {
    if (node) {
      node.hidden = !visible;
    }
  }

  function setText(id, value) {
    var node = byId(id);
    if (node) {
      node.textContent = value === undefined || value === null ? "" : String(value);
    }
  }

  function showInline(node, message) {
    if (!node) {
      return;
    }
    if (!message) {
      node.textContent = "";
      node.hidden = true;
      return;
    }
    node.textContent = message;
    node.hidden = false;
  }

  function setAttrs(node, attrs) {
    Object.keys(attrs).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    return node;
  }

  function appendAll(parent, children) {
    children.forEach(function (child) {
      if (child) {
        parent.appendChild(child);
      }
    });
    return parent;
  }

  function makeTag(text, className) {
    return el("span", "tag " + (className || "tag-neutral"), text);
  }

  function makeButton(text, className, attrs) {
    var button = el("button", className || "btn btn-quiet", text);
    button.type = "button";
    if (attrs) {
      setAttrs(button, attrs);
    }
    return button;
  }

  function blockHead(title, subtitle, extra) {
    var head = el("div", "block-head");
    var left = el("div");
    left.appendChild(el("h2", null, title));
    if (subtitle) {
      left.appendChild(el("p", null, subtitle));
    }
    head.appendChild(left);
    if (extra) {
      head.appendChild(extra);
    }
    return head;
  }

  function emptyMini(title, text) {
    var box = el("div", "empty-mini");
    box.appendChild(el("strong", null, title));
    if (text) {
      box.appendChild(el("span", null, text));
    }
    return box;
  }

  function statTile(value, label, note) {
    var tile = el("article", "stat");
    tile.appendChild(el("div", "stat-label", label));
    tile.appendChild(el("div", "stat-value", value));
    tile.appendChild(el("div", "stat-note", note));
    return tile;
  }

  function safeDate(value) {
    if (!value) {
      return null;
    }
    var date = new Date(value);
    if (isNaN(date.getTime())) {
      return null;
    }
    return date;
  }

  function formatClock(value) {
    var date = safeDate(value);
    if (!date) {
      return "时间未知";
    }
    try {
      return date.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" });
    } catch (err) {
      return date.toISOString().slice(11, 16);
    }
  }

  function formatDateTime(value) {
    var date = safeDate(value);
    if (!date) {
      return "时间未知";
    }
    try {
      return date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      });
    } catch (err) {
      return date.toISOString().slice(0, 16).replace("T", " ");
    }
  }

  function relativeAge(value) {
    var date = safeDate(value);
    if (!date) {
      return "时间未知";
    }
    var minutes = Math.round((Date.now() - date.getTime()) / 60000);
    if (minutes < 0) {
      minutes = 0;
    }
    if (minutes < 1) {
      return "刚刚";
    }
    if (minutes < 60) {
      return minutes + " 分钟前";
    }
    var hours = Math.round(minutes / 60);
    if (hours < 24) {
      return hours + " 小时前";
    }
    var days = Math.round(hours / 24);
    if (days < 8) {
      return days + " 天前";
    }
    return formatDateTime(value);
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function ApiError(status, payload, raw) {
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    this.raw = raw;
    this.message = describeError(this);
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function sanitizeMessage(text) {
    return String(text || "")
      .replace(/\s*[（(]HTTP\s*\d+[）)]/gi, "")
      .replace(/\s*[（(][a-z0-9_]+[）)]/gi, "")
      .replace(/HTTP\s*\d+/gi, "上游服务错误");
  }

  function friendlyReason(text) {
    return sanitizeMessage(text)
      .replace(/运动执行器/g, "车辆执行通道")
      .replace(/执行器/g, "车辆执行通道");
  }

  function describeError(error) {
    if (error && error.payload && error.payload.error) {
      var detail = error.payload.error;
      if (detail.code && FRIENDLY_ERRORS[detail.code]) {
        return FRIENDLY_ERRORS[detail.code];
      }
      if (detail.message) {
        return sanitizeMessage(detail.message);
      }
    }
    if (error && error.status) {
      return "请求没有完成，请稍后重试。";
    }
    if (error && error.name === "TypeError") {
      return "网络连接失败，请检查服务是否可达后重试。";
    }
    return error && error.message ? sanitizeMessage(error.message) : "网络请求失败，请稍后重试。";
  }

  function toast(message, isError) {
    if (!els.toast) {
      return;
    }
    els.toast.textContent = message;
    els.toast.className = isError ? "toast toast-error" : "toast";
    els.toast.hidden = false;
    if (state.toastTimer) {
      window.clearTimeout(state.toastTimer);
    }
    state.toastTimer = window.setTimeout(function () {
      els.toast.hidden = true;
    }, isError ? 7000 : 4200);
  }

  function authHeaders(hasBody) {
    var headers = { Accept: "application/json" };
    if (hasBody) {
      headers["Content-Type"] = "application/json";
    }
    if (state.token) {
      headers.Authorization = "Bearer " + state.token;
    }
    return headers;
  }

  function fetchJSON(path, options) {
    var opts = options || {};
    var init = {
      method: opts.method || "GET",
      headers: authHeaders(Boolean(opts.body)),
      credentials: "same-origin",
      cache: "no-store"
    };
    if (opts.body !== undefined) {
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(function (response) {
      return response.text().then(function (text) {
        var payload = null;
        if (text) {
          try {
            payload = JSON.parse(text);
          } catch (err) {
            payload = null;
          }
        }
        if (!response.ok) {
          throw new ApiError(response.status, payload, text);
        }
        if (payload === null) {
          throw new ApiError(response.status, null, "响应不是 JSON");
        }
        return payload;
      });
    });
  }

  // ------------------------------------------------------------- basic state
  function isRealChatReady() {
    return Boolean(state.health && state.health.ok && state.health.llm && state.health.llm.configured);
  }

  function routeCount() {
    if (!state.routes || !Array.isArray(state.routes.routes)) {
      return 0;
    }
    return state.routes.routes.length;
  }

  function robotCount() {
    if (!state.fleet || !state.fleet.snapshot || !Array.isArray(state.fleet.snapshot.robots)) {
      return 0;
    }
    return state.fleet.snapshot.robots.length;
  }

  function pendingProposals() {
    return (state.proposals || []).filter(function (proposal) {
      return proposal && proposal.approval && proposal.approval.state === "pending";
    });
  }

  function approvedProposals() {
    return (state.proposals || []).filter(function (proposal) {
      return proposal && proposal.approval && proposal.approval.state === "approved";
    });
  }

  function rejectedProposals() {
    return (state.proposals || []).filter(function (proposal) {
      return proposal && proposal.approval && proposal.approval.state === "rejected";
    });
  }

  function proposalStatus(proposal) {
    var approval = (proposal && proposal.approval) || {};
    if (approval.state === "approved") {
      return { label: "已确认 · 未执行", className: "tag-ok" };
    }
    if (approval.state === "rejected") {
      return { label: "已驳回", className: "tag-danger" };
    }
    return { label: "待确认", className: "tag-warn" };
  }

  function workorderStatus(status) {
    if (status === "in_progress") {
      return { label: "处理中", className: "tag-teal", index: 1 };
    }
    if (status === "pending_verify") {
      return { label: "待复查", className: "tag-warn", index: 2 };
    }
    if (status === "closed") {
      return { label: "已销项", className: "tag-ok", index: 3 };
    }
    return { label: "待处理", className: "tag-warn", index: 0 };
  }

  function findDemoWorkorder(id) {
    var list = state.demo.workorders || [];
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].id === id) {
        return list[i];
      }
    }
    return null;
  }

  function selectedDemoWorkorder() {
    var found = findDemoWorkorder(state.demo.selectedId);
    if (found) {
      return found;
    }
    return (state.demo.workorders || [])[0] || null;
  }

  function pushDemoHistory(order, actor, text, kind) {
    order.updatedAt = nowIso();
    order.history.push(Demo.makeEntry(actor, text, kind));
  }

  function pushDemoEvent(type, text, woId) {
    state.demo.events.push({ at: nowIso(), type: type, text: text, woId: woId || null });
  }

  // ---------------------------------------------------------------- chrome
  function renderChrome() {
    document.querySelectorAll("[data-set-mode]").forEach(function (button) {
      button.setAttribute("aria-pressed", button.getAttribute("data-set-mode") === state.mode ? "true" : "false");
    });
    show(els.demoBar, state.mode === "demo");
    if (els.taskModeTag) {
      els.taskModeTag.textContent = state.mode === "demo" ? "示例体验" : "真实连接";
      els.taskModeTag.className = "tag " + (state.mode === "demo" ? "tag-demo" : "tag-neutral");
    }
    if (els.reviewModeTag) {
      els.reviewModeTag.textContent = state.mode === "demo" ? "示例体验" : "真实连接";
      els.reviewModeTag.className = "tag " + (state.mode === "demo" ? "tag-demo" : "tag-neutral");
    }

    var dot = els.sidebarDot;
    var title = els.sidebarStatusTitle;
    var detail = els.sidebarStatusDetail;
    if (!dot || !title || !detail) {
      return;
    }
    dot.className = "status-dot status-dot-unknown";
    if (state.mode === "demo") {
      dot.className = "status-dot status-dot-warn";
      title.textContent = "示例模式 · 本地数据";
      detail.textContent = "不调用生产接口，不控制设备";
      return;
    }
    if (state.healthLoading) {
      title.textContent = "正在检查服务";
      detail.textContent = "助手与登记状态";
      return;
    }
    if (state.healthError || !state.health) {
      dot.className = "status-dot status-dot-down";
      title.textContent = "服务不可达";
      detail.textContent = "登记与助手暂不可用";
      return;
    }
    if (state.health.llm && state.health.llm.configured) {
      dot.className = "status-dot status-dot-ok";
      title.textContent = "巡查助手可用";
      detail.textContent = state.real.sessionVerified ? "本会话已回复" : "已配置 · 待首次回复";
      return;
    }
    dot.className = "status-dot status-dot-warn";
    title.textContent = "助手待配置";
    detail.textContent = "聊天暂不可用，登记仍可查看";
  }

  function renderChat() {
    var isDemo = state.mode === "demo";
    var messages = isDemo ? state.demo.messages : state.real.messages;
    var sending = isDemo ? state.demo.sending : state.real.sending;
    var ready = isDemo || isRealChatReady();
    var transcript = els.chatTranscript;

    setText("chat-heading", isDemo ? "示例助手（本地规则）" : "巡查助手");
    setText(
      "chat-subtitle",
      isDemo ? "不调用云，不写入生产；只演示本页流程" : "描述目标，助手先核对条件"
    );

    var chatState = els.chatState;
    if (chatState) {
      if (isDemo) {
        chatState.textContent = "本地示例 · 非云";
        chatState.className = "tag tag-demo";
      } else if (state.healthLoading) {
        chatState.textContent = "正在检查服务";
        chatState.className = "tag tag-neutral";
      } else if (state.healthError) {
        chatState.textContent = "服务不可达";
        chatState.className = "tag tag-danger";
      } else if (!isRealChatReady()) {
        chatState.textContent = "助手待配置";
        chatState.className = "tag tag-warn";
      } else if (sending) {
        chatState.textContent = "正在回复";
        chatState.className = "tag tag-neutral";
      } else if (state.real.sessionVerified) {
        chatState.textContent = "本会话已回复";
        chatState.className = "tag tag-ok";
      } else if (state.real.lastError) {
        chatState.textContent = "上次回复失败，可重试";
        chatState.className = "tag tag-danger";
      } else {
        chatState.textContent = "待首次回复";
        chatState.className = "tag tag-neutral";
      }
    }

    clear(transcript);
    if (!messages.length) {
      transcript.appendChild(buildChatEmpty(isDemo));
    } else {
      messages.forEach(function (message) {
        transcript.appendChild(buildMessage(message, isDemo));
      });
    }

    var blocked = "";
    if (!isDemo) {
      if (state.healthLoading) {
        blocked = "正在检查巡查助手与登记表，请稍候。";
      } else if (state.healthError) {
        blocked = "巡查助手暂不可达，当前不能发起对话。请检查连接后点顶部“刷新”。";
      } else if (!isRealChatReady()) {
        blocked = "巡查助手尚未配置，聊天暂不可用。登记信息仍可查看；请联系维护者完成配置。";
      }
    }
    showInline(els.chatBlocked, blocked);

    els.chatInput.disabled = !ready || sending;
    if (isDemo) {
      els.chatInput.placeholder = "例如：怎么走一遍大坝工单？或问问示例里有哪些逻辑站点。";
      setText(
        "composer-hint",
        state.demo.sending
          ? "示例助手正在整理本地回复，不调用云。"
          : "示例助手只使用本地规则，不调用云、不创建生产计划。Ctrl + Enter 发送。"
      );
    } else {
      els.chatInput.placeholder = "例如：明早九点前，巡查大坝坝顶和下游观察点，重点看积水和警示牌。";
      setText(
        "composer-hint",
        isRealChatReady()
          ? "仅生成待确认计划；车辆执行尚未连接。Ctrl + Enter 发送。"
          : "巡查助手暂不可用；登记信息仍可查看。"
      );
    }
    showInline(els.chatError, isDemo ? "" : state.real.lastError || "");
    updateSendState();
    if (messages.length) {
      els.chatTranscript.scrollTop = els.chatTranscript.scrollHeight;
    }
  }

  function updateSendState() {
    if (!els.sendButton || !els.chatInput) {
      return;
    }
    var isDemo = state.mode === "demo";
    var ready = isDemo || isRealChatReady();
    var sending = isDemo ? state.demo.sending : state.real.sending;
    els.sendButton.disabled = !ready || sending || !els.chatInput.value.trim();
    var length = els.chatInput.value.length;
    setText("char-count", length + " / 2000");
  }

  function captureDraft() {
    if (!els.chatInput) {
      return;
    }
    if (state.mode === "demo") {
      state.demo.draft = els.chatInput.value;
    } else {
      state.real.draft = els.chatInput.value;
    }
  }

  function buildChatEmpty(isDemo) {
    var box = el("div", "chat-empty");
    box.appendChild(el("span", "empty-kicker", isDemo ? "示例助手 · 本地规则" : "巡查助手 · 先核对条件"));
    box.appendChild(el("h3", null, isDemo ? "先走一遍流程，不碰真实设备" : "先说地点、检查目标和时间"));
    box.appendChild(
      el(
        "p",
        null,
        isDemo
          ? "可以问怎么写大坝工单草案，或直接去「待我处理」走一遍处理与复查。所有记录只在本页。"
          : "助手会先核对路线、车辆和时间；条件不足时先问清楚。"
      )
    );
    if (!isDemo) {
      box.appendChild(
        el("p", "empty-example", "例如：明早九点前，巡查大坝坝顶和下游观察点，重点看积水和警示牌。")
      );
    }
    return box;
  }

  function roleLabel(role, isDemo) {
    if (role === "user") {
      return "你";
    }
    if (role === "assistant") {
      return isDemo ? "示例助手" : "巡查助手";
    }
    return "系统";
  }

  function buildMessage(message, isDemo) {
    var role = message.role || "assistant";
    var wrapper = el("article", "message message-" + role + (message.pending ? " message-pending" : ""));
    var head = el("div", "message-head");
    head.appendChild(el("span", "message-role", roleLabel(role, isDemo)));
    var time = el("time", "message-time", formatClock(message.at || nowIso()));
    head.appendChild(time);
    if (isDemo && role === "assistant") {
      head.appendChild(makeTag("示例", "tag-demo"));
    }
    wrapper.appendChild(head);
    wrapper.appendChild(el("div", "message-body", message.text || ""));
    if (message.events && message.events.length) {
      wrapper.appendChild(buildTrace(message.events));
    }
    return wrapper;
  }

  function buildTrace(events) {
    var failed = events.filter(function (event) {
      return !event.ok;
    }).length;
    var details = el("details", "trace");
    details.appendChild(
      el("summary", null, "技术轨迹 · " + events.length + " 步" + (failed ? " · " + failed + " 步未完成" : ""))
    );
    var list = el("ul", "trace-list");
    events.forEach(function (event) {
      var item = el("li", "trace-item " + (event.ok ? "ok" : "fail"));
      var row = el("div", "trace-row");
      row.appendChild(el("span", "trace-name", TOOL_LABELS[event.name] || "工具调用"));
      row.appendChild(el("span", "trace-status", event.ok ? "完成" : "未完成"));
      if (event.duration_ms !== undefined && event.duration_ms !== null) {
        row.appendChild(el("span", "trace-time", event.duration_ms + " ms"));
      }
      item.appendChild(row);
      if (event.arguments !== undefined) {
        var args = el("pre", "trace-args");
        try {
          args.textContent = JSON.stringify(event.arguments, null, 2);
        } catch (err) {
          args.textContent = "参数无法展开";
        }
        item.appendChild(args);
      }
      if (event.clarification_required) {
        item.appendChild(el("p", "trace-note", "需要补充信息；没有创建计划。"));
      }
      if (event.error_code) {
        item.appendChild(el("p", "trace-note", "错误代码：" + event.error_code));
      }
      if (event.proposal_id) {
        var jump = makeButton("定位待确认计划", "trace-jump", { "data-scroll-proposal": event.proposal_id });
        item.appendChild(jump);
      }
      list.appendChild(item);
    });
    details.appendChild(list);
    return details;
  }

  // ------------------------------------------------------------- task panel
  function renderPrep() {
    if (!els.prepList) {
      return;
    }
    clear(els.prepList);
    var tag = els.prepTag;
    if (state.mode === "demo") {
      if (tag) {
        tag.textContent = "示例";
        tag.className = "tag tag-demo";
      }
      appendAll(els.prepList, [
        prepRow("示例场景", "大坝与河道", "逻辑站点，不是实时地图", ""),
        prepRow("示例工单", (state.demo.workorders || []).length + " 条", "本地示例数据，不写生产", ""),
        prepRow("本地规则", "可用", "不调用远端模型，不创建生产计划", "ok"),
        prepRow("车辆执行", "尚未连接", "示例不会下发任何设备动作", "warn")
      ]);
      setText("prep-foot", "示例模式不读取生产登记表；切换回真实连接后再刷新服务状态。");
      return;
    }

    var healthState = "";
    var healthValue = "检查中";
    var healthDetail = "正在读取服务状态";
    if (!state.healthLoading) {
      if (state.healthError || !state.health) {
        healthState = "down";
        healthValue = "不可达";
        healthDetail = "服务状态读取失败；登记与对话暂不可用";
      } else if (state.health.llm && state.health.llm.configured) {
        healthState = "ok";
        healthValue = "可发起";
        healthDetail = state.real.sessionVerified ? "本会话已回复" : "已配置，待首次回复";
      } else {
        healthState = "warn";
        healthValue = "模型待配置";
        healthDetail = "聊天暂不可用；登记信息仍可查看";
      }
    }

    var routesValue = state.routesLoading ? "检查中" : routeCount() + " 条";
    var routesDetail = state.routesError
      ? state.routesError
      : routeCount()
        ? "按检查点顺序展示，不是地图"
        : "需要维护者现场标定并登记";
    var routesState = state.routesError ? "down" : state.routesLoading ? "" : routeCount() ? "ok" : "warn";

    var fleetValue = state.fleetLoading ? "检查中" : robotCount() + " 台";
    var fleetDetail = state.fleetError
      ? state.fleetError
      : robotCount()
        ? "仅登记，不读取在线、位置或电量"
        : "尚无已登记车辆，不能分配巡检";
    var fleetState = state.fleetError ? "down" : state.fleetLoading ? "" : robotCount() ? "ok" : "warn";

    var tagText = state.healthLoading || state.routesLoading || state.fleetLoading ? "读取中" : "登记可用";
    var tagClass = "tag tag-neutral";
    if (!state.healthLoading && (state.healthError || state.routesError || state.fleetError)) {
      tagText = "部分不可用";
      tagClass = "tag tag-warn";
    } else if (!state.routesLoading && !state.fleetLoading && !routeCount() && !robotCount()) {
      tagText = "待登记";
      tagClass = "tag tag-warn";
    }
    if (tag) {
      tag.textContent = tagText;
      tag.className = tagClass;
    }

    appendAll(els.prepList, [
      prepRow("巡查助手", healthValue, healthDetail, healthState),
      prepRow("登记路线", routesValue, routesDetail, routesState),
      prepRow("登记车辆", fleetValue, fleetDetail, fleetState)
    ]);
    setText(
      "prep-foot",
      "登记信息读取于 " +
        (state.routesLoadedAt || state.fleetLoadedAt
          ? formatDateTime(state.routesLoadedAt || state.fleetLoadedAt)
          : "尚未读取") +
        "，来源为维护者登记表。"
    );
  }

  function prepRow(name, value, detail, stateClass) {
    var row = el("div", "prep-item " + (stateClass || ""));
    row.appendChild(el("span", "prep-dot"));
    var main = el("div");
    main.appendChild(el("div", "prep-name", name));
    main.appendChild(el("div", "prep-detail", detail));
    row.appendChild(main);
    var valueNode = el("span", "prep-value " + (stateClass === "warn" ? "is-warn" : stateClass === "down" ? "is-down" : ""), value);
    row.appendChild(valueNode);
    return row;
  }

  function renderPlans() {
    if (!els.plansList) {
      return;
    }
    clear(els.plansList);
    setText("plans-title", state.mode === "demo" ? "示例计划" : "待确认计划");
    setText(
      "plans-subtitle",
      state.mode === "demo" ? "本地示例 · 仅本页" : "来自服务端提案"
    );

    if (state.mode === "demo") {
      setText("plans-count", "1");
      els.plansList.appendChild(buildDemoPlanCard());
      setText(
        "plans-foot",
        "示例计划只保存在本页；确认不会下发设备。"
      );
      return;
    }

    if (state.proposalsLoading && !state.proposals.length) {
      setText("plans-count", "—");
      els.plansList.appendChild(emptyMini("正在读取计划记录…", "只读取已存在的提案，不会创建或修改计划。"));
      setText("plans-foot", "计划读取中。");
      return;
    }

    var pending = pendingProposals();
    setText("plans-count", String(pending.length));
    if (state.proposalsError && !state.proposals.length) {
      var errorBox = emptyMini("计划列表读取失败", state.proposalsError);
      var retry = makeButton("重试读取", "text-button", { "data-retry-plans": "1" });
      errorBox.appendChild(retry);
      els.plansList.appendChild(errorBox);
      setText("plans-foot", "计划读取失败，可重试。");
      return;
    }

    if (!pending.length) {
      var box = emptyMini(
        "还没有待确认计划",
        "在左侧描述目标，助手会先核对已登记路线与车辆；条件不足时会先澄清，不会用示例路线补位。"
      );
      if (approvedProposals().length) {
        var link = el("a", "text-button", "查看已确认计划（仍未执行）");
        link.href = "#review";
        link.setAttribute("data-nav", "review");
        box.appendChild(link);
      }
      els.plansList.appendChild(box);
    } else {
      pending.forEach(function (proposal) {
        els.plansList.appendChild(buildPlanCard(proposal));
      });
    }

    var foot = "计划来自服务端提案。";
    if (state.proposalsError) {
      foot += " 最近一次刷新失败：" + state.proposalsError;
    } else if (pending.length) {
      foot = "确认后记录审批结果。";
    }
    setText("plans-foot", foot);
  }

  function buildPlanCard(proposal) {
    var status = proposalStatus(proposal);
    var mission = proposal.mission || {};
    var route = mission.route || {};
    var card = el(
      "article",
      "plan-card " + (proposal.approval && proposal.approval.state === "approved" ? "is-approved" : proposal.approval && proposal.approval.state === "rejected" ? "is-rejected" : "")
    );
    setAttrs(card, { "data-proposal-id": proposal.proposal_id || "" });
    card.appendChild(el("div", "plan-title", route.name || "未命名路线"));
    card.appendChild(
      el(
        "div",
        "plan-meta",
        (route.zone || "未标区域") +
          " · 计划 v" +
          (proposal.plan_version || 1) +
          " · " +
          formatDateTime(proposal.created_at)
      )
    );
    card.appendChild(makeTag(status.label, status.className));

    var checks = el("div", "plan-checks");
    (mission.checks || []).slice(0, 3).forEach(function (check) {
      checks.appendChild(el("span", "plan-check", check.label || "检查项"));
    });
    if ((mission.checks || []).length > 3) {
      checks.appendChild(el("span", "plan-check", "+" + ((mission.checks || []).length - 3) + " 项"));
    }
    card.appendChild(checks);
    card.appendChild(el("p", "plan-copy", "审批绑定这个计划版本，不代表执行。"));

    if (proposal.approval && proposal.approval.state === "pending") {
      var note = el("input", "plan-note");
      note.type = "text";
      note.maxLength = 500;
      note.placeholder = "审批意见（可选）";
      note.setAttribute("aria-label", "面向这条计划的审批意见");
      if (state.deciding === proposal.proposal_id) {
        note.disabled = true;
      }
      card.appendChild(note);

      var actions = el("div", "plan-actions");
      var approve = makeButton("确认计划（不执行）", "btn btn-primary", {
        "data-decision": "approve",
        "data-proposal-id": proposal.proposal_id || ""
      });
      var reject = makeButton("驳回", "btn btn-danger", {
        "data-decision": "reject",
        "data-proposal-id": proposal.proposal_id || ""
      });
      if (state.deciding === proposal.proposal_id) {
        approve.disabled = true;
        reject.disabled = true;
        approve.textContent = "处理中…";
        reject.textContent = "处理中…";
      }
      appendAll(actions, [approve, reject]);
      card.appendChild(actions);
    } else if (proposal.approval && proposal.approval.decided_at) {
      card.appendChild(
        el("p", "plan-decision", "已记录决定：" + formatDateTime(proposal.approval.decided_at))
      );
    }
    return card;
  }

  function buildDemoPlanCard() {
    var plan = state.demo.plan;
    var card = el("article", "plan-card" + (plan.status === "confirmed" ? " is-approved" : plan.status === "rejected" ? " is-rejected" : ""));
    card.appendChild(el("div", "plan-title", plan.title));
    card.appendChild(
      el("div", "plan-meta", plan.route + " · 计划 v" + plan.version + " · " + formatDateTime(plan.createdAt))
    );
    var status = plan.status === "confirmed"
      ? { label: "示例 · 已确认未执行", className: "tag-ok" }
      : plan.status === "rejected"
        ? { label: "示例 · 已驳回", className: "tag-danger" }
        : { label: "示例 · 待确认", className: "tag-warn" };
    card.appendChild(makeTag(status.label, status.className));
    var checks = el("div", "plan-checks");
    (plan.checks || []).forEach(function (check) {
      checks.appendChild(el("span", "plan-check", check));
    });
    card.appendChild(checks);
    card.appendChild(el("p", "plan-copy", plan.note));

    if (plan.status === "pending") {
      var actions = el("div", "plan-actions");
      actions.appendChild(
        makeButton("确认示例计划（不执行）", "btn btn-primary", { "data-demo-plan-action": "approve" })
      );
      actions.appendChild(makeButton("驳回", "btn btn-danger", { "data-demo-plan-action": "reject" }));
      card.appendChild(actions);
    } else {
      card.appendChild(
        el(
          "p",
          "plan-decision",
          (plan.status === "confirmed" ? "已确认 · 仍未执行" : "已驳回") +
            (plan.decidedAt ? " · " + formatDateTime(plan.decidedAt) : "")
        )
      );
    }
    return card;
  }

  function decideProposal(proposalId, decision, note, card) {
    if (!proposalId || state.deciding) {
      return;
    }
    state.deciding = proposalId;
    if (card) {
      card.setAttribute("aria-busy", "true");
      card.querySelectorAll("button").forEach(function (button) {
        button.disabled = true;
      });
    }
    fetchJSON("/api/proposals/" + encodeURIComponent(proposalId) + "/decision", {
      method: "POST",
      body: { decision: decision, actor: "operator-ui", note: note || "" }
    })
      .then(function () {
        toast(
          decision === "approve"
            ? "计划已确认，但仍是未执行状态。"
            : "计划已驳回。",
          false
        );
      })
      .catch(function (error) {
        toast(describeError(error), true);
        if (error && error.status === 401) {
          openSettings();
        }
      })
      .then(function () {
        return loadProposals();
      })
      .then(function () {
        state.deciding = "";
        renderPlans();
      });
  }

  function setMode(mode) {
    if (mode !== "real" && mode !== "demo") {
      return;
    }
    if (mode === state.mode) {
      return;
    }
    captureDraft();
    state.mode = mode;
    document.querySelectorAll("[data-template]").forEach(function (card) {
      card.classList.remove("is-filled");
    });
    setText("template-feedback", "未发送");
    if (els.chatInput) {
      els.chatInput.value = mode === "demo" ? state.demo.draft : state.real.draft;
    }
    if (mode === "demo") {
      toast("已进入示例体验：仅本地示例数据，不控制设备，不写入生产系统。", false);
    } else {
      toast("已回到真实连接；真实会话与示例会话分别保留。", false);
      var needsRefresh =
        !state.health ||
        state.healthError ||
        !state.routes ||
        state.routesError ||
        !state.fleet ||
        state.fleetError ||
        state.proposalsError;
      if (needsRefresh) {
        refreshRealData(true);
      }
    }
    renderAll();
  }

  // ------------------------------------------------------------------ chat
  function sendChat() {
    if (!els.chatInput) {
      return;
    }
    var text = els.chatInput.value.trim();
    if (!text) {
      return;
    }
    if (state.mode === "demo") {
      sendDemoChat(text);
      return;
    }
    if (state.real.sending) {
      return;
    }
    if (!isRealChatReady()) {
      toast(
        state.healthError
          ? "巡查助手暂不可达，当前不能发起对话。请检查连接后刷新。"
          : "巡查助手尚未配置，聊天暂不可用。",
        true
      );
      return;
    }

    state.real.sending = true;
    state.real.lastError = "";
    var userMessage = { role: "user", text: text, at: nowIso() };
    var pendingMessage = {
      role: "assistant",
      text: "正在核对登记信息与执行边界…",
      pending: true,
      at: nowIso()
    };
    state.real.messages.push(userMessage, pendingMessage);
    els.chatInput.value = "";
    state.real.draft = "";
    setText("template-feedback", "已发送");
    updateSendState();
    renderChat();
    showInline(els.chatError, "");

    var body = { message: text };
    if (state.real.conversationId) {
      body.conversation_id = state.real.conversationId;
    }

    fetchJSON("/api/chat", { method: "POST", body: body })
      .then(function (payload) {
        var index = state.real.messages.indexOf(pendingMessage);
        var reply = payload.reply || "助手没有返回可读文本。可以换一种说法，或稍后重试。";
        var assistant = {
          role: "assistant",
          text: reply,
          events: payload.tool_events || [],
          at: nowIso()
        };
        if (index >= 0) {
          state.real.messages.splice(index, 1, assistant);
        } else {
          state.real.messages.push(assistant);
        }
        state.real.sessionVerified = true;
        state.real.lastError = "";
        if (payload.conversation_id) {
          state.real.conversationId = payload.conversation_id;
        }
        if ((payload.proposals || []).length) {
          loadProposals();
        }
      })
      .catch(function (error) {
        var index = state.real.messages.indexOf(pendingMessage);
        if (index >= 0) {
          state.real.messages.splice(index, 1);
        }
        var friendly = describeError(error);
        state.real.messages.push({ role: "system", text: "这次没有完成：" + friendly, at: nowIso() });
        state.real.sessionVerified = false;
        state.real.lastError = friendly;
        if (!els.chatInput.value) {
          els.chatInput.value = text;
          state.real.draft = text;
          setText("template-feedback", "未发送");
        }
        if (error && error.status === 401) {
          openSettings();
        }
      })
      .then(function () {
        state.real.sending = false;
        if (state.mode === "real") {
          renderChat();
          renderChrome();
          renderPrep();
          renderSettings();
        } else {
          updateSendState();
        }
      });
  }

  function sendDemoChat(text) {
    if (state.demo.sending) {
      return;
    }
    state.demo.sending = true;
    var pendingMessage = {
      role: "assistant",
      text: "示例助手正在整理本地规则…",
      pending: true,
      at: nowIso()
    };
    state.demo.messages.push({ role: "user", text: text, at: nowIso() }, pendingMessage);
    els.chatInput.value = "";
    state.demo.draft = "";
    setText("template-feedback", "已发送");
    updateSendState();
    renderChat();

    window.setTimeout(function () {
      var index = state.demo.messages.indexOf(pendingMessage);
      var assistant = {
        role: "assistant",
        text: Demo.replyFor(text),
        at: nowIso()
      };
      if (index >= 0) {
        state.demo.messages.splice(index, 1, assistant);
      }
      state.demo.sending = false;
      if (state.mode === "demo") {
        renderChat();
      } else {
        updateSendState();
      }
    }, 360);
  }

  // -------------------------------------------------------------- inbox demo
  function renderInbox() {
    if (!els.inboxReal || !els.inboxDemo) {
      return;
    }
    show(els.inboxReal, state.mode === "real");
    show(els.inboxDemo, state.mode === "demo");
    if (state.mode === "demo") {
      renderDemoInbox();
    }
  }

  function renderDemoInbox() {
    var list = els.demoWoList;
    var detail = els.demoWoDetail;
    if (!list || !detail) {
      return;
    }
    clear(list);
    clear(detail);
    var orders = (state.demo.workorders || []).slice();
    orders.sort(function (a, b) {
      var rank = { open: 0, in_progress: 1, pending_verify: 2, closed: 3 };
      var delta = (rank[a.status] || 0) - (rank[b.status] || 0);
      if (delta !== 0) {
        return delta;
      }
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    });
    setText("demo-wo-count", String(orders.length));

    orders.forEach(function (order) {
      var status = workorderStatus(order.status);
      var button = makeButton("", "wo-item", {
        "data-demo-action": "select",
        "data-id": order.id,
        "aria-current": order.id === state.demo.selectedId ? "true" : "false"
      });
      button.textContent = "";
      var top = el("div", "wo-item-top");
      top.appendChild(el("span", "wo-item-title", order.title));
      top.appendChild(makeTag(status.label, status.className));
      button.appendChild(top);
      button.appendChild(
        el(
          "span",
          "wo-item-meta",
          order.location + " · 更新 " + relativeAge(order.updatedAt) + (order.reopened ? " · 曾重开" : "")
        )
      );
      list.appendChild(button);
    });

    if (!orders.length) {
      list.appendChild(emptyMini("示例工单已清空", "点“重置示例数据”恢复初始示例数据。"));
      return;
    }

    var selected = selectedDemoWorkorder();
    if (!selected) {
      return;
    }
    detail.appendChild(buildDemoWorkorder(selected));
  }

  function buildDemoWorkorder(order) {
    var status = workorderStatus(order.status);
    var wrapper = el("div", "wo-detail");
    var head = el("div", "wo-detail-head");
    var headMain = el("div");
    headMain.appendChild(el("p", "eyebrow", "示例工单 · 仅本地示例数据"));
    headMain.appendChild(el("h2", null, order.title));
    headMain.appendChild(
      el(
        "p",
        "wo-location",
        order.location + " · 更新 " + relativeAge(order.updatedAt) + " · " + order.source
      )
    );
    head.appendChild(headMain);
    head.appendChild(makeTag(status.label, status.className));
    wrapper.appendChild(head);

    wrapper.appendChild(buildStepper(order.status));
    wrapper.appendChild(el("p", "wo-summary", order.summary));

    var columns = el("div", "wo-columns");
    var main = el("div");
    main.appendChild(el("h3", "wo-section-title", "现场要判断什么"));
    main.appendChild(el("p", "wo-task", order.task));

    var evidence = el("details", "evidence-block");
    evidence.appendChild(
      el("summary", null, "查看证据（" + (order.evidence || []).length + " 条 · 示例）")
    );
    var evidenceList = el("div", "evidence-list");
    (order.evidence || []).forEach(function (item) {
      var card = el("div", "evidence-item");
      card.appendChild(el("strong", null, item.label));
      card.appendChild(el("p", null, item.detail));
      var meta = el("div", "evidence-meta");
      meta.appendChild(el("span", null, relativeAge(item.at)));
      meta.appendChild(el("span", null, "来源：" + item.source));
      card.appendChild(meta);
      if (/照片|图/.test(item.label)) {
        card.appendChild(el("div", "evidence-placeholder", "证据占位：示例不含真实照片，不能用占位图冒充现场证据。"));
      }
      evidenceList.appendChild(card);
    });
    evidence.appendChild(evidenceList);
    main.appendChild(evidence);
    main.appendChild(buildDemoActionPanel(order));
    columns.appendChild(main);

    var historyBlock = el("div", "history-block");
    historyBlock.appendChild(el("h3", "wo-section-title", "处理轨迹"));
    var history = el("ol", "history-list");
    (order.history || []).slice().reverse().forEach(function (item) {
      var row = el(
        "li",
        "history-item " +
          (item.kind === "process" || item.kind === "submit"
            ? "is-process"
            : item.kind === "start"
              ? "is-start"
              : item.kind === "verify_pass"
                ? "is-pass"
                : item.kind === "verify_fail"
                  ? "is-fail"
                  : "")
      );
      row.appendChild(el("div", "history-time", formatDateTime(item.at)));
      row.appendChild(el("div", "history-text", item.text));
      row.appendChild(el("div", "history-actor", item.actor));
      history.appendChild(row);
    });
    historyBlock.appendChild(history);
    columns.appendChild(historyBlock);
    wrapper.appendChild(columns);
    return wrapper;
  }

  function buildStepper(status) {
    var current = workorderStatus(status).index;
    var steps = ["待处理", "处理中", "待复查", "已销项"];
    var stepper = el("div", "stepper");
    steps.forEach(function (label, index) {
      var step = el(
        "div",
        "step" + (index < current ? " is-done" : index === current ? " is-current" : "")
      );
      if (index === current) {
        step.setAttribute("aria-current", "step");
      }
      step.appendChild(el("span", "step-dot"));
      step.appendChild(el("span", null, label));
      stepper.appendChild(step);
    });
    return stepper;
  }

  function buildDemoActionPanel(order) {
    var panel = el("section", "action-panel");
    if (order.status === "open") {
      panel.appendChild(el("h3", null, "下一步：到现场处理"));
      panel.appendChild(
        el("p", null, "先核对证据，再开始。开始处理只改变本地示例状态，不控制设备，也不会写入生产系统。")
      );
      var start = makeButton("到现场，开始处理", "btn btn-primary", {
        "data-demo-action": "start",
        "data-id": order.id
      });
      var actions = el("div", "action-row");
      actions.appendChild(start);
      panel.appendChild(actions);
      return panel;
    }

    if (order.status === "in_progress") {
      panel.appendChild(el("h3", null, "提交处理说明"));
      panel.appendChild(
        el("p", null, "写清做了什么、还缺什么。提交后进入待复查，不等于销项。")
      );
      var processLabel = el("label", "field-label", "处理说明");
      processLabel.setAttribute("for", "demo-process-note");
      panel.appendChild(processLabel);
      var note = el("textarea", null, "");
      note.id = "demo-process-note";
      note.placeholder = "例如：已疏通排水口，警示牌已扶正；补拍积水位置与警示牌全景。";
      note.maxLength = 500;
      panel.appendChild(note);
      var submit = makeButton("提交处理结果", "btn btn-primary", {
        "data-demo-action": "submit",
        "data-id": order.id
      });
      var row = el("div", "action-row");
      row.appendChild(submit);
      panel.appendChild(row);
      return panel;
    }

    if (order.status === "pending_verify") {
      panel.appendChild(el("h3", null, "等待复查"));
      panel.appendChild(
        el("p", null, "处理已提交。请核对证据和说明：复查合格才销项，不合格会保留记录并重新打开。")
      );
      var verifyLabel = el("label", "field-label", "复查意见");
      verifyLabel.setAttribute("for", "demo-verify-note");
      panel.appendChild(verifyLabel);
      var verifyNote = el("textarea", null, "");
      verifyNote.id = "demo-verify-note";
      verifyNote.placeholder = "复查意见（不合格时建议写清缺什么，例如：照片角度不足、固定点未拍清）";
      verifyNote.maxLength = 500;
      panel.appendChild(verifyNote);
      var actions = el("div", "action-row");
      actions.appendChild(
        makeButton("复查合格，销项", "btn btn-primary", {
          "data-demo-action": "verify-pass",
          "data-id": order.id
        })
      );
      actions.appendChild(
        makeButton("复查不合格，重新打开", "btn btn-danger", {
          "data-demo-action": "verify-fail",
          "data-id": order.id
        })
      );
      panel.appendChild(actions);
      return panel;
    }

    panel.appendChild(el("h3", null, "复查合格 · 已销项"));
    var result = el("div", "result-banner");
    result.appendChild(el("strong", null, "本地示例闭环完成"));
    result.appendChild(
      el("p", null, "处理与复查记录保留在本页；这只是示例，不代表现场绩效或真实设备结果。")
    );
    panel.appendChild(result);
    return panel;
  }

  function handleDemoAction(action, id) {
    if (state.mode !== "demo") {
      return;
    }
    if (action === "reset") {
      openConfirm({
        title: "重置示例数据",
        message: "本地示例工单、计划与处理记录将恢复初始状态；不会影响生产系统，也不会控制设备。",
        confirmLabel: "重置示例",
        onConfirm: function () {
          Demo.reset(state.demo);
          state.demo.sending = false;
          state.demo.draft = "";
          document.querySelectorAll("[data-template]").forEach(function (card) {
            card.classList.remove("is-filled");
          });
          setText("template-feedback", "未发送");
          if (state.mode === "demo" && els.chatInput) {
            els.chatInput.value = "";
          }
          renderAll();
          updateSendState();
          toast("示例数据已重置；仍未连接生产接口。", false);
        }
      });
      return;
    }

    var order = findDemoWorkorder(id) || selectedDemoWorkorder();
    if (!order) {
      return;
    }

    if (action === "select") {
      state.demo.selectedId = order.id;
      renderDemoInbox();
      return;
    }

    if (action === "start") {
      if (order.status !== "open") {
        return;
      }
      order.status = "in_progress";
      pushDemoHistory(order, "示例操作者", "开始处理：已到达示例现场，准备记录处理说明。", "start");
      renderDemoInbox();
      renderReview();
      renderField();
      toast("示例：已开始处理，仍未写入生产系统。", false);
      var processNote = byId("demo-process-note");
      if (processNote) {
        processNote.focus();
      }
      return;
    }

    if (action === "submit") {
      if (order.status !== "in_progress") {
        return;
      }
      var processNote = byId("demo-process-note");
      var note = processNote ? processNote.value.trim() : "";
      if (note.length < 4) {
        toast("请先写至少 4 个字的处理说明，再提交。", true);
        if (processNote) {
          processNote.focus();
        }
        return;
      }
      order.status = "pending_verify";
      pushDemoHistory(order, "示例操作者", "提交处理：" + note, "submit");
      renderDemoInbox();
      renderReview();
      renderField();
      toast("示例：处理已提交，进入待复查。提交处理不等于合格。", false);
      return;
    }

    if (action === "verify-pass") {
      var verifyPassNote = byId("demo-verify-note");
      var reviewComment = verifyPassNote ? verifyPassNote.value.trim() : "";
      openConfirm({
        title: "记录复查合格并销项",
        message:
          "确认这条示例工单的证据与处理说明足以复查合格？销项只保存在本页，保留处理轨迹；不会写入生产系统。",
        confirmLabel: "记录复查合格",
        onConfirm: function () {
          var target = findDemoWorkorder(id);
          if (!target || target.status !== "pending_verify") {
            return;
          }
          target.status = "closed";
          pushDemoHistory(
            target,
            "示例复查人",
            "复查合格，销项。复查意见：" + (reviewComment || "未填写复查意见。"),
            "verify_pass"
          );
          renderDemoInbox();
          renderReview();
          renderField();
          toast("示例：复查合格，已销项（仅本地）。", false);
        }
      });
      return;
    }

    if (action === "verify-fail") {
      if (order.status !== "pending_verify") {
        return;
      }
      var verifyNote = byId("demo-verify-note");
      var reason = verifyNote ? verifyNote.value.trim() : "";
      if (!reason) {
        reason = "复查不合格，证据或处理说明不足，需要补充。";
      }
      order.status = "open";
      order.reopened = true;
      order.verifyAttempts = (order.verifyAttempts || 0) + 1;
      pushDemoHistory(order, "示例复查人", "复查不合格，重新打开：" + reason, "verify_fail");
      renderDemoInbox();
      renderReview();
      renderField();
      toast("示例：复查不合格，已重新打开（保留轨迹）。", false);
    }
  }

  // ------------------------------------------------------------------ field
  function renderField() {
    if (!els.fieldReal || !els.fieldDemo) {
      return;
    }
    show(els.fieldReal, state.mode === "real");
    show(els.fieldDemo, state.mode === "demo");
    if (state.mode === "demo") {
      renderDemoField();
    } else {
      renderRealField();
    }
  }

  function renderRealField() {
    var root = els.fieldReal;
    clear(root);
    var grid = el("div", "field-real-grid");
    var main = el("div", "field-main");
    var side = el("div", "field-side");

    var routeBlock = el("section", "block");
    routeBlock.setAttribute("aria-label", "已登记路线");
    routeBlock.appendChild(
      blockHead("已登记路线", "按检查点顺序显示，不是地图坐标", makeTag(state.routesLoading ? "读取中" : routeCount() + " 条", "tag-neutral"))
    );
    if (state.routesError) {
      routeBlock.appendChild(emptyMini("路线注册表读取失败", state.routesError));
    } else if (state.routesLoading && !state.routes) {
      routeBlock.appendChild(emptyMini("正在读取登记表…", "只读取维护者已核验的路线。"));
    } else if (!routeCount()) {
      routeBlock.appendChild(
        emptyMini("尚无已核验的标定路线", "需要维护者完成现场标定并登记。没有路线就不能生成计划，也不会用示例路线补位。")
      );
    } else {
      state.routes.routes.forEach(function (route) {
        routeBlock.appendChild(buildRealRoute(route));
      });
    }
    var routeFoot = el(
      "p",
      "block-foot",
      "登记表读取于 " +
        (state.routesLoadedAt ? formatDateTime(state.routesLoadedAt) : "尚未读取") +
        "；只包含检查点顺序，没有坐标、实时位置或定位数据。"
    );
    routeBlock.appendChild(routeFoot);
    main.appendChild(routeBlock);

    var fleetBlock = el("section", "block");
    fleetBlock.setAttribute("aria-label", "车辆登记");
    fleetBlock.appendChild(
      blockHead("车辆登记", "本地登记表，不是在线遥测", makeTag(state.fleetLoading ? "读取中" : robotCount() + " 台", "tag-neutral"))
    );
    if (state.fleetError) {
      fleetBlock.appendChild(emptyMini("车辆登记读取失败", state.fleetError));
    } else if (state.fleetLoading && !state.fleet) {
      fleetBlock.appendChild(emptyMini("正在读取车辆登记…", "只读取维护者已核验的车辆。"));
    } else if (!robotCount()) {
      fleetBlock.appendChild(
        emptyMini("尚无已登记的车辆", "需要维护者核对车辆型号、能力和使用状态后登记；历史候选名称不能当作在线车辆。")
      );
    } else {
      (state.fleet.snapshot.robots || []).forEach(function (robot) {
        var row = el("div", "fleet-entry");
        var mainInfo = el("div");
        mainInfo.appendChild(el("div", "fleet-name", robot.name || "未命名车辆"));
        mainInfo.appendChild(
          el(
            "div",
            "fleet-meta",
            (robot.enabled ? "已登记" : "已停用") + " · 遥测未连接 · 在线、位置、电量未读取"
          )
        );
        var caps = el("div", "cap-list");
        (robot.capabilities || []).forEach(function (cap) {
          caps.appendChild(el("span", "cap", cap));
        });
        mainInfo.appendChild(caps);
        row.appendChild(mainInfo);
        row.appendChild(makeTag(robot.enabled ? "已登记" : "未启用", robot.enabled ? "tag-neutral" : "tag-warn"));
        fleetBlock.appendChild(row);
      });
    }
    fleetBlock.appendChild(
      el(
        "p",
        "block-foot",
        "登记表读取于 " +
          (state.fleetLoadedAt ? formatDateTime(state.fleetLoadedAt) : "尚未读取") +
          "；登记不等于在线或可执行，本页不读取车辆位置、电量或健康状态。"
      )
    );
    side.appendChild(fleetBlock);

    var capabilityBlock = el("section", "block");
    capabilityBlock.setAttribute("aria-label", "能力边界");
    capabilityBlock.appendChild(
      blockHead("能力边界", "数据来源：登记表；不补造缺失数据", makeTag("只读", "tag-neutral"))
    );
    if (state.capabilitiesError) {
      capabilityBlock.appendChild(emptyMini("能力清单读取失败", state.capabilitiesError));
    }
    var capabilityExecution =
      state.capabilities && state.capabilities.capabilities && state.capabilities.capabilities.execution;
    var reason =
      (capabilityExecution && friendlyReason(capabilityExecution.reason)) ||
      (state.health && state.health.execution && friendlyReason(state.health.execution.reason)) ||
      "执行通道尚未接入；确认计划不会下发车辆。";
    var boundary = el("ul", "boundary-list");
    [
      ["车辆执行", reason],
      ["实时定位", "没有定位或遥测数据；现场只用逻辑站点，不画假地图。"],
      ["现场视频", "本页不拉取视频，也不提供远程画面。"],
      ["水位、雨量、渗压", "没有数据源，不显示编造数值。"],
      ["自动安全判定", "不自动判断坝体渗漏、岸坡安全或水质；需要人工和专业判断。"]
    ].forEach(function (item) {
      var li = el("li");
      li.appendChild(el("strong", null, item[0]));
      li.appendChild(el("span", null, item[1]));
      boundary.appendChild(li);
    });
    var capabilityDetails = el("details", "boundary-details");
    capabilityDetails.appendChild(el("summary", null, "查看车辆执行、定位、视频与数据源边界"));
    capabilityDetails.appendChild(boundary);
    capabilityBlock.appendChild(capabilityDetails);
    side.appendChild(capabilityBlock);

    appendAll(grid, [main, side]);
    root.appendChild(grid);
  }

  function buildRealRoute(route) {
    var entry = el("article", "route-entry");
    var head = el("div", "route-entry-head");
    var main = el("div");
    main.appendChild(el("h3", null, route.name || "未命名路线"));
    main.appendChild(el("p", "route-zone", (route.zone || "未标区域") + " · " + (route.enabled ? "已登记" : "未启用")));
    head.appendChild(main);
    head.appendChild(makeTag(route.enabled ? "已登记" : "未启用", route.enabled ? "tag-neutral" : "tag-warn"));
    entry.appendChild(head);

    if ((route.checks || []).length) {
      var checks = el("div", "route-check-row");
      route.checks.forEach(function (check) {
        checks.appendChild(el("span", "route-check", check.label || "检查项"));
      });
      entry.appendChild(checks);
    }
    if ((route.checkpoints || []).length) {
      var chain = el("ol", "checkpoint-chain");
      route.checkpoints.forEach(function (point, index) {
        var li = el("li", "checkpoint");
        li.appendChild(el("span", "checkpoint-index", String(index + 1).padStart(2, "0")));
        li.appendChild(el("span", null, point));
        chain.appendChild(li);
      });
      entry.appendChild(chain);
    }
    entry.appendChild(el("p", "fineprint", "检查点顺序仅用于业务说明，不代表地理坐标或实时位置。"));
    return entry;
  }

  function renderDemoField() {
    var track = els.demoTopology;
    var detail = els.demoNodeDetail;
    if (!track || !detail) {
      return;
    }
    clear(track);
    clear(detail);
    var selected = state.demo.fieldNodeId || "crest";
    var selectedNode = DEMO_NODES[0];
    DEMO_NODES.forEach(function (node) {
      if (node.id === selected) {
        selectedNode = node;
      }
      var orders = node.area
        ? (state.demo.workorders || []).filter(function (order) {
            return order.area === node.area;
          })
        : [];
      var status = nodeStatus(orders);
      var latest = orders.slice().sort(function (a, b) {
        return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
      })[0];
      var button = makeButton("", "node-card" + (node.id === selected ? " is-active" : ""), {
        "data-demo-node": node.id,
        "aria-pressed": node.id === selected ? "true" : "false"
      });
      button.appendChild(el("span", "node-stage", node.stage));
      button.appendChild(el("span", "node-name", node.name));
      button.appendChild(
        el(
          "span",
          "node-meta",
          status.label + (latest ? " · 更新 " + relativeAge(latest.updatedAt) : " · 仅逻辑位置")
        )
      );
      track.appendChild(button);
    });

    var relatedOrders = selectedNode.area
      ? (state.demo.workorders || []).filter(function (order) {
          return order.area === selectedNode.area;
        })
      : [];
    var nodeStatusInfo = nodeStatus(relatedOrders);
    var latestOrder = relatedOrders.slice().sort(function (a, b) {
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    })[0];

    var head = el("div", "node-detail-head");
    var headMain = el("div");
    headMain.appendChild(el("p", "eyebrow", "示例逻辑节点 · 位置仅示意"));
    headMain.appendChild(el("h2", null, selectedNode.name));
    headMain.appendChild(el("p", "node-detail-desc", selectedNode.desc));
    head.appendChild(headMain);
    head.appendChild(makeTag(nodeStatusInfo.label, nodeStatusInfo.className));
    detail.appendChild(head);

    var facts = el("div", "node-facts");
    appendAll(facts, [
      nodeFact("数据来源", "本地示例"),
      nodeFact("数据年龄", latestOrder ? "更新于 " + relativeAge(latestOrder.updatedAt) : "无示例记录"),
      nodeFact("关联工单", relatedOrders.length + " 条")
    ]);
    detail.appendChild(facts);

    var ordersBlock = el("div", "node-orders");
    ordersBlock.appendChild(el("h3", null, "关联的示例工单"));
    if (!relatedOrders.length) {
      ordersBlock.appendChild(
        el("p", "fineprint", "这个节点只有逻辑位置，没有示例工单；也不代表现场安全。")
      );
    } else {
      relatedOrders.forEach(function (order) {
        var row = el("div", "node-order");
        var info = el("div");
        info.appendChild(el("div", "node-order-title", order.title));
        info.appendChild(
          el("div", "node-order-meta", order.location + " · 更新 " + relativeAge(order.updatedAt))
        );
        row.appendChild(info);
        var status = workorderStatus(order.status);
        row.appendChild(makeTag(status.label, status.className));
        ordersBlock.appendChild(row);
      });
      var go = makeButton("在待我处理查看", "text-button", { "data-goto-inbox": relatedOrders[0].id });
      ordersBlock.appendChild(go);
    }
    detail.appendChild(ordersBlock);
  }

  function nodeStatus(orders) {
    if (orders.some(function (order) { return order.status === "pending_verify"; })) {
      return { label: "待复查", className: "tag-warn" };
    }
    if (orders.some(function (order) { return order.status === "open" || order.status === "in_progress"; })) {
      return { label: "待处理", className: "tag-warn" };
    }
    if (orders.some(function (order) { return order.status === "closed"; })) {
      return { label: "已销项", className: "tag-ok" };
    }
    return { label: "无待办记录", className: "tag-neutral" };
  }

  function nodeFact(label, value) {
    var fact = el("div", "node-fact");
    fact.appendChild(el("span", null, label));
    fact.appendChild(el("strong", null, value));
    return fact;
  }

  // ----------------------------------------------------------------- review
  function renderReview() {
    if (!els.reviewContent) {
      return;
    }
    clear(els.reviewContent);
    if (state.mode === "demo") {
      renderDemoReview();
    } else {
      renderRealReview();
    }
  }

  function renderRealReview() {
    var root = els.reviewContent;
    var pending = pendingProposals().length;
    var approved = approvedProposals().length;
    var rejected = rejectedProposals().length;
    var total = (state.proposals || []).length;
    var stats = el("div", "stat-grid");
    appendAll(stats, [
      statTile(state.proposalsLoading && !total ? "—" : String(total), "计划提案", "来自服务端的提案记录"),
      statTile(state.proposalsLoading && !total ? "—" : String(pending), "待确认", "等待人工决定"),
      statTile(state.proposalsLoading && !total ? "—" : String(approved), "已确认 · 未执行", "确认只记录审批"),
      statTile(state.proposalsLoading && !total ? "—" : String(rejected), "已驳回", "未进入执行")
    ]);
    root.appendChild(stats);

    var grid = el("div", "review-grid");
    var main = el("div", "review-main");
    var plansBlock = el("section", "block");
    plansBlock.setAttribute("aria-label", "计划记录");
    plansBlock.appendChild(
      blockHead("计划记录", "真实计划提案与审批状态；不是执行结果", makeTag(total + " 条", "tag-neutral"))
    );
    if (state.proposalsError && !total) {
      plansBlock.appendChild(emptyMini("计划记录读取失败", state.proposalsError));
    } else if (state.proposalsLoading && !total) {
      plansBlock.appendChild(emptyMini("正在读取计划记录…", "不会创建或修改提案。"));
    } else if (!total) {
      plansBlock.appendChild(
        emptyMini("还没有计划提案", "通过真实巡查助手核对已登记路线后，待确认计划会出现在任务中心，也会记入这里。")
      );
    } else {
      var list = el("div", "review-list");
      state.proposals.forEach(function (proposal) {
        var status = proposalStatus(proposal);
        var route = (proposal.mission && proposal.mission.route) || {};
        var row = el("div", "review-plan");
        var info = el("div");
        info.appendChild(el("div", "review-plan-title", route.name || "未命名路线"));
        info.appendChild(
          el(
            "div",
            "review-plan-meta",
            (route.zone || "未标区域") +
              " · 计划 v" +
              (proposal.plan_version || 1) +
              " · " +
              formatDateTime(proposal.created_at) +
              " · 执行状态：未执行"
          )
        );
        info.appendChild(
          el(
            "p",
            "review-plan-meta",
            "审批绑定计划版本 v" + (proposal.plan_version || 1) + "；确认不等于执行。"
          )
        );
        row.appendChild(info);
        row.appendChild(makeTag(status.label, status.className));
        list.appendChild(row);
      });
      plansBlock.appendChild(list);
    }
    plansBlock.appendChild(
      el(
        "p",
        "block-foot",
        state.proposalsError && total
          ? "最近一次刷新失败：" + state.proposalsError + "。"
          : "计划记录读取于 " +
            (state.proposalsLoadedAt ? formatDateTime(state.proposalsLoadedAt) : "尚未读取") +
            "。"
      )
    );
    main.appendChild(plansBlock);

    var side = el("div", "review-side");
    var executionBlock = el("section", "block");
    executionBlock.setAttribute("aria-label", "执行结果");
    executionBlock.appendChild(blockHead("执行结果", "来源：服务端计划记录 · 未执行", makeTag("尚无记录", "tag-warn")));
    var executionDetails = el("details", "boundary-details");
    executionDetails.appendChild(el("summary", null, "查看执行能力边界"));
    var executionBody = el("div", "execution-result");
    executionBody.appendChild(el("h3", null, "没有执行结果"));
    executionBody.appendChild(
      el(
        "p",
        null,
        (state.health && state.health.execution && friendlyReason(state.health.execution.reason)) ||
          "服务只返回计划与审批状态；首版没有车辆执行通道。"
      )
    );
    executionBody.appendChild(
      el("p", null, "因此这里不计算完成率，也不把提案当作执行。")
    );
    executionDetails.appendChild(executionBody);
    executionBlock.appendChild(executionDetails);
    side.appendChild(executionBlock);

    appendAll(grid, [main, side]);
    root.appendChild(grid);
  }

  function renderDemoReview() {
    var root = els.reviewContent;
    var orders = state.demo.workorders || [];
    var open = orders.filter(function (order) {
      return order.status === "open" || order.status === "in_progress";
    }).length;
    var pendingVerify = orders.filter(function (order) {
      return order.status === "pending_verify";
    }).length;
    var closed = orders.filter(function (order) {
      return order.status === "closed";
    }).length;
    var reopened = orders.filter(function (order) {
      return order.reopened;
    }).length;

    var stats = el("div", "stat-grid");
    appendAll(stats, [
      statTile(String(orders.length), "示例工单", "本地示例数据，不是生产工单"),
      statTile(String(open), "待处理 / 处理中", "仍需人工处理"),
      statTile(String(pendingVerify), "待复查", "提交处理不等于合格"),
      statTile(String(closed), "已销项", "重开 " + reopened + " 条 · 本页模拟")
    ]);
    root.appendChild(stats);

    var grid = el("div", "review-grid");
    var main = el("div", "review-main");
    var timelineBlock = el("section", "block");
    timelineBlock.setAttribute("aria-label", "示例流程记录");
    timelineBlock.appendChild(
      blockHead("流程记录", "按时间倒序；全部为本地模拟记录", makeTag("模拟", "tag-demo"))
    );

    var entries = [];
    var seen = {};
    orders.forEach(function (order) {
      (order.history || []).forEach(function (item) {
        var key = [order.id, item.at, item.kind, item.text].join("|");
        if (seen[key]) {
          return;
        }
        seen[key] = true;
        entries.push({
          at: item.at,
          kind: item.kind,
          text: item.text,
          actor: item.actor,
          title: order.title,
          source: "示例工单 · " + order.location
        });
      });
    });
    (state.demo.events || []).forEach(function (event) {
      if (event.type !== "plan" && event.type !== "load") {
        return;
      }
      var kind = event.type === "plan" ? "plan" : "note";
      var key = [event.woId || "demo", event.at, kind, event.text].join("|");
      if (seen[key]) {
        return;
      }
      seen[key] = true;
      entries.push({
        at: event.at,
        kind: kind,
        text: event.text,
        actor: "示例系统",
        title: null,
        source: "本地示例"
      });
    });
    entries.sort(function (a, b) {
      return new Date(b.at).getTime() - new Date(a.at).getTime();
    });

    if (!entries.length) {
      timelineBlock.appendChild(emptyMini("还没有流程记录", "创建或处理示例工单后，这里会出现本地记录。"));
    } else {
      var timeline = el("div", "timeline");
      entries.slice(0, 16).forEach(function (item) {
        var kindClass =
          item.kind === "process" || item.kind === "submit"
            ? "kind-process"
            : item.kind === "start"
              ? "kind-start"
              : item.kind === "verify_pass"
                ? "kind-pass"
                : item.kind === "verify_fail"
                  ? "kind-fail"
                  : item.kind === "plan"
                    ? "kind-plan"
                    : "";
        var row = el("div", "timeline-item " + kindClass);
        var top = el("div", "timeline-top");
        top.appendChild(el("time", "timeline-time", formatDateTime(item.at)));
        top.appendChild(el("span", "timeline-kind", kindLabel(item.kind)));
        if (item.title) {
          top.appendChild(el("span", "timeline-kind", item.title));
        }
        row.appendChild(top);
        row.appendChild(el("div", "timeline-text", item.text));
        row.appendChild(el("div", "timeline-source", item.actor + " · " + item.source));
        timeline.appendChild(row);
      });
      timelineBlock.appendChild(timeline);
      if (entries.length > 16) {
        timelineBlock.appendChild(el("p", "block-foot", "只显示最近 16 条；其余记录仍在本地示例状态中。"));
      } else {
        timelineBlock.appendChild(
          el("p", "block-foot", "记录只保留在本页内存；刷新页面会恢复初始示例。")
        );
      }
    }
    main.appendChild(timelineBlock);

    var side = el("div", "review-side");
    var countsBlock = el("section", "block");
    countsBlock.appendChild(blockHead("示例记录中的动作", "含初始示例记录；同一动作只计一次", makeTag("不计算完成率", "tag-neutral")));
    var processCount = 0;
    var verifyCount = 0;
    orders.forEach(function (order) {
      (order.history || []).forEach(function (item) {
        if (item.kind === "process" || item.kind === "submit") {
          processCount += 1;
        } else if (item.kind === "verify_pass" || item.kind === "verify_fail") {
          verifyCount += 1;
        }
      });
    });
    var detail = el("dl", "detail-list");
    appendDetail(detail, [
      ["提交处理", processCount + " 次"],
      ["复查动作", verifyCount + " 次"],
      ["重开工单", reopened + " 条"],
      ["已销项", closed + " 条"],
      ["计划审批", demoPlanStatusText()]
    ]);
    var countsBody = el("div", "review-note");
    countsBody.appendChild(detail);
    countsBody.appendChild(
      el("p", "fineprint", "这些数字来自本地示例流程，不代表现场绩效、覆盖率或安全结论。")
    );
    countsBlock.appendChild(countsBody);
    side.appendChild(countsBlock);

    var boundaryBlock = el("section", "block");
    boundaryBlock.appendChild(blockHead("示例边界", "来源：本地示例 · 不计算完成率", makeTag("示例", "tag-demo")));
    var boundaryDetails = el("details", "boundary-details");
    boundaryDetails.appendChild(el("summary", null, "查看为什么不能算真实复盘"));
    var boundaryBody = el("div", "review-note");
    boundaryBody.appendChild(
      el(
        "p",
        null,
        "示例没有真实车辆、车辆执行通道、定位、水位或工单接口；所有处理与复查都是本页模拟。切回真实连接后，只统计服务端返回的计划提案。"
      )
    );
    boundaryBody.appendChild(
      el(
        "p",
        "review-boundary",
        "不计算完成率，不把示例数字带入真实页面，也不写入生产系统。"
      )
    );
    boundaryDetails.appendChild(boundaryBody);
    boundaryBlock.appendChild(boundaryDetails);
    side.appendChild(boundaryBlock);

    appendAll(grid, [main, side]);
    root.appendChild(grid);
  }

  function kindLabel(kind) {
    if (kind === "start") {
      return "开始处理";
    }
    if (kind === "process" || kind === "submit") {
      return "提交处理";
    }
    if (kind === "verify_pass") {
      return "复查合格";
    }
    if (kind === "verify_fail") {
      return "复查不合格";
    }
    if (kind === "plan") {
      return "计划审批";
    }
    if (kind === "created") {
      return "创建工单";
    }
    return "记录";
  }

  function demoPlanStatusText() {
    if (state.demo.plan.status === "confirmed") {
      return "已确认 · 未执行";
    }
    if (state.demo.plan.status === "rejected") {
      return "已驳回";
    }
    return "待确认";
  }

  function appendDetail(list, rows) {
    rows.forEach(function (row) {
      list.appendChild(el("dt", null, row[0]));
      list.appendChild(el("dd", null, row[1]));
    });
  }

  // -------------------------------------------------------------------- api
  function refreshRealData(silent) {
    if (state.mode === "demo") {
      if (!silent) {
        toast("示例模式使用本地数据，不刷新生产服务；切回真实连接可刷新。", false);
      }
      return;
    }
    if (state.refreshing) {
      return;
    }
    state.refreshing = true;
    if (els.refreshButton) {
      els.refreshButton.disabled = true;
    }
    Promise.all([loadHealth(), loadRoutes(), loadFleet(), loadCapabilities(), loadProposals()]).then(function () {
      state.refreshing = false;
      if (els.refreshButton) {
        els.refreshButton.disabled = false;
      }
      if (!silent) {
        var failed = Boolean(state.healthError || state.routesError || state.fleetError || state.capabilitiesError || state.proposalsError);
        toast(failed ? "刷新完成，部分数据读取失败；请查看对应区域。" : "服务状态与登记表已刷新。", failed);
      }
    });
  }

  function loadHealth() {
    state.healthLoading = true;
    renderChrome();
    renderPrep();
    renderChat();
    return fetchJSON("/api/health")
      .then(function (payload) {
        state.health = payload;
        state.healthError = "";
        state.healthCheckedAt = nowIso();
      })
      .catch(function (error) {
        state.health = null;
        state.healthError = describeError(error);
      })
      .then(function () {
        state.healthLoading = false;
        renderChrome();
        renderPrep();
        renderChat();
        renderSettings();
      });
  }

  function loadRoutes() {
    state.routesLoading = true;
    renderPrep();
    renderField();
    return fetchJSON("/api/routes")
      .then(function (payload) {
        state.routes = payload;
        state.routesError = "";
        state.routesLoadedAt = nowIso();
      })
      .catch(function (error) {
        state.routes = null;
        state.routesError = describeError(error);
      })
      .then(function () {
        state.routesLoading = false;
        renderPrep();
        renderField();
        renderSettings();
      });
  }

  function loadFleet() {
    state.fleetLoading = true;
    renderPrep();
    renderField();
    return fetchJSON("/api/fleet")
      .then(function (payload) {
        state.fleet = payload;
        state.fleetError = "";
        state.fleetLoadedAt = nowIso();
      })
      .catch(function (error) {
        state.fleet = null;
        state.fleetError = describeError(error);
      })
      .then(function () {
        state.fleetLoading = false;
        renderPrep();
        renderField();
        renderSettings();
      });
  }

  function loadCapabilities() {
    state.capabilitiesLoading = true;
    renderPrep();
    renderField();
    return fetchJSON("/api/capabilities")
      .then(function (payload) {
        state.capabilities = payload;
        state.capabilitiesError = "";
        state.capabilitiesLoadedAt = nowIso();
      })
      .catch(function (error) {
        state.capabilities = null;
        state.capabilitiesError = describeError(error);
      })
      .then(function () {
        state.capabilitiesLoading = false;
        renderPrep();
        renderField();
        renderReview();
        renderSettings();
      });
  }

  function loadProposals() {
    state.proposalsLoading = true;
    renderPlans();
    renderReview();
    return fetchJSON("/api/proposals?limit=50")
      .then(function (payload) {
        state.proposals = payload.proposals || [];
        state.proposalsError = "";
        state.proposalsLoadedAt = nowIso();
      })
      .catch(function (error) {
        state.proposalsError = describeError(error);
      })
      .then(function () {
        state.proposalsLoading = false;
        renderPlans();
        renderReview();
        renderPrep();
        renderSettings();
      });
  }

  // -------------------------------------------------------------- navigation
  function pageFromHash() {
    var page = String(window.location.hash || "").replace(/^#/, "");
    return PAGE_LABELS[page] ? page : "tasks";
  }

  function showPage(page, focus) {
    if (!PAGE_LABELS[page]) {
      page = "tasks";
    }
    state.page = page;
    document.querySelectorAll("[data-page-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-page-panel") !== page;
    });
    document.querySelectorAll("[data-nav]").forEach(function (link) {
      if (link.classList.contains("nav-item") && link.getAttribute("data-nav") === page) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
    setText("crumb-current", PAGE_LABELS[page]);
    document.title = PAGE_LABELS[page] + " · VelaGuard";
    if (focus) {
      var heading = document.querySelector('[data-page-panel="' + page + '"] h1');
      if (heading) {
        heading.focus();
      }
    }
  }

  // ------------------------------------------------------------------ modal
  function openSettings() {
    if (!els.settingsModal) {
      return;
    }
    state.settingsOpener = document.activeElement;
    renderSettings();
    els.tokenInput.value = state.token;
    els.settingsModal.hidden = false;
    document.body.classList.add("modal-open");
    window.setTimeout(function () {
      if (els.settingsCard) {
        els.settingsCard.focus();
      }
    }, 0);
  }

  function closeSettings() {
    if (!els.settingsModal || els.settingsModal.hidden) {
      return;
    }
    els.settingsModal.hidden = true;
    if (els.confirmModal && !els.confirmModal.hidden) {
      return;
    }
    document.body.classList.remove("modal-open");
    if (state.settingsOpener && document.body.contains(state.settingsOpener)) {
      state.settingsOpener.focus();
    }
  }

  function openConfirm(options) {
    var opts = options || {};
    state.confirmAction = typeof opts.onConfirm === "function" ? opts.onConfirm : null;
    state.confirmOpener = document.activeElement;
    setText("confirm-title", opts.title || "确认操作");
    setText("confirm-message", opts.message || "");
    var action = els.confirmActionButton;
    if (action) {
      action.textContent = opts.confirmLabel || "确认";
      action.className = "btn " + (opts.danger ? "btn-danger" : "btn-primary");
      action.disabled = false;
    }
    els.confirmModal.hidden = false;
    document.body.classList.add("modal-open");
    window.setTimeout(function () {
      if (action) {
        action.focus();
      } else if (els.confirmCard) {
        els.confirmCard.focus();
      }
    }, 0);
  }

  function closeConfirm() {
    if (!els.confirmModal || els.confirmModal.hidden) {
      return;
    }
    els.confirmModal.hidden = true;
    state.confirmAction = null;
    if (els.settingsModal && !els.settingsModal.hidden) {
      return;
    }
    document.body.classList.remove("modal-open");
    if (state.confirmOpener && document.body.contains(state.confirmOpener)) {
      state.confirmOpener.focus();
    }
  }

  function renderSettings() {
    if (!els.settingsHealth) {
      return;
    }
    clear(els.settingsHealth);
    var llm = (state.health && state.health.llm) || {};
    var cloudValue = state.healthLoading
      ? "检查中"
      : state.healthError
        ? "不可达"
        : llm.configured
          ? "可发起"
          : "未配置";
    var sessionValue = state.mode === "demo"
      ? "示例模式（不调用云）"
      : state.real.sessionVerified
        ? "本会话已回复"
        : state.real.sending
          ? "等待回复"
          : "待首次回复";
    var tokenValue = state.token
      ? "已设置（仅本标签页）"
      : llm.access_token_required
        ? "服务要求口令，尚未设置"
        : "未设置";
    appendDetail(els.settingsHealth, [
      ["巡查助手", cloudValue],
      ["本会话", sessionValue],
      ["访问口令", tokenValue],
      ["车辆执行", "尚未连接"]
    ]);
    setText(
      "settings-checked",
      state.healthCheckedAt ? "最近检查：" + formatDateTime(state.healthCheckedAt) : "尚未检查。"
    );
    setText(
      "token-state",
      state.token
        ? "已设置访问口令，只保存在当前标签页。"
        : llm.access_token_required
          ? "服务要求访问口令；未设置时登记与计划可能读取失败。"
          : "尚未设置访问口令。"
    );

    clear(els.settingsTech);
    var dataSource = state.health && state.health.data && state.health.data.routes_source;
    if (dataSource === "local_registry") {
      dataSource = "本地登记表";
    }
    appendDetail(els.settingsTech, [
      ["服务版本", (state.health && state.health.version) || "未提供"],
      ["模型", llm.model || "未配置"],
      ["云端端点", llm.base_url || "未配置"],
      ["配置状态", llm.configured ? "已配置" : "未配置"],
      ["配置缺失", (llm.missing || []).length ? (llm.missing || []).join("、") : "无"],
      ["车辆执行", state.health && state.health.execution && state.health.execution.executor === "none_v1" ? "尚未连接（首版）" : (state.health && state.health.execution && state.health.execution.executor) || "尚未连接"],
      ["数据来源", dataSource || "本地登记表"]
    ]);
    if (state.healthError) {
      els.settingsTech.appendChild(el("dt", null, "最近错误"));
      els.settingsTech.appendChild(el("dd", null, state.healthError));
    }
  }

  function trapFocus(event) {
    if (event.key !== "Tab") {
      return;
    }
    var modal = null;
    if (els.confirmModal && !els.confirmModal.hidden) {
      modal = els.confirmCard;
    } else if (els.settingsModal && !els.settingsModal.hidden) {
      modal = els.settingsCard;
    }
    if (!modal) {
      return;
    }
    var focusable = modal.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable.length) {
      return;
    }
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (document.activeElement === modal) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // --------------------------------------------------------------- settings
  function saveToken() {
    var token = els.tokenInput.value.trim();
    state.token = token;
    try {
      if (token) {
        window.sessionStorage.setItem("cloudAgentToken", token);
      } else {
        window.sessionStorage.removeItem("cloudAgentToken");
      }
    } catch (err) {
      toast("当前浏览器不允许 sessionStorage；口令只在本页内存中有效。", true);
    }
    renderSettings();
    var inDemo = state.mode === "demo";
    toast(
      token
        ? inDemo
          ? "访问口令已保存到本标签页；切回真实连接后生效。"
          : "访问口令已保存到本标签页，正在刷新登记。"
        : "访问口令已清空。",
      false
    );
    if (!inDemo) {
      refreshRealData(true);
    }
  }

  function clearToken() {
    state.token = "";
    els.tokenInput.value = "";
    try {
      window.sessionStorage.removeItem("cloudAgentToken");
    } catch (err) {
      /* storage can be unavailable */
    }
    renderSettings();
    toast("访问口令已清空。", false);
    if (state.mode !== "demo") {
      refreshRealData(true);
    }
  }

  function loadToken() {
    try {
      state.token = window.sessionStorage.getItem("cloudAgentToken") || "";
    } catch (err) {
      state.token = "";
    }
    if (els.tokenInput) {
      els.tokenInput.value = state.token;
    }
  }

  // ----------------------------------------------------------------- events
  function bindEvents() {
    document.addEventListener("click", function (event) {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) {
        return;
      }
      var nav = event.target.closest("[data-nav]");
      if (nav) {
        var page = nav.getAttribute("data-nav");
        if (page && PAGE_LABELS[page]) {
          event.preventDefault();
          if (window.location.hash !== "#" + page) {
            window.location.hash = page;
          } else {
            showPage(page, true);
          }
        }
      }
    });

    document.querySelectorAll("[data-set-mode]").forEach(function (button) {
      button.addEventListener("click", function () {
        setMode(button.getAttribute("data-set-mode"));
      });
    });

    if (els.demoExit) {
      els.demoExit.addEventListener("click", function () {
        setMode("real");
      });
    }

    if (els.refreshButton) {
      els.refreshButton.addEventListener("click", function () {
        if (state.mode === "demo") {
          toast("示例模式使用本地数据，不刷新生产服务；切回真实连接可刷新。", false);
          return;
        }
        refreshRealData(false);
      });
    }

    if (els.settingsButton) {
      els.settingsButton.addEventListener("click", openSettings);
    }

    document.querySelectorAll("[data-close-settings]").forEach(function (node) {
      node.addEventListener("click", closeSettings);
    });

    document.querySelectorAll("[data-confirm-cancel]").forEach(function (node) {
      node.addEventListener("click", closeConfirm);
    });

    if (els.confirmActionButton) {
      els.confirmActionButton.addEventListener("click", function () {
        var action = state.confirmAction;
        closeConfirm();
        if (action) {
          action();
        }
      });
    }

    if (els.tokenSave) {
      els.tokenSave.addEventListener("click", saveToken);
    }
    if (els.tokenClear) {
      els.tokenClear.addEventListener("click", clearToken);
    }

    if (els.chatForm) {
      els.chatForm.addEventListener("submit", function (event) {
        event.preventDefault();
        sendChat();
      });
    }

    if (els.chatInput) {
      els.chatInput.addEventListener("input", function () {
        captureDraft();
        updateSendState();
      });
      els.chatInput.addEventListener("keydown", function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
          event.preventDefault();
          sendChat();
        }
      });
    }

    if (els.chatSuggestions) {
      els.chatSuggestions.addEventListener("click", function (event) {
        var button = event.target.closest("[data-suggestion]");
        if (!button || !els.chatInput) {
          return;
        }
        els.chatInput.value = button.getAttribute("data-suggestion");
        captureDraft();
        els.chatInput.focus();
        updateSendState();
      });
    }

    document.querySelectorAll("[data-template]").forEach(function (card) {
      card.addEventListener("click", function () {
        var key = card.getAttribute("data-template");
        var draft = TEMPLATE_DRAFTS[key] || "";
        if (!draft || !els.chatInput) {
          return;
        }
        els.chatInput.value = draft;
        captureDraft();
        els.chatInput.focus();
        updateSendState();
        document.querySelectorAll("[data-template]").forEach(function (other) {
          other.classList.toggle("is-filled", other === card);
        });
        setText("template-feedback", "已填入草案 · 尚未发送");
      });
    });

    if (els.plansList) {
      els.plansList.addEventListener("click", function (event) {
        var demoPlanButton = event.target.closest("[data-demo-plan-action]");
        if (demoPlanButton) {
          var action = demoPlanButton.getAttribute("data-demo-plan-action");
          if (state.demo.plan.status !== "pending") {
            return;
          }
          state.demo.plan.status = action === "approve" ? "confirmed" : "rejected";
          state.demo.plan.decidedAt = nowIso();
          pushDemoEvent(
            "plan",
            action === "approve" ? "确认示例计划，仍未执行。" : "驳回示例计划。"
          );
          renderPlans();
          renderReview();
          toast(
            action === "approve"
              ? "示例计划已确认，仍未执行；没有设备动作。"
              : "示例计划已驳回。",
            false
          );
          return;
        }

        var retry = event.target.closest("[data-retry-plans]");
        if (retry) {
          loadProposals();
          return;
        }

        var decision = event.target.closest("[data-decision]");
        if (decision) {
          var proposalId = decision.getAttribute("data-proposal-id");
          var card = decision.closest("[data-proposal-id]");
          var noteInput = card ? card.querySelector(".plan-note") : null;
          decideProposal(
            proposalId,
            decision.getAttribute("data-decision"),
            noteInput ? noteInput.value : "",
            card
          );
        }
      });
    }

    if (els.chatTranscript) {
      els.chatTranscript.addEventListener("click", function (event) {
        var jump = event.target.closest("[data-scroll-proposal]");
        if (!jump) {
          return;
        }
        var target = document.querySelector(
          '[data-proposal-id="' + jump.getAttribute("data-scroll-proposal") + '"]'
        );
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          var button = target.querySelector("button");
          if (button) {
            button.focus();
          }
        }
      });
    }

    if (els.inboxReal) {
      els.inboxReal.addEventListener("click", function (event) {
        if (event.target.closest("[data-enter-demo]")) {
          setMode("demo");
          return;
        }
        if (event.target.closest("#inbox-refresh")) {
          refreshRealData(false);
        }
      });
    }

    if (els.inboxDemo) {
      els.inboxDemo.addEventListener("click", function (event) {
        var actionButton = event.target.closest("[data-demo-action]");
        if (actionButton) {
          handleDemoAction(
            actionButton.getAttribute("data-demo-action"),
            actionButton.getAttribute("data-id")
          );
        }
      });
    }

    if (els.demoTopology) {
      els.demoTopology.addEventListener("click", function (event) {
        var node = event.target.closest("[data-demo-node]");
        if (!node) {
          return;
        }
        state.demo.fieldNodeId = node.getAttribute("data-demo-node");
        renderDemoField();
        var next = document.querySelector(
          '[data-demo-node="' + state.demo.fieldNodeId + '"]'
        );
        if (next) {
          next.focus();
        }
      });
    }

    if (els.demoNodeDetail) {
      els.demoNodeDetail.addEventListener("click", function (event) {
        var button = event.target.closest("[data-goto-inbox]");
        if (!button) {
          return;
        }
        state.demo.selectedId = button.getAttribute("data-goto-inbox");
        renderDemoInbox();
        if (window.location.hash !== "#inbox") {
          window.location.hash = "inbox";
        } else {
          showPage("inbox", true);
        }
      });
    }

    window.addEventListener("hashchange", function () {
      showPage(pageFromHash(), true);
    });

    window.addEventListener("offline", function () {
      show(els.offlineBar, true);
      toast("浏览器已离线；巡查助手与刷新会失败。", true);
    });

    window.addEventListener("online", function () {
      show(els.offlineBar, false);
      toast("网络已恢复，正在刷新服务状态。", false);
      if (state.mode === "real") {
        refreshRealData(true);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        if (els.confirmModal && !els.confirmModal.hidden) {
          event.preventDefault();
          closeConfirm();
          return;
        }
        if (els.settingsModal && !els.settingsModal.hidden) {
          event.preventDefault();
          closeSettings();
          return;
        }
      }
      trapFocus(event);
    });
  }

  function renderAll() {
    renderChrome();
    renderChat();
    renderPrep();
    renderPlans();
    renderInbox();
    renderField();
    renderReview();
    if (els.settingsModal && !els.settingsModal.hidden) {
      renderSettings();
    }
  }

  function initializeElements() {
    els.healthStatus = null;
    els.sidebarStatus = byId("sidebar-status");
    els.sidebarDot = byId("sidebar-dot");
    els.sidebarStatusTitle = byId("sidebar-status-title");
    els.sidebarStatusDetail = byId("sidebar-status-detail");
    els.crumb = byId("crumb-current");
    els.refreshButton = byId("refresh-button");
    els.settingsButton = byId("settings-button");
    els.demoBar = byId("demo-bar");
    els.demoExit = byId("demo-exit");
    els.offlineBar = byId("offline-bar");
    els.taskModeTag = byId("task-mode-tag");
    els.reviewModeTag = byId("review-mode-tag");
    els.chatTranscript = byId("chat-transcript");
    els.chatSuggestions = byId("chat-suggestions");
    els.chatForm = byId("chat-form");
    els.chatInput = byId("chat-input");
    els.sendButton = byId("send-button");
    els.chatError = byId("chat-error");
    els.chatBlocked = byId("chat-blocked");
    els.chatState = byId("chat-state");
    els.templateFeedback = byId("template-feedback");
    els.prepList = byId("prep-list");
    els.prepTag = byId("prep-tag");
    els.plansList = byId("plans-list");
    els.plansCount = byId("plans-count");
    els.inboxReal = byId("inbox-real");
    els.inboxDemo = byId("inbox-demo");
    els.demoWoList = byId("demo-wo-list");
    els.demoWoDetail = byId("demo-wo-detail");
    els.fieldReal = byId("field-real");
    els.fieldDemo = byId("field-demo");
    els.demoTopology = byId("demo-topology");
    els.demoNodeDetail = byId("demo-node-detail");
    els.reviewContent = byId("review-content");
    els.settingsModal = byId("settings-modal");
    els.settingsCard = byId("settings-card");
    els.settingsHealth = byId("settings-health");
    els.settingsTech = byId("settings-tech");
    els.tokenInput = byId("token-input");
    els.tokenSave = byId("token-save");
    els.tokenClear = byId("token-clear");
    els.confirmModal = byId("confirm-modal");
    els.confirmCard = byId("confirm-card");
    els.confirmActionButton = byId("confirm-action");
    els.toast = byId("toast");
  }

  document.addEventListener("DOMContentLoaded", function () {
    initializeElements();
    loadToken();
    bindEvents();
    showPage(pageFromHash(), false);
    show(els.offlineBar, !navigator.onLine);
    renderAll();
    refreshRealData(true);
  });
})();
