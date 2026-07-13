# CLAUDE.md — 抖音直播看板

面向品牌自播直播间的弹幕舆情与实时氛围监控，使用者是VOC分析和管理人员，不是直播间中控。改代码前先读本文件，历史决策和踩坑按需读 `HANDOFF.md` 和 `WORKLOG.md`。

## 铁律

1. **所有统计查询必须按当前活跃source过滤**。双采集链路（live主源/browser备源）同时入库，不过滤就重复计数。stats.py里的查询统一走scope辅助函数拼`AND source=?`，新查询照做。
2. **备源记录没有 level / fans_level / sec_uid**，user_id另一套（不是webcastUid）。任何依赖这三个字段的功能，备源活跃时必须降级（隐藏或提示），不能显示错数据。
3. **昵称是抖音服务端脱敏过的**（`X***`），拿不到真名，用user_id尾4位`#xxxx`区分人，别再尝试去星号。
4. **屏蔽名单（blocklist/word_blocklist）和VOC配置跨场次、跨房间保留**，任何清理/归档逻辑不得碰这几张表。
5. Windows下curl传中文JSON会乱码，调外部API用Python requests或先写UTF-8临时文件`--data-binary @file`。

## 架构速查

数据流：`采集器 → server.handle_record(打source) → Store入SQLite → 活跃源记录push给前端WS`。前端REST轮询（5-7s）+ WS增量。

- `src/server.py` FastAPI主服务：双采集器调度、REST/WS、备源worker子进程管理、健康监控自动切源
- `src/collector_live.py` 主源：douyinLive.exe子进程（端口1088）+ WS解JSON
- `src/collector_browser.py` + `src/parse.py` 备源：Playwright无头hook WebSocket + 自写proto解析，跑在独立子进程（`server.py --browser-worker`），记录POST回`/internal/recs`
- `src/store.py` SQLite读写与迁移；`src/stats.py` 全部聚合统计
- `src/web/dashboard.html` 看板主页面，单文件内联CSS/JS

## 字段schema（SQLite，danmu.db）

- `danmu`: room_id, user_id, sec_uid, nickname, gender, level, fans_level, content, ts, created_at, source（sec_uid/level/fans_level仅主源有值）
- `gift`: gift_name, repeat_count + 通用列；`enter`/`likes`: 通用列（likes多count）
- `room_stat`: online_count快照；`meta`: key-value（total_user累计场观等）
- `blocklist` / `word_blocklist`: 屏蔽名单，不随数据清理

加列走`store.py`的`_MIGRATIONS`列表（ALTER TABLE补列，兼容旧库），不要改CREATE TABLE后指望旧库自动变。

## 代码约定

- **新REST接口**：server.py只写薄wrapper（照`/api/summary`的三段式：`_conn()` → try调stats → finally close），SQL和聚合逻辑一律放stats.py，函数签名收`source`参数
- **新看板卡片**：dashboard.html照`.panel` + `h2`带`<span class="bar">`结构，配色只用`:root`里的CSS变量（`--bg2`卡片底、`--accent`抖音红、`--cyan/--green/--amber`语义色）
- **弹详情**：复用`#mask`通用弹层 + `renderRows()`，别新造modal
- **图表**：canvas 2D手绘（照`drawChart`），不引第三方库，整个前端零外部依赖
- **block_type等协议枚举**：抖音API用数字不用字符串

## 测试

```
pytest tests/
```

测试归主线写（code-writer不写测试）。核心聚合逻辑（stats）和存储迁移必须有用例，UI样式不写测试。

## 运行 / 打包

```
python src/server.py          # http://127.0.0.1:8848/
python -m PyInstaller build.spec --noconfirm --distpath dist --workpath build_work
```

主源依赖第三方douyinLive.exe（gitignore，下载方式见HANDOFF第五节）。环境变量：`DY_WEB_RID`默认房间、`DY_DB`库路径、`DISABLE_LIVE`/`DISABLE_BROWSER`禁用单源（调试用）。

## 必读的坑（详见HANDOFF第六节、WORKLOG 2026-07-11）

- Playwright必须headless=True且跑独立子进程；douyinLive子进程Popen要`close_fds=True`
- douyinLive连上后约11秒热身才推消息，最后一个客户端断开就拆房间监听，采集器别频繁重连
- 暴力kill chromium会在%TEMP%堆playwright临时profile，最终把spawn搞挂
