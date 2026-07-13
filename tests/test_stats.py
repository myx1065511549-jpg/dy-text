"""stats.py 聚合统计单测:场次过滤、双源不重复计数、场次汇总。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from store import Store
import stats


def _mk():
    db = tempfile.mktemp(suffix=".db")
    return db, Store(db)


def _chat(s, uid, content, source="live"):
    s.save({"type": "chat", "room_id": "1", "user_id": uid, "nickname": "n" + uid,
            "content": content, "ts": 1, "source": source})


def _enter(s, uid, source="live"):
    s.save({"type": "enter", "room_id": "1", "user_id": uid, "nickname": "n" + uid,
            "ts": 1, "source": source})


def test_stats_scoped_to_current_session():
    """summary/top_users 只统计当前场次,旧场数据不混入。"""
    db, s = _mk()
    _chat(s, "u1", "第一场弹幕")
    _enter(s, "u1")
    s.commit()
    s.new_session("1")
    _chat(s, "u2", "第二场弹幕")
    _chat(s, "u2", "第二场再来一条")
    _enter(s, "u2")
    _enter(s, "u3")
    s.commit()

    sm = stats.summary(s.conn, "live")
    assert sm["danmu"] == 2, sm
    assert sm["enter"] == 2, sm
    assert sm["distinct_users"] == 2, sm  # u2 u3

    top = stats.top_users(s.conn, 10, "live")
    assert len(top) == 1 and top[0]["user_id"] == "u2" and top[0]["count"] == 2

    s.close()
    os.remove(db)


def test_stats_source_filter_no_double_count():
    """双源同时入库,按 source 过滤后不重复计数。"""
    db, s = _mk()
    _chat(s, "u1", "同一条", source="live")
    _chat(s, "111111", "同一条", source="browser")
    s.commit()
    assert stats.summary(s.conn, "live")["danmu"] == 1
    assert stats.summary(s.conn, "browser")["danmu"] == 1
    s.close()
    os.remove(db)


def test_sessions_summary():
    db, s = _mk()
    # 第一场:2人发言、3人进场,含一条VOC(价格)
    _chat(s, "u1", "多少钱一件")
    _chat(s, "u2", "主播好")
    for u in ("u1", "u2", "u3"):
        _enter(s, u)
    s.commit()
    s.new_session("2")
    # 第二场:双源混入,live 更全应按 live 统计
    _chat(s, "u4", "有优惠吗", source="live")
    _chat(s, "u5", "怎么买", source="live")
    _chat(s, "111111", "有优惠吗", source="browser")
    _enter(s, "u4", source="live")
    s.commit()

    out = stats.sessions_summary(s.conn)
    assert len(out) == 2
    cur, old = out[0], out[1]  # 倒序,当前场在前

    assert old["ended_at"] is not None
    assert old["danmu"] == 2 and old["enter"] == 3
    assert old["speakers"] == 2 and old["enter_users"] == 3
    assert old["talk_rate"] == round(2 / 3, 3)  # u1 u2 都发言且都有进场记录
    assert any(v["category"] == "价格优惠" and v["count"] == 1 for v in old["voc"])

    assert cur["ended_at"] is None
    assert cur["source"] == "live"
    assert cur["danmu"] == 2, cur  # 不含 browser 那条
    assert cur["enter"] == 1
    # u4 u5 发言但只有 u4 有进场记录 → 交集口径 1/1,不会超100%
    assert cur["talk_rate"] == 1.0

    s.close()
    os.remove(db)


def test_sessions_summary_excludes_blocked():
    """屏蔽用户不计入场次汇总。"""
    db, s = _mk()
    _chat(s, "u1", "正常弹幕")
    _chat(s, "spam", "价格价格价格")
    s.commit()
    s.block("spam", "工作人员")
    out = stats.sessions_summary(s.conn)
    assert out[0]["danmu"] == 1
    assert out[0]["speakers"] == 1
    s.close()
    os.remove(db)


def test_voc_risk_category():
    """风险负面分类命中并置顶,is_risk 标记正确。"""
    db, s = _mk()
    _chat(s, "u1", "这是假货吧避雷")
    _chat(s, "u2", "多少钱")
    _chat(s, "u3", "主播好")
    s.commit()
    out = stats.voc(s.conn, 0, "live")
    assert out[0]["category"] == "风险负面" and out[0]["is_risk"] is True
    assert out[0]["count"] == 1
    assert {v["category"]: v["count"] for v in out}["价格优惠"] == 1
    s.close()
    os.remove(db)


def test_voc_config_editable():
    """改配置表后 voc/voc_danmu 按新分类生效。"""
    db, s = _mk()
    _chat(s, "u1", "包邮到新疆吗")
    s.commit()
    assert s.set_voc_config([
        {"category": "物流范围", "keywords": "包邮, 新疆, 偏远", "is_risk": False}])
    out = stats.voc(s.conn, 0, "live")
    assert len(out) == 1 and out[0]["category"] == "物流范围" and out[0]["count"] == 1
    d = stats.voc_danmu(s.conn, "物流范围", 0, 10, "live")
    assert d["total"] == 1 and d["danmu"][0]["content"] == "包邮到新疆吗"
    # 旧分类已不存在
    assert stats.voc_danmu(s.conn, "价格优惠", 0, 10, "live")["total"] == 0
    s.close()
    os.remove(db)


def test_voc_series_buckets():
    """voc_series 按时间桶计数,空桶补零保证时间轴连续。"""
    db, s = _mk()
    _chat(s, "u1", "多少钱")
    _chat(s, "u2", "有优惠吗")
    _chat(s, "u3", "无关弹幕")
    s.commit()
    # 手工把三条弹幕拉开到不同时间桶:10:00 / 10:00 / 10:12
    ids = [r[0] for r in s.conn.execute("SELECT id FROM danmu ORDER BY id").fetchall()]
    for i, t in zip(ids, ["2026-07-13 10:00:30", "2026-07-13 10:01:10", "2026-07-13 10:12:00"]):
        s.conn.execute("UPDATE danmu SET created_at=? WHERE id=?", (t, i))
    s.commit()
    out = stats.voc_series(s.conn, "live", bucket_min=5)
    assert any(c["category"] == "风险负面" for c in out["categories"])
    ts = [p["t"] for p in out["series"]]
    assert ts == ["10:00", "10:05", "10:10"]  # 空桶10:05补零
    assert out["series"][0]["counts"]["价格优惠"] == 2
    assert out["series"][1]["counts"]["价格优惠"] == 0
    s.close()
    os.remove(db)


def test_activity_series_and_danmu_at():
    """activity_series 分钟聚合补零;danmu_at 取指定分钟原文。"""
    db, s = _mk()
    _chat(s, "u1", "第一分钟弹幕A")
    _chat(s, "u2", "第一分钟弹幕B")
    _chat(s, "u3", "第三分钟弹幕")
    _enter(s, "u4")
    s.save({"type": "like", "room_id": "1", "user_id": "u5", "nickname": "n5",
            "count": 7, "ts": 1, "source": "live"})
    s.commit()
    times = {1: "2026-07-13 10:00:10", 2: "2026-07-13 10:00:50", 3: "2026-07-13 10:02:20"}
    for i, t in times.items():
        s.conn.execute("UPDATE danmu SET created_at=? WHERE id=?", (t, i))
    s.conn.execute("UPDATE enter SET created_at='2026-07-13 10:00:30'")
    s.conn.execute("UPDATE likes SET created_at='2026-07-13 10:02:00'")
    s.commit()

    out = stats.activity_series(s.conn, "live")
    assert [p["t"] for p in out] == ["10:00", "10:01", "10:02"]
    assert out[0] == {"t": "10:00", "date": "2026-07-13", "danmu": 2, "enter": 1, "likes": 0}
    assert out[1]["danmu"] == 0 and out[1]["enter"] == 0  # 空桶补零
    assert out[2]["danmu"] == 1 and out[2]["likes"] == 7  # 点赞取SUM(count)

    d = stats.danmu_at(s.conn, "2026-07-13", "10:00", 100, "live")
    assert d["total"] == 2
    assert {x["content"] for x in d["danmu"]} == {"第一分钟弹幕A", "第一分钟弹幕B"}
    s.close()
    os.remove(db)


def _chat_full(s, uid, content, level=None, fans=None, gender=None, source="live"):
    s.save({"type": "chat", "room_id": "1", "user_id": uid, "nickname": "n" + uid,
            "content": content, "ts": 1, "source": source,
            "level": level, "fans_level": fans, "gender": gender})


def test_audience_profile():
    """画像:粉丝团占比/等级桶/性别;备源无字段时 available=False。"""
    db, s = _mk()
    _chat_full(s, "u1", "a", level=35, fans=5, gender=1)
    _chat_full(s, "u1", "b", level=35, fans=5, gender=1)
    _chat_full(s, "u2", "c", level=12, fans=0, gender=2)
    _chat_full(s, "u3", "d", level=3, gender=1)
    s.commit()
    a = stats.audience(s.conn, "live")
    assert a["available"] is True
    assert a["danmu_total"] == 4 and a["fans_danmu"] == 2
    assert a["fans_danmu_pct"] == 0.5
    assert a["speakers"] == 3 and a["fans_speakers"] == 1
    lv = {x["bucket"]: x["count"] for x in a["levels"]}
    assert lv["Lv30+"] == 1 and lv["Lv10-19"] == 1 and lv["Lv1-9"] == 1
    assert a["gender"] == {"male": 2, "female": 1, "unknown": 0}

    # 备源:level 全 NULL → 不可用
    db2, s2 = _mk()
    _chat(s2, "111111", "备源弹幕", source="browser")
    s2.commit()
    assert stats.audience(s2.conn, "browser")["available"] is False
    s.close(); s2.close()
    os.remove(db); os.remove(db2)


def test_online_series_merges_sources():
    """在线人数是房间级数据,不按源过滤:主源断供时备源的点仍在序列里。"""
    db, s = _mk()
    s.save({"type": "room_stat", "room_id": "1", "online_count": 100, "ts": 1, "source": "live"})
    s.save({"type": "room_stat", "room_id": "1", "online_count": 105, "ts": 2, "source": "browser"})
    s.save({"type": "room_stat", "room_id": "1", "online_count": 110, "ts": 3, "source": "browser"})
    s.commit()
    out = stats.online_series(s.conn)
    assert [p["v"] for p in out] == [100, 105, 110]
    # summary 的当前在线取最新一条,同样跨源
    assert stats.summary(s.conn, "live")["online"] == 110
    # 场次汇总峰值跨源
    assert stats.sessions_summary(s.conn)[0]["peak_online"] == 110
    s.close()
    os.remove(db)


def test_summary_talk_rate():
    """summary 的发言转化率:交集口径。"""
    db, s = _mk()
    _chat(s, "u1", "发言且进场")
    _chat(s, "u9", "只发言没进场")
    for u in ("u1", "u2", "u3", "u4"):
        _enter(s, u)
    s.commit()
    sm = stats.summary(s.conn, "live")
    assert sm["enter_users"] == 4
    assert sm["talk_rate"] == 0.25  # 只有 u1 是进场后开口
    s.close()
    os.remove(db)


if __name__ == "__main__":
    test_stats_scoped_to_current_session()
    test_stats_source_filter_no_double_count()
    test_sessions_summary()
    test_sessions_summary_excludes_blocked()
    test_voc_risk_category()
    test_voc_config_editable()
    test_voc_series_buckets()
    test_activity_series_and_danmu_at()
    test_audience_profile()
    test_online_series_merges_sources()
    test_summary_talk_rate()
    print("test_stats OK")
