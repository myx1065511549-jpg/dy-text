"""
模块五:存储(SQLite)。
单文件数据库,零配置,适合 Win 单机程序。
按消息类型分表:弹幕 / 礼物 / 进场 / 点赞 / 房间统计。
Store.save(record) 按 record["type"] 分发入库。
"""
import os
import sqlite3
import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS danmu (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, user_id TEXT, nickname TEXT, gender INTEGER,
  content TEXT, ts INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS gift (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, user_id TEXT, nickname TEXT,
  gift_name TEXT, repeat_count INTEGER, ts INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS enter (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, user_id TEXT, nickname TEXT, ts INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS likes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, user_id TEXT, nickname TEXT, count INTEGER, ts INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS room_stat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, online_count INTEGER, ts INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS blocklist (
  user_id TEXT PRIMARY KEY, nickname TEXT, blocked_at TEXT
);
CREATE TABLE IF NOT EXISTS word_blocklist (
  word TEXT PRIMARY KEY, blocked_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT
);
CREATE INDEX IF NOT EXISTS idx_danmu_room_ts ON danmu(room_id, ts);
CREATE INDEX IF NOT EXISTS idx_danmu_user ON danmu(user_id);
CREATE INDEX IF NOT EXISTS idx_danmu_created ON danmu(created_at);
CREATE INDEX IF NOT EXISTS idx_enter_created ON enter(created_at);
"""

# 切换直播间时要清空的数据表(屏蔽名单不清)
_DATA_TABLES = ("danmu", "gift", "enter", "likes", "room_stat")


class Store:
    def __init__(self, path="danmu.db"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _now(self):
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def save(self, r: dict):
        t = r.get("type")
        now = self._now()
        c = self.conn
        if t == "chat":
            c.execute(
                "INSERT INTO danmu(room_id,user_id,nickname,gender,content,ts,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("nickname"),
                 r.get("gender"), r.get("content"), r.get("ts"), now))
        elif t == "gift":
            c.execute(
                "INSERT INTO gift(room_id,user_id,nickname,gift_name,repeat_count,ts,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("nickname"),
                 r.get("gift_name"), r.get("count"), r.get("ts"), now))
        elif t == "enter":
            c.execute(
                "INSERT INTO enter(room_id,user_id,nickname,ts,created_at) VALUES(?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("nickname"),
                 r.get("ts"), now))
        elif t == "like":
            c.execute(
                "INSERT INTO likes(room_id,user_id,nickname,count,ts,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("nickname"),
                 r.get("count"), r.get("ts"), now))
        elif t == "room_stat":
            c.execute(
                "INSERT INTO room_stat(room_id,online_count,ts,created_at) VALUES(?,?,?,?)",
                (r.get("room_id"), r.get("online_count"), r.get("ts"), now))
        else:
            return False
        return True

    def commit(self):
        self.conn.commit()

    def clear(self):
        """切换直播间时清空数据表 + meta,但保留屏蔽名单。"""
        for t in _DATA_TABLES:
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.execute("DELETE FROM meta")
        self.conn.commit()

    # ---- 累计场观等单值状态存 meta ----
    def set_meta(self, key, value):
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def get_meta(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    # ---- 屏蔽名单 ----
    def block(self, user_id, nickname):
        if not user_id:
            return False
        self.conn.execute(
            "INSERT INTO blocklist(user_id,nickname,blocked_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname",
            (user_id, nickname or "", self._now()))
        self.conn.commit()
        return True

    def unblock(self, user_id):
        self.conn.execute("DELETE FROM blocklist WHERE user_id=?", (user_id,))
        self.conn.commit()

    def blocklist(self):
        rows = self.conn.execute(
            "SELECT user_id, nickname, blocked_at FROM blocklist ORDER BY blocked_at DESC"
        ).fetchall()
        return [{"user_id": a, "nickname": b, "blocked_at": c} for a, b, c in rows]

    def blocked_ids(self):
        return {r[0] for r in self.conn.execute("SELECT user_id FROM blocklist").fetchall()}

    # ---- 屏蔽词 ----
    def block_word(self, word):
        word = (word or "").strip()
        if not word:
            return False
        self.conn.execute(
            "INSERT OR IGNORE INTO word_blocklist(word,blocked_at) VALUES(?,?)",
            (word, self._now()))
        self.conn.commit()
        return True

    def unblock_word(self, word):
        self.conn.execute("DELETE FROM word_blocklist WHERE word=?", ((word or "").strip(),))
        self.conn.commit()

    def word_blocklist(self):
        rows = self.conn.execute(
            "SELECT word, blocked_at FROM word_blocklist ORDER BY blocked_at DESC").fetchall()
        return [{"word": a, "blocked_at": b} for a, b in rows]

    def blocked_words(self):
        return [r[0] for r in self.conn.execute("SELECT word FROM word_blocklist").fetchall()]

    def counts(self) -> dict:
        cur = self.conn.cursor()
        out = {}
        for tbl in ("danmu", "gift", "enter", "likes", "room_stat"):
            out[tbl] = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        return out

    def recent_danmu(self, n=10):
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT nickname, content, created_at FROM danmu ORDER BY id DESC LIMIT ?",
            (n,)).fetchall()
        return [{"nickname": a, "content": b, "created_at": c} for a, b, c in rows]

    def close(self):
        self.conn.commit()
        self.conn.close()
