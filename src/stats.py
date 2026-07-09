"""
看板聚合统计:热词、在线人数序列、汇总计数。
从 SQLite 只读查询,给 server 的 REST 接口用。
"""
import re
import jieba
from collections import Counter

# 常见虚词/口水词,不进热词
STOPWORDS = set(
    "的 了 是 我 你 他 她 它 们 在 有 和 就 不 人 都 一 也 很 到 说 要 去 会 着 没 "
    "看 好 这 那 啊 吧 呢 吗 哦 呀 嘛 哈 什么 怎么 可以 直接 一个 现在 已经 我们 "
    "你们 他们 自己 这个 那个 不是 就是 还是 这样 那样 这里 大家".split()
)


def hotwords(conn, limit=30):
    rows = conn.execute("SELECT content FROM danmu").fetchall()
    cnt = Counter()
    for (c,) in rows:
        if not c:
            continue
        for w in jieba.cut(c):
            w = w.strip()
            if len(w) < 2:
                continue
            if w in STOPWORDS:
                continue
            if re.fullmatch(r"[0-9a-zA-Z]+", w):
                continue
            cnt[w] += 1
    return [{"word": w, "count": n} for w, n in cnt.most_common(limit)]


def online_series(conn, limit=600):
    rows = conn.execute(
        "SELECT created_at, online_count FROM room_stat "
        "WHERE online_count IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    rows = rows[::-1]
    return [{"t": a, "v": b} for a, b in rows]


def summary(conn):
    def cnt(t):
        return conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    row = conn.execute(
        "SELECT online_count FROM room_stat WHERE online_count IS NOT NULL "
        "ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "danmu": cnt("danmu"), "gift": cnt("gift"),
        "enter": cnt("enter"), "likes": cnt("likes"),
        "online": row[0] if row else None,
    }


def top_users(conn, limit=10):
    rows = conn.execute(
        "SELECT nickname, COUNT(*) n FROM danmu WHERE nickname!='' "
        "GROUP BY nickname ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
    return [{"nickname": a, "count": b} for a, b in rows]
