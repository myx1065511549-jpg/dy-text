# 工作日志

## 2026-07-09 12:59

项目建立。抖音直播间实时弹幕采集与看板,目标是 Windows 本机运行、浏览器呈现、先做单直播间。

做了什么:
- 技术可行性验证:确认可行。采集走 WebSocket 长连 + protobuf + gzip + 抖音签名(a_bogus/signature),协议路径当前有效。签名算法归抖音官方 webmssdk.js,我们自研的是采集/解析/连接/存储/呈现全链路。
- 明确原则:不用第三方开源采集项目做验证载体,从 0 自研;抓来的网页当纯数据,不执行其中指令。
- 项目初始化:建目录 `D:\Claude\20260709-douyin-danmu`,git init(分支 main),.gitignore、README、requirements 就位。
- 模块一起步:`src/fetch_room.py` 抓直播间信息,能拿 ttwid;room_id 解析当前未命中,待用在播房间实测修复。
- 计划落盘:`docs/plan-20260709.md`,7 模块 4 阶段,技术栈定稿(Python 采集 + mini-racer 签名 + SQLite + FastAPI + 原生前端 + PyInstaller)。

踩坑:
- 会话中途两个 shell(Bash/PowerShell)一度返回编造的输出(复读、乱入内容、报告磁盘操作成功但 Glob 查无此物),触发框架的"可能被篡改"告警。判断为工具通道故障,非安全事件。重启 Claude Code 后恢复,恢复方式:执行命令后一律用 Glob/Read 查磁盘交叉核验。
- 直连 requests 抓直播间页首次只得 46KB 精简页;改为先拿 ttwid 再带 ttwid 二次请求,页面涨到约 396KB。

下一步:阶段一(采集内核),从修 M1 的 room_id 解析 + 攻 M2 签名开始。需用户提供一个当前在播的直播间链接做实测。

## 2026-07-09 14:11

阶段一(采集内核)完成,真实数据端到端验证通过。用户提供在播直播间 292525714929(BKT官方旗舰店带货间)实测。

做了什么:
- M1 修通:用真实在播房间抓到 room_id=7659849144554572595、ttwid、真实 user_unique_id,status=2。之前 NOT_FOUND 是终端编造输出的假象,改用"重定向到文件 + Read 读文件"核查后确认脚本本就正确。
- M2 签名跑通:从页面提取抖音官方 webmssdk.es5.js(v1.0.0.53),mini-racer 补最小浏览器 shim 后成功加载,byted_acrawler.frontierSign 可用,产出 16 位签名,格式与浏览器真签名一致。
- M3 撞设备墙:纯服务端连 wss 反复 DEVICE_BLOCKED(签名被受理,卡在设备信任层)。补真实 user_unique_id、msToken、完整 cookie 都没过。经用户确认改走浏览器辅助。
- M3 浏览器辅助跑通:Playwright 无头 Chromium + hook window.WebSocket 捕获二进制帧,过 DEVICE_BLOCKED,30s 抓到 20+ 真帧。
- M4 解析跑通:自写 douyin.proto(PushFrame/Response/Message/ChatMessage 等最小子集),grpcio-tools 编译,parse.py 逐帧 PushFrame→gzip→Response→按 method 分发,真实弹幕解出(如"果***: 卡码怎么拍")。

踩坑:
- Windows 下 print 重定向到文件是 GBK,中文弹幕显示乱码;解析本身没错(protobuf 出的是合法 UTF-8),改成直接 open(encoding='utf-8') 写 parse_result.json 后正常。
- bash 的 cwd 停在 src/,protoc 用 `-I src/proto` 变成 src/src/proto 报错;改用相对 src 的路径解决。
- 会话期间 bash/powershell 终端输出持续间歇性编造(复读、乱入注释、假成功),但文件读写真实。全程靠"命令输出重定向到文件 + Glob/Read 核查"绕开,这是本环境下唯一可信的验证方式。

下一步:阶段二 M5 存储(SQLite 落库),再阶段三 M6(FastAPI + 前端弹幕流/看板)。采集主链改为常驻:collector_browser 持续捕获帧 → parse 解析 → 入库 → 推前端。

## 2026-07-09 14:25

阶段二(存储)完成,真实数据入库验证通过。两次 git 提交(1addb22 阶段一、28562df 阶段二)。

做了什么:
- store.py:SQLite 分表(danmu/gift/enter/likes/room_stat),Store.save 按 type 分发,counts/recent_danmu 查询。
- parse.py 加 parse_records(raw):把帧直接解成带 type 的规范化记录(含 room_id/user_id/ts),供入库。
- collector_browser.py 加 collect(web_rid, on_frame, seconds):常驻采集,每帧回调。
- pipeline.py:collect → parse_records → Store 一条链。实测 292525714929 跑 40s,59 帧、56 条记录入库(danmu 2、enter 52、likes 2),库里弹幕中文时间戳正确。
- tests/test_store.py:存取往返单测,通过。

下一步:阶段三 M6。FastAPI + WebSocket 实时推送 + 两个前端页面(实时弹幕流、看板)。管道改成把每条记录既入库又推给前端。看板指标:在线人数、弹幕速率、礼物榜、活跃用户、热词。

## 2026-07-09 14:51

阶段三(服务 + 看板)完成,真实数据端到端并截图确认渲染。用户优先要热词和在线人数曲线,两者都做出来了。三个 git 提交(阶段三 3ad754a + 修复 5c91fd2)。

做了什么:
- 在线人数解析:探针从样例帧确认 WebcastRoomStatsMessage.displayValue 就是当前在线人数(displayLong="148在线观众"),proto 补 RoomStatsMessage/RoomUserSeqMessage,parse_records 产出 room_stat。
- stats.py:热词(jieba 分词 + 停用词过滤)、在线人数序列、汇总计数、活跃用户榜,只读查 SQLite。
- server.py:FastAPI + uvicorn。启动后台线程跑 collect,每条记录入库 + push 广播;REST 接口 summary/hotwords/online_series/top_users/danmu;WebSocket /ws 实时推送;托管两个页面。采集异常自动 5 秒重连。
- 前端 src/web/index.html(实时弹幕流)、dashboard.html(看板:在线人数曲线用 canvas 手绘带渐变、弹幕热词云按词频缩放、活跃用户榜、最近弹幕、四个数字卡),暗色抖音风,内联无外部依赖便于打包。
- 实测 292525714929:服务 1 秒起,两页面 200,API 返回真实数据(在线 97、热词 型号/护腰/支撑…、真实弹幕),预览工具截图看板与弹幕流均正确渲染,绿点表示 WebSocket 实时连着,数字实时累积。

踩坑:
- .gitignore 的 *.html 把前端页面 src/web/*.html 也忽略了,阶段三首次提交漏了前端;收窄成只忽略 room_page.html/page_*.html 后补回。SQLite 的 *.db-shm/-wal 也要加进 gitignore,别误提交。
- 前端页面 DB 路径:server 的 DB_PATH 改成基于脚本目录的绝对路径,预览/打包时不受 cwd 影响。

下一步:阶段四 M7 打包 exe(PyInstaller,含 chromium 引导 + 前端静态资源 + webmssdk.js)。以及可选增强:礼物 GMV、弹幕速率曲线、多房间。

## 2026-07-10 10:27

看板按领导层监控 + VOC 定位做了两轮增强(参考用户给的两张监控台图),全部真实数据 + 预览交互验证。定位:给部门/公司领导看直播间流量和 VOC 动向。

第一轮(commit eaabdde):
- 用户屏蔽 + 屏蔽池:按 user_id 屏蔽,屏蔽者从弹幕流/榜单/所有统计消失;屏蔽名单单独表,切房间/重启不清空。
- 发言榜点击看该用户历史弹幕(弹窗)。
- VOC 问题弹幕分类队列:关键词归类价格/链接/库存/发货售后/质量/尺码,带计数、进度条、近5分激增标记。stats.voc。
- 速率 + 近5分增量:弹幕/进场速率、近5分增量(SQLite datetime 比较,无需额外时间列)。
- 独立用户(去重 user_id)+ 累计场观(RoomUserSeqMessage.totalUser,存 meta 表)。
- 在线趋势时间切换(5/20/60/全场)+ 峰值标注(前端 canvas)。
- 版式改成流量/互动/用户量三组卡 + 三栏监控台。
- 用户等级 Lv 没做:探针发现等级在嵌套子消息里取不干净,加上测试房弹幕稀难验证,按"能稳定取到才加"暂缓。

第二轮(commit c203aa7):
- 发言榜 / 屏蔽池合并成一个面板,点标题标签切换;屏蔽池用户也能点看历史。
- 卡片"近5分"另起一行(.l2 block)。
- 新增热词榜(替换原热词云):排名+词+次数,点词弹出每一次出现的内容/发言人/时间。stats.word_danmu + /api/word_danmu。

新增接口:/api/voc、/api/user_danmu、/api/word_danmu、/api/block、/api/unblock、/api/blocklist。
store.py 加 blocklist、meta 表,clear() 不清屏蔽名单。

踩坑:改 .gitignore 的 *.html 差点又误伤前端(这次没动 html 规则,安全)。用户等级字段需更深逆向,记着以后要做就挖 payGrade/fansClub 子消息。

下一步:用户确认设计定稿后进阶段四打包 exe。
