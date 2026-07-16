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


def test_products_dict():
    """商品字典 upsert:同 product_id 更新不新增,按 idx 排序,归当前场次。"""
    db = tempfile.mktemp(suffix=".db")
    s = Store(db)
    s.current_session("1")
    s.save_products("1", [
        {"product_id": "p2", "title": "商品二", "price": 8800, "idx": 2},
        {"product_id": "p1", "title": "商品一", "price": 16800, "idx": 1},
    ])
    ps = s.products()
    assert [p["product_id"] for p in ps] == ["p1", "p2"]  # 按 idx 排序
    assert ps[0]["title"] == "商品一" and ps[0]["price"] == 16800
    # 改价+上新品:同id更新,新id新增
    s.save_products("1", [
        {"product_id": "p1", "title": "商品一改", "price": 9900, "idx": 1},
        {"product_id": "p3", "title": "商品三", "price": 100, "idx": 3},
    ])
    ps = s.products()
    assert len(ps) == 3
    assert next(p for p in ps if p["product_id"] == "p1")["title"] == "商品一改"
    # 新场次商品字典独立
    s.new_session("1")
    assert s.products() == []
    s.close()
    os.remove(db)


def test_explain_dedup():
    """讲解信号每5秒一条心跳,只在换品时打点。"""
    db = tempfile.mktemp(suffix=".db")
    s = Store(db)
    s.current_session("1")
    for _ in range(3):
        s.save({"type": "explain", "room_id": "1", "product_id": "p1", "status": 2, "ts": 1})
    s.save({"type": "explain", "room_id": "1", "product_id": "p2", "status": 2, "ts": 2})
    s.save({"type": "explain", "room_id": "1", "product_id": "p2", "status": 2, "ts": 3})
    s.save({"type": "explain", "room_id": "1", "product_id": "p1", "status": 2, "ts": 4})
    s.commit()
    rows = s.conn.execute(
        "SELECT product_id FROM explain_event ORDER BY id").fetchall()
    # p1(3条合1) -> p2(2条合1) -> p1(回讲再打1)
    assert [r[0] for r in rows] == ["p1", "p2", "p1"]
    s.close()
    os.remove(db)


if __name__ == "__main__":
    test_store_roundtrip()
    test_session_archive()
    test_new_session_resets_total_user()
    test_products_dict()
    test_explain_dedup()
    print("test_store OK")
