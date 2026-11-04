(function (global) {
  "use strict";

  function isoAgo(minutes) {
    return new Date(Date.now() - minutes * 60000).toISOString();
  }

  function entry(minutes, actor, text, kind) {
    return { at: isoAgo(minutes), actor: actor, text: text, kind: kind || "note" };
  }

  function makeWorkOrders() {
    return [
      {
        id: "WO-DEMO-011",
        title: "坝下巡查便道：临时围挡倒伏",
        location: "大坝 · 下游巡查便道",
        area: "downstream",
        status: "closed",
        priority: "常规",
        source: "本地示例数据",
        createdAt: isoAgo(355),
        updatedAt: isoAgo(210),
        summary:
          "巡查记录显示便道一侧临时围挡倒伏，占用半幅通行宽度。需要人工扶正并确认固定，复查时还要看通道是否恢复。",
        task: "现场处理并补拍固定点近景与通道全景；复查只判断证据是否足够，不代替现场安全评估。",
        evidence: [
          {
            label: "巡查记录（示例）",
            detail: "围挡倒伏约 2 米，未见人员受伤；当时仅记录，没有移动围挡。",
            at: isoAgo(350),
            source: "本地示例记录"
          },
          {
            label: "现场照片（示例占位）",
            detail: "本地示例不含真实照片。处理与复查都要求重新拍摄，占位图不能作为证据。",
            at: isoAgo(350),
            source: "占位，不是证据"
          }
        ],
        history: [
          entry(350, "示例巡查", "创建示例工单，状态为待处理。", "created"),
          entry(320, "示例操作者", "提交处理：围挡已扶正，并加临时固定。", "process"),
          entry(300, "示例复查人", "复查不合格，重新打开：照片未包含固定点，角度不足。", "verify_fail"),
          entry(260, "示例操作者", "重新提交处理：补充固定点近景与通道全景。", "process"),
          entry(240, "示例复查人", "复查合格，销项。记录保留前后证据。", "verify_pass")
        ],
        verifyAttempts: 2,
        reopened: true
      },
      {
        id: "WO-DEMO-017",
        title: "坝顶防浪墙内侧积水与警示牌倾斜",
        location: "大坝 · 坝顶巡查段 K0+180",
        area: "crest",
        status: "open",
        priority: "需现场判断",
        source: "本地示例数据",
        createdAt: isoAgo(38),
        updatedAt: isoAgo(38),
        summary:
          "巡查记录显示防浪墙内侧有一片积水，警示牌向内侧倾斜。需要人工到现场判断排水口是否堵塞，并把警示牌扶正。",
        task: "沿坝顶步道行走，不翻越护栏、不探身到临水侧。先看排水口，再处理警示牌；处理说明里写清是否仍影响通行。",
        evidence: [
          {
            label: "巡查记录（示例）",
            detail: "K0+180 路面见积水约 2 米，警示牌倾斜约 15°，未见护栏破损。",
            at: isoAgo(41),
            source: "本地示例记录"
          },
          {
            label: "现场照片（示例占位）",
            detail: "本地示例不含真实照片；现场处理时需补拍积水位置和警示牌同一角度。",
            at: isoAgo(41),
            source: "占位，不是证据"
          }
        ],
        history: [entry(38, "示例巡查", "创建示例工单，等待人工处理。", "created")],
        verifyAttempts: 0,
        reopened: false
      },
      {
        id: "WO-DEMO-021",
        title: "下游观察点岸坡冲刷痕迹复核",
        location: "大坝 · 下游观察点步道",
        area: "downstream",
        status: "open",
        priority: "需人工判断",
        source: "本地示例数据",
        createdAt: isoAgo(72),
        updatedAt: isoAgo(72),
        summary:
          "巡查记录提到下游步道外侧有冲刷痕迹，不能仅凭这一条记录判断岸坡是否安全。需要人工远观、拍照并标记位置，必要时转交水利专业人员。",
        task: "只从步道内侧观察，不靠近临水边缘，不进入河道。记录冲刷范围与参照物；无法判断时选择复查不合格并说明原因。",
        evidence: [
          {
            label: "巡查记录（示例）",
            detail: "下游观察点外侧约 3 米范围见浅色冲刷痕迹，未见明显塌陷；未靠近边缘。",
            at: isoAgo(75),
            source: "本地示例记录"
          },
          {
            label: "现场照片（示例占位）",
            detail: "本地示例不含真实照片。需要包含参照物和拍摄方向，避免只拍局部。",
            at: isoAgo(75),
            source: "占位，不是证据"
          }
        ],
        history: [entry(72, "示例巡查", "创建示例工单，等待人工判断。", "created")],
        verifyAttempts: 0,
        reopened: false
      }
    ];
  }

  function makePlan() {
    return {
      title: "大坝坝顶与下游观察点巡查",
      route: "坝顶巡查线（示例）",
      zone: "大坝 · 水利场景",
      checks: ["坝顶路面积水", "防浪墙与警示牌", "下游岸坡冲刷痕迹"],
      version: 2,
      createdAt: isoAgo(15),
      status: "pending",
      decidedAt: null,
      note: "示例计划只保存在本页。确认只表示接受这个计划版本，不会下发设备。"
    };
  }

  function createState() {
    return {
      plan: makePlan(),
      workorders: makeWorkOrders(),
      selectedId: "WO-DEMO-017",
      fieldNodeId: "crest",
      messages: [],
      events: [
        {
          at: isoAgo(180),
          type: "load",
          woId: null,
          text: "载入本地示例数据；未连接生产系统，也不会控制设备。"
        }
      ]
    };
  }

  function reset(state) {
    var next = createState();
    state.plan = next.plan;
    state.workorders = next.workorders;
    state.selectedId = next.selectedId;
    state.fieldNodeId = next.fieldNodeId;
    state.events = next.events;
    state.messages.length = 0;
  }

  function replyFor(message) {
    var text = String(message || "");
    if (/工单|复查|销项|待我处理/.test(text)) {
      return "示例助手：示例工单在「待我处理」。流程是查看证据 → 提交处理 → 待复查 → 复查合格销项或不合格重开。提交处理不等于合格，所有记录只在本页。";
    }
    if (/计划|确认|提案|批准/.test(text)) {
      return "示例助手：右侧有一份本地示例计划。确认只记录审批，不会执行。真实模式里这部分由巡查助手核对登记表后生成。";
    }
    if (/坝|水库|河|岸|水|警示|渗/.test(text)) {
      return "示例助手：已把目标整理成大坝坝顶与下游观察点的草案。这是本地规则回复，不调用云，也不会创建生产计划。真实能力仍以登记路线和车辆为准，不自动判断坝体安全或水质。";
    }
    if (/路线|能力|车辆|登记|能做什么/.test(text)) {
      return "示例助手：示例里有坝前水域、坝顶入口、坝顶巡查段、下游观察点四个逻辑节点，但位置只是示意，没有定位、水位、雨量或车辆遥测。真实模式会先核对登记表，没有数据就直说。";
    }
    return "示例助手：收到。示例体验只演示任务、工单、现场和复盘界面，不连接远端模型，也不写入生产系统。你可以点上方场景模板填入真实模式草案，或去「待我处理」走一遍大坝工单闭环。";
  }

  global.VelaDemo = {
    createState: createState,
    reset: reset,
    replyFor: replyFor,
    nowIso: function () {
      return new Date().toISOString();
    },
    makeEntry: function (actor, text, kind) {
      return {
        at: new Date().toISOString(),
        actor: actor,
        text: text,
        kind: kind || "note"
      };
    }
  };
})(window);
