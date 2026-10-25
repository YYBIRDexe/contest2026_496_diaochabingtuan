# 水利巡检脊椎 Agent 状态查询

查询回放巡检告警。当前分只反映新版；历史高风险锁存保持人工。delivered仅接收端存储回执，pending才是待人工；来源标签不参与评分或锁存。不得声称人工已接单。

## 操作
1. 使用官方 read_file 工具读取 /data/ai_agent/sp/state.json。
2. 文件缺失或读取失败时明确说“无法确认”，不要编造事件，也不要改文件。
3. 根据 records 内的 event、assessment、pending、delivered、escalation_score 回答，列出事件ID、版本和车号。
4. assessment.decision 是锁存后的处置级别。IMMEDIATE_HUMAN 表示立即请求人工；即使当前评分下降，也不能自行解除。若 escalation_score 高于当前 score，说明是此前高风险锁存。
5. delivered=true 只表示接收端持久回执已写回；pending=true 表示人工处理任务仍待处理，两者可以同时成立。不能将送达说成人工已接单。
6. mode=replay 或来源模拟时，必须明确“回放/模拟事件”。本技能不能证明磁贴识别是真实事故。
7. 不运行写文件、删除、运动、关闭告警或更改评分阈值的工具。不读取任何配置、密钥、网络密码。

## 示例
用户：“查询脊椎巡检告警状态，调用工具查实际记录。”
→ read_file /data/ai_agent/sp/state.json
→ 基于实际工具返回解释，说明人工是否仍待处理与远端持久送达状态。

来源REPLAY_UNAUTHENTICATED只是验收来源标签，不是评分因素，也不是触发锁存的额外条件。锁存依据是历史最高处置级别；本版本尚无人工接单或关闭接口。只允许解释现有规则，不能自行补充未实现的政策。
