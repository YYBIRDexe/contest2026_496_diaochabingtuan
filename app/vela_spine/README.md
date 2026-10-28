# Vela Spine — W0/W1/W2 development increment

2026-10-28 最新部署：任务编号边界、AUTO 排除已有非终态车辆、保存失败正确报错及严格车辆应答核验已部署到真实 Gemini-S1。101 项主机回归通过；更新后三轮真板与 PC 模拟三车/模拟人工平台闭环及逐轮重启全部通过，另有真板 ID/AUTO 边界检查。写入三个分区校验和匹配，原有143文件和181项权限回读一致；厂商工具尾部阶段错误如实保留。实际模型 task_status 查询通过，未识别自然语言及参数仍不保证。实际烧录镜像含私有数据，仅VM私有目录保存；详见设备验收/五项续作-20261027/最新固件真板验收-20261028.md。真实平台、车辆和长期USB/IP稳定性仍待验证。下列历史记录保留当时状态。

一条命令启动隔离服务并执行真板＋模拟车测试的用法见 [board-acceptance.md](host/board-acceptance.md)。测试专用密钥必须与真实平台密钥分开，测试会在板上创建单独目录，不自动清理原任务或事件数据。

人工处理协议与部署说明见 [host/HUMAN-PROTOCOL.md](host/HUMAN-PROTOCOL.md)。

2026-10-26新增三车HTTP网络模拟器，协议与复现命令见[host/ROBOT-PROTOCOL.md](host/ROBOT-PROTOCOL.md)。具备持久任务归属、回执状态机、版本/命令去重及离线注入；仅PC模拟，尚未接入Gemini派单或真实车辆。

当前实现（2026-10-25）：真实Gemini已部署评分、事件持久化、版本去重、高风险锁存及自动投递。新增版本绑定的人工接单→提交处理结果→复核关闭，平台排队后须等板端保存确认才生效，旧版本关闭不能清除新告警。独立人工页面已在真实平台/板端通过浏览器联调，仍未并入8130生产界面。官方ai_agent每次只读刷新状态再由真实DeepSeek解释。默认S1/S2/S3三车，分配器容量4仅为扩展。以下历史章节以当时检查点为准，人工新能力见文末及host/HUMAN-PROTOCOL.md。没有车辆运动命令。

## 最新需求

2026-10-21用户要求删除“一车发现Tag另一车对齐”，加入Tag任务分配，按异常紧急度评分超过阈值立即人工介入。Tag名称仅映射场景证据，不是写死的紧急类别。

评分：S=(40C+30T+20P+10G)/5，四项0..5分别为后果、时间紧迫性、人员暴露、扩散趋势。默认严格S>70立即人工；S=70不越阈值。权重是当前C核心固定版本，阈值可配置；修改权重须更新C并重跑测试，不能只改JSON。

因子标尺（演示工程初值，非应急行业标准）：
- C后果：0无影响，1轻微，2局部功能受限，3重要功能受损，4严重伤害/设施损坏可能，5生命危险/灾难性后果。
- T紧迫性：0无需处置，1可排期，2本轮处理，3需尽快处理，4很短响应窗口，5正在发生且不能等待。
- P人员暴露：0已确认无人，1可能接近，2有限暴露，3明确有人处于影响区，4多人暴露，5直接有人处于危险中。
- G趋势：0稳定，1变化缓慢，2有恶化迹象，3持续恶化，4快速扩散，5快速失控。

未知值=-1，score为已知证据下界，未越阈值也进入HUMAN_REVIEW；已知下界越阈值仍立即通知。低质量证据不能乘系数把高风险降成安全。时间过期要求复核；已经升级的事件不会被新低分静默撤销。AUTO仅表示未触发即时人工要求，不代表可直接运动或机器人有修复能力。

config/scenario.json为虚构磁贴情境预置；真实车端只发送Tag/观测，未来由可信上下文适配器生成因子并记录来源。当前host接口只用于本机受控回放，不能直接暴露到网络接收任意车辆提交的分值。同一Tag换一组上下文会得到不同分数；还未实现视觉语义/LLM证据提取。

## Tag分配

分配器对最多8项待检任务、4辆车进行穷举，先最小化未覆盖优先级总和，再最小化成本。输入包含预算、就绪/新鲜度、已验证可达边和保守能量成本；已占用/执行中的任务不直接改派。输出PROPOSAL_ONLY，并明确未分配项。

这不是连续路径求解器。每项能耗必须是含安全余量的保守预算包，不能用直线距离代替；在途任务取消、归属版本事务与车端提交属于后续集成，当前不会自动发车。没有任何对齐/面对面动作。

## 构建与运行

Windows（已使用MSVC编译）：
```powershell
./build-host.ps1
python -m unittest discover -s tests -v
python -m host.demo --output var/demo
```

Linux主机编译方式（命令待在目标环境验证）：
```sh
mkdir -p build
cc -std=c99 -Wall -Wextra -Werror -fPIC -shared native/spine.c -o build/libspine.so
```

demo启动仅127.0.0.1的临时HTTP接收端，8个场景入队并实际传输/持久存储；结束关闭服务，不改平台生产服务。report.json记录评分、分配、投递结果。outbox通知按紧急度优先，同event/revision重传幂等，相同revision不同正文拒绝；高版本升级另发通知。通知ACK与人工接单分离。

host/outbox.py的SQLite/HTTP为参考适配器，不适用于直接复制到当前NuttX。尚须接入板端网络、持久层和ai_agent事件/工具注册；板端资源耗尽、掉电以及真实网络压力未验收。测试中的重启是进程/数据库重开，不是板掉电。

## W0实际阻塞

2026-10-22更新：已按用户明确指令在Ubuntu终端执行现有PC公钥授权，SSH恢复。源码已传入独立目录/home/ggbird/codex-spine-20261022；Ubuntu GCC构建、14项测试及8事件HTTP回放均通过。新增NuttX Make/Kconfig接入及无运动诊断CLI（评分与分配selftest），独立nsh_minidisplay_codex_spine候选正在构建。以下SSH认证阻塞为历史，板端ai_agent缺失及真机验收边界仍成立。

设备1234 ADB正常，uname报告NuttX；ai_agent --help实际返回command not found，即当前固件没有可调用的该命令。free约906MiB与已记录的物理内存/BSP范围问题未闭环，不能据此分配大内存或直接刷旧候选。平台连接状态waiting_cable，无法宣称实体小米平台收到通知。

需要恢复并核实官方构建环境、匹配固件/板型与备份路径，再完成真实ai_agent启动及本核心的板端集成。当前交付如实记为W0探针完成但启动门槛未过，W1核心PC验证通过，W2主机参考链路通过，板端到平台验收未完成。

## 2026-10-22 实体平台接收与候选固件验收进展
用户已打开小米AIoT平台。严格SSH身份/主机校验连通192.168.137.134，独立接收端位于/home/sunrise/vela-spine-w2-20261022，127.0.0.1:8132；PC经SSH隧道127.0.0.1:18132访问。未修改8130生产服务。已实际持久接收D_TAG_1高风险上下文92分IMMEDIATE_HUMAN并浏览器核实红色告警。来源PC原生C回放，非Gemini发出，持久ACK不等于人工接单。报告：设备验收/Spine-W0-20261021/platform-live-report.json。
Ubuntu SSH已恢复；Windows和Ubuntu各14测试通过，新增接收页后Windows14测试再次通过。ARM整包编译exit0，含vela_spine与ai_agent。打包脚本exit1（Dragon成功后的末尾钩子），独立容器/分区CRC/组件校验及RAM范围检查通过；不能把打包脚本称为exit0。候选下载至设备验收/Spine-W0-20261021/candidate/gemini-s1-spine-20261022.img，SHA256 def6f5043ba7243092817bcb49184a14abeb43404972e995319aa71cf458529e。
部署新增事实：当前ADB /dev/bootloader=8388608字节，/dev/bootloader0=1048576，/dev/nand1=268435456。候选sys_partition.fex中bootloader=32768扇区即16MiB，与现有8MiB不一致；不得按候选布局直接覆盖现有分区。恢复/备份路线未验证，未刷写、重启或改动板内文件。真实Gemini启动、板端持久通知/网络适配与Gemini→平台仍未验收；不能标记W0—W2全部完成。DSH最新仍10/20 23:05，未改其生产文件。日志最近push失败，不能承诺本轮最新日志已全部远程同步。

### 事件入口（回放协议验收）

默认场景采用S1左岸、S2右岸、S3机房三车。`python3 -m host.sim_acceptance --output /绝对路径/全新目录`可用PC/Ubuntu经ADB对实际Gemini运行27条回放入口用例，并单独验证6条主机C分配提案。需可用的原生主机库和板端vela_spine命令；输出不会伪称网络车端身份、板端去重或持久ACK。设备短路径适配NAME_MAX=32，命令行保持小于64字符。

### 本地持久事件与待通知状态

先创建专用目录，例如`mkdir /data/queue`，再运行`vela_spine --ingest /data/in /data/queue`。`vela_spine --pending /data/queue`按紧急、复核优先顺序列出最新待处理记录。

- ACCEPTED_PERSISTED：验证事件并同步保存后返回；DUPLICATE：同一事件同一版本及相同内容，不写快照、不新增待处理记录。
- STALE_IGNORED：忽略旧版本，返回当前保存状态，durable_ack=false；同版本不同内容或更换车辆/Tag归属会拒绝。
- durable_ack=true只确认本地存储，ack_scope始终LOCAL_STORAGE_ONLY，不是远端平台ACK或人工确认。
- 高风险或复核状态会锁存，后续低分保存current_decision、latched并保留待人工状态；尚无人工关闭接口。
- 保存最新版本而非完整历史。最多32个事件，快照上限64KiB；容量耗尽、文件锁忙、数据损坏或写入失败时返回错误，不自动删除旧事件或确认新事件。
- 文件锁保护读改写；临时文件写完后fsync、close、rename，CRC32检测意外损坏。CRC不是身份认证。软件重启恢复已真机验证，硬断电和Flash耗尽行为尚未真机验收。
- `--event`仍是原来的无状态诊断入口；它的27项回归不等于持久入口验收。

主机测试：设置SPINE_CLI运行tests/test_store_cli.py；fsync故障注入需要另行链接tests/fsync_fault.c及`--wrap=fsync`，该文件不会进入固件。板端分阶段运行`host.store_acceptance --phase seed/resume`，中间执行真实正常重启；只使用专用测试目录，不应对业务存储目录执行损坏注入。

`vela_spine --event /data/ingress-replay.json` 读取最多4096字节JSON，嵌套上限16层。
字段：event_id、robot_id、tag_id（64字节内ASCII标识）、revision（正整数）、policy_version（spine-v2）、mode（replay）、fresh（布尔）、factors（四项-1至5整数，缺省未知）。拒绝重复键、未知键、尾随JSON、NUL和非法值。

输出保留事件/车辆/Tag/版本，调用同一原生C评分核，来源标为REPLAY_UNAUTHENTICATED，status为VALIDATED_ONLY；motion和durable_ack均false。该入口不是车端身份认证、去重账本、持久ACK或运动授权。live模式尚未接入，测试fresh字段只作为回放输入，不作为真实数据新鲜度证明。

主机验收：编译spine_main.c、native/spine.c、native/ingress.c及已有cJSON，设置SPINE_CLI到可执行文件，运行tests/test_ingress_cli.py。板端需启用EXAMPLES_VELA_SPINE及NETUTILS_CJSON，重新编译烧录后验收，不能用主机通过代替真机通过。


## 原生可靠投递与常驻服务（2026-10-25）

本节是人工流程接入前的投递检查点；人工操作能力已由文末章节扩展。

- 单次投递：vela_spine --deliver ROOT PRIVATE_IPV4:PORT。严格匹配HTTP200、Content-Length、notification_id及persisted=true；平台存储回执与人工处理分开。
- 前台worker：vela_spine --watch ROOT PRIVATE_IPV4:PORT [cycles]。不传cycles持续运行；失败2/4/8/16/32/60秒退避，空闲2秒检查，单实例fcntl锁，网络等待期间释放事件库锁，存储损坏退出，锁忙可重试。每次启动最多128条状态日志。
- 板端服务：vela_spine --service。固定业务目录/data/ai_agent/sp，endpoint.txt保存私网IPv4:port；存在该配置时Gemini独立配置的启动脚本自动拉起。移除endpoint.txt可禁用下次开机启动；停止当前进程应按ps中确切PID终止。
- 仅私网HTTP，当前实体平台链路仍依赖PC的SSH字节转发；不是生产认证通道。没有人工接单/关闭、真车身份校验或运动执行回执。
- delivered=true与pending=true可以并存；高风险原始原因在escalation_event/escalation_score保留。新版本再次待发；收到旧版ACK不确认新版。快照仅保留最新事件版本，不能当完整审计历史。

agent_adapter保存固定只读状态文件的JSON/XML、观察到的DSML文本适配；仅转换read_file到/data/ai_agent/sp/state.json，其他工具和路径不适配。官方read_file本身继续检查目录权限，原生服务目录被write_file/edit_file保留路径保护。此适配没有使整个官方Agent成为安全沙箱。agent_adapter/official-agent-and-boot.patch及安装器用于复现独立Gemini配置修改；不适用于直接刷其他板型。

该阶段主机原生C及Python测试43项通过；人工及UTF8增量后的完整回归为59项。板端结果和失败尝试分别留在工作区设备验收目录，不能只凭主机结果宣称烧录与运行成功。

Linux一键复现：`bash build-host-linux.sh /path/to/openvela/apps/netutils/cjson/cJSON`。使用同一源码树的mbedTLS构建实际C核心、CLI、fsync故障注入及只读适配库，再执行59项测试；Windows脚本仅覆盖便携评分/分配库。

Agent查询部署还需安装`agent_adapter/spine-status.md`至板端技能目录，并在Linux ADB主机运行`python3 agent_adapter/install_context.py --backup-dir /私有目录`。该脚本保留既有USER.md，将项目查询约定幂等加入官方用户上下文，原文备份不进入仓库。仅放置技能或上下文约定不足以保证每次刷新，曾发生旧历史被误称为当前读取结果。因此query_context.c在匹配巡检/脊椎查询或`ask /spine`时，先调用官方read_file读取两个固定文件，校验快照schema/CRC，每次构造仅含本轮数据的LLM消息并禁用该次解释的后续工具。读取失败、技能达到4KiB或快照达到32KiB时拒绝解释；原生库64KiB容量与查询32KiB上限不同。一般对话不走该分支。模型文本仍只用于解释，原生C决定评分、锁存和投递。

历史service6镜像SHA256：`9ad369b86b74d137eb2426d95decd2e22f9887d5058add7a62e068be2a5bf960`。真实烧录100%与三分区CRC匹配，正常软件重启后单worker及四条回放状态保留通过。两次查询实际读取3111/3099字节快照，真实LLM分别2135/2306ms；首次请求期间墙上时间从1970跳至2026而单调耗时正常，不代表RTC日期已校准。新事件rev1/2在实体平台独立SQLite核对92/20分及历史92锁存。全量重装后的配置和状态由私有备份显式恢复，随后才进行普通重启验收。

## 人工接单、处理与复核关闭（2026-10-25）

独立人工页面已与真实Gemini完成回放联调。平台持久排队，原生服务验签、精确版本/接单人/顺序检查并保存后回签，平台才显示CLAIMED/HANDLED/CLOSED。重复请求不重复生效，旧关闭不影响新版。CLOSED后pending=false但保留历史分级；新高风险版本重新请求人工。

最终human2镜像SHA256：2f1f879b460801b12b3e5a60d06fcd2cc434baf73b26d68ed10bda1ebfe2618b。59项主机测试通过，真实浏览器三步操作、正常重启保留、原始签名旧关闭重放拒绝、实体平台SQLite独立查询及DeepSeek关闭状态解释通过。官方技能摘要追加已修复长度越界和中文截断，真板长技能压力下摘要1023B且LLM成功。

配置与信任边界见host/HUMAN-PROTOCOL.md。人工入口独立于8130生产界面；仍为受控回放和PC转发，没有车辆执行、动态路线或多用户权限。全量重装使用显式私有恢复，普通软件重启持久化已验证。AI Coding与源码提交走既有校验上传流程。

## 2026-10-28 后续加固状态

真板当前运行 guard 版本，模拟三车和模拟人工流程已进行三轮闭环及重启检查，记录见设备验收。后续源码增加任务标识长度约束、避让已有非终态任务的 AUTO 分配、保存失败的错误返回，以及对车辆 ACK / 状态消息来源、序号、重复键和尾随内容的严格核验；上述加固现已部署到真板，并完成三轮模拟闭环、逐轮重启及ID/AUTO边界验证；143文件和181项权限恢复核对一致。101项主机测试通过。原打包脚本返回1，后续私有数据镜像由Dragon单独生成成功，实际写入三个分区校验和匹配；尾部阶段错误仍保留。PC 模拟器仅用于单控制器、每车同时最多一个活动任务的验收，不能代替真车或小米 AIoT 实训平台联调。

## 发送意图与停止回执加固（2026-10-28）

已复现并修复两个故障窗口：执行器已接收但ACK不可信时，旧PENDING状态允许直接取消；旧STOP回执到达时，新版本任务可能被误确认停止。发送前现先持久化DISPATCHING，未知接收结果不释放归属；停止请求只接受STOP_CONFIRMED，完成/失败回报只更新观测。确认落盘还须原子匹配当前任务版本、车辆、停止命令ID及递增序号。PC模拟器为终态与停止请求竞态提供显式静止确认，并拒绝对已服务另一任务的车辆确认旧任务停止。109项主机回归通过；最终候选仍在真板部署验收，不能用主机通过代替真板结果。状态机与回滚注意事项见host/BOARD-TASK-PROTOCOL.md。
