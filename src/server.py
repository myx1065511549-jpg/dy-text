"""
模块六:本地服务 + 双数据源。
两条采集链路并行,都采都存(打 source 标签做保底):
  - live   :douyinLive 本地服务(主源,更细,带用户等级/粉丝团/真实标识)
  - browser:Playwright 浏览器 hook(备源)
默认展示主源;主源失效可一键切到备源;所有统计按当前活跃源过滤,避免重复计数。

运行:python src/server.py  → 浏览器打开 http://127.0.0.1:8848/
"""
import os
import sys
import json
import time
import asyncio
import threading
import subprocess
import sqlite3
import webbrowser
import urllib.request

# ---- 打包(frozen)支持 ----
_FROZEN = getattr(sys, "frozen", False)
_BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _res(rel):
    return os.path.join(_BASE, rel)


if _FROZEN:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _res("ms-playwright"))

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
import uvicorn

sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "proto"))
import collector_browser
import collector_live
from parse import parse_records
from store import Store
import stats

WEB_DIR = _res("web")
WEB_RID = os.environ.get("DY_WEB_RID", "292525714929")
_DATA_DIR = os.path.dirname(sys.executable) if _FROZEN else _BASE
DB_PATH = os.environ.get("DY_DB", os.path.join(_DATA_DIR, "danmu.db"))
PORT = int(os.environ.get("DY_PORT", "8848"))

app = FastAPI()
clients = set()
loop = None
blocked_ids = set()

current_rid = [WEB_RID]
switch_gen = [0]            # 房间切换代次,变化即让两个采集器停当前连接
cleared_gen = [-1]         # 已为哪个代次清过库
clear_lock = threading.Lock()

active_source = ["live"]    # 当前展示的数据源
src_last = {"live": 0.0, "browser": 0.0}   # 各源最近一条记录时间(健康判断)
manual_until = [0.0]        # 手动切源后的宽限期,期间不自动切
browser_store = [None]       # 备源(浏览器 worker)记录经 /internal/recs 入库用
browser_lock = threading.Lock()
worker_proc = [None]         # 备源浏览器采集子进程(隔离 Playwright)


# ---------------- 广播 ----------------
async def _broadcast(data: str):
    dead = []
    for ws in list(clients):
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def push(obj: dict):
    if loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(
                _broadcast(json.dumps(obj, ensure_ascii=False)), loop)
        except Exception:
            pass


# ---------------- 采集:两源共用的入库+推送 ----------------
def handle_record(name, store, r):
    t = r.get("type")
    src_last[name] = time.time()
    if t == "total_user":
        if active_source[0] == name:
            store.set_meta("total_user", r["total_user"])
            store.commit()
        return
    r["source"] = name
    store.save(r)
    store.commit()
    if active_source[0] != name:      # 非活跃源只入库不推前端
        return
    uid = r.get("user_id")
    blocked = uid in blocked_ids
    if t == "chat":
        if not blocked:
            push({"kind": "chat", "user_id": uid, "nickname": r.get("nickname"),
                  "content": r.get("content"), "level": r.get("level")})
    elif t == "room_stat" and r.get("online_count") is not None:
        push({"kind": "online", "t": time.strftime("%H:%M:%S"), "v": r["online_count"]})
    elif t in ("enter", "like", "gift"):
        if not blocked:
            push({"kind": t, "nickname": r.get("nickname")})


def maybe_clear(store, gen):
    with clear_lock:
        if cleared_gen[0] != gen:
            store.clear()
            cleared_gen[0] = gen


def run_collector(name, collect_impl):
    store = Store(DB_PATH)
    my_gen = -1
    while True:
        gen = switch_gen[0]
        if gen != my_gen:
            maybe_clear(store, gen)
            my_gen = gen

        def should_stop():
            return switch_gen[0] != my_gen

        try:
            collect_impl(current_rid[0], store, should_stop)
        except Exception as e:
            import traceback
            print(f"[collector {name}] {traceback.format_exc()}", file=sys.stderr, flush=True)
            push({"kind": "sys", "msg": f"{name}源中断: {str(e)[:60]}"})
        if switch_gen[0] == my_gen:
            time.sleep(2)


# ---- 备源:独立子进程跑浏览器采集(隔离 Playwright,避开线程/asyncio 冲突) ----
def _worker_cmd(room):
    if _FROZEN:
        return [sys.executable, "--browser-worker", room, str(PORT)]
    return [sys.executable, os.path.join(_BASE, "server.py"), "--browser-worker", room, str(PORT)]


def kill_worker():
    p = worker_proc[0]
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass


def spawn_worker():
    if os.environ.get("DISABLE_BROWSER"):
        return
    kill_worker()
    try:
        worker_proc[0] = subprocess.Popen(
            _worker_cmd(current_rid[0]),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def run_browser_worker(room, port):
    """子进程入口:主线程跑浏览器采集,把记录批量 POST 给主服务。"""
    url = f"http://127.0.0.1:{port}/internal/recs"

    def on_frame(raw):
        recs = parse_records(raw)
        if not recs:
            return
        try:
            data = json.dumps(recs, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
    collector_browser.collect(room, on_frame, seconds=10 ** 9)


def live_impl(rid, store, should_stop):
    if not collector_live.ensure_douyinlive():
        time.sleep(5)
        return
    collector_live.collect(rid, lambda r: handle_record("live", store, r),
                           should_stop=should_stop)


def health_monitor():
    """看护备源 worker(挂了重拉);主源失效且备源正常时自动切备源(兜底)。"""
    while True:
        time.sleep(8)
        if not os.environ.get("DISABLE_BROWSER"):
            p = worker_proc[0]
            if p is None or p.poll() is not None:
                spawn_worker()
        now = time.time()
        if now < manual_until[0]:
            continue                       # 手动切源宽限期,不自动切
        live_ok = (now - src_last.get("live", 0)) < 15
        browser_ok = (now - src_last.get("browser", 0)) < 15
        want = "live" if live_ok else ("browser" if browser_ok else active_source[0])
        if want != active_source[0]:
            active_source[0] = want         # 优先主源,主源失效才用备源,备源恢复主源后切回
            push({"kind": "source", "source": want, "auto": True})


# ---------------- 启动 ----------------
@app.on_event("startup")
async def _startup():
    global loop
    loop = asyncio.get_event_loop()
    s = Store(DB_PATH)
    blocked_ids.update(s.blocked_ids())
    s.close()
    browser_store[0] = Store(DB_PATH)
    if not os.environ.get("DISABLE_LIVE"):
        threading.Thread(target=run_collector, args=("live", live_impl), daemon=True).start()
    spawn_worker()   # 备源浏览器采集(独立进程)
    threading.Thread(target=health_monitor, daemon=True).start()


# ---------------- 页面 ----------------
def _page(name):
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/")
def index():
    return _page("dashboard.html")


@app.get("/dashboard")
def dashboard():
    return _page("dashboard.html")


@app.get("/stream")
def stream():
    return _page("index.html")


def _conn():
    return sqlite3.connect(DB_PATH)


def _src():
    return active_source[0]


# ---------------- 数据源 ----------------
@app.get("/api/config")
def api_config():
    return {"web_rid": current_rid[0], "source": active_source[0]}


@app.post("/internal/recs")
async def internal_recs(request: Request):
    """备源 worker 回传的记录批量入库(source=browser)。"""
    try:
        recs = await request.json()
    except Exception:
        return {"ok": False}
    with browser_lock:
        st = browser_store[0]
        if st is not None:
            for r in recs:
                try:
                    handle_record("browser", st, r)
                except Exception:
                    pass
    return {"ok": True}


@app.get("/api/sources")
def api_sources():
    now = time.time()

    def ok(n):
        return (now - src_last.get(n, 0)) < 15
    return {
        "active": active_source[0],
        "live": {"ok": ok("live"), "available": collector_live.douyinlive_available()},
        "browser": {"ok": ok("browser")},
    }


@app.post("/api/switch_source")
def api_switch_source(source: str):
    if source in ("live", "browser"):
        active_source[0] = source
        manual_until[0] = time.time() + 30   # 手动切换给 30 秒宽限,不被自动切覆盖
        push({"kind": "source", "source": source})
    return {"source": active_source[0]}


@app.post("/api/switch")
def api_switch(web_rid: str):
    rid = (web_rid or "").strip()
    if rid:
        current_rid[0] = rid
        switch_gen[0] += 1          # 主源采集器停当前连接、换新房间
        with clear_lock:
            if browser_store[0] is not None:
                browser_store[0].clear()
            cleared_gen[0] = switch_gen[0]
        spawn_worker()              # 备源 worker 换新房间重启
        push({"kind": "switch", "web_rid": rid})
    return {"web_rid": current_rid[0]}


# ---------------- 统计接口(按当前活跃源过滤) ----------------
@app.get("/api/summary")
def api_summary():
    c = _conn()
    try:
        return stats.summary(c, _src())
    finally:
        c.close()


@app.get("/api/hotwords")
def api_hotwords():
    c = _conn()
    try:
        return stats.hotwords(c, 40, _src())
    finally:
        c.close()


@app.get("/api/voc")
def api_voc(range: int = 0):
    c = _conn()
    try:
        return stats.voc(c, range, _src())
    finally:
        c.close()


@app.get("/api/voc_danmu")
def api_voc_danmu(category: str, range: int = 0, limit: int = 200):
    c = _conn()
    try:
        return stats.voc_danmu(c, category, range, limit, _src())
    finally:
        c.close()


@app.get("/api/online_series")
def api_online_series():
    c = _conn()
    try:
        return stats.online_series(c, 600, _src())
    finally:
        c.close()


@app.get("/api/top_users")
def api_top_users():
    c = _conn()
    try:
        return stats.top_users(c, 15, _src())
    finally:
        c.close()


@app.get("/api/user_danmu")
def api_user_danmu(user_id: str, limit: int = 100):
    c = _conn()
    try:
        return stats.user_danmu(c, user_id, limit, _src())
    finally:
        c.close()


@app.get("/api/word_danmu")
def api_word_danmu(word: str, limit: int = 200):
    c = _conn()
    try:
        return stats.word_danmu(c, word, limit, _src())
    finally:
        c.close()


@app.get("/api/danmu")
def api_danmu(limit: int = 60):
    c = _conn()
    try:
        sc, sp = stats._src(_src())
        rows = c.execute(
            f"SELECT user_id, nickname, content, created_at, level FROM danmu "
            f"WHERE {stats.NB}{sc} ORDER BY id DESC LIMIT ?", sp + [limit]).fetchall()
        return [{"user_id": u, "nickname": a, "content": b, "created_at": d, "level": lv}
                for u, a, b, d, lv in rows][::-1]
    finally:
        c.close()


# ---------------- 屏蔽 ----------------
@app.post("/api/block")
def api_block(user_id: str, nickname: str = ""):
    uid = (user_id or "").strip()
    if not uid:
        return {"ok": False}
    c = _conn()
    try:
        c.execute("INSERT INTO blocklist(user_id,nickname,blocked_at) "
                  "VALUES(?,?,datetime('now','localtime')) "
                  "ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname", (uid, nickname))
        c.commit()
    finally:
        c.close()
    blocked_ids.add(uid)
    push({"kind": "blocked", "user_id": uid, "nickname": nickname})
    return {"ok": True}


@app.post("/api/unblock")
def api_unblock(user_id: str):
    uid = (user_id or "").strip()
    c = _conn()
    try:
        c.execute("DELETE FROM blocklist WHERE user_id=?", (uid,))
        c.commit()
    finally:
        c.close()
    blocked_ids.discard(uid)
    push({"kind": "unblocked", "user_id": uid})
    return {"ok": True}


@app.get("/api/blocklist")
def api_blocklist():
    c = _conn()
    try:
        rows = c.execute(
            "SELECT user_id, nickname, blocked_at FROM blocklist ORDER BY blocked_at DESC").fetchall()
        return [{"user_id": a, "nickname": b, "blocked_at": d} for a, b, d in rows]
    finally:
        c.close()


@app.post("/api/block_word")
def api_block_word(word: str):
    w = (word or "").strip()
    if not w:
        return {"ok": False}
    c = _conn()
    try:
        c.execute("INSERT OR IGNORE INTO word_blocklist(word,blocked_at) "
                  "VALUES(?,datetime('now','localtime'))", (w,))
        c.commit()
    finally:
        c.close()
    push({"kind": "word_blocked", "word": w})
    return {"ok": True}


@app.post("/api/unblock_word")
def api_unblock_word(word: str):
    w = (word or "").strip()
    c = _conn()
    try:
        c.execute("DELETE FROM word_blocklist WHERE word=?", (w,))
        c.commit()
    finally:
        c.close()
    push({"kind": "word_unblocked", "word": w})
    return {"ok": True}


@app.get("/api/word_blocklist")
def api_word_blocklist():
    c = _conn()
    try:
        rows = c.execute(
            "SELECT word, blocked_at FROM word_blocklist ORDER BY blocked_at DESC").fetchall()
        return [{"word": a, "blocked_at": b} for a, b in rows]
    finally:
        c.close()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        clients.discard(websocket)


if __name__ == "__main__":
    if "--browser-worker" in sys.argv:
        i = sys.argv.index("--browser-worker")
        room = sys.argv[i + 1]
        port = sys.argv[i + 2] if len(sys.argv) > i + 2 else str(PORT)
        run_browser_worker(room, port)
    else:
        threading.Timer(2.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
        print(f"抖音直播看板已启动,请在浏览器打开 http://127.0.0.1:{PORT}/")
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
