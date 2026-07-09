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
