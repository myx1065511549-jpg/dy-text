"""
模块四:protobuf 帧解析。
读取 browser_frames.b64 里捕获的真实帧,逐帧解析:
  PushFrame -> (payload 若 gzip 则解压) -> Response -> 遍历 messagesList
按 method 解出弹幕(WebcastChatMessage)、进场、点赞、礼物等。

结果写文件,不依赖终端输出。
"""
import os
import sys
import gzip
import json
import base64

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "proto"))
import douyin_pb2 as dy  # noqa: E402


def _maybe_gunzip(data: bytes) -> bytes:
    if len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B:
        try:
            return gzip.decompress(data)
        except Exception:
            return data
    return data


def parse_frame(raw: bytes) -> dict:
    frame = dy.PushFrame()
    frame.ParseFromString(raw)
    info = {"payloadType": frame.payloadType, "method": frame.method, "messages": []}
    if not frame.payload:
        return info
    body = _maybe_gunzip(frame.payload)
    resp = dy.Response()
    try:
        resp.ParseFromString(body)
    except Exception as e:
        info["response_error"] = str(e)[:120]
        return info
    info["needAck"] = resp.needAck
    for m in resp.messagesList:
        item = {"method": m.method}
        try:
            if m.method == "WebcastChatMessage":
                cm = dy.ChatMessage()
                cm.ParseFromString(m.payload)
                item["nickname"] = cm.user.nickName
                item["content"] = cm.content
            elif m.method == "WebcastMemberMessage":
                mm = dy.MemberMessage()
                mm.ParseFromString(m.payload)
                item["nickname"] = mm.user.nickName
                item["member_count"] = mm.memberCount
            elif m.method == "WebcastLikeMessage":
                lm = dy.LikeMessage()
                lm.ParseFromString(m.payload)
                item["nickname"] = lm.user.nickName
                item["like_count"] = lm.count
            elif m.method == "WebcastGiftMessage":
                gm = dy.GiftMessage()
                gm.ParseFromString(m.payload)
                item["nickname"] = gm.user.nickName
                item["gift"] = gm.gift.name
                item["repeat"] = gm.repeatCount
        except Exception as e:
            item["decode_error"] = str(e)[:120]
        info["messages"].append(item)
    return info


def parse_records(raw: bytes) -> list:
    """把一帧解成规范化记录列表(带 type 字段),直接供入库。"""
    records = []
    frame = dy.PushFrame()
    frame.ParseFromString(raw)
    if not frame.payload:
        return records
    resp = dy.Response()
    try:
        resp.ParseFromString(_maybe_gunzip(frame.payload))
    except Exception:
        return records
    for m in resp.messagesList:
        try:
            if m.method == "WebcastChatMessage":
                x = dy.ChatMessage(); x.ParseFromString(m.payload)
                records.append({"type": "chat", "room_id": str(x.common.roomId),
                                "user_id": str(x.user.id), "nickname": x.user.nickName,
                                "gender": x.user.gender, "content": x.content,
                                "ts": x.common.createTime})
            elif m.method == "WebcastMemberMessage":
                x = dy.MemberMessage(); x.ParseFromString(m.payload)
                records.append({"type": "enter", "room_id": str(x.common.roomId),
                                "user_id": str(x.user.id), "nickname": x.user.nickName,
                                "ts": x.common.createTime})
            elif m.method == "WebcastLikeMessage":
                x = dy.LikeMessage(); x.ParseFromString(m.payload)
                records.append({"type": "like", "room_id": str(x.common.roomId),
                                "user_id": str(x.user.id), "nickname": x.user.nickName,
                                "count": x.count, "ts": x.common.createTime})
            elif m.method == "WebcastGiftMessage":
                x = dy.GiftMessage(); x.ParseFromString(m.payload)
                records.append({"type": "gift", "room_id": str(x.common.roomId),
                                "user_id": str(x.user.id), "nickname": x.user.nickName,
                                "gift_name": x.gift.name, "count": x.repeatCount,
                                "ts": x.common.createTime})
            elif m.method == "WebcastRoomStatsMessage":
                x = dy.RoomStatsMessage(); x.ParseFromString(m.payload)
                records.append({"type": "room_stat", "room_id": str(x.common.roomId),
                                "online_count": x.displayValue,
                                "ts": x.common.createTime})
            elif m.method == "WebcastRoomUserSeqMessage":
                x = dy.RoomUserSeqMessage(); x.ParseFromString(m.payload)
                if x.totalUser:
                    records.append({"type": "total_user", "total_user": x.totalUser})
        except Exception:
            continue
    return records


def main(path="browser_frames.b64"):
    out = {"frames": 0, "chat": [], "method_counts": {}, "errors": 0}
    if not os.path.exists(path):
        out["error"] = f"no file: {path}"
        return out
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    out["frames"] = len(lines)
    for b64 in lines:
        try:
            info = parse_frame(base64.b64decode(b64))
        except Exception as e:
            out["errors"] += 1
            continue
        for m in info.get("messages", []):
            meth = m.get("method", "?")
            out["method_counts"][meth] = out["method_counts"].get(meth, 0) + 1
            if meth == "WebcastChatMessage" and m.get("content"):
                out["chat"].append({"nickname": m.get("nickname", ""),
                                    "content": m["content"]})
    return out


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "browser_frames.b64"
    result = main(path)
    # 直接写 UTF-8 文件,避开 Windows stdout GBK 乱码
    with open("parse_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("frames:", result["frames"], "chat:", len(result["chat"]),
          "-> parse_result.json")
