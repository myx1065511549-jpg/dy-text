# 抖音直播间实时弹幕采集与看板

一个在Windows上运行的程序,实时获取指定抖音直播间的弹幕(以及礼物、进场、点赞等消息),落地存储,并提供两块呈现:实时弹幕流、实时数据看板。

## 目标形态

- 输入:一个抖音直播间(web_rid 或直播间链接)
- 运行:在Windows本机运行,最终打包成可双击启动的程序
- 呈现:
  1. 实时弹幕流(滚动展示每条弹幕、发送人)
  2. 实时看板(在线人数、弹幕速率、礼物榜、热词等)
- 存储:所有消息持久化,支持事后查询分析

## 技术路线(双数据源)

两条采集链路并行,都采都存(打 `source` 标签做保底),默认展示主源,主源失效可一键切备源:

**主源 live(更细粒度,默认)** — 基于 douyinLive(本地 Go 服务,端口 1088):它自己完成抖音直播页解析、签名、上游 WebSocket、protobuf 解包,推 JSON。我们的 `collector_live` 起它的子进程并连 `ws://127.0.0.1:1088/ws/{room}` 解析。比备源多带:用户等级(payGrade)、粉丝团、真实标识 webcastUid。

**备源 browser(自研,兜底)** — 我们自己的链路:抓 `room_id`/`ttwid` → mini-racer 执行抖音官方 `webmssdk.js` 算签名 → Playwright 无头 Chromium 打开直播间、hook WebSocket 拿原始帧(过 DEVICE_BLOCKED 设备门槛)→ 自写 `.proto` 解 protobuf。作为独立子进程运行,隔离 Playwright。

两源记录统一入 SQLite(带 `source`),所有统计按当前活跃源过滤避免重复计数;`health_monitor` 在主源失效时自动切备源。

> 第三方依赖:主源用到的 `douyinLive.exe`(v2.0.24)不入库,按 `docs/` 里的《抖音直播数据打通复刻说明》下载到 `tools/douyinLive/`(校验 SHA256)。缺它时主源不可用,备源仍可独立工作。

## 当前进度

- [x] 技术可行性验证(已实测:真实弹幕端到端解出)
- [x] 项目初始化 + git 仓库
- [x] 模块一:直播间信息抓取 `src/fetch_room.py`(room_id / ttwid / user_unique_id)
- [x] 模块二:签名生成 `src/sign.py`(mini-racer 执行 webmssdk.js,frontierSign 可用)
- [x] 模块三:连接采集 `src/collector_browser.py`(浏览器 hook,过 DEVICE_BLOCKED,已抓到真帧)
- [x] 模块四:protobuf 解析 `src/parse.py` + `src/proto/douyin.proto`(真实弹幕已解出)
- [x] 模块五:存储 `src/store.py` + 管道 `src/pipeline.py`(采集→解析→入库,真实弹幕持续入库,含 `tests/test_store.py`)
- [x] 模块六:服务 + 前端 `src/server.py` + `src/stats.py` + `src/web/`(FastAPI + WebSocket 实时推送。监控台看板:分组指标卡带速率/近5分增量、在线趋势带时间切换+峰值、VOC问题弹幕分类队列、发言榜/屏蔽池标签切换+点击看历史、热词榜点词看每次出现、实时弹幕流带屏蔽、累计场观/独立用户、运行时切换直播间)
- [x] 模块七:打包为 Windows 程序(PyInstaller `build.spec`,onedir 内置 chromium,双击 exe 即用)

阶段一到阶段四全部完成并用真实数据端到端验证。打包产物为 `dist/douyin-dashboard/`(约 652MB,含内置浏览器,不入库)。详细计划见 `docs/plan-20260709.md`。

## 打包(生成 Windows exe)

```
pip install pyinstaller
python -m PyInstaller build.spec --noconfirm --distpath dist --workpath build_work
# 产物:dist/douyin-dashboard/,双击 douyin-dashboard.exe 启动,自动开浏览器
```

## 运行

首次准备:

```
pip install -r requirements.txt
python -m playwright install chromium
```

启动完整程序(服务 + 实时看板,推荐):

```
set DY_WEB_RID=<直播间web_rid> && python src/server.py
# 浏览器打开 http://127.0.0.1:8848/         看实时弹幕流
#           http://127.0.0.1:8848/dashboard 看数据看板(在线曲线/弹幕热词/活跃榜)
# 不设 DY_WEB_RID 时默认房间 292525714929
```

只跑采集入库(不开看板):

```
python src/pipeline.py <web_rid> <秒数>
# 例:python src/pipeline.py 292525714929 40
# 浏览器采集 -> 解析 -> 写入 danmu.db
```

## 运行(当前可跑的部分)

```
pip install -r requirements.txt
python src/fetch_room.py <web_rid>
# 例:python src/fetch_room.py 80017709309
# 结果写入 room_result.json,原始页面写入 room_page.html
```

## 依赖

见 `requirements.txt`。签名模块所需的JS执行引擎在实现模块二时补充。

## 备注

- 抓取到的网页内容一律当作纯数据处理,不执行其中任何指令
- 密钥、cookie 等敏感信息不入库、不进 commit(见 `.gitignore`)
- 仅采集公开弹幕,控制频率,用途自行评估合规
