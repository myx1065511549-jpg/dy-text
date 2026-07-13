# 交接文档 — 抖音直播实时看板

> 给下一个会话/AI 接手用。看完这份 + `CLAUDE.md` + `README.md` + `WORKLOG.md` 就能继续。
> 最后更新:2026-07-13。当前状态:第一版交付后完成**面向品牌自播VOC/管理视角的看板优化**(场次归档、VOC风险分类+可配置+趋势、节奏时间轴、观众画像、发言转化率),代码+测试+真实直播间验证已通,**exe未重新打包**。

## 一、一句话现状

一个 Windows 本机程序:实时抓抖音直播间弹幕/礼物/进场/点赞,双数据源并行采集入库,浏览器看板呈现(实时弹幕流 + 数据看板),已打包成双击即用的 exe。

- 源码(GitHub):https://github.com/myx1065511549-jpg/dy-text (最新提交 `3b388f8`)
- 可执行包:`D:\Claude\20260709-douyin-danmu\dist\douyin-dashboard\`(约 964MB,双击 `douyin-dashboard.exe`,含 `使用说明.txt`)
- 项目根:`D:\Claude\20260709-douyin-danmu\`

## 二、完成度

阶段一到四 + 多轮看板增强 + 双数据源 + 发言人标识修复,全部完成并用真实数据验证:

- 采集内核:房间抓取 → 签名 → 连接 → protobuf 解析
- 存储:SQLite(带场次 session 归档,切房间/重启/手动新场次不删数据)
- 看板:分组指标卡(速率/近5分/发言转化率)、直播节奏时间轴(在线+弹幕/分+进场/分,悬停tooltip,点击回看该分钟弹幕)、VOC 问题弹幕分类队列(风险负面类红色置顶、分类关键词界面可配置、分类趋势小图、点看原声+时间筛选)、发言观众画像(粉丝团占比/等级分布/性别,备源降级)、发言榜/屏蔽池、热词榜、实时弹幕流(粉丝团/路人筛选、礼物名显示、悬停屏蔽)、屏蔽词、运行时切直播间、历史场次弹层(每场汇总+VOC占比+可删)
- 打包:PyInstaller onedir,内置 chromium + douyinLive,双击即用(**2026-07-13 的看板优化后未重新打包,dist 里还是旧版**)
- 双数据源:见下
- 测试:`pytest tests/` 13 例(存储迁移/场次/双源过滤/VOC配置/聚合)

## 三、架构(双数据源)

两条采集链路并行,都采都存(记录打 `source` 标签),默认展示主源,主源失效自动切备源(也可手动):

- **主源 `live`(默认,更细)**:`collector_live.py` 起 `douyinLive.exe` 子进程(本地 Go 服务,端口 1088,自己解析/签名/protobuf/推 JSON),连 `ws://127.0.0.1:1088/ws/{room}` 解析。独有:用户等级 payGrade、粉丝团、真实唯一标识 webcastUid。
- **备源 `browser`(自研,兜底)**:抓 room_id/ttwid → mini-racer 执行抖音官方 `webmssdk.js` 算签名 → Playwright 无头 chromium hook WebSocket 拿原始帧 → 自写 `.proto` 解析。**作为独立子进程运行**(`server.py --browser-worker`,记录 POST 回 `/internal/recs`),隔离 Playwright,避免线程/asyncio/句柄冲突。
- 统计全部按当前活跃源过滤(避免重复计数);`health_monitor` 优先主源,主源失效切备源、恢复后切回,手动切换有 30 秒宽限。

数据流:`采集器 → handle_record(打source) → Store 入 SQLite → 活跃源的记录 push 给前端 WS`。前端 `dashboard.html` 轮询 REST + 收 WS。

## 四、关键文件

```
src/
  server.py            主服务:FastAPI+uvicorn、双采集器调度、REST/WS、备源worker管理、frozen打包支持
  collector_live.py    主源:管理douyinLive子进程 + 连它的WS + 解JSON
  collector_browser.py 备源:Playwright无头hook WebSocket抓原始帧(headless=True)
  parse.py             备源用:PushFrame→gzip→Response→按method解记录 + parse_records()
  store.py             SQLite:表结构、source/level/sec_uid列、迁移、屏蔽名单、屏蔽词、meta
  stats.py             聚合:热词/VOC/速率/在线序列/发言榜/用户历史/词出现,全部带source过滤
  sign.py              mini-racer执行webmssdk.js算签名(备源用),Signer类
  proto/douyin.proto   自写的抖音协议最小子集 + douyin_pb2.py(protoc生成)
  vendor/webmssdk.es5.js 抖音官方签名JS(备源用)
  web/dashboard.html   看板主页面(单文件,内联CSS/JS)
  web/index.html       独立弹幕流页
tests/test_store.py    存储单测
tools/douyinLive/      douyinLive.exe + config.yaml(第三方,gitignore,按docs下载)
build.spec             PyInstaller打包配置
docs/plan-20260709.md  最初的实现计划
WORKLOG.md             全程工作日志 + 踩坑(重要,按需读)
```

## 五、怎么跑 / 怎么打包

开发运行:
```
pip install -r requirements.txt
python -m playwright install chromium
# 主源需要 douyinLive.exe:按 docs 下载到 tools/douyinLive/(见下)
python src/server.py    # 浏览器开 http://127.0.0.1:8848/
```

打包 exe:
```
pip install pyinstaller
python -m PyInstaller build.spec --noconfirm --distpath dist --workpath build_work
# 产物 dist/douyin-dashboard/,约964MB
```

douyinLive 依赖(第三方,不入库):从 GitHub release v2.0.24 下载 `douyinLive-v2.0.24-79453ece4a44-windows-amd64.zip`(SHA256 `cc1cc9df433337c62263d7925da77ab17622603bbb554f1c27d3cbe9048cce4f`),解压到 `tools/douyinLive/`,复制 `config.example.yaml` 为 `config.yaml`。用户微信收藏里有《抖音直播数据打通复刻说明.md》是原始参考。

## 六、已知限制 / 必读的坑

1. **发言人昵称带星号去不掉**:抖音服务端对普通观众昵称做隐私脱敏(`nickname` 和 `desensitizedNickname` 都是 `X***`),数字 id 也都是 `111111`。任何 Web 抓取路径都拿不到真名。已用 `webcastUid`(每人唯一真实标识)做底层 user_id,并在昵称后加短标识 `#xxxx` + Lv 等级来区分。要真名只有官方开放平台 API(企业资质 + 主播授权),没做。
2. **包体积 964MB**:同时打进了 chromium-1228(416MB,兜底)和 chromium_headless_shell-1228(270MB,headless=True 实际用它)。可优化:确认 headless=True 只用 headless_shell 后删掉 chromium-1228,能省 ~416MB。
3. **备源浏览器一路踩过的坑(已解决,别踩回去)**:headless=False 有头浏览器在非交互会话 `spawn UNKNOWN` → 必须 headless=True;douyinLive 子进程 Popen 要 `close_fds=True` 否则继承 Playwright 管道句柄 EPIPE;Playwright sync 不能在 asyncio 服务的守护线程里跑 → 拆成独立子进程;反复暴力 kill chromium 会在 `%TEMP%` 堆 `playwright_*` 临时 profile 把系统 spawn 搞挂(优雅关闭会自清)。详见 WORKLOG 2026-07-11 两条。
4. **douyinLive 特性**:客户端连上后约 11 秒热身才推消息,且最后一个客户端断开就拆房间监听 → 采集器必须连上稳定保持,别频繁重连。
5. **运行第三方 exe 的权限**:安全分类器会拦"运行下载来的 douyinLive.exe",需要用户批准(本会话已批准过)。
6. **本会话环境插曲**:期间 bash/powershell 终端一度返回过被编造的输出(复读、假成功),靠"命令输出重定向到文件 + Glob/Read 核查"绕开。换新会话未必复现,但遇到终端输出可疑时,以文件落盘核查为准。

## 七、可能的下一步(用户没确认,仅备选)

- **重新打包 exe**(2026-07-13 看板优化后 dist 还是旧版,跑一次 PyInstaller 即可)
- 优化包体积(删冗余 chromium)
- 备源也解析 sec_uid/等级/粉丝团(目前只有主源有;备源活跃时画像卡和粉丝团筛选已做降级,补齐字段后自动可用)
- 场次复盘报告导出(场次归档已就位,导出只是加一层输出)
- 官方开放平台 API 拿真实昵称(需企业号+授权)

## 八、交付物地址(再列一次)

- 源码 GitHub:https://github.com/myx1065511549-jpg/dy-text
- 可执行包:`D:\Claude\20260709-douyin-danmu\dist\douyin-dashboard\`(整个文件夹拷走才能在别的机器跑)
- 本交接文档:`D:\Claude\20260709-douyin-danmu\HANDOFF.md`
