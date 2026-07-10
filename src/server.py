"""
模块六:本地服务 + 实时推送。
FastAPI 提供两个页面(实时弹幕流 / 看板)、REST 聚合接口、WebSocket 实时推送。
启动时在后台线程跑浏览器采集,每条记录既入库又广播给前端。

运行:
  set DY_WEB_RID=<直播间web_rid> && python src/server.py
  浏览器打开 http://127.0.0.1:8848/(弹幕流)、/dashboard(看板)
"""
import os
import sys
import json
import time
import asyncio
import threading
import sqlite3

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collector_browser import collect
from parse import parse_records
from store import Store
import stats

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
WEB_RID = os.environ.get("DY_WEB_RID", "292525714929")
DB_PATH = os.environ.get("DY_DB", os.path.join(HERE, "danmu.db"))
PORT = int(os.environ.get("DY_PORT", "8848"))

app = FastAPI()
clients = set()
loop = None
current_rid = [WEB_RID]          # 当前监控的直播间(可运行时切换)
switch_event = threading.Event()  # 置位表示要切房间,采集器据此停当前浏览器
blocked_ids = set()               # 已屏蔽用户(内存镜像,用于实时推送跳过)


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
        data = json.dumps(obj, ensure_ascii=False)
        try:
            asyncio.run_coroutine_threadsafe(_broadcast(data), loop)
        except Exception:
            pass


def collector_thread():
    store = Store(DB_PATH)
    last_rid = None
    while True:
        rid = current_rid[0]
        if rid != last_rid:
            store.clear()          # 换房间就清库,统计对新房间从零开始
            last_rid = rid
        switch_event.clear()

        def on_frame(raw):
            recs = parse_records(raw)
            for r in recs:
                t = r["type"]
                if t == "total_user":
                    store.set_meta("total_user", r["total_user"])
                    continue
                store.save(r)
                uid = r.get("user_id")
                blocked = uid in blocked_ids
                if t == "chat":
                    if not blocked:
                        push({"kind": "chat", "user_id": uid,
                              "nickname": r.get("nickname"), "content": r.get("content")})
                elif t == "room_stat" and r.get("online_count") is not None:
                    push({"kind": "online", "t": time.strftime("%H:%M:%S"),
                          "v": r["online_count"]})
                elif t in ("enter", "like", "gift"):
                    if not blocked:
                        push({"kind": t, "nickname": r.get("nickname")})
            if recs:
                store.commit()

        try:
            collect(rid, on_frame, seconds=36000,
                    should_stop=lambda: switch_event.is_set())
        except Exception as e:
            if switch_event.is_set():
                continue  # 切房间导致的中断,直接进下一轮
            push({"kind": "sys", "msg": f"采集中断,5秒后重连: {str(e)[:80]}"})
            time.sleep(5)


@app.on_event("startup")
async def _startup():
    global loop
    loop = asyncio.get_event_loop()
    s = Store(DB_PATH)                 # 确保建表
    blocked_ids.update(s.blocked_ids())  # 载入已有屏蔽名单
    s.close()
    threading.Thread(target=collector_thread, daemon=True).start()


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


@app.get("/api/summary")
def api_summary():
    c = _conn()
    try:
        return stats.summary(c)
    finally:
        c.close()


@app.get("/api/hotwords")
def api_hotwords():
    c = _conn()
    try:
        return stats.hotwords(c, 40)
    finally:
        c.close()


@app.get("/api/online_series")
def api_online_series():
    c = _conn()
    try:
        return stats.online_series(c)
    finally:
        c.close()


@app.get("/api/top_users")
def api_top_users():
    c = _conn()
    try:
        return stats.top_users(c, 10)
    finally:
        c.close()


@app.get("/api/danmu")
def api_danmu(limit: int = 60):
    c = _conn()
    try:
        rows = c.execute(
            f"SELECT user_id, nickname, content, created_at FROM danmu WHERE {stats.NB} "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"user_id": u, "nickname": a, "content": b, "created_at": d}
                for u, a, b, d in rows][::-1]
    finally:
        c.close()


@app.get("/api/voc")
def api_voc(range: int = 0):
    c = _conn()
    try:
        return stats.voc(c, range)
    finally:
        c.close()


@app.get("/api/voc_danmu")
def api_voc_danmu(category: str, range: int = 0, limit: int = 200):
    c = _conn()
    try:
        return stats.voc_danmu(c, category, range, limit)
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


@app.get("/api/user_danmu")
def api_user_danmu(user_id: str, limit: int = 100):
    c = _conn()
    try:
        return stats.user_danmu(c, user_id, limit)
    finally:
        c.close()


@app.get("/api/word_danmu")
def api_word_danmu(word: str, limit: int = 200):
    c = _conn()
    try:
        return stats.word_danmu(c, word, limit)
    finally:
        c.close()


@app.post("/api/block")
def api_block(user_id: str, nickname: str = ""):
    uid = (user_id or "").strip()
    if not uid:
        return {"ok": False}
    c = _conn()
    try:
        c.execute(
            "INSERT INTO blocklist(user_id,nickname,blocked_at) "
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
            "SELECT user_id, nickname, blocked_at FROM blocklist ORDER BY blocked_at DESC"
        ).fetchall()
        return [{"user_id": a, "nickname": b, "blocked_at": d} for a, b, d in rows]
    finally:
        c.close()


@app.get("/api/config")
def api_config():
    return {"web_rid": current_rid[0]}


@app.post("/api/switch")
def api_switch(web_rid: str):
    rid = (web_rid or "").strip()
    if rid:
        current_rid[0] = rid
        switch_event.set()   # 通知采集线程停当前浏览器、换新房间
        push({"kind": "switch", "web_rid": rid})
    return {"web_rid": current_rid[0]}


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
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
