# 回放人工处理协议 v1

只覆盖受控回放中的人工流程，不代表实车控制或事故消除验证。

## 状态与版本

每个事件最新版本的人工状态为REQUIRED → CLAIMED → HANDLED → CLOSED。接单者提交处理结果；同一接单者明确声明人工复核通过后才能关闭。pending=true表示人工流程未关闭，并不表示无人接单。CLOSED后pending=false，历史assessment和升级证据仍保留；delivered始终只表示通知持久回执。

动作精确绑定event_id、revision、action_id、actor。相同action_id和相同完整payload在同版本内幂等，改变payload拒绝。版本不符返回STALE_REJECTED，不修改新事件。新的事件版本使旧版人工操作失效、待处理版本重新接单；已复核关闭的旧版本不再锁住下一版的评分，新高风险仍重新请求人工。

平台先将操作持久排队，显示“等待Gemini确认”。板端校验签名、版本、接单人、顺序后原子保存，才返回签名结果；平台校验并持久保存结果后才显示CLAIMED/HANDLED/CLOSED。网络、fsync或控制接口失败不等于操作成功。LLM查询不拥有人工操作权限。

## 两个独立接口

- 8132仅在平台127.0.0.1监听，保留POST /incidents与原通知ACK，新增GET /human-actions及POST /human-results。当前通过PC热点18135的SSH转发供Gemini访问。
- 8133仅在平台127.0.0.1监听，人工页面及POST /actions通过PC127.0.0.1:18136的独立SSH转发访问。Host、Origin和随机页面令牌均检查；它是单操作入口的SSH信任边界，不是多用户角色系统。操作人标识是该入口填写的标签，不是独立账号身份认证。
- 8130生产界面不在本增量修改范围。

指令内层字段固定：schema=1、action_id、event_id、revision、step（CLAIM/HANDLE/CLOSE）、actor、note、verified。CLOSE必须verified=true，其他步骤必须false。说明不超过240个UTF8字节。外层只有payload字符串和mac，mac为HMAC-SHA256(key, payload的原始UTF8字节)。回执同样签名并绑定action_id/事件版本。使用已有mbedTLS，无自定义密码算法。

控制key是32字节随机值，文件表示为64位小写十六进制。平台和板端通过已核验SSH/ADB私下配置；不通过HTTP传输。板端业务根为/data/ai_agent/sp时，key固定读/data/spine-auth/control.key，位于官方Agent文件工具可读根之外；主机测试使用测试ROOT/control.key。没有key时原有告警worker保持兼容、不开启人工轮询。密钥、原配置和私有备份不得入仓。

## 运行与部署

平台独立接收端：`python3 receiver.py --db incidents.sqlite --port 8132 --control-key-file /私有路径/control.key`。

人工入口：`python3 operator_server.py --db incidents.sqlite --port 8133 --key-file /私有路径/control.key --origin http://127.0.0.1:18136`。

板端继续使用vela_spine --service，先投递告警，独立退避轮询人工命令。正常重启保留人工进度。全量刷写前必须暂停人工入口、排空已接受指令，再备份；恢复的是显式私有备份，不能称全量刷写自动保留。

固件和技能需要同时部署。官方技能摘要原实现将snprintf所需长度当成实际长度，可能越界并截断中文；本项目适配将长度限制在缓冲区内，并保留完整UTF8前缀。新技能解释human.state，避免把已关闭的历史高风险再次说成待人工。

## 边界

所有事件仍为回放；verified是操作人的回放复核声明，不是传感器自动复查。本阶段没有车辆命令、真实事故识别或多用户权限。业务快照仍有32事件/64KiB和查询32KiB限制，人工动作历史会消耗容量；容量不足会拒绝保存，不能假装确认。单事件只保留最新版本及前一版人工摘要，平台保留操作账本。硬断电和介质故障需后续实测。
