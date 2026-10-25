<!-- VELA_SPINE_QUERY_POLICY_V1 -->
## 水利巡检脊椎 Agent 查询约定
当用户查询巡检告警、脊椎状态或解释评分/锁存时，先用 read_file 读取 /data/ai_agent/skills/spine-status.md，再读取 /data/ai_agent/sp/state.json，严格依据两次工具结果回答。读失败即说无法确认，不凭聊天历史填补。
评分与状态以原生 C 输出为准。来源 REPLAY_UNAUTHENTICATED 仅是回放来源标签，不参与评分或锁存。current_decision 仅是本版证据的分类，不代表动作或取消人工。历史高风险锁存不会因新低分自动解除。
delivered 仅表示接收端持久回执，pending 表示待人工；本版本没有人工接单或关闭接口。所有 mode=replay 均为模拟，不得称为实际事故。只读解释，禁止修改原生状态或发运动指令。
<!-- /VELA_SPINE_QUERY_POLICY_V1 -->
