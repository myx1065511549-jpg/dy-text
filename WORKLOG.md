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

## 2026-07-10 16:37

阶段四(打包 exe)完成,源码已推 GitHub。交付第一版。

看板又加了几轮微调(均已提交):热词榜屏蔽词+屏蔽词池+手动输入、VOC 点击看原声+时间筛选+屏蔽联动、屏蔽词点击看原声、发言榜/屏蔽池合并标签、卡片近5分另起一行、热词榜、全局细滚轴、布局改为以 VOC 底边为共用基准(JS 同步中间/右列高度,三栏底边对齐、切标签不跳)。

打包:
- PyInstaller onedir,build.spec。datas 含 web/vendor/proto + 内置 chromium-1228;collect_all 收 playwright/jieba/py_mini_racer/uvicorn/fastapi 等;excludes 排除 Anaconda 带的 matplotlib/PyQt5/numpy/sphinx 等无关大包。
- server.py 加 frozen 支持:_MEIPASS 资源路径、PLAYWRIGHT_BROWSERS_PATH 指向内置 chromium、DB 写到 exe 同目录、启动自动开浏览器。
- 采集器踩坑:headless=True 实际用 chrome-headless-shell(未打包),报 Executable doesn't exist;改成 headless=False + args --headless=new,用已打包的完整 chromium chrome.exe。开发验证抓 27 帧,打包后 exe 实测抓到真实弹幕(danmu/enter/online/累计场观都有)。
- 第一次瘦身重打包失败:旧 dist/_internal 被 chrome 子进程占用,rm 失败导致 && 短路 PyInstaller 没跑;彻底杀进程再删再打。
- 产物 dist/douyin-dashboard/ 约 652MB(从 1.5GB 瘦到 652MB),含 douyin-dashboard.exe(13.8MB)+ _internal + 使用说明.txt。整个文件夹拷走即可在别的 Win 机运行。

GitHub:
- 远程 https://github.com/myx1065511549-jpg/dy-text.git,git push -u origin main 成功(GCM 系统凭证,推送时浏览器登录)。
- dist/build_work 及 chromium 不入库(.gitignore),GitHub 只放源码。

交付物:
- 源码:https://github.com/myx1065511549-jpg/dy-text
- 可执行包:D:\Claude\20260709-douyin-danmu\dist\douyin-dashboard\ (整个文件夹)

下一步(如继续):优化包体积(playwright 驱动裁剪)、用户等级 Lv(需深挖 payGrade 子消息)、导出复盘、健康评分模块。

## 2026-07-11 01:03

按用户给的《抖音直播数据打通复刻说明》接入 douyinLive 作双数据源。

验证结论:douyinLive(Go 本地服务,端口 1088,自己解析/签名/protobuf,推 JSON)数据粒度更细——带 webcastUid(真实稳定标识)、payGrade.level(用户等级,我们之前拿不到)、fansClub 粉丝团等级/状态、荣誉等级、头像。数字 user.id 两边都被抖音打码成 111111,真正唯一标识是 webcastUid。

架构:
- 主源 live:collector_live 起 douyinLive.exe 子进程 + 连 ws://127.0.0.1:1088/ws/{room},解 JSON。带用户等级。
- 备源 browser:浏览器 hook。
- 两源都采都存,记录打 source 标签('live'/'browser'),stats 全部按当前活跃源过滤避免重复计数;默认 live,health_monitor 主源失效自动切备源,前端可手动切。
- store 加 source/level/fans_level/sec_uid 列 + 迁移;stats 每个函数加 source 参数;弹幕流/发言榜显示 Lv 徽章。

踩坑(备源浏览器一路踩):
- Playwright sync 在守护线程 + 主线程 asyncio,起有头浏览器 spawn UNKNOWN;根因是 headless=False(有头)在非交互会话起不来。改 headless=True(无头 shell)后任何会话都能起。
- 之前用 headless=False+--headless=new 是为了强制用完整 chrome.exe(打包只打了它)。改无头后要把 chromium_headless_shell 也打进 exe。
- 反复起停 chromium 在 Temp 堆了 114 个 playwright_ 临时 profile,把系统 spawn 搞挂;优雅关闭会自清,是暴力 kill 导致。
- douyinLive 子进程继承 Playwright node 驱动管道句柄导致 EPIPE;Popen 加 close_fds=True 解决。
- 最终把备源浏览器采集放独立子进程(server.py --browser-worker 模式),记录 POST 回 /internal/recs,彻底隔离 Playwright。
- douyinLive 连上后要约 11 秒热身才推消息,且客户端断开就拆房间;采集器要连上稳定保持,不能频繁重连。

打包:build.spec 增加 chromium_headless_shell-1228 和 tools/douyinLive;server.py frozen 下 --browser-worker 用 sys.executable 自身。tools/ 与 dist/ 不入库。

GitHub:源码已推(ebd10d8)。第三方 douyinLive 二进制按 docs 说明下载,不入库。

## 2026-07-13 11:38

看板优化P0+P1（计划见 ~/.claude/plans/zazzy-fluttering-rabin.md，定位：品牌自播VOC与管理视角）：

- P0：新建项目CLAUDE.md（双源过滤铁律、schema、代码约定、坑索引）
- P1场次归档：切房间/启动/手动「新场次」不再删数据，改为session归档。store.py加session表+5表session_id列（走_MIGRATIONS，旧库兼容已验证）；stats.py的_src升级_scope（source+session双过滤，全部查询生效）+sessions_summary（每场按数据更全的源统计防双源重复计数）；server.py新增POST /api/new_session、GET /api/sessions、DELETE /api/session/{id}；前端顶栏场次时间+新场次/历史场次按钮+历史场次弹层（复用#mask）
- 顺手修掉resetAll引用不存在的$('cloud')导致切房间时JS抛错的bug
- 转化率踩坑：直接speakers/enters会超100%（开播采集前已在房间的人发言但无进场记录），改为交集口径（发言且有进场记录/进场人数），真实数据验证29/422≈6.9%合理
- 测试：tests/test_stats.py新建4例+test_store.py加2例，7 passed；真实直播间端到端验证（新场次归零、历史场次弹层3场、当前场拒删）
- 注意：浏览器pane对高频弹幕流页面截图会超时，验证用read_page/JS读DOM代替

## 2026-07-13 12:00

看板优化P2到P4完成,全部计划落地:

- P2 VOC增强:新增「风险负面」分类(红色高亮+置顶+脉冲提示);分类和关键词入库voc_config表,VOC卡片⚙配置弹层可编辑(跨场次保留);VOC分类趋势小图(5分钟/桶,多线canvas)
- P3 节奏时间轴:原「在线人数趋势」升级为「直播节奏」,在线+弹幕/分+进场/分三线同轴(时间线性映射,不再按index等距),悬停tooltip显示各值,点击任意位置弹出该分钟弹幕原文(/api/danmu_at)
- P4:发言观众画像卡(粉丝团弹幕占比/等级分布桶/性别比,备源活跃时显示降级提示);指标卡新增「发言转化」(交集口径,与场次汇总一致);弹幕流礼物行显示礼物名×数量(WS推送补gift_name/count字段);弹幕流「全部/粉丝团/路人」筛选(备源置灰)
- 测试13例全绿;真实直播间端到端验证(接口+DOM+交互链路),console零错误
- 遗留:exe未重新打包,dist还是旧版;截图工具对高频弹幕页面会超时,验证以DOM/接口为准
- HANDOFF.md已同步更新

## 2026-07-13 12:10

修在线人数折线消失:douyinLive偶发整场只推1条RoomStats(弹幕/进场正常,仅在线人数消息断供),而在线序列按活跃源过滤,主源活跃时序列只剩1个点画不成线。根因是设计问题:在线人数是房间级数据,两源报同一个值,按源过滤只对用户级数据防重复计数有意义。修复:online_series/summary当前在线/场次峰值全部改为只按session过滤不按source过滤;前端loadSeries加10秒轮询兜底(WS仍只推活跃源)。加1例跨源合并测试,14 passed,浏览器canvas像素级验证红线恢复。
