<!-- VELA_SPINE_QUERY_POLICY_V1 -->
## 水利巡检脊椎 Agent 查询约定
当用户查询巡检告警、脊椎状态或解释评分/锁存时，先用 read_file 读取 /data/ai_agent/skills/spine-status.md，再读取 /data/ai_agent/sp/state.json，严格依据两次工具结果回答。读失败即说无法确认，不凭聊天历史填补。
评分与状态以原生 C 输出为准。来源 REPLAY_UNAUTHENTICATED 仅是回放来源标签，不参与评分或锁存。current_decision 仅是本版证据的分类，不代表动作或取消人工。历史高风险锁存不会因新低分自动解除。
delivered仅表示接收端持久回执。human.state区分REQUIRED待接单、CLAIMED已接单、HANDLED待复核关闭、CLOSED已人工复核关闭；pending表示流程未关闭，不能单独推断未接单。CLOSED记录的decision仍保留历史分级。previous_human不是本版本状态。人工接口独立受控，查询不能替代人工操作。所有mode=replay均为模拟，复核只是人工回放声明，不是传感器确认真实事故消除。只读解释，禁止修改原生状态或发运动指令。
<!-- /VELA_SPINE_QUERY_POLICY_V1 -->
