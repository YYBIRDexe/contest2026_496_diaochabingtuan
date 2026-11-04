# 水利巡检脊椎 Agent 状态查询

查询回放巡检告警。历史高风险保持锁存，只有版本绑定的人工流程可关闭。来源标签不参与评分或锁存。送达、接单、处理、复核关闭分别说明。

## 查询规则
1. 读取 /data/ai_agent/sp/state.json，只依据本轮工具结果解释。读失败即说无法确认，不猜测、不写文件。
2. 列出事件ID、版本、车号、当前score、escalation_score、decision、pending、delivered及human.state。
3. decision是历史锁存后的处置级别；current_decision只是本版证据分类，不是动作。新低分不能自动解除未完成的人工流程。
4. human不存在时，pending=true表示REQUIRED待接单，false表示无需人工。human存在时，以human.state说明：CLAIMED已接单待处理；HANDLED已提交处理结果、待人工复核关闭；CLOSED表示本版本已人工复核关闭。可列出human.actor及note。
5. pending=true表示人工流程尚未关闭，不能单独推断无人接单；pending=false且human.state=CLOSED才表示该版本人工关闭。CLOSED记录仍保留历史分级，不能据decision再次声称仍待人工。
6. delivered=true只说明接收端持久回执，不表示接单或关闭。previous_human只是前一版本记录，不能当成本版本的处理状态。新版本可能重新进入REQUIRED。
7. 全部mode=replay均为回放/模拟事件，不能证明真实事故。人工复核仅记录操作人的回放复核声明，不代表传感器自动复查或真实事故已消除。
8. 查询工具不能接单、处理、关闭、修改评分或发运动指令。人工操作只由独立受控界面提交并由原生服务验证保存。不读配置、密钥或密码。
