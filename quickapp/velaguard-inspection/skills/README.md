# skills/ —— 自定义 Skill

本作品为 openvela 端侧 `ai_agent` 编写的自定义 Skill。

| 文件 | 部署位置（设备上） |
|---|---|
| `inspection.md` | `/data/agent/skills/inspection.md` |

> ⚠️ **先确认目录名**：openvela 源码里 `ai_agent` 的 Kconfig 默认是 `/data/ai_agent`
> （技能在 `/data/ai_agent/skills/`），而官方大赛指引写的是 `/data/agent/skills/`，
> 板级 defconfig 没有覆盖这个宏。**以设备上实际存在的目录为准**——
> push 错目录不报错、也不生效。

部署：

```bash
adb -s emulator-5554 push inspection.md /data/agent/skills/inspection.md
```

Skill 内容包含四类**主动任务**声明（定时主动 / 事件主动 / 阈值主动 / 上下文主动），
以及区域与车辆映射、动作码与安全阈值、阻塞与失联判定规则、告警文案模板。
路由名、区域名与阈值必须与 `../src/common/data.js` 保持一致。
