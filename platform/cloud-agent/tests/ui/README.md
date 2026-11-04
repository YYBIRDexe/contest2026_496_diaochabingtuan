# 新版前端静态验证清单（Codex 执行）

当前 DSH 环境未运行 shell、未启动浏览器、未执行截图，因此本目录不是“已通过”的测试结果，而是交给已授权环境执行的静态与交互验证清单。

## 入口

- 页面：`http://<平台>:8130/`
- 文件：`platform/cloud-agent/static/index.html`、`styles.css`、`app.js`、`demo-data.js`、`assets/`
- 后端与接口无需改动；真实页面继续使用 `/api/health`、`/api/chat`、`/api/routes`、`/api/fleet`、`/api/capabilities`、`/api/proposals`、`/api/proposals/<id>/decision`。

## 建议自动/半自动检查

0. 静态结构（标准库，不启动浏览器）：`python3 tests/ui/check_static.py`。它只检查文件、ID、CSP 相关内联样式、demo 模块不发请求等静态条件，**不是浏览器或后端测试**。`tests/ui/check_static.py` 不匹配 `test*.py`，不会进入现有 unittest discover。

1. 静态资源：`GET /` 返回 200，CSP 仍为同源；`GET /static/styles.css`、`/static/app.js`、`/static/demo-data.js`、`/static/assets/water-scene.png`、`/static/assets/water-dam.svg` 均 200 且 MIME 正确。`water-scene.png` 约 1.9 MB，低于静态 5 MB 上限。
2. 真实空注册表：`/api/routes` 与 `/api/fleet` 为空时，任务中心“现场准备”显示待登记；现场页不出现路线节点、不出现虚构车辆；待我处理显示真实空态。
3. 真实云对话：health 为 configured 时只显示“可发起 · 本会话未验证”；实际发送成功后显示“本会话已收到云回复”；失败显示友好错误并保留输入，不出现 Key/环境变量。
4. 多轮会话：连续两轮请求使用同一 `conversation_id`；刷新按钮只重读 GET 接口，不创建计划。
5. 计划：`/api/proposals` 有待确认项时显示卡片；“确认计划（不执行）”调用 decision 后状态为已确认但仍未执行；重复点击被禁用；驳回可用。
6. 示例隔离：切换“示例体验”后，不产生任何写请求；模板只填草案不发送；示例聊天为本地规则；工单“开始处理→提交处理→待复查→复查合格销项/不合格重开”可走通；本地计划确认只改本地状态；退出示例后真实会话与真实数据仍在。
7. 视觉/视口：1920×1080、1280×800、窄屏无横向溢出；重点确认 1920 首屏输入框与发送按钮同屏、1280×800 至少助手入口清楚；224px 深蓝侧栏、白工作面、河流青主按钮、水纹背景、无校徽；页头 `water-scene.png` 裁切正常、可见“水利场景示意 · 非现场”，且不在工单证据区；触控按钮 ≥44px；中文长文案不截断关键信息。
8. 可访问性：Tab 焦点顺序；弹窗 Escape 关闭并归还焦点；示例条持续可见；减少动效偏好下信息不丢失。
9. 回归：不运行或修改后端测试；部署后确认现有 62 项后端测试仍为原结果，真实模型配置与数据注册表未被前端改动。

## scene-v2 动态场景样板

- 页面：`http://<平台>:8130/static/scene-v2/index.html`
- 文件：`platform/cloud-agent/static/scene-v2/`（`index.html`、`scene.css`、`scene.js`、`voice.js`、`scene-config.js`、`asr-config.json`、`assets/scene-draft.svg`）
- 静态检查：`python3 tests/ui/check_scene_v2.py`。只检查文件、热点、CSP 内联限制、旧 `voice_trigger` 未接入、真实 `/api/chat`、触控尺寸与 ASR 端点为空等静态条件，**不是浏览器、麦克风、ASR 或视觉测试**。
- 必看交互：三热点→子菜单→详情→返回；大坝点击 420ms 扩散后推进；Escape 逐层返回；静态展示与减少动效下仍可操作；语音打开→授权→录音→停止→取消/识别中/失败/未转写；转写结果只进可编辑草案。
- 必看边界：`/api/health` 未配置时显示未配置；`/api/chat` 503 不回退模拟；`/api/chat` 成功不显示“已执行”；无工单接口时“查看待办”显示未接入。
- 麦克风：本轮把 `Permissions-Policy` 的 `microphone=(self)` 只放开到 scene-v2 页面；部署后必须实际检查响应头与 `getUserMedia`。未配置 ASR 端点时，录音成功也只显示“已采集、未转写”。

## 明确未验证

- 未执行浏览器渲染、截图、Lighthouse、axe、屏幕阅读器。
- 未对真实 8130 服务发请求，未验证真实云回复与提案决定。
- 未验证 1920/1280/窄屏实际换行与触控尺寸，只按 CSS 断点和静态结构设计。
- 未验证 scene-v2 的麦克风授权、录音、ASR 转写与真实 `/api/chat` 往返。
- 示例流程仅前端内存，刷新页面恢复初始；没有后端工单接口。
