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

VOC_CATS = [
    ("价格优惠", ["多少钱", "价格", "优惠", "便宜", "贵", "折扣", "券", "打折", "降价", "返现", "几块", "多少"]),
    ("链接下单", ["链接", "怎么买", "下单", "小黄车", "购物车", "几号", "第几", "上链接", "拍下", "哪里买", "怎么拍", "拍了"]),
    ("库存补货", ["库存", "有货", "还有", "补货", "断货", "卖完", "没货", "抢", "秒没", "还有吗"]),
    ("发货售后", ["发货", "物流", "快递", "什么时候到", "几天到", "退款", "退货", "换货", "售后", "投诉", "骗", "假货", "坏了", "客服"]),
    ("质量效果", ["质量", "效果", "怎么样", "真的假的", "材质", "靠谱", "耐用", "好用吗", "有用吗"]),
    ("尺码型号", ["尺码", "型号", "多大", "尺寸", "码数", "大小", "身高", "体重", "多重", "适合"]),
]


def _src(source):
    """按数据源过滤的 SQL 片段 + 参数。"""
    return (" AND source=?", [source]) if source else ("", [])


def _blocked_words(conn):
    return {r[0] for r in conn.execute("SELECT word FROM word_blocklist").fetchall()}


def _cut_time(range_min):
    if not range_min or range_min <= 0:
        return None
    return (datetime.datetime.now() - datetime.timedelta(minutes=range_min)
            ).strftime("%Y-%m-%d %H:%M:%S")


def hotwords(conn, limit=30, source=None):
    sc, sp = _src(source)
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


def voc(conn, range_min=0, source=None):
    sc, sp = _src(source)
    bw = _blocked_words(conn)
    rows = conn.execute(f"SELECT content, created_at FROM danmu WHERE {NB}{sc}", sp).fetchall()
    ago5 = (datetime.datetime.now() - datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    cut = _cut_time(range_min)
    total = {c: 0 for c, _ in VOC_CATS}
    recent = {c: 0 for c, _ in VOC_CATS}
    for content, created in rows:
        if not content or any(b in content for b in bw):
            continue
        if cut and (not created or created < cut):
            continue
        for cat, kws in VOC_CATS:
            if any(k in content for k in kws):
                total[cat] += 1
                if created and created >= ago5:
                    recent[cat] += 1
    out = [{"category": c, "count": total[c], "recent": recent[c]} for c, _ in VOC_CATS]
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


def voc_danmu(conn, category, range_min=0, limit=200, source=None):
    kws = dict(VOC_CATS).get(category)
    if not kws:
        return {"category": category, "total": 0, "danmu": []}
    sc, sp = _src(source)
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


def word_danmu(conn, word, limit=200, source=None):
    sc, sp = _src(source)
    rows = conn.execute(
        f"SELECT nickname, content, created_at FROM danmu WHERE content LIKE ? AND {NB}{sc} "
        "ORDER BY id DESC LIMIT ?", [f"%{word}%"] + sp + [limit]).fetchall()
    return {"word": word, "total": len(rows),
            "danmu": [{"nickname": a, "content": b, "created_at": c} for a, b, c in rows]}


def _count_since(conn, table, seconds, source=None):
    sc, sp = _src(source)
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE created_at >= datetime('now','localtime',?) "
        f"AND {NB}{sc}", [f"-{seconds} seconds"] + sp).fetchone()[0]


def summary(conn, source=None):
    sc, sp = _src(source)

    def cnt(t):
        return conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {NB}{sc}", sp).fetchone()[0]

    online = conn.execute(
        f"SELECT online_count FROM room_stat WHERE online_count IS NOT NULL{sc} "
        "ORDER BY id DESC LIMIT 1", sp).fetchone()
    distinct_users = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT user_id FROM danmu WHERE {NB}{sc} "
        f"UNION SELECT user_id FROM enter WHERE {NB}{sc})", sp + sp).fetchone()[0]
    total_user = conn.execute("SELECT value FROM meta WHERE key='total_user'").fetchone()
    return {
        "danmu": cnt("danmu"), "gift": cnt("gift"),
        "enter": cnt("enter"), "likes": cnt("likes"),
        "online": online[0] if online else None,
        "total_user": int(total_user[0]) if total_user and total_user[0] else None,
        "distinct_users": distinct_users,
        "rates": {
            "danmu_min": _count_since(conn, "danmu", 60, source),
            "danmu_5min": _count_since(conn, "danmu", 300, source),
            "enter_min": _count_since(conn, "enter", 60, source),
            "enter_5min": _count_since(conn, "enter", 300, source),
            "like_5min": _count_since(conn, "likes", 300, source),
        },
    }


def online_series(conn, limit=600, source=None):
    sc, sp = _src(source)
    rows = conn.execute(
        f"SELECT created_at, online_count FROM room_stat "
        f"WHERE online_count IS NOT NULL{sc} ORDER BY id DESC LIMIT ?", sp + [limit]).fetchall()
    return [{"t": a, "v": b} for a, b in rows[::-1]]


def top_users(conn, limit=15, source=None):
    sc, sp = _src(source)
    rows = conn.execute(
        f"SELECT user_id, nickname, MAX(level) lv, COUNT(*) n FROM danmu "
        f"WHERE nickname!='' AND {NB}{sc} GROUP BY user_id ORDER BY n DESC LIMIT ?",
        sp + [limit]).fetchall()
    return [{"user_id": a, "nickname": b, "level": c, "count": d} for a, b, c, d in rows]


def user_danmu(conn, user_id, limit=100, source=None):
    sc, sp = _src(source)
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
