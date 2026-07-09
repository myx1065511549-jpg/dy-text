"""store.py 存取往返单测。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from store import Store


def test_store_roundtrip():
    db = tempfile.mktemp(suffix=".db")
    s = Store(db)
    assert s.save({"type": "chat", "room_id": "1", "user_id": "u1",
                   "nickname": "n1", "gender": 1, "content": "hi", "ts": 100})
    assert s.save({"type": "enter", "room_id": "1", "user_id": "u2",
                   "nickname": "n2", "ts": 101})
    assert s.save({"type": "like", "room_id": "1", "user_id": "u3",
                   "nickname": "n3", "count": 5, "ts": 102})
    assert s.save({"type": "gift", "room_id": "1", "user_id": "u4",
                   "nickname": "n4", "gift_name": "玫瑰", "count": 2, "ts": 103})
    assert s.save({"type": "unknown"}) is False  # 未知类型不入库
    s.commit()

    c = s.counts()
    assert c["danmu"] == 1, c
    assert c["enter"] == 1, c
    assert c["likes"] == 1, c
    assert c["gift"] == 1, c

    recent = s.recent_danmu(5)
    assert len(recent) == 1
    assert recent[0]["content"] == "hi"
    assert recent[0]["nickname"] == "n1"

    s.close()
    os.remove(db)


if __name__ == "__main__":
    test_store_roundtrip()
    print("test_store_roundtrip OK")
