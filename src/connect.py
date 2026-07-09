"""
模块三:WebSocket 连接连通性测试。
流程:抓房间信息 -> 拼 wss 查询参数 -> 用 Signer 算 signature -> 连抖音 IM wss。
本测试只统计一段时间内收到的二进制帧数量和字节数:
只要能收到帧,就说明签名被抖音接受、连接建立成功(M2+M3 同时验证)。
解析帧内容是 M4 的事,这里不解析。

所有结果写文件,不依赖终端输出。
"""
import sys
import json
import time
import random
import string
import threading
from urllib.parse import urlencode

_MST_CHARS = string.ascii_letters + string.digits + "-_"


def gen_ms_token(n: int = 107) -> str:
    return "".join(random.choice(_MST_CHARS) for _ in range(n))

import websocket
from fetch_room import fetch_room
from sign import Signer

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

WSS_HOST = "wss://webcast5-ws-web-lf.douyin.com/webcast/im/push/v2/"


def build_params(room_id: str, user_unique_id: str) -> dict:
    return {
        "app_name": "douyin_web",
        "version_code": "180800",
        "webcast_sdk_version": "1.0.14-beta.0",
        "update_version_code": "1.0.14-beta.0",
        "compress": "gzip",
        "device_platform": "web",
        "cookie_enabled": "true",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Mozilla",
        "browser_version": UA,
        "browser_online": "true",
        "tz_name": "Asia/Shanghai",
        "cursor": "",
        "internal_ext": "",
        "host": "https://live.douyin.com",
        "aid": "6383",
        "live_id": "1",
        "did_rule": "3",
        "endpoint": "live_pc",
        "support_wrds": "1",
        "user_unique_id": user_unique_id,
        "im_path": "/webcast/im/fetch/",
        "identity": "audience",
        "need_persist_msg_count": "15",
        "insert_task_id": "",
        "live_reason": "",
        "room_id": room_id,
        "heartbeatDuration": "0",
    }


def run_test(web_rid: str, seconds: int = 15) -> dict:
    out = {"stage": "start", "web_rid": web_rid}
    try:
        info = fetch_room(web_rid)
        out["room_id"] = info["room_id"]
        out["status"] = info["status"]
        out["ttwid_got"] = bool(info["ttwid"])
        if not (info["room_id"] and info["ttwid"]):
            out["stage"] = "fetch_room_incomplete"
            return out

        # 优先用页面里的真实 user_unique_id,拿不到再退回随机(随机大概率 DEVICE_BLOCKED)
        user_unique_id = info.get("user_unique_id") or str(
            random.randint(7300000000000000000, 7399999999999999999))
        out["user_unique_id"] = user_unique_id
        params = build_params(info["room_id"], user_unique_id)

        # msToken 参与设备信任,参数和 cookie 都要带
        ms_token = info.get("cookies", {}).get("msToken") or gen_ms_token()
        params["msToken"] = ms_token

        signer = Signer()
        signature = signer.sign(params)
        out["signature"] = signature
        params["signature"] = signature
        out["stage"] = "signed"

        wss_url = WSS_HOST + "?" + urlencode(params)
        out["wss_url_len"] = len(wss_url)

        # 用完整 cookie 集(含 ttwid、msToken 等),不只 ttwid
        cookie_jar = dict(info.get("cookies", {}))
        cookie_jar.setdefault("ttwid", info["ttwid"])
        cookie_jar["msToken"] = ms_token
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_jar.items())
        out["cookie_keys"] = list(cookie_jar.keys())

        stats = {"frames": 0, "bytes": 0, "first_frame_ms": None,
                 "opened": False, "error": None, "close": None}
        t0 = time.time()

        def on_open(ws):
            stats["opened"] = True

        def on_message(ws, message):
            stats["frames"] += 1
            stats["bytes"] += len(message) if message else 0
            if stats["first_frame_ms"] is None:
                stats["first_frame_ms"] = int((time.time() - t0) * 1000)

        def on_error(ws, err):
            stats["error"] = str(err)[:300]

        def on_close(ws, code, msg):
            stats["close"] = {"code": code, "msg": str(msg)[:120] if msg else None}

        ws = websocket.WebSocketApp(
            wss_url,
            header={"User-Agent": UA},
            cookie=cookie_str,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        # 到点强制关闭
        threading.Timer(seconds, ws.close).start()
        ws.run_forever(ping_interval=0)

        out["stats"] = stats
        out["stage"] = "done"
        out["verdict"] = "SIGNATURE_ACCEPTED" if stats["frames"] > 0 else "NO_FRAMES"
    except Exception as e:
        out["error_type"] = type(e).__name__
        out["error"] = str(e)[:800]
    return out


if __name__ == "__main__":
    web_rid = sys.argv[1] if len(sys.argv) > 1 else "292525714929"
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    print(json.dumps(run_test(web_rid, secs), ensure_ascii=False, indent=2))
