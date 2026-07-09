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
CREATE INDEX IF NOT EXISTS idx_danmu_room_ts ON danmu(room_id, ts);
"""


class Store:
    def __init__(self, path="danmu.db"):
        self.path = path
        self.conn = sqlite3.connect(path)
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
