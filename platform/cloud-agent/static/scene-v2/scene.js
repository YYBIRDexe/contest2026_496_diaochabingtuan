/* VelaGuard scene-v2 — scene routing, hot spots, draft composer, real /api/chat. */
(function () {
  "use strict";

  var CFG = window.VelaSceneConfig || {};
  var app = document.getElementById("v2-app");
  var reducedMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false, addEventListener: null };

  var ACTION_ORDER = ["new", "todo", "recheck"];

  var ACTION_COPY = {
    new: {
      name: "新建巡查",
      desc: "写清重点，交给助手核对条件",
      icon: "plus"
    },
    todo: {
      name: "查看待办",
      desc: "读取真实工单；当前未接入工单接口",
      icon: "list"
    },
    recheck: {
      name: "指定点复查",
      desc: "对未闭环点位按同角度补证",
      icon: "target"
    }
  };

  var SPOTS = {
    dam: {
      id: "dam",
      name: "大坝巡查",
      short: "大坝",
      blurb: "坝顶、坝前水域与下游观察点。先看范围与待办，再决定是否安排。",
      points: ["坝顶防浪墙", "坝前水域", "下游观察点"],
      newLede: "先把大坝的重点写成草案。带入底部输入框后仍可修改，发送前不会创建计划。",
      newNote: "例如：优先看防浪墙内侧积水；16:00 前完成。",
      recheckLede: "选择上次未闭环的点位，按同一位置、同一角度补证。复查提交后仍需人工判断。",
      draftTail: "请先核对已登记路线、车辆和时间；缺少条件时请说明缺口，不要创建无法执行的计划。"
    },
    building: {
      id: "building",
      name: "科研楼巡查",
      short: "科研楼",
      blurb: "设备间、屋顶排水与实验区通道。这里只生成草案，不读取门禁或设备状态。",
      points: ["设备间门禁", "屋顶排水", "实验区通道"],
      newLede: "把科研楼的巡查重点写成草案；门禁、设备状态与权限都需要人工或专用系统确认。",
      newNote: "例如：先看屋顶排水口，再核对设备间门禁记录。",
      recheckLede: "选择要复查的设备间或屋顶点位，补上上次未闭环的证据。",
      draftTail: "请先核对已登记路线、车辆与授权范围；没有权限或登记时说明缺口，不要创建无法执行的计划。"
    }
  };

  var SPOT_ORDER = ["dam", "building"];
  var HOME_FEATURE_BY_SPOT = { dam: "5", building: "3" };
  var FEATURES = {
    "2": {
      id: "2",
      name: "执行异常",
      description: "车辆反馈及执行异常",
      status: "车辆遥测接口未接入",
      note: "当前不显示电量、位姿或互联网连接数据；待真实设备接口接入后再展示。"
    },
    "3": {
      id: "3",
      name: "异常事件",
      description: "巡检发现的异常事件",
      status: "异常事件数据接口未接入",
      note: "当前没有可展示的真实事件记录，不生成模拟告警或虚构事件。"
    },
    "5": {
      id: "5",
      name: "巡迹地图",
      description: "固定预设地图及一轮巡检的车辆轨迹",
      status: "地图与轨迹数据尚未接入",
      note: "当前不展示模拟地图、路线或车辆轨迹；接入真实数据后再呈现。"
    },
    "4": {
      id: "4",
      name: "云端自检",
      description: "知识库与云端 Agent 自诊",
      status: "诊断记录与知识库状态尚未接入",
      note: "页面仅展示设计中的功能框架，不代表云端自诊正在运行。"
    },
    "6": {
      id: "6",
      name: "巡检复盘",
      description: "结构化任务与巡检结果回顾",
      status: "任务与复盘记录尚未接入",
      note: "不展示伪造的任务编号、状态、数量或历史轨迹。"
    },
    "7": {
      id: "7",
      name: "Gemini-S1",
      description: "端侧智能节点专属页面",
      status: "设备状态接口未接入",
      note: "所有设备状态均为未验证，不推断 Gemini-S1 已在线。"
    }
  };

  var SVG_NS = "http://www.w3.org/2000/svg";

  var ART_CODE = {
    dam: "01 / DAM",
    building: "03 / LAB"
  };

  /* Panel art reuses the delivered scene image below. */

  var state = {
    route: { view: "scene", spot: null, action: null },
    lastSpot: null,
    pendingTimer: null,
    burstTimer: null,
    focusSpotOnScene: false,
    token: "",
    conversationId: null,
    busy: false,
    lastMessage: "",
    lastPrimed: "",
    toastTimer: null,
    helpOpen: false,
    helpReturnFocus: null,
    voiceReturnFocus: null,
    voiceSeq: null,
    voicePoll: 0,
    voicePending: "",
    perf: null,
    perfRaf: 0,
    typingEl: null
  };

  var els = {};

  /* --------------------------------------------------------------- utils */

  function $(id) {
    return document.getElementById(id);
  }

  function h(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  var ICON_PATHS = {
    plus: ["M12 5v14", "M5 12h14"],
    list: ["M8 6h12", "M8 12h12", "M8 18h12", "M4 6h.01", "M4 12h.01", "M4 18h.01"],
    target: ["M12 3v3", "M12 18v3", "M3 12h3", "M18 12h3", "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z", "M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"],
    chevron: ["m9 6 6 6-6 6"],
    arrowLeft: ["M19 12H5", "m11 18-6-6 6-6"],
    arrowRight: ["M5 12h14", "m13 6 6 6-6 6"],
    close: ["m6 6 12 12", "M18 6 6 18"],
    refresh: ["M20 11a8 8 0 1 0-2.4 5.7", "M20 5v6h-6"],
    check: ["m5 12 4 4L19 6"],
    alert: ["M12 3 2.5 20h19z", "M12 9v5", "M12 17.5h.01"],
    keyboard: ["M4 7h16v10H4z", "M7 11h.01", "M10 11h.01", "M13 11h.01", "M16 11h.01", "M8 14h8"],
    compass: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "m15.5 8.5-2 5-5 2 2-5z"],
    info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5", "M12 8h.01"]
  };

  function icon(name, className) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.7");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    if (className) {
      svg.setAttribute("class", className);
    }
    var paths = ICON_PATHS[name] || ICON_PATHS.info;
    for (var i = 0; i < paths.length; i += 1) {
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", paths[i]);
      svg.appendChild(path);
    }
    return svg;
  }

  function storageGet(key) {
    try {
      return window.sessionStorage.getItem(key);
    } catch (err) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      if (value === null || value === undefined) {
        window.sessionStorage.removeItem(key);
      } else {
        window.sessionStorage.setItem(key, value);
      }
      return true;
    } catch (err) {
      return false;
    }
  }

  function isStatic() {
    return app.getAttribute("data-static") === "on";
  }

  function toast(message, isError) {
    if (!els.toast) {
      return;
    }
    els.toast.textContent = message;
    els.toast.className = isError ? "toast is-error" : "toast";
    els.toast.hidden = false;
    if (state.toastTimer) {
      window.clearTimeout(state.toastTimer);
    }
    state.toastTimer = window.setTimeout(function () {
      els.toast.hidden = true;
    }, isError ? 7000 : 3800);
  }

  function announce(text) {
    if (els.live) {
      els.live.textContent = "";
      window.setTimeout(function () {
        els.live.textContent = text;
      }, 40);
    }
  }

  /* --------------------------------------------------------------- route */

  function parseRoute() {
    var raw = (window.location.hash || "").replace(/^#\/?/, "");
    var parts = raw.split("/").filter(Boolean);
    if (parts[0] === "feature") {
      var featureId = parts[1];
      if (!featureId || !FEATURES[featureId]) {
        return { view: "scene", spot: null, action: null, invalid: Boolean(featureId) };
      }
      return { view: "feature", feature: featureId, spot: null, action: null };
    }
    if (!parts.length || parts[0] !== "scene") {
      return { view: "scene", spot: null, action: null };
    }
    var spotId = parts[1];
    if (!spotId || !SPOTS[spotId]) {
      return { view: "scene", spot: null, action: null, invalid: Boolean(spotId) };
    }
    var actionId = parts[2];
    if (actionId) {
      if (ACTION_ORDER.indexOf(actionId) === -1) {
        return { view: "menu", spot: spotId, action: null, invalid: true };
      }
      return { view: "detail", spot: spotId, action: actionId };
    }
    return { view: "menu", spot: spotId, action: null };
  }

  function routeHash(route) {
    if (route && route.view === "feature" && route.feature) {
      return "#/feature/" + route.feature;
    }
    if (!route || route.view === "scene" || !route.spot) {
      return "#/scene";
    }
    if (route.view === "detail" && route.action) {
      return "#/scene/" + route.spot + "/" + route.action;
    }
    return "#/scene/" + route.spot;
  }

  function navigate(hash) {
    if (window.location.hash === hash) {
      renderRoute({ focusPanel: true });
      return;
    }
    window.location.hash = hash;
  }

  function goUp() {
    if (state.route.spot || state.route.view === "feature") {
      if (state.route.spot) state.focusSpotOnScene = true;
      navigate("#/scene");
    }
  }

  function renderRoute(options) {
    var opts = options || {};
    if (state.pendingTimer) {
      window.clearTimeout(state.pendingTimer);
      state.pendingTimer = null;
    }
    if (els.chatInput) workspaceDrafts[draftKey(state.route)] = els.chatInput.value;
    var route = parseRoute();
    if (route.invalid) {
      window.history.replaceState(null, "", "#/scene");
      route = { view: "scene", spot: null, action: null };
    }
    state.route = route;
    els.chatInput.value = workspaceDrafts[draftKey(route)] || "";
    updateCount();
    var main=$("main");
    if (route.spot || route.view === "feature") { main.setAttribute("inert", "");main.setAttribute("aria-hidden","true"); }
    else { main.removeAttribute("inert");main.removeAttribute("aria-hidden"); }

    var panelOpen = route.view !== "scene";
    app.setAttribute("data-level", route.view);
    app.setAttribute("data-panel", panelOpen ? "open" : "closed");
    els.panel.setAttribute("aria-hidden", panelOpen ? "false" : "true");
    setActiveSpot(route.spot);
    setActiveFeature(route.feature);
    if (route.spot) {
      /* Hotspot coordinates live in the config, not in the SPOTS copy table.
         Reading them off SPOTS produced "--focus-x: undefined%". */
      var coord = (CFG && CFG.spots && CFG.spots[route.spot]) || {};
      if (typeof coord.x === "number" && typeof coord.y === "number") {
        app.style.setProperty("--focus-x", coord.x + "%");
        app.style.setProperty("--focus-y", coord.y + "%");
      } else {
        app.style.removeProperty("--focus-x");
        app.style.removeProperty("--focus-y");
      }
    }

    if (!panelOpen) {
      parkComposer();
      /* Keep the composer available inside the existing task workspace,
         but do not show the white text-entry dock on the homepage. */
      els.dock.hidden = true;
      document.querySelector('label.sr-only[for="chat-input"]').textContent="输入巡查目标";
      els.chatInput.placeholder="例如：明早九点前，先看大坝坝顶和下游观察点。";
      els.sendButton.querySelector("span").textContent="发送";
      els.panelContent.textContent = "";
      document.title = "VelaGuard · 智慧巡检";
      if (state.focusSpotOnScene && state.lastSpot) {
        state.focusSpotOnScene = false;
        window.setTimeout(function () {
          focusSpotControl(state.lastSpot);
        }, 30);
      }
      return;
    }

    if (route.view === "feature") {
      buildFeaturePage(route.feature);
      document.title = FEATURES[route.feature].name + " · VelaGuard";
      if (opts.focusPanel !== false) {
        window.requestAnimationFrame(function () {
          var featureFocus = els.panelContent.querySelector("[data-panel-focus]");
          if (featureFocus) featureFocus.focus({ preventScroll: true });
        });
      }
      return;
    }

    buildPanel(route);
    var spot = SPOTS[route.spot];
    document.title = (route.view === "menu" ? spot.name : ACTION_COPY[route.action].name + " · " + spot.short) + " · VelaGuard";

    if (opts.focusPanel !== false) {
      window.requestAnimationFrame(function () {
        var focusTarget = els.panelContent.querySelector("[data-panel-focus]");
        if (focusTarget) {
          focusTarget.focus({ preventScroll: true });
        }
      });
    }
  }

  function setActiveSpot(spotId) {
    var controls = document.querySelectorAll("[data-spot]");
    for (var i = 0; i < controls.length; i += 1) {
      var control = controls[i];
      var active = control.getAttribute("data-spot") === spotId;
      control.classList.toggle("is-active", active);
      control.setAttribute("aria-expanded", active ? "true" : "false");
    }
    if (spotId) {
      state.lastSpot = spotId;
    }
  }

  function setActiveFeature(featureId) {
    var controls = document.querySelectorAll("[data-feature]");
    for (var i = 0; i < controls.length; i += 1) {
      var control = controls[i];
      var active = control.getAttribute("data-feature") === String(featureId || "");
      control.classList.toggle("is-active", active);
      control.setAttribute("aria-expanded", active ? "true" : "false");
    }
  }

  function focusSpotControl(spotId) {
    var controls = document.querySelectorAll('[data-spot="' + spotId + '"]');
    for (var i = 0; i < controls.length; i += 1) {
      if (controls[i].getClientRects().length) {
        controls[i].focus({ preventScroll: true });
        return;
      }
    }
  }

  /* --------------------------------------------------------------- panel */

  function svgNode(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (name) {
      node.setAttribute(name, attrs[name]);
    });
    return node;
  }

  /* Object workspaces keep one composer and preserve each unsent draft. */
  var workspaceDrafts = {};
  var workspacePoints = {};
  var workspaceFields = {};
  function draftKey(route) {
    return route && route.spot ? route.spot + ":" + (route.action || "new") : "home";
  }
  function parkComposer() {
    if (els.dockHome && els.dock) {
      els.dockHome.parentNode.insertBefore(els.dock, els.dockHome.nextSibling);
      els.dock.hidden = false;
    }
  }
  function selectedPoints() {
    var key = draftKey(state.route);
    return workspacePoints[key] || (workspacePoints[key] = []);
  }
  function syncPoints() {
    var selected = selectedPoints();
    els.panelContent.querySelectorAll("[data-point]").forEach(function(button) {
      button.setAttribute("aria-pressed", selected.indexOf(button.getAttribute("data-point")) >= 0 ? "true" : "false");
    });
    els.panelContent.querySelectorAll("[data-region]").forEach(function(region) {
      region.setAttribute("data-selected", selected.indexOf(region.getAttribute("data-region")) >= 0 ? "true" : "false");
    });
    var summary = $("workspace-summary");
    if (summary) summary.textContent = selected.length ? selected.join(" · ") : "尚未选择点位";
    var count = $("workspace-count");
    if (count) count.textContent = state.route.action==="todo" ? "待接入" : "已选 " + selected.length + " 处";
  }
  function choosePoint(point) {
    var selected=selectedPoints(), i=selected.indexOf(point);
    if(i<0)selected.push(point);else selected.splice(i,1);
    syncPoints();
    announce((i<0?"已选择":"已取消")+point);
  }
  function buildDiagram(spot) {
    var figure=h("section","workspace-visual");
    figure.setAttribute("aria-label",spot.short+"点位示意");
    figure.setAttribute("data-place",spot.id);
    figure.appendChild(h("p","workspace-code",ART_CODE[spot.id]+" / 区域选择"));
    figure.appendChild(h("h3",null,spot.id==="dam"?"沿坝而行。":"逐层查看。"));
    figure.appendChild(h("p","workspace-visual-lede",state.route.action==="todo"?"接入后，工单会关联到这些点位。":"点击图中点位，把巡查范围选清楚。"));
    var drawing=h("div","workspace-drawing");
    var svg=svgNode("svg",{viewBox:"0 0 640 520","aria-hidden":"true",focusable:"false"});
    var shapes;
    if(spot.id==="dam") shapes=[
      ["path",{d:"M0 235Q200 150 640 250V520H0Z",fill:"#0d64d4"}],
      ["path",{d:"M0 416Q230 325 640 399V520H0Z",fill:"#1243b2"}],
      ["path",{d:"M14 292Q235 122 537 205L582 351Q293 251 30 434Z",fill:"#a7cee2"}],
      ["path",{d:"M14 292Q235 122 537 205L548 227Q250 149 19 319Z",fill:"#fff"}],
      ["path",{d:"M30 289Q263 137 530 205",stroke:"#356f9e","stroke-width":"3",fill:"none"}],
      ["path",{d:"M176 254L245 232 273 349 200 382Z M288 226L358 228 393 341 321 355Z M400 236L468 255 503 367 435 347Z",fill:"#072654"}],
      ["path",{d:"M191 262L231 251 255 346 215 361Z M304 244L345 245 374 335 333 342Z M416 254L455 264 484 354 445 341Z",fill:"#2366b4"}],
      ["path",{d:"M215 361L255 346Q300 403 353 425L288 445Q241 415 215 361Z M333 342L374 335Q420 390 470 406L410 425Q357 390 333 342Z M445 341L484 354Q521 403 559 416L520 434Q476 401 445 341Z",fill:"#5de4e7"}],
      ["path",{d:"M182 253l20 119M290 229l31 126M400 237l35 111",stroke:"#effbff","stroke-width":"14",fill:"none"}],
      ["path",{d:"M22 276v28M109 231v27M208 193v25M313 179v24M422 187v25M523 208v24",stroke:"#31628a","stroke-width":"3",fill:"none"}],
      ["path",{d:"M320 464Q457 435 606 466",stroke:"#40bbdf","stroke-width":"3",fill:"none",opacity:".5"}]
    ];
    else shapes=[
      ["path",{d:"M60 422L300 343 591 417 346 496Z",fill:"#bad9e8"}],
      ["path",{d:"M201 406L395 450 425 129 249 89Z",fill:"#205ca8"}],
      ["path",{d:"M395 450L425 129 504 78 478 393Z",fill:"#082b5e"}],
      ["path",{d:"M249 89L425 129 504 78 329 39Z",fill:"#8ec5df"}],
      ["path",{d:"M249 89L201 406",stroke:"#ecfbff","stroke-width":"8",fill:"none"}],
      ["path",{d:"M225 254L413 296M236 182L419 223M214 331L406 373",stroke:"#6ba5d3","stroke-width":"2",fill:"none"}],
      ["path",{d:"M278 108L242 408M352 128L321 428",stroke:"#84e6ef","stroke-width":"2",fill:"none"}],
      ["path",{d:"M65 442L342 516 593 438",stroke:"#89b5cf","stroke-width":"2",fill:"none"}]
    ];
    shapes.forEach(function(s){svg.appendChild(svgNode(s[0],s[1]));});
    var overlays = spot.id==="dam" ? [
      "M30 289Q263 137 530 205", "M490 245Q562 220 624 270", "M310 449Q440 424 560 450"
    ] : ["M210 331L406 373", "M249 89L425 129 504 78 329 39Z", "M225 254L413 296"];
    overlays.forEach(function(d,i) { svg.appendChild(svgNode("path", {
      d:d,fill:"none",stroke:"#41e4eb","stroke-width":"8","stroke-linecap":"round",
      "class":"workspace-region","data-region":spot.points[i],"data-selected":"false"
    })); });
    drawing.appendChild(svg);
    spot.points.forEach(function(point,index){
      var marker=h("button","map-point");marker.type="button";
      marker.setAttribute("data-point",point);marker.setAttribute("data-index",String(index));
      marker.setAttribute("aria-label","图示选择："+point);marker.setAttribute("aria-pressed","false");
      marker.disabled=state.route.action==="todo";
      marker.appendChild(h("span","map-point-dot"));marker.appendChild(h("span","map-point-label",point));
      marker.addEventListener("click",function(){choosePoint(point);});drawing.appendChild(marker);
    });
    figure.appendChild(drawing);
    var bottom=h("div","workspace-map-foot");bottom.appendChild(h("span",null,"局部示意 · 非实时地图"));
    var count=h("strong",null,"已选 0 处");count.id="workspace-count";bottom.appendChild(count);figure.appendChild(bottom);
    return figure;
  }
  function buildFeaturePage(featureId) {
    var feature = FEATURES[featureId];
    if (!feature) return;

    parkComposer();
    els.dock.hidden = true;

    var panel = els.panelContent;
    panel.textContent = "";
    panel.scrollTop = 0;
    panel.removeAttribute("data-place");
    panel.setAttribute("data-mode", "feature");

    var top = h("header", "workspace-top");
    var back = h("button", "workspace-back", "返回主菜单");
    back.type = "button";
    back.prepend(icon("arrowLeft", "icon"));
    back.addEventListener("click", function () { navigate("#/scene"); });
    top.appendChild(back);

    var title = h("h2", null, "功能" + feature.id + " · " + feature.name);
    title.id = "panel-title";
    title.tabIndex = -1;
    title.setAttribute("data-panel-focus", "");
    top.appendChild(title);
    top.appendChild(h("span", "workspace-location", "功能入口 / 占位页"));
    panel.appendChild(top);

    /* Stage-4 read-only submenus: all feature 2–7 route to one audited UI.
       The previous stage-3 placeholder builder remains unreachable as a safe
       fallback if submenu.js is absent (not an alternate data source). */
    if (window.VelaSubmenus && window.VelaSubmenus.mount(featureId, panel)) {
      return;
    }
    if (featureId === "4" || featureId === "6" || featureId === "7") {
      buildHubFeaturePage(featureId, panel);
      return;
    }

    var body = h("section", "feature-placeholder");
    body.setAttribute("aria-labelledby", "feature-title");
    var card = h("div", "feature-placeholder-card");
    card.appendChild(h("p", "feature-kicker", "FUNCTION " + feature.id + " / VELAGUARD"));
    var heading = h("h3", null, feature.name);
    heading.id = "feature-title";
    card.appendChild(heading);
    card.appendChild(h("p", "feature-description", feature.description));
    var status = h("p", "feature-status", feature.status);
    status.setAttribute("role", "status");
    card.appendChild(status);
    card.appendChild(h("p", "feature-note", feature.note));

    var returnButton = h("button", "feature-return", "返回主菜单");
    returnButton.type = "button";
    returnButton.addEventListener("click", function () { navigate("#/scene"); });
    card.appendChild(returnButton);
    body.appendChild(card);
    panel.appendChild(body);
  }


/* Dedicated stage-UI pages: intentional empty states; no hardware/API polling. */
function hubStatus(label, value) {
  var row = h("div", "hub-status-row");
  row.appendChild(h("span", "hub-status-label", label));
  row.appendChild(h("strong", "hub-status-value", value));
  return row;
}

function hubCard(kicker, heading, description) {
  var card = h("section", "hub-panel-card");
  card.appendChild(h("p", "hub-kicker", kicker));
  card.appendChild(h("h3", null, heading));
  if (description) card.appendChild(h("p", "hub-card-desc", description));
  return card;
}

function hubPill(value) {
  return h("span", "hub-pill", value);
}

function hubCapability(name, description) {
  var item = h("div", "hub-capability");
  item.appendChild(h("strong", null, name));
  item.appendChild(h("p", null, description));
  return item;
}

function buildHubFeaturePage(featureId, panel) {
  var body = h("div", "hub-feature-body");
  var intro = h("div", "hub-feature-intro");
  var feature = FEATURES[featureId];
  intro.appendChild(h("p", "hub-kicker", "VELAGUARD / FUNCTION " + feature.id));
  intro.appendChild(h("h3", null, feature.description));
  intro.appendChild(h("p", "hub-feature-disclaimer", "UI 框架展示 · 未接入的数据均明确标记，不代表真实运行结果"));
  body.appendChild(intro);

  var grid = h("div", "hub-page-grid");
  if (featureId === "4") {
    var diag = hubCard("CLOUD AGENT", "自诊流程", "知识库检索 → 诊断分析 → 结果建议；仅为规划中的流程说明。当前不触发诊断。");
    diag.appendChild(hubPill("自诊接口待接入"));
    diag.appendChild(hubStatus("云端 Agent 自诊状态", "未验证"));
    diag.appendChild(hubStatus("最近诊断", "暂无已接入记录"));
    var know = hubCard("KNOWLEDGE BASE", "知识依据", "展示知识来源、匹配证据和诊断依据的位置；知识库接口接入后才能查询。 ");
    know.appendChild(hubStatus("知识库连接", "待接入"));
    know.appendChild(hubStatus("检索结果", "暂无真实数据"));
    var note = hubCard("DIAGNOSIS OUTPUT", "诊断结论", "接入后可在此显示诊断原因、证据、风险等级与处理建议。涉及安全的处置应由人工确认。");
    note.classList.add("hub-card-wide");
    note.appendChild(hubPill("当前没有真实诊断结果"));
    grid.appendChild(diag); grid.appendChild(know); grid.appendChild(note);
  } else if (featureId === "6") {
    var tasks = hubCard("STRUCTURED TASKS", "结构化任务", "未来展示语音或人工巡检需求转化出的任务字段，保持任务来源和人工确认边界。 ");
    tasks.appendChild(hubStatus("任务记录", "未接入"));
    tasks.appendChild(hubStatus("任务 ID / 优先级", "暂无真实数据"));
    tasks.appendChild(hubStatus("车辆归属 / 执行状态", "暂无真实数据"));
    var review = hubCard("INSPECTION REVIEW", "巡检复盘", "将任务计划、执行记录和异常闭环关联展示；本页不生成虚构复盘。 ");
    review.appendChild(hubStatus("已完成轮次", "暂无已接入记录"));
    review.appendChild(hubStatus("事件与处理依据", "暂无真实数据"));
    review.appendChild(hubStatus("复核结论", "待接入"));
    var flow = hubCard("WORKFLOW", "结构化到复盘的业务关系", "自然语言意图 → 结构化任务 → 执行记录 → 异常复核与巡检复盘。这是流程说明，不代表已执行。 ");
    flow.classList.add("hub-card-wide");
    flow.appendChild(hubPill("实际任务与历史数据尚未接入"));
    grid.appendChild(tasks); grid.appendChild(review); grid.appendChild(flow);
  } else if (featureId === "7") {
    var identity = hubCard("EDGE NODE / GEMINI-S1", "设备与协同状态", "定位：VelaGuard 端侧智能处理节点。该说明是系统设计角色，不是实时设备探测结果。 ");
    identity.appendChild(hubStatus("设备在线", "未验证"));
    identity.appendChild(hubStatus("与云端连接", "未验证"));
    identity.appendChild(hubStatus("与巡检车辆协同", "未验证"));
    var work = hubCard("AGENT ACTIVITY", "当前工作状态", "重点展示 Gemini-S1 此刻的实际职责，而不只是硬件占用率。 ");
    work.appendChild(hubStatus("当前 Agent 阶段", "未接入"));
    work.appendChild(hubStatus("当前任务", "暂无真实数据"));
    work.appendChild(hubStatus("最近上报", "暂无真实数据"));
    var capability = hubCard("EDGE CAPABILITIES", "端侧能力定位", "以下是拟展示的系统职责，不表示所有能力已在本设备上验收。 ");
    capability.appendChild(hubCapability("轻量识别与异常初判", "在端侧初筛事件，明确证据不足的情况。"));
    capability.appendChild(hubCapability("本地任务分配", "按已验证的设备侧算法和授权边界执行。"));
    capability.appendChild(hubCapability("云端协同上报", "复杂异常交由云端与人工完成后续判断。"));
    var runtime = hubCard("DEVICE HEALTH", "运行信息", "CPU、内存、温度、运行时长和心跳需由真实设备接口提供。 ");
    runtime.appendChild(hubStatus("CPU / 内存 / 温度", "未接入"));
    runtime.appendChild(hubStatus("运行时长 / 最近心跳", "未接入"));
    grid.appendChild(identity);grid.appendChild(work);grid.appendChild(capability);grid.appendChild(runtime);
  }

  body.appendChild(grid);
  var home = h("button", "feature-return hub-return", "返回主菜单");
  home.type = "button";
  home.addEventListener("click", function () { navigate("#/scene"); });
  body.appendChild(home);
  panel.appendChild(body);
}

  function buildPanel(route) {
    parkComposer();
    var panel=els.panelContent, spot=SPOTS[route.spot],action=route.action||"new";
    panel.textContent="";panel.scrollTop=0;
    panel.setAttribute("data-mode",action);
    panel.setAttribute("data-place",spot.id);
    var top=h("header","workspace-top");
    var back=h("button","workspace-back","返回水岸");back.type="button";back.prepend(icon("arrowLeft","icon"));
    back.addEventListener("click",function(){state.focusSpotOnScene=true;navigate("#/scene");});top.appendChild(back);
    var title=h("h2",null,spot.name);title.id="panel-title";title.tabIndex=-1;title.setAttribute("data-panel-focus","");top.appendChild(title);
    top.appendChild(h("span","workspace-location","河海 · "+spot.short+"工作区"));panel.appendChild(top);
    var grid=h("div","workspace-grid");grid.appendChild(buildDiagram(spot));
    var task=h("section","workspace-task");task.setAttribute("aria-label",spot.short+"巡查编辑");
    var tabs=h("nav","workspace-tabs");tabs.setAttribute("aria-label","巡查操作");
    [["new","发起巡查"],["todo","待处理"],["recheck","指定点复查"]].forEach(function(pair){
      var tab=h("button",null,pair[1]);tab.type="button";tab.setAttribute("aria-pressed",action===pair[0]?"true":"false");
      tab.addEventListener("click",function(){navigate("#/scene/"+spot.id+"/"+pair[0]);});tabs.appendChild(tab);
    });task.appendChild(tabs);
    if(action==="todo") {
      var empty=h("div","workspace-empty");empty.appendChild(icon("list","icon"));
      empty.appendChild(h("p","workspace-kicker","待处理工单"));empty.appendChild(h("h3",null,"等待接入工单来源"));
      empty.appendChild(h("p",null,"接入后，这里会显示需要处理的事项、现场证据和复查进度。"));
      empty.appendChild(h("span","workspace-status","工单接口未接入"));
      var create=h("button","secondary-btn","先发起一轮巡查");create.type="button";create.addEventListener("click",function(){navigate("#/scene/"+spot.id+"/new");});empty.appendChild(create);task.appendChild(empty);
      els.dock.hidden=true;task.appendChild(els.dock);
    } else {
      var intro=h("div","workspace-intro");intro.appendChild(h("p","workspace-kicker",action==="new"?"01 / 选择范围，写下要求":"02 / 回到原点，补齐证据"));
      intro.appendChild(h("h3",null,action==="new"?"这轮巡查看哪里？":"这次需要复查什么？"));
      intro.appendChild(h("p",null,action==="new"?"选好点位，再说清重点和时间。助手会先核对执行条件。":"选择复查点位，说明上次的问题与需要补拍的内容。"));task.appendChild(intro);
      var selection=h("section","workspace-selection");selection.setAttribute("aria-label","巡查点位");
      var selectionHead=h("div","workspace-selection-head");selectionHead.appendChild(h("strong",null,"巡查点位"));
      selectionHead.appendChild(h("span",null,"可多选 · 与左侧图示同步"));selection.appendChild(selectionHead);
      var chips=h("div","workspace-chips");spot.points.forEach(function(point){
        var chip=h("button",null,point);chip.type="button";chip.setAttribute("data-point",point);chip.setAttribute("aria-pressed","false");chip.appendChild(icon("check","icon"));
        chip.addEventListener("click",function(){choosePoint(point);});chips.appendChild(chip);
      });selection.appendChild(chips);
      var summary=h("p","workspace-summary");summary.id="workspace-summary";summary.setAttribute("aria-live","polite");selection.appendChild(summary);task.appendChild(selection);
      var key=draftKey(route), fields=workspaceFields[key] || (workspaceFields[key]={time:"",handling:""});
      var extra=h("details","workspace-extra");extra.open=window.innerHeight>=900;
      extra.appendChild(h("summary",null,"时间与异常处理（选填）"));
      var extraRow=h("div","workspace-extra-row");
      var timeLabel=h("label",null,"完成时间");
      var time=h("input");time.type="text";time.maxLength=80;time.value=fields.time;time.placeholder="例如：明天下午三点前";
      time.addEventListener("input",function(){fields.time=time.value;});timeLabel.appendChild(time);extraRow.appendChild(timeLabel);
      var handlingLabel=h("label",null,"异常处理");var handling=h("select");
      [["","交给助手核对"],["发现异常时先报告，等待人工处理","发现异常先报告"],["仅记录异常并保留现场证据，不自行处置","仅记录与补证"]].forEach(function(pair){
        var option=h("option",null,pair[1]);option.value=pair[0];handling.appendChild(option);
      });handling.value=fields.handling;handling.addEventListener("change",function(){fields.handling=handling.value;});handlingLabel.appendChild(handling);extraRow.appendChild(handlingLabel);
      extra.appendChild(extraRow);task.appendChild(extra);
      var label=h("label","workspace-input-label","巡查要求");label.setAttribute("for","chat-input");
      label.appendChild(h("span",null,action==="new"?"时间、重点或特别说明":"上次问题、补证要求"));task.appendChild(label);
      var composerHost=h("div","workspace-composer");composerHost.appendChild(els.dock);task.appendChild(composerHost);
      task.appendChild(h("p","workspace-confirm","提交后先核对并生成待确认计划，车辆不会自动执行。"));
    }
    grid.appendChild(task);panel.appendChild(grid);
    document.querySelector('label.sr-only[for="chat-input"]').textContent="";
    els.chatInput.placeholder=action==="recheck"?"例如：复查上次坝顶积水，补拍同位置、同角度的照片。":spot.newNote.replace(/^例如：/,"例如：");
    els.sendButton.querySelector("span").textContent="提交给助手";
    syncPoints();
  }
  function workspaceMessage(raw) {
    var route=state.route;
    if(!route.spot || route.action==="todo")return raw;
    var selected=selectedPoints();
    var fields=workspaceFields[draftKey(route)] || {};
    if(!raw && !selected.length && !fields.time && !fields.handling)return "";
    var spot=SPOTS[route.spot],recheck=route.action==="recheck";
    return "【"+spot.name+" · "+(recheck?"指定点复查":"发起巡查")+"】\n"+
      "点位："+(selected.length?selected.join("、"):"待澄清")+"\n"+
      (fields.time?"完成时间："+fields.time+"\n":"")+
      (fields.handling?"异常处理："+fields.handling+"\n":"")+
      (raw?"要求："+raw+"\n":"")+
      (recheck?"请按原位置、原角度补证；提交后仍需人工复查。\n":"")+spot.draftTail;
  }

  /* --------------------------------------------------------------- draft */

  function updateCount() {
    var value = els.chatInput.value || "";
    els.charCount.textContent = value.length + " / 2000";
  }

  function receiveTranscript(text) {
    var clean = typeof text === "string" ? text.trim() : "";
    if (!clean) {
      return;
    }
    els.chatInput.value = clean;
    state.lastPrimed = clean;
    updateCount();
    els.chatInput.focus({ preventScroll: true });
    toast("识别文字已进入草案；请核对后手动发送。");
    announce("识别文字已进入草案，尚未发送。");
  }

  /* --------------------------------------------------------------- voice */

  function onVoiceState(voiceState) {
    var current = voiceState || "idle";
    var accessibleNames = {
      idle: "语音输入",
      listening: "正在录音，点击停止",
      stopping: "正在结束录音",
      recognizing: "语音识别中",
      requesting: "正在请求麦克风权限",
      captured: "录音已采集，尚未转写",
      error: "语音输入不可用",
      unavailable: "语音输入不可用",
      done: "语音转写完成"
    };
    els.voiceBtn.setAttribute("data-state", current);
    els.voiceBtn.setAttribute("aria-label", accessibleNames[current] || "语音输入");
    els.voiceBtn.setAttribute("aria-pressed", current === "listening" ? "true" : "false");
  }

  function initVoice() {
    if (!window.VelaVoice) {
      onVoiceState("unavailable");
      return;
    }
    window.VelaVoice.init({
      configUrl: CFG.asrConfig,
      getToken: function () {
        return state.token;
      },
      onText: receiveTranscript,
      onState: onVoiceState,
      onManual: function () {
        window.VelaVoice.close();
        els.chatInput.focus({ preventScroll: true });
      }
    });
    onVoiceState("idle");
  }

  /* The wake-word bridge writes the transcript into the service inbox.  The
     page only displays and sends it; it never records audio itself. */
  function queueVoiceMessage(text) {
    var clean = typeof text === "string" ? text.trim() : "";
    if (!clean) {
      return;
    }
    state.voicePending = clean;
    trySendVoice();
  }

  function trySendVoice() {
    if (!state.voicePending || state.busy) {
      return;
    }
    var text = state.voicePending;
    state.voicePending = "";
    els.chatInput.value = text;
    state.lastPrimed = text;
    updateCount();
    toast("唤醒语音已转写，正在自动发送…");
    window.setTimeout(function () {
      if (state.busy) {
        state.voicePending = text;
        return;
      }
      if (els.chatInput.value.trim() !== text) {
        return;
      }
      sendMessage(undefined, false, { suppressSheet: true });
    }, 500);
  }

  function initVoiceInbox() {
    if (window.location.protocol === "file:") {
      return;
    }
    function poll() {
      requestJson("/api/voice/latest", { method: "GET" }, 5000).then(function (data) {
        var seq = Number(data && data.seq) || 0;
        if (state.voiceSeq === null) {
          state.voiceSeq = seq;
          return;
        }
        if (seq > state.voiceSeq) {
          state.voiceSeq = seq;
          queueVoiceMessage(data && data.text);
        }
      }).catch(function () {
        /* The inbox endpoint may not exist on older deployments; keep quiet. */
      });
    }
    poll();
    state.voicePoll = window.setInterval(poll, 900);
  }

  function toggleVoice() {
    /* Keep the existing click feedback; the device-side wake-word bridge remains
       responsible for recognition and the inbox continues to be polled. */
    toast("语音入口已就绪。");
    announce("语音入口已就绪。");
  }

  /* ---------------------------------------------------------------- chat */

  function buildHeaders(hasBody) {
    var headers = { Accept: "application/json" };
    if (hasBody) {
      headers["Content-Type"] = "application/json";
    }
    if (state.token) {
      headers.Authorization = "Bearer " + state.token;
    }
    return headers;
  }

  function parseJson(text) {
    if (!text) {
      return null;
    }
    try {
      return JSON.parse(text);
    } catch (err) {
      return null;
    }
  }

  function requestJson(path, options, timeoutMs) {
    var controller = new AbortController();
    var timer = window.setTimeout(function () {
      controller.abort();
    }, timeoutMs || 80000);
    var init = {
      method: options.method || "GET",
      headers: buildHeaders(Boolean(options.body)),
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal
    };
    if (options.body !== undefined) {
      init.body = JSON.stringify(options.body);
    }
    return fetch(path, init).then(function (response) {
      return response.text().then(function (text) {
        window.clearTimeout(timer);
        var payload = parseJson(text);
        if (!response.ok) {
          var error = new Error("http_error");
          error.status = response.status;
          error.payload = payload;
          throw error;
        }
        if (!payload) {
          var parseError = new Error("invalid_json");
          parseError.status = response.status;
          throw parseError;
        }
        return payload;
      });
    }).catch(function (error) {
      window.clearTimeout(timer);
      throw error;
    });
  }

  function setChatState(label, kind) {
    els.chatState.textContent = label;
    els.chatState.setAttribute("data-state", kind || "");
  }

  function setBusy(busy) {
    state.busy = busy;
    els.sendButton.disabled = busy;
    els.sendButton.querySelector("span").textContent = busy ? "核对中…" : (state.route.spot ? "提交给助手" : "发送");
    els.chatForm.setAttribute("aria-busy", busy ? "true" : "false");
    if (!busy) {
      window.setTimeout(trySendVoice, 300);
    }
  }

  function openSheet() {
    if (!els.assistantSheet.hidden) {
      return;
    }
    els.assistantSheet.hidden = false;
    window.requestAnimationFrame(function () {
      els.transcript.scrollTop = els.transcript.scrollHeight;
    });
  }

  function closeSheet() {
    els.assistantSheet.hidden = true;
  }

  function appendMessage(role, text, options) {
    var opts = options || {};
    var wrap = h("div", "msg msg-" + role);
    var label = role === "user" ? "你" : role === "error" ? "请求失败" : role === "note" ? "说明" : "巡查助手";
    wrap.appendChild(h("p", "msg-role", label));

    var bubble = h("div", "bubble");
    bubble.textContent = text;
    wrap.appendChild(bubble);

    if (opts.code) {
      var code = h("span", "error-code", opts.code);
      bubble.appendChild(code);
    }

    if (opts.retry) {
      var retry = h("button", "mini-btn retry-btn", "重试");
      retry.type = "button";
      retry.addEventListener("click", function () {
        sendMessage(opts.retry, true);
      });
      wrap.appendChild(retry);
    }

    els.transcript.appendChild(wrap);
    window.requestAnimationFrame(function () {
      els.transcript.scrollTop = els.transcript.scrollHeight;
    });
    return wrap;
  }

  function appendTyping() {
    removeTyping();
    var wrap = h("div", "msg msg-assistant");
    wrap.appendChild(h("p", "msg-role", "巡查助手"));
    var typing = h("div", "typing");
    typing.appendChild(document.createTextNode("正在核对条件"));
    typing.appendChild(h("i"));
    typing.appendChild(h("i"));
    typing.appendChild(h("i"));
    wrap.appendChild(typing);
    els.transcript.appendChild(wrap);
    state.typingEl = wrap;
    window.requestAnimationFrame(function () {
      els.transcript.scrollTop = els.transcript.scrollHeight;
    });
  }

  function removeTyping() {
    if (state.typingEl && state.typingEl.parentNode) {
      state.typingEl.parentNode.removeChild(state.typingEl);
    }
    state.typingEl = null;
  }

  function friendlyError(error) {
    var code = error && error.payload && error.payload.error && error.payload.error.code;
    var status = error && error.status;
    var map = {
      llm_not_configured: "模型尚未配置。页面不会生成模拟回复；请在设备上完成模型配置后重试。",
      llm_auth_failed: "模型认证未通过，请维护者检查设备配置；页面不会回退到示例回复。",
      llm_unreachable: "模型服务暂时不可达，请稍后重试。",
      llm_timeout: "模型服务响应超时，请稍后重试。",
      llm_rate_limited: "模型服务繁忙，请稍后重试。",
      llm_response_too_large: "模型返回内容过大，请缩小问题范围后重试。",
      llm_invalid_response: "模型返回了无法识别的结果，请稍后重试。",
      rate_limited: "请求过于频繁，请稍等片刻再发送。",
      request_too_large: "请求内容过大，请缩短后重试。",
      message_too_long: "消息过长，请缩短到 2000 字以内。",
      tool_loop_limit: "本轮工具调用达到上限，未生成最终答复；请缩小问题范围后重试。",
      unauthorized: "需要访问口令。请在“访问口令”中填写维护者提供的口令后重试。",
      invalid_conversation_id: "会话标识失效；下一次发送会自动开启新会话。",
      invalid_message: "消息不能为空。"
    };
    if (code && map[code]) {
      return map[code];
    }
    if (status === 401) {
      return map.unauthorized;
    }
    if (status === 413) {
      return map.request_too_large;
    }
    if (status === 429) {
      return map.rate_limited;
    }
    if (status === 503) {
      return map.llm_not_configured;
    }
    if (error && error.name === "AbortError") {
      return "助手响应超时（80 秒）。请求可能已经到达服务；请先刷新会话状态再重试。";
    }
    if (error && error.message === "invalid_json") {
      return "服务返回的不是合法 JSON，请检查服务日志。";
    }
    return "网络请求失败，请确认服务可达、页面与接口同源后重试。";
  }

  function handleChatError(error, message) {
    removeTyping();
    var code = error && error.payload && error.payload.error && error.payload.error.code;
    var status = error && error.status;
    if (code === "invalid_conversation_id") {
      state.conversationId = null;
      storageSet("velaSceneConversationId", null);
    }
    var text = friendlyError(error);
    appendMessage("error", text, { code: code || (status ? "HTTP " + status : "network"), retry: message });
    setChatState("请求失败", "error");
    setBusy(false);
    state.lastMessage = message;
    if (status === 401) {
      els.tokenDetails.open = true;
      els.tokenInput.focus();
    }
    announce("巡查助手请求失败：" + text);
  }

  function sendMessage(override, isRetry, sendOptions) {
    var sendOpts = sendOptions || {};
    if (state.busy) {
      return;
    }
    var rawDraft=els.chatInput.value.trim();
    var message = typeof override === "string" ? override.trim() : workspaceMessage(rawDraft);
    var sentKey=draftKey(state.route);
    var fromWorkspace=Boolean(state.route.spot);
    if (!message) {
      toast("先写一句巡查目标，或从热点带入草案。", true);
      els.chatInput.focus();
      return;
    }
    if (message.length > 2000) {
      toast("消息最多 2000 字，请缩短后发送。", true);
      return;
    }
    if (window.location.protocol === "file:") {
      if (!sendOpts.suppressSheet) openSheet();
      appendMessage("user", message);
      appendMessage("error", "当前是本地文件预览，无法访问同源 /api/chat。请通过服务的 /static/scene-v2/ 地址打开后再发送；页面不会伪造回复。", { code: "file_preview" });
      setChatState("预览模式", "error");
      return;
    }

    if (!sendOpts.suppressSheet) openSheet();
    if (!isRetry) {
      appendMessage("user", message);
      els.chatInput.value = "";
      if(fromWorkspace) workspaceDrafts[sentKey]="";
      state.lastPrimed = "";
      updateCount();
    }
    state.lastMessage = message;
    setBusy(true);
    setChatState("核对中", "");
    appendTyping();
    announce("已发送，正在等待真实服务回复。");

    requestJson("/api/chat", {
      method: "POST",
      body: { message: message, conversation_id: state.conversationId || undefined }
    }, 80000).then(function (data) {
      removeTyping();
      var reply = typeof data.reply === "string" && data.reply.trim() ? data.reply : "服务返回成功，但没有文本答复。";
      appendMessage("assistant", reply);

      if (typeof data.conversation_id === "string" && data.conversation_id) {
        state.conversationId = data.conversation_id;
        storageSet("velaSceneConversationId", data.conversation_id);
      }

      var proposals = Array.isArray(data.proposals) ? data.proposals : [];
      if (proposals.length) {
        appendMessage("note", "已创建 " + proposals.length + " 条待确认计划；确认不等于执行。请回到主控制台的任务中心核对条件，不要把它当作已下发任务。", {});
      }

      var toolEvents = Array.isArray(data.tool_events) ? data.tool_events : [];
      if (toolEvents.length) {
        appendMessage("note", "本轮调用 " + toolEvents.length + " 次服务端工具；执行状态仍为未执行。", {});
      }

      if (data.execution && data.execution.state && data.execution.state !== "not_executed") {
        appendMessage("note", "服务返回了非预期的执行状态；请维护者核对，页面不据此宣称车辆已执行。", {});
      }

      setChatState("本会话已回复", "ok");
      setBusy(false);
      state.lastMessage = "";
      setService("ready");
      announce("收到真实服务回复。");
    }).catch(function (error) {
      handleChatError(error, message);
      if(fromWorkspace && !isRetry) {
        if(!workspaceDrafts[sentKey]) workspaceDrafts[sentKey]=rawDraft;
        if(draftKey(state.route)===sentKey && !els.chatInput.value) { els.chatInput.value=rawDraft;updateCount(); }
      }
    });
  }

  function checkHealth() {
    if (window.location.protocol === "file:") {
      setService("preview");
      return;
    }
    requestJson("/api/health", { method: "GET" }, 12000).then(function (data) {
      var configured = Boolean(data && data.llm && data.llm.configured);
      setService(configured ? "ready" : "unconfigured");
    }).catch(function () {
      setService("offline");
    });
  }

  function setService(kind) {
    var map = {
      checking: "正在检查助手",
      ready: "助手可发起",
      unconfigured: "助手未配置",
      offline: "服务未连接",
      preview: "静态预览"
    };
    els.servicePill.setAttribute("data-state", kind);
    els.serviceText.textContent = map[kind] || map.checking;
  }

  /* --------------------------------------------------------------- token */

  function initToken() {
    state.token = storageGet("cloudAgentToken") || "";
    updateTokenState();
  }

  function updateTokenState() {
    if (state.token) {
      els.tokenState.textContent = "已设置（仅当前标签页）；不会显示或写入日志。";
    } else {
      els.tokenState.textContent = "尚未设置；只保存在本页会话，不写入日志。";
    }
  }

  function saveToken() {
    var value = els.tokenInput.value.trim();
    state.token = value;
    var stored = storageSet("cloudAgentToken", value || null);
    els.tokenInput.value = "";
    updateTokenState();
    if (!stored && value) {
      toast("浏览器不允许 sessionStorage；口令只在本页内存中有效。", true);
    } else {
      toast(value ? "访问口令已保存到当前标签页。" : "访问口令已清除。");
    }
    checkHealth();
  }

  function clearToken() {
    state.token = "";
    els.tokenInput.value = "";
    storageSet("cloudAgentToken", null);
    updateTokenState();
    toast("访问口令已清除。");
  }

  /* --------------------------------------------------------------- help */

  function focusableIn(node) {
    return node.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])');
  }

  function openHelp() {
    if (!els.helpModal.hidden) {
      return;
    }
    state.helpReturnFocus = document.activeElement;
    els.helpModal.hidden = false;
    els.helpToggle.setAttribute("aria-expanded", "true");
    state.helpOpen = true;
    document.addEventListener("keydown", trapHelp, true);
    window.requestAnimationFrame(function () {
      els.helpCard.focus();
    });
  }

  function closeHelp() {
    if (els.helpModal.hidden) {
      return;
    }
    els.helpModal.hidden = true;
    els.helpToggle.setAttribute("aria-expanded", "false");
    state.helpOpen = false;
    document.removeEventListener("keydown", trapHelp, true);
    if (state.helpReturnFocus && typeof state.helpReturnFocus.focus === "function") {
      state.helpReturnFocus.focus();
    }
    state.helpReturnFocus = null;
  }

  function trapHelp(event) {
    if (!state.helpOpen || event.key !== "Tab") {
      return;
    }
    var items = focusableIn(els.helpCard);
    if (!items.length) {
      return;
    }
    var first = items[0];
    var last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  /* ---------------------------------------------------------- static/perf */

  function applyStatic(value, silent) {
    var on = value === "on";
    app.setAttribute("data-static", on ? "on" : "off");
    els.staticToggle.setAttribute("aria-pressed", on ? "true" : "false");
    els.staticLabel.textContent = on ? "静态展示 · 开" : "静态展示";
    storageSet("velaSceneStatic", on ? "on" : "off");
    if (!silent) {
      toast(on ? "静态展示：装饰动效已暂停，交互仍可用。" : "动态展示：轻量波纹已恢复。");
    }
  }

  function initStatic() {
    var saved = storageGet("velaSceneStatic");
    // Default to the static presentation on this panel: the animated water is
    // the main CPU cost on the E5's software renderer.  A user who explicitly
    // chose "dynamic" keeps that choice for this page session.
    applyStatic(saved === "off" ? "off" : "on", true);
  }

  function initPerf() {
    var params = new URLSearchParams(window.location.search);
    if (params.get("perf") !== "1") {
      return;
    }
    els.perf.hidden = false;
    state.perf = { last: 0, lastPaint: 0, intervals: [], total: 0, long: 0 };
    state.perfRaf = window.requestAnimationFrame(perfTick);
  }

  function perfTick(timestamp) {
    if (document.hidden || !state.perf) {
      return;
    }
    if (state.perf.last) {
      var delta = timestamp - state.perf.last;
      if (delta > 0 && delta < 5000) {
        state.perf.intervals.push(delta);
        state.perf.total += 1;
        if (delta > 50) {
          state.perf.long += 1;
        }
        if (state.perf.intervals.length > 240) {
          state.perf.intervals.shift();
        }
      }
    }
    state.perf.last = timestamp;
    if (timestamp - state.perf.lastPaint > 500) {
      paintPerf();
      state.perf.lastPaint = timestamp;
    }
    state.perfRaf = window.requestAnimationFrame(perfTick);
  }

  function paintPerf() {
    if (!state.perf || !els.perfText) {
      return;
    }
    var sorted = state.perf.intervals.slice().sort(function (a, b) {
      return a - b;
    });
    var p95 = 0;
    var max = 0;
    if (sorted.length) {
      p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))];
      max = sorted[sorted.length - 1];
    }
    var longPct = state.perf.total ? (state.perf.long / state.perf.total) * 100 : 0;
    els.perfText.textContent = "最近 " + sorted.length + " 帧 · 长帧(>50ms) 累计 " + longPct.toFixed(1) + "% · p95 " + p95.toFixed(1) + " ms · 最大 " + max.toFixed(1) + " ms";
  }

  function stopPerf() {
    if (state.perfRaf) {
      window.cancelAnimationFrame(state.perfRaf);
      state.perfRaf = 0;
    }
  }

  function resumePerf() {
    if (els.perf.hidden || !state.perf || state.perfRaf) {
      return;
    }
    state.perf.last = 0;
    state.perfRaf = window.requestAnimationFrame(perfTick);
  }

  function onVisibilityChange() {
    var hidden = document.hidden;
    app.setAttribute("data-hidden", hidden ? "true" : "false");
    if (hidden) {
      stopPerf();
    } else {
      resumePerf();
    }
  }

  /* --------------------------------------------------------------- scene */

  function homeHotspot(spotId) {
    var featureId = HOME_FEATURE_BY_SPOT[spotId];
    if (featureId) {
      return document.querySelector('.hotspot[data-feature="' + featureId + '"]');
    }
    return document.querySelector('.hotspot[data-spot="' + spotId + '"]');
  }

  function initFeatureEntries() {
    var entries = document.querySelectorAll(".hotspots [data-feature], .hub-entry[data-feature]");
    for (var i = 0; i < entries.length; i += 1) {
      (function (button) {
        button.addEventListener("click", function () {
          navigate("#/feature/" + button.getAttribute("data-feature"));
        });
      })(entries[i]);
    }
  }

  function initSpots() {
    var configSpots = (CFG && CFG.spots) || {};
    SPOT_ORDER.forEach(function (spotId) {
      var button = homeHotspot(spotId);
      if (!button) {
        return;
      }
      var spotConfig = configSpots[spotId];
      if (spotConfig) {
        if (typeof spotConfig.x === "number") {
          button.style.setProperty("--x", spotConfig.x + "%");
        }
        if (typeof spotConfig.y === "number") {
          button.style.setProperty("--y", spotConfig.y + "%");
        }
        if (spotConfig.side === "left" || spotConfig.side === "right") {
          button.setAttribute("data-side", spotConfig.side);
        }
      }
      if (!HOME_FEATURE_BY_SPOT[spotId]) {
        button.addEventListener("click", function () {
          activateSpot(spotId);
        });
      }
    });
    buildSpotList();
  }

  function buildSpotList() {
    var list = $("spot-list");
    if (!list) {
      return;
    }
    list.textContent = "";
    var entries = [
      { kind: "feature", id: "2", name: "执行异常", detail: "车辆反馈" },
      { kind: "feature", id: "3", name: "异常事件", detail: "巡检发现" },
      { kind: "feature", id: "5", name: "巡迹地图", detail: "固定预设地图" }
    ];
    entries.forEach(function (entry) {
      var button = h("button");
      button.type = "button";
      if (entry.kind === "feature") {
        button.setAttribute("data-feature", entry.id);
      } else {
        button.setAttribute("data-spot", entry.id);
      }
      button.setAttribute("aria-controls", "side-panel");
      button.setAttribute("aria-expanded", "false");
      button.appendChild(h("strong", null, entry.name));
      button.appendChild(h("span", null, entry.detail));
      button.addEventListener("click", function () {
        if (entry.kind === "feature") {
          navigate("#/feature/" + entry.id);
        } else {
          activateSpot(entry.id);
        }
      });
      list.appendChild(button);
    });
  }

  var layoutFrame = 0;

  function scheduleHotspotLayout() {
    if (layoutFrame) {
      return;
    }
    layoutFrame = window.requestAnimationFrame(function () {
      layoutFrame = 0;
      layoutHotspots();
    });
  }

  function layoutHotspots() {
    var width = els.sceneMedia.offsetWidth;
    var height = els.sceneMedia.offsetHeight;
    if (!width || !height) {
      return;
    }
    var size = (CFG && CFG.assetSize) || { w: 1672, h: 941 };
    if (els.sceneImg && els.sceneImg.naturalWidth && els.sceneImg.naturalHeight) {
      size = { w: els.sceneImg.naturalWidth, h: els.sceneImg.naturalHeight };
    }
    if (!size.w || !size.h) {
      return;
    }
    var scale = Math.max(width / size.w, height / size.h);
    var renderedWidth = size.w * scale;
    var renderedHeight = size.h * scale;
    var offsetX = (width - renderedWidth) / 2;
    var offsetY = (height - renderedHeight) / 2;
    var configSpots = (CFG && CFG.spots) || {};

    SPOT_ORDER.forEach(function (spotId) {
      var spot = configSpots[spotId];
      if (!spot) {
        return;
      }
      var button = homeHotspot(spotId);
      if (!button) {
        return;
      }
      var x = offsetX + (spot.x / 100) * renderedWidth;
      var y = offsetY + (spot.y / 100) * renderedHeight;
      button.style.setProperty("--x", x + "px");
      button.style.setProperty("--y", y + "px");
    });
  }

  function activateSpot(spotId) {
    if (state.pendingTimer) {
      window.clearTimeout(state.pendingTimer);
      state.pendingTimer = null;
    }
    if (state.route.view !== "scene" && state.route.spot === spotId) {
      state.focusSpotOnScene = true;
      navigate("#/scene");
      return;
    }

    state.lastSpot = spotId;
    var button = document.querySelector('.hotspot[data-spot="' + spotId + '"]');
    if (!button) {
      return;
    }

    if (window.matchMedia && window.matchMedia("(max-width: 900px)").matches) {
      navigate("#/scene/" + spotId);
      return;
    }

    if (!els.sceneImg || !els.sceneImg.naturalWidth) {
      navigate("#/scene/" + spotId);
      return;
    }

    if (reducedMotion.matches || isStatic()) {
      navigate("#/scene/" + spotId);
      return;
    }

    if (state.burstTimer) {
      window.clearTimeout(state.burstTimer);
    }
    var bursting = document.querySelectorAll(".hotspot.is-bursting");
    for (var i = 0; i < bursting.length; i += 1) {
      bursting[i].classList.remove("is-bursting");
    }
    button.classList.add("is-bursting");
    state.burstTimer = window.setTimeout(function () {
      button.classList.remove("is-bursting");
      state.burstTimer = null;
    }, 760);

    state.pendingTimer = window.setTimeout(function () {
      state.pendingTimer = null;
      navigate("#/scene/" + spotId);
    }, 480);
  }

  function initSceneImage() {
    if (!els.sceneImg) {
      return;
    }
    if (els.sceneImg.complete && els.sceneImg.naturalWidth) {
      scheduleHotspotLayout();
    } else if (els.sceneImg.complete) {
      app.classList.add("asset-missing");
      if (els.sceneStamp) {
        els.sceneStamp.textContent = "场景图未加载 · 使用巡查点列表";
      }
    }

    /* The delivered art is the first paint.  The draft is only a fallback when
       the delivered asset is missing or fails to load.  Never silently fall
       back to the old scene-v2.png. */
    var DRAFT_SRC = "/static/scene-v2/assets/scene-draft.svg?v=20261018-v3";
    if (!CFG.asset) {
      app.setAttribute("data-asset", "draft");
      els.sceneImg.src = DRAFT_SRC;
      if (els.sceneStamp) {
        els.sceneStamp.textContent = "构图首稿 · 非最终素材";
      }
      return;
    }

    var url = CFG.asset + "?v=" + encodeURIComponent(CFG.assetVersion || "1");
    var probe = new Image();
    probe.onload = function () {
      els.sceneImg.src = url;
      els.sceneImg.hidden = false;
      app.setAttribute("data-asset", "delivered");
      if (els.sceneStamp) {
        els.sceneStamp.textContent = "正式场景图 · 虚构示意";
      }
      window.requestAnimationFrame(function () {
        scheduleHotspotLayout();
      });
    };
    probe.onerror = function () {
      /* Keep a usable committed draft and say so; never pretend the delivered asset exists. */
      app.setAttribute("data-asset", "pending");
      els.sceneImg.src = DRAFT_SRC;
      if (els.sceneStamp) {
        els.sceneStamp.textContent = "正式图未加载 · 使用构图首稿";
      }
      toast("正式场景图未加载，当前仍是构图首稿；热点按首稿坐标标定。", true);
    };
    probe.src = url;
  }

  /* --------------------------------------------------------------- events */

  function onKeydown(event) {
    if (event.key === "Escape") {
      if (state.helpOpen) {
        event.preventDefault();
        closeHelp();
        return;
      }
      var voicePop = $("voice-pop");
      if (voicePop && !voicePop.hidden) {
        event.preventDefault();
        if (window.VelaVoice) {
          window.VelaVoice.close();
        }
        return;
      }
      if (!els.assistantSheet.hidden) {
        if (event.target === els.chatInput) {
          els.chatInput.blur();
          return;
        }
        event.preventDefault();
        closeSheet();
        return;
      }
      if (app.getAttribute("data-panel") === "open") {
        event.preventDefault();
        goUp();
      }
    }
  }

  function initChatEvents() {
    els.chatForm.addEventListener("submit", function (event) {
      event.preventDefault();
      sendMessage();
    });

    els.chatInput.addEventListener("input", updateCount);
    els.chatInput.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        sendMessage();
      }
    });

    els.sheetClose.addEventListener("click", closeSheet);
    els.tokenSave.addEventListener("click", saveToken);
    els.tokenClear.addEventListener("click", clearToken);
    els.tokenInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        saveToken();
      }
    });
  }

  function init() {
    var splash = document.getElementById("boot-splash");
    function hideSplash() {
      if (splash && splash.parentNode) {
        splash.style.opacity = "0";
        window.setTimeout(function () {
          if (splash.parentNode) {
            splash.remove();
          }
        }, 220);
      }
    }
    if (document.readyState === "complete") {
      window.setTimeout(hideSplash, 260);
    } else {
      window.addEventListener("load", function () {
        window.setTimeout(hideSplash, 260);
      }, { once: true });
      window.setTimeout(hideSplash, 6000);
    }
    els.panel = $("side-panel");
    els.panelContent = $("panel-content");
    els.servicePill = $("service-pill");
    els.serviceText = $("service-text");
    els.staticToggle = $("static-toggle");
    els.staticLabel = $("static-label");
    els.helpToggle = $("help-toggle");
    els.helpModal = $("help-modal");
    els.helpCard = $("help-card");
    els.helpOk = $("help-ok");
    els.assistantSheet = $("assistant-sheet");
    els.sheetClose = $("sheet-close");
    els.transcript = $("transcript");
    els.chatState = $("chat-state");
    els.tokenDetails = $("token-details");
    els.tokenInput = $("token-input");
    els.tokenSave = $("token-save");
    els.tokenClear = $("token-clear");
    els.tokenState = $("token-state");
    els.chatForm = $("chat-form");
    els.chatInput = $("chat-input");
    els.dock = $("dock");
    els.dockHome = document.createComment("home composer position");
    els.dock.parentNode.insertBefore(els.dockHome,els.dock);
    els.charCount = $("char-count");
    els.sendButton = $("send-button");
    els.voiceBtn = $("voice-btn");
    els.sceneMedia = $("scene-media");
    els.sceneImg = $("scene-img");
    els.sceneStamp = $("scene-stamp");
    els.toast = $("toast");
    els.live = $("live");
    els.perf = $("perf");
    els.perfText = $("perf-text");

    state.conversationId = storageGet("velaSceneConversationId") || null;
    initToken();
    initStatic();
    initSpots();
    initFeatureEntries();
    initSceneImage();
    scheduleHotspotLayout();
    if (els.sceneImg) {
      els.sceneImg.addEventListener("load", scheduleHotspotLayout);
      els.sceneImg.addEventListener("error", function () {
        app.classList.add("asset-missing");
        if (els.sceneStamp) {
          els.sceneStamp.textContent = "场景图未加载 · 使用巡查点列表";
        }
      });
    }
    initChatEvents();
    initVoice();
    initVoiceInbox();
    checkHealth();
    initPerf();
    updateCount();

    if (!window.location.hash) {
      window.history.replaceState(null, "", "#/scene");
    }
    renderRoute({ focusPanel: false });

    window.addEventListener("hashchange", function () {
      renderRoute({ focusPanel: true });
    });
    document.addEventListener("keydown", onKeydown);
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("resize", scheduleHotspotLayout);
    window.addEventListener("orientationchange", scheduleHotspotLayout);

    els.staticToggle.addEventListener("click", function () {
      applyStatic(isStatic() ? "off" : "on");
    });
    els.helpToggle.addEventListener("click", openHelp);
    els.helpOk.addEventListener("click", closeHelp);
    var helpClosers = document.querySelectorAll("[data-close-help]");
    for (var i = 0; i < helpClosers.length; i += 1) {
      helpClosers[i].addEventListener("click", closeHelp);
    }
    els.voiceBtn.addEventListener("click", toggleVoice);

    if (reducedMotion.addEventListener) {
      reducedMotion.addEventListener("change", function () {
        if (reducedMotion.matches) {
          toast("已跟随系统“减少动效”偏好；仍可用静态展示手动暂停。");
        }
      });
    }
  }

  init();
})();

(function initLiveWater() {
  var canvas = document.getElementById("scene-water");
  var media = document.getElementById("scene-media");
  var app = document.getElementById("v2-app");
  if (!canvas || !media || !app || !window.Path2D || !window.VelaWaterArt) return;
  var ctx = canvas.getContext("2d");
  if (!ctx) return;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var raf = 0, last = 0, width = 0, height = 0;
  var water = new Path2D("M730-100C460 120 1110 220 790 380S400 480 160 580L-100 700V1100H1700V-100Z");
  var bank = new Path2D("M1120-100H1700V530C1510 520 1370 526 1240 500C1080 466 940 470 730 566L690 530L660 476C842 440 980 398 1040 340C1100 282 1080 190 1120-100Z");
  var dam = new Path2D("M-80 549Q400 286 955 435L1050 650L1030 799Q500 900-80 910Z");
  var spill = new Path2D("M389 635L475 615 513 691 676 768 558 799 405 715Z M580 616L670 612 713 678 890 743 782 770 612 706Z M770 619L846 635 887 709 1030 762 958 782 802 717Z");
  // Compute contour topology once; each frame only deforms cached vertices.
  var shapes = window.VelaWaterArt.geometry();
  var colors = [["#59f6eb","#1db4ec","#1d49ba"],["#a2fff1","#32d5ef","#2058cb"],["#d3fff4","#5bf2ed","#2368d5"],["#defff8","#7df5ef","#2368d5"]];
  var opacity = [[.50,.17,.025],[.72,.23,.02],[.90,.22,.005],[.66,0,0]];
  function point(p,t) {
    var d=.55+p[1]/1400;
    return [p[0]+Math.sin(p[0]*.013+p[1]*.009+t*.58)*6*d,
      p[1]+Math.cos(p[0]*.008-p[1]*.012+t*.49)*2.6*d];
  }
  function reflectionGradient(i) {
    var g=ctx.createLinearGradient(0,0,0,1000);
    [0,.48,1].forEach(function(at,j){
      var c=colors[i][j],n=parseInt(c.slice(1),16);
      g.addColorStop(at,"rgba("+(n>>16)+","+((n>>8)&255)+","+(n&255)+","+opacity[i][j]+")");
    });return g;
  }
  function allowed() { return !document.hidden && app.getAttribute("data-static") !== "on" && app.getAttribute("data-hidden") !== "true" && app.getAttribute("data-panel") !== "open" && !reduce.matches; }
  function resize() {
    var b = media.getBoundingClientRect();
    width = canvas.width = Math.max(1, Math.round(b.width * .5));
    height = canvas.height = Math.max(1, Math.round(b.height * .5));
  }
  function draw(now) {
    ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,width,height);
    var scale = Math.max(width / 1600, height / 900);
    ctx.setTransform(scale,0,0,scale,(width-1600*scale)/2,(height-900*scale)/2);
    ctx.scale(1,.9); ctx.save(); ctx.clip(water);
    var t = now / 1000;
    var base=ctx.createLinearGradient(650,0,800,1000);
    [[0,"#21e2ec"],[.22,"#05b8ed"],[.47,"#067af0"],[.7,"#1246cb"],[1,"#071b89"]].forEach(function(s){base.addColorStop(s[0],s[1]);});
    ctx.fillStyle=base;ctx.fillRect(0,0,1600,1000);
    shapes.forEach(function(polygons,layer) {
      ctx.beginPath();
      polygons.forEach(function(poly) {
        var q=poly.map(function(p){return point(p,t);}),n=q.length;
        ctx.moveTo((q[n-1][0]+q[0][0])/2,(q[n-1][1]+q[0][1])/2);
        for(var i=0;i<n;i++) {
          var p=q[i],next=q[(i+1)%n];
          ctx.quadraticCurveTo(p[0],p[1],(p[0]+next[0])/2,(p[1]+next[1])/2);
        }ctx.closePath();
      });
      ctx.fillStyle=reflectionGradient(layer);ctx.fill("evenodd");
    });
    ctx.restore();
    // Exact land exclusion: reflections can never paint over bank, dam or outlet.
    ctx.globalCompositeOperation="destination-out";ctx.fill(bank);
    ctx.save();ctx.translate(-90,140);ctx.scale(.84,.84);ctx.fill(dam);ctx.fill(spill);ctx.restore();
    ctx.globalCompositeOperation="source-over";
  }
  function frame(now) {
    if (!allowed()) { raf=0;return; }
    raf=requestAnimationFrame(frame);
    if(now-last < 1000/12) return;
    last=now;draw(now);
  }
  function sync() {
    if(!allowed()) { cancelAnimationFrame(raf);raf=0;ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,width,height); }
    else if(!raf) { last=0;raf=requestAnimationFrame(frame); }
  }
  resize();new ResizeObserver(resize).observe(media);
  new MutationObserver(sync).observe(app,{attributes:true,attributeFilter:["data-static","data-hidden","data-panel"]});
  reduce.addEventListener("change",sync);document.addEventListener("visibilitychange",sync);sync();
}());
