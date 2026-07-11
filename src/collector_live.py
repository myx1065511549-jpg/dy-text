"""
主数据源采集器:基于 douyinLive(本地 Go 服务)。
职责:
  1. 启动/管理 douyinLive.exe 子进程(本地 WS 服务,默认端口 1088)。
  2. 连 ws://127.0.0.1:1088/ws/{room},把它推的 JSON 解成我们的记录(source='live')。
     这条源比浏览器 hook 更细:带真实标识 webcastUid、用户等级、粉丝团等级。
  3. 断线自动重连;支持外部 should_stop 停止(切房间/切源用)。
"""
import os
import sys
import json
import time
import subprocess
import threading

import websocket

DL_PORT = int(os.environ.get("DL_PORT", "1088"))
_proc = None


def _dl_dir():
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "douyinLive")      # 打包后
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "tools", "douyinLive")  # 开发时


def douyinlive_available():
    return os.path.exists(os.path.join(_dl_dir(), "douyinLive.exe"))


def ensure_douyinlive():
    """启动 douyinLive.exe(若未在跑)。返回是否可用。"""
    global _proc
    d = _dl_dir()
    exe = os.path.join(d, "douyinLive.exe")
    cfg = os.path.join(d, "config.yaml")
    if not os.path.exists(exe):
        return False
    if _proc is not None and _proc.poll() is None:
        return True
    try:
        args = [exe, "--config", cfg, "--port", str(DL_PORT), "--log-level", "info"]
        _proc = subprocess.Popen(
            args, cwd=d,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,   # 不继承 Playwright node 驱动的管道句柄,避免 EPIPE
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(2.5)
        return _proc.poll() is None
    except Exception:
        return False


def stop_douyinlive():
    global _proc
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
        except Exception:
            pass


def _num(x):
    try:
        return int(x)
    except Exception:
        return None


def parse_live_msg(d: dict):
    """把 douyinLive 一条 JSON 解成我们的记录。"""
    method = d.get("method")
    common = d.get("common") or {}
    room_id = str(common.get("roomId") or "")
    u = d.get("user") or {}
    if method == "WebcastChatMessage":
        pg = u.get("payGrade") or {}
        fc = (u.get("fansClub") or {}).get("data") or {}
        return {"type": "chat", "source": "live", "room_id": room_id,
                "user_id": str(u.get("webcastUid") or u.get("idStr") or ""),
                "sec_uid": u.get("webcastUid") or "",
                "nickname": u.get("nickname") or "",
                "gender": _num(u.get("gender")),
                "level": _num(pg.get("level")),
                "fans_level": _num(fc.get("level")),
                "content": d.get("content") or "",
                "ts": _num(d.get("eventTime"))}
    if method == "WebcastMemberMessage":
        return {"type": "enter", "source": "live", "room_id": room_id,
                "user_id": str(u.get("webcastUid") or u.get("idStr") or ""),
                "nickname": u.get("nickname") or "",
                "ts": _num(d.get("eventTime"))}
    if method == "WebcastLikeMessage":
        return {"type": "like", "source": "live", "room_id": room_id,
                "user_id": str(u.get("webcastUid") or u.get("idStr") or ""),
                "nickname": u.get("nickname") or "",
                "count": _num(d.get("count")), "ts": _num(d.get("eventTime"))}
    if method == "WebcastGiftMessage":
        g = d.get("gift") or {}
        return {"type": "gift", "source": "live", "room_id": room_id,
                "user_id": str(u.get("webcastUid") or u.get("idStr") or ""),
                "nickname": u.get("nickname") or "",
                "gift_name": g.get("name") or d.get("giftName") or "",
                "count": _num(d.get("repeatCount") or d.get("count")) or 1,
                "ts": _num(d.get("eventTime"))}
    if method == "WebcastRoomStatsMessage":
        online = _num(d.get("displayValue"))
        if online is not None:
            return {"type": "room_stat", "source": "live", "room_id": room_id,
                    "online_count": online}
    if method == "WebcastRoomUserSeqMessage":
        tu = _num(d.get("totalUser") or d.get("total"))
        if tu:
            return {"type": "total_user", "total_user": tu}
    return None


def collect(room, on_record, should_stop=None):
    """连 douyinLive WS 持续采集;断线重连;should_stop 触发即停。"""
    def on_message(ws, message):
        try:
            d = json.loads(message)
        except Exception:
            return
        rec = parse_live_msg(d)
        if rec:
            on_record(rec)

    url = f"ws://127.0.0.1:{DL_PORT}/ws/{room}"
    while not (should_stop and should_stop()):
        ws = websocket.WebSocketApp(url, on_message=on_message,
                                    on_error=lambda w, e: None)
        stop_flag = {"v": False}

        def watch():
            while not stop_flag["v"]:
                if should_stop and should_stop():
                    try:
                        ws.close()
                    except Exception:
                        pass
                    return
                time.sleep(0.5)

        threading.Thread(target=watch, daemon=True).start()
        try:
            ws.run_forever()
        except Exception:
            pass
        stop_flag["v"] = True
        if should_stop and should_stop():
            break
        time.sleep(2)   # 断线,2 秒后重连
