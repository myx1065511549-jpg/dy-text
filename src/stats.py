"""
看板聚合统计。支持双数据源:所有查询按当前数据源 source 过滤,
避免两条采集链路同时入库造成重复计数。涉及用户的统计排除屏蔽名单。
"""
import re
import jieba
import datetime
from collections import Counter

STOPWORDS = set(
    "的 了 是 我 你 他 她 它 们 在 有 和 就 不 人 都 一 也 很 到 说 要 去 会 着 没 "
    "看 好 这 那 啊 吧 呢 吗 哦 呀 嘛 哈 什么 怎么 可以 直接 一个 现在 已经 我们 "
    "你们 他们 自己 这个 那个 不是 就是 还是 这样 那样 这里 大家".split()
)

# 排除屏蔽用户
NB = "user_id NOT IN (SELECT user_id FROM blocklist)"

def _voc_cats(conn):
    """VOC 分类从配置表读(界面可编辑,种子见 store.DEFAULT_VOC_CATS)。
    返回 [(category, [keywords], is_risk)]。"""
    rows = conn.execute(
        "SELECT category, keywords, is_risk FROM voc_config ORDER BY sort").fetchall()
    return [(c, [k.strip() for k in (kw or "").split(",") if k.strip()], bool(r))
            for c, kw, r in rows]


def _cur_session(conn):
    row = conn.execute(
        "SELECT id FROM session WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else None

def _scope(conn, source, session_id=None):
    """按数据源 + 场次过滤的 SQL 片段 + 参数。session_id 不传时取当前进行中的场次。"""
    sql, params = "", []
    if source:
        sql += " AND source=?"
        params.append(source)
    if session_id is None:
        session_id = _cur_session(conn)
    if session_id is not None:
        sql += " AND session_id=?"
        params.append(session_id)
    return sql, params


def _blocked_words(conn):
    return {r[0] for r in conn.execute("SELECT word FROM word_blocklist").fetchall()}


def _cut_time(range_min):
    if not range_min or range_min <= 0:
        return None
    return (datetime.datetime.now() - datetime.timedelta(minutes=range_min)
            ).strftime("%Y-%m-%d %H:%M:%S")


def hotwords(conn, limit=30, source=None, session_id=None):
    sc, sp = _scope(conn, source, session_id)
    bw = _blocked_words(conn)
    rows = conn.execute(f"SELECT content FROM danmu WHERE {NB}{sc}", sp).fetchall()
    cnt = Counter()
    for (c,) in rows:
        if not c or any(b in c for b in bw):
            continue
        for w in jieba.cut(c):
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS or w in bw or re.fullmatch(r"[0-9a-zA-Z]+", w):
                continue
            cnt[w] += 1
    return [{"word": w, "count": n} for w, n in cnt.most_common(limit)]


def voc(conn, range_min=0, source=None, session_id=None):
    cats = _voc_cats(conn)
    sc, sp = _scope(conn, source, session_id)
    bw = _blocked_words(conn)
    rows = conn.execute(f"SELECT content, created_at FROM danmu WHERE {NB}{sc}", sp).fetchall()
    ago5 = (datetime.datetime.now() - datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    cut = _cut_time(range_min)
    total = {c: 0 for c, _, _ in cats}
    recent = {c: 0 for c, _, _ in cats}
    for content, created in rows:
        if not content or any(b in content for b in bw):
            continue
        if cut and (not created or created < cut):
            continue
        for cat, kws, _ in cats:
            if any(k in content for k in kws):
                total[cat] += 1
                if created and created >= ago5:
                    recent[cat] += 1
    out = [{"category": c, "count": total[c], "recent": recent[c], "is_risk": r}
           for c, _, r in cats]
    # 风险类置顶,其余按命中数排
    out.sort(key=lambda x: (not x["is_risk"], -x["count"]))
    return out


def voc_danmu(conn, category, range_min=0, limit=200, source=None, session_id=None):
    kws = {c: k for c, k, _ in _voc_cats(conn)}.get(category)
    if not kws:
        return {"category": category, "total": 0, "danmu": []}
    sc, sp = _scope(conn, source, session_id)
    bw = _blocked_words(conn)
    cut = _cut_time(range_min)
    rows = conn.execute(
        f"SELECT nickname, content, created_at FROM danmu WHERE {NB}{sc} ORDER BY id DESC", sp).fetchall()
    out = []
    for nick, content, created in rows:
        if not content or any(b in content for b in bw):
            continue
        if cut and (not created or created < cut):
            continue
        if any(k in content for k in kws):
            out.append({"nickname": nick, "content": content, "created_at": created})
            if len(out) >= limit:
                break
    return {"category": category, "total": len(out), "danmu": out}


def voc_series(conn, source=None, session_id=None, bucket_min=5, max_buckets=72):
    """VOC 各分类按时间桶的命中数走势(管理端看问题何时爆发)。"""
    cats = _voc_cats(conn)
    sc, sp = _scope(conn, source, session_id)
    bw = _blocked_words(conn)
    rows = conn.execute(
        f"SELECT content, created_at FROM danmu WHERE {NB}{sc} AND created_at IS NOT NULL",
        sp).fetchall()
    empty = {"categories": [{"category": c, "is_risk": r} for c, _, r in cats], "series": []}
    if not rows:
        return empty

    def bucket(created):
        t = datetime.datetime.strptime(created[:16], "%Y-%m-%d %H:%M")
        return t - datetime.timedelta(minutes=t.minute % bucket_min)

    hits = {}
    lo = hi = None
    for content, created in rows:
        try:
            b = bucket(created)
        except ValueError:
            continue
        lo = b if lo is None or b < lo else lo
        hi = b if hi is None or b > hi else hi
        if not content or any(bb in content for bb in bw):
            continue
        for cat, kws, _ in cats:
            if any(k in content for k in kws):
                d = hits.setdefault(b, {})
                d[cat] = d.get(cat, 0) + 1
    if lo is None:
        return empty
    series = []
    step = datetime.timedelta(minutes=bucket_min)
    b = lo
    while b <= hi:
        series.append({"t": b.strftime("%H:%M"),
                       "counts": {c: hits.get(b, {}).get(c, 0) for c, _, _ in cats}})
        b += step
    return {"categories": empty["categories"], "series": series[-max_buckets:]}


def activity_series(conn, source=None, session_id=None):
    """每分钟弹幕/进场/点赞聚合,空桶补零(节奏时间轴用,与在线趋势同轴叠加)。"""
    sc, sp = _scope(conn, source, session_id)
    out = {}
    for table, expr, key in (("danmu", "COUNT(*)", "danmu"),
                             ("enter", "COUNT(*)", "enter"),
                             ("likes", "COALESCE(SUM(count),0)", "likes")):
        rows = conn.execute(
            f"SELECT substr(created_at,1,16) m, {expr} FROM {table} "
            f"WHERE {NB}{sc} AND created_at IS NOT NULL GROUP BY m", sp).fetchall()
        for m, n in rows:
            if len(m or "") == 16:
                out.setdefault(m, {"danmu": 0, "enter": 0, "likes": 0})[key] = n
    if not out:
        return []
    keys = sorted(out)
    lo = datetime.datetime.strptime(keys[0], "%Y-%m-%d %H:%M")
    hi = datetime.datetime.strptime(keys[-1], "%Y-%m-%d %H:%M")
    series = []
    t = lo
    while t <= hi:
        k = t.strftime("%Y-%m-%d %H:%M")
        d = out.get(k, {"danmu": 0, "enter": 0, "likes": 0})
        series.append({"t": k[11:], "date": k[:10], **d})
        t += datetime.timedelta(minutes=1)
    return series[-720:]  # 上限12小时


def danmu_at(conn, date, minute, limit=300, source=None, session_id=None):
    """某一分钟的弹幕原文(节奏时间轴点击回看)。"""
    sc, sp = _scope(conn, source, session_id)
    rows = conn.execute(
        f"SELECT nickname, content, created_at FROM danmu WHERE {NB}{sc} "
        f"AND substr(created_at,1,16)=? ORDER BY id LIMIT ?",
        sp + [f"{date} {minute}", limit]).fetchall()
    return {"minute": minute, "total": len(rows),
            "danmu": [{"nickname": a, "content": b, "created_at": c} for a, b, c in rows]}


def word_danmu(conn, word, limit=200, source=None, session_id=None):
    sc, sp = _scope(conn, source, session_id)
    rows = conn.execute(
        f"SELECT nickname, content, created_at FROM danmu WHERE content LIKE ? AND {NB}{sc} "
        "ORDER BY id DESC LIMIT ?", [f"%{word}%"] + sp + [limit]).fetchall()
    return {"word": word, "total": len(rows),
            "danmu": [{"nickname": a, "content": b, "created_at": c} for a, b, c in rows]}


def _count_since(conn, table, seconds, source=None, session_id=None):
    sc, sp = _scope(conn, source, session_id)
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE created_at >= datetime('now','localtime',?) "
        f"AND {NB}{sc}", [f"-{seconds} seconds"] + sp).fetchone()[0]


def summary(conn, source=None):
    sc, sp = _scope(conn, source)

    def cnt(t):
        return conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {NB}{sc}", sp).fetchone()[0]

    # 在线人数是房间级数据,两源报的是同一个值,只按场次过滤
    # (douyinLive 偶发整场不推 RoomStats,按源过滤会导致主源活跃时在线序列断供)
    osc, osp = _scope(conn, None)
    online = conn.execute(
        f"SELECT online_count FROM room_stat WHERE online_count IS NOT NULL{osc} "
        "ORDER BY id DESC LIMIT 1", osp).fetchone()
    distinct_users = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT user_id FROM danmu WHERE {NB}{sc} "
        f"UNION SELECT user_id FROM enter WHERE {NB}{sc})", sp + sp).fetchone()[0]
    enter_users = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM enter WHERE {NB}{sc}", sp).fetchone()[0]
    # 转化率交集口径,与 sessions_summary 一致
    speak_enter = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM danmu WHERE {NB}{sc} "
        f"AND user_id IN (SELECT user_id FROM enter WHERE {NB}{sc})", sp + sp).fetchone()[0]
    total_user = conn.execute("SELECT value FROM meta WHERE key='total_user'").fetchone()
    return {
        "danmu": cnt("danmu"), "gift": cnt("gift"),
        "enter": cnt("enter"), "likes": cnt("likes"),
        "online": online[0] if online else None,
        "total_user": int(total_user[0]) if total_user and total_user[0] else None,
        "distinct_users": distinct_users,
        "enter_users": enter_users,
        "talk_rate": round(speak_enter / enter_users, 3) if enter_users else None,
        "rates": {
            "danmu_min": _count_since(conn, "danmu", 60, source),
            "danmu_5min": _count_since(conn, "danmu", 300, source),
            "enter_min": _count_since(conn, "enter", 60, source),
            "enter_5min": _count_since(conn, "enter", 300, source),
            "like_5min": _count_since(conn, "likes", 300, source),
        },
    }


def online_series(conn, limit=600, session_id=None):
    """在线人数序列。房间级数据两源同值,不按源过滤,任一源断供由另一源补。"""
    sc, sp = _scope(conn, None, session_id)
    rows = conn.execute(
        f"SELECT created_at, online_count FROM room_stat "
        f"WHERE online_count IS NOT NULL{sc} ORDER BY id DESC LIMIT ?", sp + [limit]).fetchall()
    return [{"t": a, "v": b} for a, b in rows[::-1]]


def top_users(conn, limit=15, source=None, session_id=None):
    sc, sp = _scope(conn, source, session_id)
    rows = conn.execute(
        f"SELECT user_id, nickname, MAX(level) lv, COUNT(*) n FROM danmu "
        f"WHERE nickname!='' AND {NB}{sc} GROUP BY user_id ORDER BY n DESC LIMIT ?",
        sp + [limit]).fetchall()
    return [{"user_id": a, "nickname": b, "level": c, "count": d} for a, b, c, d in rows]


def user_danmu(conn, user_id, limit=100, source=None, session_id=None):
    sc, sp = _scope(conn, source, session_id)
    rows = conn.execute(
        f"SELECT content, created_at FROM danmu WHERE user_id=?{sc} ORDER BY id DESC LIMIT ?",
        [user_id] + sp + [limit]).fetchall()
    nick = conn.execute(
        "SELECT nickname FROM danmu WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return {
        "user_id": user_id,
        "nickname": nick[0] if nick else "",
        "total": len(rows),
        "danmu": [{"content": a, "created_at": b} for a, b in rows],
    }


def audience(conn, source=None, session_id=None):
    """发言观众画像:粉丝团占比/等级分布/性别比。备源无这些字段时 available=False。"""
    sc, sp = _scope(conn, source, session_id)
    total = conn.execute(f"SELECT COUNT(*) FROM danmu WHERE {NB}{sc}", sp).fetchone()[0]
    profiled = conn.execute(
        f"SELECT COUNT(*) FROM danmu WHERE {NB}{sc} AND level IS NOT NULL", sp).fetchone()[0]
    if not total or not profiled:
        return {"available": False}
    fans_danmu = conn.execute(
        f"SELECT COUNT(*) FROM danmu WHERE {NB}{sc} AND fans_level>0", sp).fetchone()[0]
    speakers = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM danmu WHERE {NB}{sc}", sp).fetchone()[0]
    fans_speakers = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM danmu WHERE {NB}{sc} AND fans_level>0",
        sp).fetchone()[0]
    levels = conn.execute(
        f"SELECT user_id, MAX(COALESCE(level,0)) FROM danmu WHERE {NB}{sc} GROUP BY user_id",
        sp).fetchall()
    buckets = [("Lv30+", 0), ("Lv20-29", 0), ("Lv10-19", 0), ("Lv1-9", 0), ("未知", 0)]
    buckets = dict(buckets)
    for _, lv in levels:
        if lv >= 30:
            buckets["Lv30+"] += 1
        elif lv >= 20:
            buckets["Lv20-29"] += 1
        elif lv >= 10:
            buckets["Lv10-19"] += 1
        elif lv >= 1:
            buckets["Lv1-9"] += 1
        else:
            buckets["未知"] += 1
    genders = {1: 0, 2: 0, 0: 0}
    for g, n in conn.execute(
            f"SELECT COALESCE(gender,0), COUNT(DISTINCT user_id) FROM danmu WHERE {NB}{sc} "
            "GROUP BY COALESCE(gender,0)", sp).fetchall():
        genders[g if g in (1, 2) else 0] += n
    return {
        "available": True,
        "danmu_total": total,
        "fans_danmu": fans_danmu,
        "fans_danmu_pct": round(fans_danmu / total, 3),
        "speakers": speakers,
        "fans_speakers": fans_speakers,
        "levels": [{"bucket": b, "count": n} for b, n in buckets.items()],
        "gender": {"male": genders[1], "female": genders[2], "unknown": genders[0]},
    }


def _session_source(conn, sid):
    """一场里两源都可能有数据,统计按该场数据更全的源,避免双源重复计数。"""
    rows = conn.execute(
        "SELECT source, COUNT(*) FROM danmu WHERE session_id=? GROUP BY source", (sid,)).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM enter WHERE session_id=? GROUP BY source", (sid,)).fetchall()
    if not rows:
        return None
    return max(rows, key=lambda x: (x[1], x[0] == "live"))[0]


def sessions_summary(conn, limit=30):
    """历史场次列表 + 每场核心指标与VOC分类占比。"""
    sess = conn.execute(
        "SELECT id, room_id, started_at, ended_at FROM session ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    bw = _blocked_words(conn)
    cats = _voc_cats(conn)
    out = []
    for sid, room, started, ended in sess:
        src = _session_source(conn, sid)
        sc, sp = _scope(conn, src, sid)

        def cnt(t):
            return conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {NB}{sc}", sp).fetchone()[0]

        speakers = conn.execute(
            f"SELECT COUNT(DISTINCT user_id) FROM danmu WHERE {NB}{sc}", sp).fetchone()[0]
        enters = conn.execute(
            f"SELECT COUNT(DISTINCT user_id) FROM enter WHERE {NB}{sc}", sp).fetchone()[0]
        # 转化率取交集口径:开播采集前已在房间的人会发言但没有进场记录,直接除会超100%
        speak_enter = conn.execute(
            f"SELECT COUNT(DISTINCT user_id) FROM danmu WHERE {NB}{sc} "
            f"AND user_id IN (SELECT user_id FROM enter WHERE {NB}{sc})",
            sp + sp).fetchone()[0]
        peak = conn.execute(
            "SELECT MAX(online_count) FROM room_stat WHERE session_id=?", (sid,)).fetchone()[0]
        voc_counts = {c: 0 for c, _, _ in cats}
        for (content,) in conn.execute(f"SELECT content FROM danmu WHERE {NB}{sc}", sp):
            if not content or any(b in content for b in bw):
                continue
            for cat, kws, _ in cats:
                if any(k in content for k in kws):
                    voc_counts[cat] += 1
        out.append({
            "id": sid, "room_id": room, "started_at": started, "ended_at": ended,
            "source": src, "danmu": cnt("danmu"), "enter": cnt("enter"),
            "gift": cnt("gift"), "likes": cnt("likes"),
            "speakers": speakers, "enter_users": enters,
            "talk_rate": round(speak_enter / enters, 3) if enters else None,
            "peak_online": peak,
            "voc": [{"category": c, "count": n} for c, n in
                    sorted(voc_counts.items(), key=lambda x: x[1], reverse=True) if n > 0],
        })
    return out
