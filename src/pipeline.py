"""
采集管道:浏览器采集 -> protobuf 解析 -> SQLite 入库。
一条常驻链:collector.collect 每收到一帧,parse_records 解成记录,Store 落库。
阶段二用它验证"真实弹幕能持续入库"。
结果写 pipeline_result.json(UTF-8),不依赖终端输出。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collector_browser import collect
from parse import parse_records
from store import Store


def run(web_rid: str, seconds: int = 30, db_path: str = "danmu.db") -> dict:
    store = Store(db_path)
    stats = {"frames": 0, "records": 0}

    def on_frame(raw: bytes):
        stats["frames"] += 1
        recs = parse_records(raw)
        for rec in recs:
            if store.save(rec):
                stats["records"] += 1
        if recs:
            store.commit()

    collect(web_rid, on_frame, seconds=seconds)
    store.commit()
    result = {
        "web_rid": web_rid,
        "seconds": seconds,
        "stats": stats,
        "db_counts": store.counts(),
        "recent_danmu": store.recent_danmu(10),
    }
    store.close()
    return result


if __name__ == "__main__":
    web_rid = sys.argv[1] if len(sys.argv) > 1 else "292525714929"
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    result = run(web_rid, secs)
    with open("pipeline_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("frames:", result["stats"]["frames"],
          "records:", result["stats"]["records"], "-> pipeline_result.json")
