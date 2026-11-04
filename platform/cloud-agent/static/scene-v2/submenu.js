/* VelaGuard feature 2–7 submenus.
 * Read-only UI; no device/mission mutations and no implicit backend requests.
 * Source-of-truth records require an explicitly installed, audited provider.
 */
(function () {
  "use strict";

  var DATA = {
    "2": {title:"执行异常", lead:"车辆状态变化 → 未完成任务 → 重规划候选 → 停止及授权确认 → 任务接续", tabs:[
      {id:"vehicles", name:"车辆状态", eyebrow:"FLEET / TELEMETRY", desc:"区分设备登记、实际遥测与不同通信链路。车队快照不等于实时遥测。", fields:["车辆ID / 登记来源","任务ID及执行状态","电量 / 观测时间 / 数据来源","位置 / 坐标系 / 位姿时间","互联网连接 / 平台链路 / 车控链路"], rules:["只有已校验来源与观测时间的车辆数据才可显示为实时。","缺失的电量、坐标系和通信链路分别显示未提供，不补零。","过期或未知状态不能自动用于新的执行授权。"], action:"请求实时车辆状态"},
      {id:"faults", name:"执行异常", eyebrow:"EXECUTION / INCIDENT", desc:"记录低电量、故障、失联、中止等执行侧事件及受影响的任务。", fields:["异常ID / 车辆ID / 类型","发生时间 / 来源及状态版本","受影响任务及已完成部分","最后命令状态及回执","异常处理与人工接管记录"], rules:["必须区分状态变化与事件已获确认。","完成任务与冻结项不得作为可重派任务。","断线及回执缺失维持未知状态，不推定车辆已停车。"], action:"确认故障及锁定任务"},
      {id:"handoff", name:"任务接续", eyebrow:"RESCHEDULE / SAFETY", desc:"剩余任务经安全过滤后形成重规划候选；不等于直接执行。", fields:["原计划ID / 版本 / 已完成及冻结任务","未完成任务及重规划前后归属","LOCAL_REPLAN / GLOBAL_REPLAN / HUMAN_REQUIRED","候选计划版本 / PROPOSAL_ONLY","STOP_REQUESTED / STOP_CONFIRMED / 拒绝理由"], rules:["严格词典序：优先级覆盖 → 能耗 → 计划变更成本 → 完成时间。","PROPOSAL_ONLY 只是候选，必须由权威账本独立授权。","STOP_REQUESTED 不等于 STOP_CONFIRMED；状态未知时维持锁定。","PENDING / DISPATCHING 不得绕过发送意图、版本与授权检查。"], action:"授权并接续任务"}
    ]},
    "3": {title:"异常事件", lead:"现场证据 → 边缘风险与不确定性U → 观察 / 升级 / 紧急人工介入 → 复核", tabs:[
      {id:"pending", name:"待处理", eyebrow:"EVENT / QUEUE", desc:"待处理异常按来源与风险依据展示；高风险先请求人工，不等诊断简报。", fields:["事件ID / revision / 事件版本","时间 / 位置 / 来源 / 证据图像","事件类型 / 紧急度 / 处理等级","AHP-Sugeno风险结果 / 不确定性U","视觉识别置信度（独立于风险评分）"], rules:["五因素 AHP-Sugeno 的风险评分与视觉置信度必须分栏。","证据缺失、质量低或时效不足时，不得当成低风险。","模型/规则/数据版本明确展示；旧spine-v2与新v3独立标注。"], action:"接单并处理"},
      {id:"archive", name:"事件记录", eyebrow:"EVIDENCE / HISTORY", desc:"以事件ID和revision组织真实证据记录，不自动合并不同版本。", fields:["事件ID / revision / policy_version","原始图像或证据引用 / 采集来源","风险判断 / 证据质量 / U","旧v2或新v3协议标识","观察 / 升级 / 告警回执"], rules:["未接生产事件源时不虚构历史事件。","回放事件必须显示来源与“回放”，不能标实时。","新v3生产持久化与AIoT协议未验收，不能映射成已完成闭环。"], action:"导出真实事件记录"},
      {id:"review", name:"处理与复核", eyebrow:"HUMAN / REVIEW", desc:"接单 → 处置记录 → 人工复核 → 关闭，需真实回执推进。", fields:["事件ID / revision / 操作人","接单与人工签名凭证状态","处置依据 / 处理时间","复核结论 / 关联任务","告警ACK / 关闭回执"], rules:["人工操作必须以实际版本和签名校验为准。","没有真实后端回执，不把按钮点击当成已处理。","既有高风险锁存不能因后续低分自动撤销。"], action:"提交处置并关闭"}
    ]},
    "4": {title:"云端自检", lead:"关联事件事实 → 知识检索 → 证据缺口 → 候选处置方案 → 人工确认", tabs:[
      {id:"pending", name:"待研判", eyebrow:"CLOUD / INBOX", desc:"接收真实事件ID与revision，保留来源、风险依据和证据缺口。", fields:["关联事件ID / revision / 原始来源","现场事实与证据时间","边缘风险评分 / 不确定性U","升级原因及待补充证据","请求协议 / 模型及规则版本"], rules:["仅有事件关联标识不意味着诊断已运行。","高紧急度事件优先人工介入，诊断简报后补。","旧版AIoT告警不等于新v3诊断输入已接通。"], action:"发起知识库诊断"},
      {id:"reports", name:"诊断简报", eyebrow:"KNOWLEDGE / REPORT", desc:"检索出处和版本可追溯；事实、推断与未知信息必须明确区分。", fields:["关联事件ID / revision","知识库出处 / 检索版本 / 时间","事实与推断分别列示","诊断依据 / 证据不足","模型及工具调用真实记录"], rules:["普通/api/chat文本不能冒充知识库检索或诊断报告。","缺少可靠出处不得给出水利安全鉴定。","新v3平台诊断未验收；仅展示实际证据。"], action:"确认诊断结果"},
      {id:"plans", name:"处置方案", eyebrow:"RECOMMENDATIONS / APPROVAL", desc:"候选方案仅供人员审查；补拍任务须回到任务系统待确认。", fields:["关联事件ID / revision","候选处置方案与适用条件","潜在风险 / 复核要求","补拍或补证的待确认任务","人工审批 / 任务账本版本"], rules:["诊断建议不自动形成机器人运动命令。","补拍建议进入待确认任务，经合法性检查和授权后才可能执行。","没有签名、账本和执行回执时一律不得显示执行成功。"], action:"批准处置并发车"}
    ]},
    "5": {title:"巡迹地图", lead:"预设资源与版本 ≠ 候选路线 ≠ 实际上报轨迹", tabs:[
      {id:"maps", name:"预设地图", eyebrow:"MAP / CATALOG", desc:"只展示经过登记的预设地图和版本；不使用场景美术图冒充实际地理测绘。", fields:["地图资源ID / 版本 / 来源","分区定义 / 坐标系 / 有效范围","站点或巡检点的登记来源","候选路线的来源和计划版本","与车辆ID的真实映射"], rules:["S1左岸、S2右岸、S3机房为项目方案分区口径，不是任意车辆映射。","当前V11资源必须核验后才可标记为已登记地图。","预设示意线不能冒充已执行行驶轨迹。"], action:"下发预设路线"},
      {id:"tracks", name:"本轮轨迹", eyebrow:"TRACK / OBSERVATION", desc:"实际轨迹必须关联巡检轮次、车辆、时间与坐标系。", fields:["轮次ID / 车辆ID / 来源","上报坐标与坐标系","定位时间 / 观测新鲜度","实际轨迹采样点及缺测区间","候选路线与实测轨迹分别标注"], rules:["没有位置上报就只显示缺失状态，不模拟车辆运动。","不以固定路线历史实测推断本轮有实时轨迹。","轨迹来源属于回放时必须显著标注来源和回放时间。"], action:"回放真实轨迹"}
    ]},
    "6": {title:"巡检复盘", lead:"自然语言 → 结构化任务 → 候选分工 → 授权与执行回执 → 巡检复盘", tabs:[
      {id:"tasks", name:"结构化任务", eyebrow:"VOICE / TASKS", desc:"把真实语音转写与结构化字段关联，保留原始需求和人工确认边界。", fields:["语音转写原文 / 识别时间 / 来源","任务ID / revision / 计划版本","区域 / 点位 / 检查项 / 优先级","车辆限制 / 能量与可达性约束","待确认 / 已授权状态及来源"], rules:["语音识别成功不等于结构化任务已保存或派发。","首页不会恢复白色输入栏；功能1原自动发送链路保持不变。","无法读取平台结构化任务时显示空态，而不是抽取聊天文本充当授权任务。"], action:"确认结构化任务"},
      {id:"progress", name:"分工与进度", eyebrow:"ASSIGNMENT / LEDGER", desc:"将候选、授权、派发和实际执行回执分层呈现。", fields:["候选计划ID / 版本 / PROPOSAL_ONLY","优先级任务覆盖 / 延期任务","能耗 / 计划变更成本 / 完成时间","预算耗尽或不可行拒绝原因","账本授权 / 派发 / 执行回执与时间"], rules:["严格词典序，不用加权和跨级抵消。","最多8个候选任务、4辆候选车；S1/S2/S3每波各最多一项，S4不获真实执行授权。","求解预算用尽时不得声称无条件全局最优。","没有账本授权与车端回执，候选不得标记为已执行。"], action:"批准并下发候选"},
      {id:"recap", name:"巡检复盘", eyebrow:"RECAP / EVIDENCE", desc:"按轮次关联任务、异常、交接与人工复核，只统计有来源的实绩。", fields:["巡检轮次与数据来源","已完成 / 未完成任务的真实回执","重分工前后归属与停止确认","事件ID / revision / 处理与复核","实测耗时 / 行驶距离 / 重排耗时"], rules:["所有性能数值需有真实记录；缺失不填零。","项目组确认车端实验完成，细节仍以具体日志核对。","旧v2告警回放不能被标注为新v3完整诊断闭环。"], action:"确认轮次复盘"}
    ]},
    "7": {title:"Gemini-S1", lead:"正在实际处理的工具请求与端侧事件，而非固定轮播的能力演示", tabs:[
      {id:"activity", name:"正在做什么", eyebrow:"EDGE / ACTIVITY", desc:"真实端侧时间线：接任务、调用原生工具、候选待授权、投递告警及等待回执。", fields:["活动记录ID / 时间戳 / 来源","当前工具名称与真实请求ID","任务 / 事件ID及revision","执行阶段 / 候选或等待回执","原生结果及失败理由"], rules:["没有实际工具记录不能显示为正在运行。","13个Skill完整加载属于既有工程记录，不等于此刻正在调用。","端侧工具结果必须以真实原生调用证据为准。"], action:"向设备发出新指令"},
      {id:"tools", name:"算法与工具", eyebrow:"NATIVE / ALGORITHMS", desc:"区分真板算法能力与当前实际工具调用记录。", fields:["工具请求ID / policy_version / 时间","真实输入摘要 / 来源和约束","原生求解结果 / 统计 / 预算","任务分配、局部/全局重规划及风险工具","AHP-Sugeno风险评分与独立不确定性U"], rules:["算法排序：优先级覆盖 → 能耗 → 计划变更成本 → 完成时间。","五因素AHP-Sugeno权重有CI/CR一致性检查，规则至多24条；不填造因素名或权重。","S1/S2/S3波次约束与最多8任务/4候选车是PDF口径，仍须逐接口核对。","PROPOSAL_ONLY 不是授权，视觉识别置信度不是风险分数。"], action:"调用原生算法"},
      {id:"health", name:"设备与链路", eyebrow:"DEVICE / LINK", desc:"Gemini-S1在线、云端和车辆控制链路应分别以真实心跳与遥测证明。", fields:["设备ID / 运行环境及版本","设备心跳时间 / 观测来源","云端链路 / 车辆链路（分别）","CPU / 内存 / 温度及采集时间","Agent与业务工具的实际注册信息"], rules:["设备登记表和功能介绍不能证明设备在线。","没有采集时间或心跳就显示未验证，不猜CPU/温度。","真板验证不代表新v3平台协议及物理停车细项全部验收。"], action:"控制设备或重启Agent"}
    ]}
  };

  function el(tag, css, txt) { var n=document.createElement(tag); if(css) n.className=css; if(txt!==undefined) n.textContent=String(txt); return n; }
  function btn(css, text, click) { var b=el("button",css,text); b.type="button"; if(click) b.addEventListener("click",click); return b; }
  function qp(s) { return encodeURIComponent(String(s)); }
  function safeName(x) { return typeof x==="string" && /^[\w.:-]{1,96}$/.test(x) ? x : ""; }
  function linkFor(fid, tab, kind, key) { var h="#/feature/"+fid+"/"+tab; return kind ? h+"/"+kind+"/"+qp(key) : h; }
  function navigate(hash) { if(location.hash===hash) mountLast(); else location.hash=hash; }
  var LAST=null, serial=0;
  function mountLast() { if(LAST && LAST.host && LAST.host.isConnected) mount(LAST.feature,LAST.host); }
  function route(fid) {
    var raw=(location.hash||"").split("?")[0].replace(/^#\//,"").split("/");
    var spec=DATA[fid], tab=spec.tabs.some(function(t){return t.id===raw[2]})?raw[2]:spec.tabs[0].id;
    var kind=raw[3]==="guide"||raw[3]==="record"?raw[3]:"";
    var key=""; try { key=decodeURIComponent(raw[4]||""); } catch(e) { key=""; }
    var qs=(location.hash||"").split("?")[1]||"", search=new URLSearchParams(qs);
    return {tab:tab,kind:kind,key:key,event:safeName(search.get("event_id")),revision:safeName(search.get("revision"))};
  }
  function emptyMessage(tab) { return "没有可核验的「"+tab.name+"」数据。当前未接入对应生产数据源；请勿将页面说明当作实时记录。"; }
  function provider() { return window.VelaSubmenuProvider && typeof window.VelaSubmenuProvider.load==="function" ? window.VelaSubmenuProvider : null; }
  function head(text, subtype) { var n=el("p","submenu-kicker",text); if(subtype)n.classList.add(subtype); return n; }
  function chip(value, kind) { return el("span","submenu-chip "+(kind||""),value); }

  function mount(feature, panel) {
    var fid=String(feature), spec=DATA[fid]; if(!spec)return false;
    LAST={feature:fid,host:panel}; var generation=++serial, state=route(fid);
    var tab=spec.tabs.filter(function(t){return t.id===state.tab})[0];
    var body=el("section","submenu-root"); body.setAttribute("aria-label",spec.title+"子菜单");
    body.appendChild(head("VELAGUARD / FUNCTION "+fid));
    var heading=el("div","submenu-intro");
    var title=el("h3",null,spec.title+" · "+tab.name); heading.appendChild(title);
    heading.appendChild(el("p",null,spec.lead)); body.appendChild(heading);
    var nav=el("nav","submenu-tabs"); nav.setAttribute("aria-label",spec.title+"栏目");
    spec.tabs.forEach(function(t){var b=btn("submenu-tab"+(t.id===tab.id?" active":""),t.name,function(){navigate(linkFor(fid,t.id));});b.setAttribute("aria-current",t.id===tab.id?"page":"false");nav.appendChild(b);});
    body.appendChild(nav);
    var content=el("div","submenu-content"); body.appendChild(content);
    panel.appendChild(body);

    function topArea(){
      var info=el("div","submenu-topline");
      info.appendChild(chip(tab.eyebrow)); info.appendChild(chip("只读 · 未授权任何车辆动作","safety"));
      content.appendChild(info);
      if(state.event && fid==="4") {
        var context=el("div","submenu-context");
        context.appendChild(el("strong",null,"关联请求：事件 "+state.event+" / revision "+(state.revision||"未提供")));
        context.appendChild(el("p",null,"此处仅传递关联标识，不代表已取得事件证据或已发起诊断。"));
        context.appendChild(btn("submenu-mini-btn","返回事件",function(){navigate("#/feature/3/pending");}));
        content.appendChild(context);
      }
    }
    topArea();
    if(state.kind==="guide"){
      var guide=el("article","submenu-detail");
      guide.appendChild(btn("submenu-back","← 返回"+tab.name,function(){navigate(linkFor(fid,tab.id));}));
      guide.appendChild(el("h4",null,state.key==="rules"?"决策与安全边界":"字段与证据要求"));
      var items=state.key==="rules"?tab.rules:tab.fields;
      var list=el("ol","submenu-guidelines"); items.forEach(function(t){list.appendChild(el("li",null,t));});
      guide.appendChild(list); content.appendChild(guide); return true;
    }
    if(fid==="5" && tab.id==="maps") {
      var mapCard=el("section","preset-map-card");
      var mapHead=el("div","preset-map-head");
      var mapTitle=el("div");mapTitle.appendChild(el("h4",null,"V11 · 大坝巡检预设地图"));
      mapTitle.appendChild(el("p",null,"母图 5940 × 4200 mm · 原有设施与道路关系保留"));mapHead.appendChild(mapTitle);
      var controls=el("div","preset-map-controls");var zoom=1;
      var frame=el("div","preset-map-viewport");frame.tabIndex=0;frame.setAttribute("aria-label","V11预设地图，可滚动查看放大后的区域");
      var img=el("img","preset-map-image");img.src="/static/scene-v2/assets/v11-preset-map.svg?v=20261103-map1";img.alt="V11大坝场地预设图，包含上下岸道路、交通桥、工作闸桥、M1至M4、W等待点及A/B/C位置；不代表实时轨迹";
      function setZoom(next){zoom=Math.max(1,Math.min(3,next));frame.setAttribute("data-zoom",String(zoom));status.textContent=zoom===1?"适应全图":zoom===2?"放大 2 倍":"放大 3 倍";}
      controls.appendChild(btn("submenu-mini-btn","缩小",function(){setZoom(zoom-1);}));controls.appendChild(btn("submenu-mini-btn","放大",function(){setZoom(zoom+1);}));controls.appendChild(btn("submenu-mini-btn","恢复全图",function(){setZoom(1);frame.scrollLeft=0;frame.scrollTop=0;}));
      var status=el("span","preset-map-scale","适应全图");status.setAttribute("role","status");controls.appendChild(status);mapHead.appendChild(controls);mapCard.appendChild(mapHead);
      frame.setAttribute("data-zoom","1");frame.appendChild(img);mapCard.appendChild(frame);
      mapCard.appendChild(el("p","preset-map-note","预设场地示意 · 不是实时测绘或导航授权。图内中心线为母图道路标线，不是车辆已行驶轨迹。"));
      var originalLink=el("a","submenu-link","查看完整矢量地图");originalLink.href=img.src;originalLink.target="_blank";originalLink.rel="noopener";mapCard.appendChild(originalLink);
      content.appendChild(mapCard);return true;
    }
    var label=el("div","submenu-info"); label.appendChild(el("h4",null,tab.name));label.appendChild(el("p",null,tab.desc));content.appendChild(label);
    var stateEl=el("div","submenu-state"); stateEl.setAttribute("role","status"); stateEl.setAttribute("aria-live","polite"); content.appendChild(stateEl);
    var cardList=el("div","submenu-records"); content.appendChild(cardList);
    var guideArea=el("div","submenu-guides");
    [{name:"查看字段详情",key:"fields",copy:"所需字段与溯源要求"},{name:"查看流程与边界",key:"rules",copy:"授权、评分与证据约束"}].forEach(function(t){
      var b=btn("submenu-guide", "", function(){navigate(linkFor(fid,tab.id,"guide",t.key));});
      b.appendChild(el("strong",null,t.name));b.appendChild(el("small",null,t.copy));guideArea.appendChild(b);
    });content.appendChild(guideArea);
    var actionBox=el("div","submenu-action");
    var action=btn("submenu-disabled",tab.action); action.disabled=true;action.setAttribute("aria-describedby","submenu-action-reason");actionBox.appendChild(action);
    var reason=el("p",null,"未接入经验证的授权/业务回执接口，操作已禁用，点击页面不会提交车辆指令。"); reason.id="submenu-action-reason";actionBox.appendChild(reason);
    content.appendChild(actionBox);
    if(fid==="3"){
      var cross=btn("submenu-link","查看云端自检栏目 →",function(){navigate("#/feature/4/pending");});
      cross.title="未选择真实事件时仅打开云端栏目，不携带虚构事件ID";content.appendChild(cross);
    }
    if(fid==="4"){
      var cross2=btn("submenu-link","查看待确认结构化任务 →",function(){navigate("#/feature/6/tasks");}); content.appendChild(cross2);
    }
    if(fid==="6") {
      var cross3=btn("submenu-link","查看 Gemini-S1 工具栏目 →",function(){navigate("#/feature/7/tools");});content.appendChild(cross3);
    }

    function showState(kind, msg) {
      stateEl.textContent="";stateEl.className="submenu-state "+kind;
      stateEl.appendChild(chip(kind==="loading"?"正在加载":kind==="error"?"读取失败":kind==="offline"?"源端离线":kind==="stale"?"数据已过期":kind==="ready"?"已验证数据":kind==="empty"?"暂无记录":"数据源未接入",kind));
      stateEl.appendChild(el("p",null,msg));
    }
    function plain(value) { if(value===null||value===undefined||value==="")return "未提供";if(typeof value==="number" && Number.isFinite(value))return String(value);if(typeof value==="boolean")return value?"是":"否";if(typeof value==="string")return value.slice(0,700);return "未提供（需经过数据适配）"; }
    function renderRows(rows, dataset){
      cardList.textContent="";
      rows.slice(0,50).forEach(function(rec,index){
        if(!rec || typeof rec!=="object" || !safeName(rec.id))return;
        var id=safeName(rec.id);
        var box=el("article","submenu-record");
        box.appendChild(el("strong",null,plain(rec.title)||id));
        box.appendChild(el("p",null,plain(rec.summary)));
        var meta=el("p","submenu-meta","记录ID "+id+" · "+plain(dataset.source)+" · "+plain(dataset.observed_at));box.appendChild(meta);
        var open=btn("submenu-mini-btn","查看记录详情",function(){
          cardList.textContent="";var detail=el("div","submenu-record-detail");
          detail.appendChild(btn("submenu-back","← 返回列表",function(){renderRows(rows,dataset);}));
          detail.appendChild(el("h4",null,plain(rec.title)||id));
          var dl=el("dl","submenu-field-list");
          var pairs=rec.fields && typeof rec.fields==="object" && !Array.isArray(rec.fields)?Object.entries(rec.fields):[];
          pairs.slice(0,40).forEach(function(pair){dl.appendChild(el("dt",null,String(pair[0]).slice(0,80)));dl.appendChild(el("dd",null,plain(pair[1])));});
          if(!pairs.length){dl.appendChild(el("dt",null,"记录字段"));dl.appendChild(el("dd",null,"适配器尚未提供经过校验的字段"));}
          detail.appendChild(dl);detail.appendChild(el("p","submenu-meta","来源："+plain(dataset.source)+" · 观测："+plain(dataset.observed_at)+" · 模式："+plain(dataset.mode)));
          if(fid==="3" && safeName(rec.event_id) && safeName(rec.revision)){
            detail.appendChild(btn("submenu-link","携带事件ID/revision进入云端自检 →",function(){navigate("#/feature/4/pending?event_id="+qp(rec.event_id)+"&revision="+qp(rec.revision));}));
          }
          cardList.appendChild(detail);
        });
        box.appendChild(open);cardList.appendChild(box);
      });
      if(!cardList.children.length)showState("empty",emptyMessage(tab));
    }
    var source=provider();
    if(!source){showState("unconnected",emptyMessage(tab));return true;}
    showState("loading","正在从已配置的只读数据适配器检查记录。此状态不是车辆在线证明。");
    Promise.resolve().then(function(){return source.load({feature:fid,tab:tab.id,event_id:state.event||null,revision:state.revision||null});}).then(function(payload){
      if(serial!==generation || !content.isConnected)return;
      if(!payload || typeof payload!=="object") {showState("error","数据适配器未返回有效结构。");return;}
      var status=payload.status;
      if(status==="offline"||status==="error"||status==="disabled") {showState(status,payload.message?plain(payload.message):"数据源当前不可用；不展示未验证记录。");return;}
      if(status==="empty") {showState("empty",emptyMessage(tab));return;}
      if(status!=="ok"&&status!=="stale") {showState("error","未知数据状态，已拒绝展示。");return;}
      if(typeof payload.source!=="string"||!payload.source.trim() || !Array.isArray(payload.records) || !payload.mode || !payload.observed_at) {
        showState("error","来源、数据模式、时间或记录列表缺失，已拒绝展示。");return;
      }
      if(payload.mode!=="live"&&payload.mode!=="snapshot"&&payload.mode!=="replay"&&payload.mode!=="archive") {
        showState("error","数据模式非法，已拒绝展示。");return;
      }
      var date=Date.parse(payload.observed_at);
      if(!Number.isFinite(date)) {showState("error","数据时间格式不可验证，已拒绝展示。");return;}
      var expired=payload.expires_at && Number.isFinite(Date.parse(payload.expires_at)) && Date.parse(payload.expires_at)<Date.now();
      if(expired || status==="stale")showState("stale","记录已过期；仅供阅读，不能用于安全判断或执行授权。");
      else if(!payload.records.length)showState("empty",emptyMessage(tab));
      else showState("ready",(payload.mode==="replay"?"【回放】":payload.mode==="archive"?"【历史归档】":payload.mode==="snapshot"?"【快照】":"【实时来源标识】")+"来源："+payload.source+" · 观测："+payload.observed_at+"。标识来自数据源，实际时效须以端到端核验为准。");
      renderRows(payload.records,payload);
    }).catch(function(err){if(serial!==generation || !content.isConnected)return;showState("error","数据读取失败："+(err&&err.message?String(err.message).slice(0,160):"未知错误"));});
    return true;
  }

  window.VelaSubmenus={mount:mount,featureIds:Object.keys(DATA)};
})();
