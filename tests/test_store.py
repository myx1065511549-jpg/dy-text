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


def test_session_archive():
    """new_session 后旧数据保留,新记录打新场次,当前场不允许删。"""
    db = tempfile.mktemp(suffix=".db")
    s = Store(db)
    s.save({"type": "chat", "room_id": "1", "user_id": "u1", "nickname": "n1",
            "content": "第一场", "ts": 1, "source": "live"})
    s.commit()
    sid1 = s.current_session()
    sid2 = s.new_session("1")
    assert sid2 != sid1
    s.save({"type": "chat", "room_id": "1", "user_id": "u2", "nickname": "n2",
            "content": "第二场", "ts": 2, "source": "live"})
    s.commit()

    # 旧数据没删,两场各一条且session_id不同
    assert s.counts()["danmu"] == 2
    rows = s.conn.execute("SELECT content, session_id FROM danmu ORDER BY id").fetchall()
    assert rows[0] == ("第一场", sid1)
    assert rows[1] == ("第二场", sid2)

    # 场次列表:第一场已结束,第二场进行中
    sess = s.sessions()
    assert len(sess) == 2
    assert sess[0]["id"] == sid2 and sess[0]["ended_at"] is None
    assert sess[1]["id"] == sid1 and sess[1]["ended_at"] is not None

    # 当前场拒删,历史场删除连带数据
    assert s.delete_session(sid2) is False
    assert s.delete_session(sid1) is True
    assert s.counts()["danmu"] == 1
    assert len(s.sessions()) == 1

    s.close()
    os.remove(db)


def test_new_session_resets_total_user():
    db = tempfile.mktemp(suffix=".db")
    s = Store(db)
    s.set_meta("total_user", 12345)
    s.commit()
    s.new_session("1")
    assert s.get_meta("total_user") is None
    s.close()
    os.remove(db)


if __name__ == "__main__":
    test_store_roundtrip()
    test_session_archive()
    test_new_session_resets_total_user()
    print("test_store OK")
