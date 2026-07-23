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
  room_id TEXT, user_id TEXT, sec_uid TEXT, nickname TEXT, gender INTEGER,
  level INTEGER, fans_level INTEGER, content TEXT, ts INTEGER, created_at TEXT,
  source TEXT
);
CREATE TABLE IF NOT EXISTS gift (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, user_id TEXT, nickname TEXT,
  gift_name TEXT, repeat_count INTEGER, ts INTEGER, created_at TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS enter (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, user_id TEXT, nickname TEXT, ts INTEGER, created_at TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS likes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, user_id TEXT, nickname TEXT, count INTEGER, ts INTEGER, created_at TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS room_stat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, online_count INTEGER, ts INTEGER, created_at TEXT, source TEXT
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
CREATE TABLE IF NOT EXISTS session (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, started_at TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS voc_config (
  category TEXT PRIMARY KEY, keywords TEXT, is_risk INTEGER DEFAULT 0, sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS product (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, session_id INTEGER,
  product_id TEXT, promotion_id TEXT,
  title TEXT, price INTEGER, idx INTEGER, cover TEXT, updated_at TEXT,
  UNIQUE(session_id, product_id)
);
CREATE TABLE IF NOT EXISTS explain_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, session_id INTEGER,
  product_id TEXT, status INTEGER, ts INTEGER, created_at TEXT, source TEXT
);
"""

# VOC 分类默认种子(界面可编辑,存 voc_config 表,跨场次保留)。
# 风险负面单列且排最前:管理端最关注的舆情信号。
# 关键词按 4849 条真实带货弹幕调过一轮(2026-07-23):用观众真实说法而非书面词
# (如"斤"而非"体重"、"什么区别"而非"型号"),实测命中率 27% -> 70%。
# 收紧过宽词:去掉裸"多少"(误伤"多少斤")、"还有"改"还有吗"("还有什么颜色"该归颜色款式)。
DEFAULT_VOC_CATS = [
    ("风险负面", "骗,假货,投诉,差评,举报,垃圾,避雷,翻车,忽悠,智商税,别买,后悔,坏了,虚假,"
                "坑人,劣质,山寨,仿的,维权,曝光,骗子,不靠谱,太差,失望,退了", 1),
    ("尺码型号", "尺码,型号,多大,尺寸,码数,大小,身高,体重,斤,适合,几号,哪款,那款,哪个,什么区别,"
                "有什么不同,啥区别,怎么选,选哪个,加大,超大,标准版,大号,小号,1号,2号,一号,二号", 0),
    ("链接下单", "链接,怎么买,下单,小黄车,购物车,几号链接,上链接,拍下,拍了,已拍,买了,怎么拍,"
                "哪里买,付款,支付,订单,抢到,加急", 0),
    ("颜色款式", "颜色,什么色,红色,黑色,白色,灰色,咖色,紫色,蓝色,粉色,绿色,款式,实物,加热款,"
                "新款,同款,看看色,过一下", 0),
    ("使用场景", "开车可以用,车上,办公室,家用,椅子上,沙发,床上,孕妇,孕妈,老人,学生,能用吗,"
                "可以用吗,适用,久坐,腰不好,腰疼", 0),
    ("发货售后", "发货,物流,快递,什么时候到,几天到,几天发,多久到,退款,退货,换货,售后,客服,"
                "运费险,包邮,邮费,快递费,签收,无理由,保障", 0),
    ("价格优惠", "多少钱,价格,优惠,便宜,贵不贵,太贵,折扣,优惠券,打折,降价,返现,活动,到手价,"
                "秒杀,划算,性价比,多少米,啥价,几块钱", 0),
    ("赠品配件", "赠品,送什么,送不送,有没有送,坐垫套,座套,椅套,套子,罩子,礼盒,配件,附送,买一送,福袋", 0),
    ("质量效果", "质量,效果,怎么样,真的假的,材质,靠谱,耐用,好用吗,有用吗,正品,质保,保修,管用,"
                "舒服吗,做工,拆洗,能洗吗,可以洗,清洗", 0),
    ("库存补货", "库存,有货,还有吗,补货,断货,卖完,没货,秒没,抢完,还有没,没有了", 0),
]

# 索引在迁移补列之后再建(否则旧库上 danmu(source) 索引会因缺列报错)
INDICES = """
CREATE INDEX IF NOT EXISTS idx_danmu_room_ts ON danmu(room_id, ts);
CREATE INDEX IF NOT EXISTS idx_danmu_user ON danmu(user_id);
CREATE INDEX IF NOT EXISTS idx_danmu_created ON danmu(created_at);
CREATE INDEX IF NOT EXISTS idx_danmu_source ON danmu(source);
CREATE INDEX IF NOT EXISTS idx_enter_created ON enter(created_at);
CREATE INDEX IF NOT EXISTS idx_danmu_session ON danmu(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_gift_session ON gift(session_id);
CREATE INDEX IF NOT EXISTS idx_enter_session ON enter(session_id);
CREATE INDEX IF NOT EXISTS idx_likes_session ON likes(session_id);
CREATE INDEX IF NOT EXISTS idx_room_stat_session ON room_stat(session_id);
CREATE INDEX IF NOT EXISTS idx_product_session ON product(session_id);
CREATE INDEX IF NOT EXISTS idx_explain_session ON explain_event(session_id, ts);
"""

# 给旧库补列(CREATE TABLE IF NOT EXISTS 不会给已存在的表加列)
_MIGRATIONS = [
    ("danmu", "sec_uid", "TEXT"), ("danmu", "level", "INTEGER"),
    ("danmu", "fans_level", "INTEGER"), ("danmu", "source", "TEXT"),
    ("gift", "source", "TEXT"), ("enter", "source", "TEXT"),
    ("likes", "source", "TEXT"), ("room_stat", "source", "TEXT"),
    ("danmu", "session_id", "INTEGER"), ("gift", "session_id", "INTEGER"),
    ("enter", "session_id", "INTEGER"), ("likes", "session_id", "INTEGER"),
    ("room_stat", "session_id", "INTEGER"),
]

# 带场次归属的数据表(屏蔽名单和VOC配置不在其中,跨场次保留)
_DATA_TABLES = ("danmu", "gift", "enter", "likes", "room_stat", "product", "explain_event")


class Store:
    def __init__(self, path="danmu.db"):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        for tbl, col, typ in _MIGRATIONS:
            try:
                self.conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
            except Exception:
                pass  # 列已存在
        self.conn.executescript(INDICES)
        if not self.conn.execute("SELECT 1 FROM voc_config LIMIT 1").fetchone():
            for i, (cat, kws, risk) in enumerate(DEFAULT_VOC_CATS):
                self.conn.execute(
                    "INSERT INTO voc_config(category,keywords,is_risk,sort) VALUES(?,?,?,?)",
                    (cat, kws, risk, i))
        self.conn.commit()

    def _now(self):
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 场次(session):数据不删,按场归档 ----
    def current_session(self, room_id=None):
        """当前未结束的场次 id;不存在则开一场(兜底,正常由 new_session 创建)。"""
        row = self.conn.execute(
            "SELECT id FROM session WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            "INSERT INTO session(room_id,started_at) VALUES(?,?)", (room_id, self._now()))
        self.conn.commit()
        return cur.lastrowid

    def new_session(self, room_id=None):
        """结束当前场次并开新场。旧数据保留;累计场观(meta)归零。"""
        now = self._now()
        self.conn.execute("UPDATE session SET ended_at=? WHERE ended_at IS NULL", (now,))
        cur = self.conn.execute(
            "INSERT INTO session(room_id,started_at) VALUES(?,?)", (room_id, now))
        self.conn.execute("DELETE FROM meta WHERE key='total_user'")
        self.conn.commit()
        return cur.lastrowid

    def sessions(self):
        rows = self.conn.execute(
            "SELECT id, room_id, started_at, ended_at FROM session ORDER BY id DESC").fetchall()
        return [{"id": a, "room_id": b, "started_at": c, "ended_at": d} for a, b, c, d in rows]

    def delete_session(self, sid):
        """删除一个历史场次及其全部数据。当前进行中的场次不允许删。"""
        row = self.conn.execute("SELECT ended_at FROM session WHERE id=?", (sid,)).fetchone()
        if row is None or row[0] is None:
            return False
        for t in _DATA_TABLES:
            self.conn.execute(f"DELETE FROM {t} WHERE session_id=?", (sid,))
        self.conn.execute("DELETE FROM session WHERE id=?", (sid,))
        self.conn.commit()
        return True

    def save(self, r: dict):
        t = r.get("type")
        now = self._now()
        src = r.get("source")
        sid = self.current_session(r.get("room_id"))
        c = self.conn
        if t == "chat":
            c.execute(
                "INSERT INTO danmu(room_id,user_id,sec_uid,nickname,gender,level,fans_level,"
                "content,ts,created_at,source,session_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("sec_uid"), r.get("nickname"),
                 r.get("gender"), r.get("level"), r.get("fans_level"),
                 r.get("content"), r.get("ts"), now, src, sid))
        elif t == "gift":
            c.execute(
                "INSERT INTO gift(room_id,user_id,nickname,gift_name,repeat_count,ts,created_at,"
                "source,session_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("nickname"),
                 r.get("gift_name"), r.get("count"), r.get("ts"), now, src, sid))
        elif t == "enter":
            c.execute(
                "INSERT INTO enter(room_id,user_id,nickname,ts,created_at,source,session_id)"
                " VALUES(?,?,?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("nickname"), r.get("ts"), now, src, sid))
        elif t == "like":
            c.execute(
                "INSERT INTO likes(room_id,user_id,nickname,count,ts,created_at,source,session_id)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (r.get("room_id"), r.get("user_id"), r.get("nickname"),
                 r.get("count"), r.get("ts"), now, src, sid))
        elif t == "room_stat":
            c.execute(
                "INSERT INTO room_stat(room_id,online_count,ts,created_at,source,session_id)"
                " VALUES(?,?,?,?,?,?)",
                (r.get("room_id"), r.get("online_count"), r.get("ts"), now, src, sid))
        elif t == "explain":
            # 讲解信号每5秒一条心跳,只在换品(product_id 变化)时打一条点
            pid = str(r.get("product_id"))
            last = c.execute(
                "SELECT product_id FROM explain_event WHERE session_id=? ORDER BY id DESC LIMIT 1",
                (sid,)).fetchone()
            if last and last[0] == pid:
                return True
            c.execute(
                "INSERT INTO explain_event(room_id,session_id,product_id,status,ts,created_at,source)"
                " VALUES(?,?,?,?,?,?,?)",
                (r.get("room_id"), sid, pid, r.get("status"), r.get("ts"), now, src))
        else:
            return False
        return True

    def commit(self):
        self.conn.commit()

    # ---- 商品字典(登录态定时 fetch 刷新,按场次归属) ----
    def save_products(self, room_id, products):
        """刷新本场商品字典。products 每项:product_id/promotion_id/title/price(分)/idx/cover。
        按 (session_id, product_id) upsert,中途上新品或改价会更新。"""
        sid = self.current_session(room_id)
        now = self._now()
        n = 0
        for p in products:
            pid = str(p.get("product_id") or "")
            if not pid:
                continue
            self.conn.execute(
                "INSERT INTO product(room_id,session_id,product_id,promotion_id,title,price,idx,cover,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(session_id,product_id) DO UPDATE SET"
                " title=excluded.title, price=excluded.price, idx=excluded.idx,"
                " cover=excluded.cover, promotion_id=excluded.promotion_id, updated_at=excluded.updated_at",
                (room_id, sid, pid, str(p.get("promotion_id") or pid),
                 p.get("title"), p.get("price"), p.get("idx"), p.get("cover"), now))
            n += 1
        self.conn.commit()
        return n

    def products(self, session_id=None):
        """本场商品字典(供前端把 product_id 翻译成商品名)。"""
        if session_id is None:
            session_id = self.current_session()
        rows = self.conn.execute(
            "SELECT product_id, promotion_id, title, price, idx, cover, updated_at"
            " FROM product WHERE session_id=? ORDER BY idx", (session_id,)).fetchall()
        return [{"product_id": a, "promotion_id": b, "title": c, "price": d,
                 "idx": e, "cover": f, "updated_at": g} for a, b, c, d, e, f, g in rows]

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

    # ---- VOC 分类配置 ----
    def voc_config(self):
        rows = self.conn.execute(
            "SELECT category, keywords, is_risk FROM voc_config ORDER BY sort").fetchall()
        return [{"category": a, "keywords": b, "is_risk": bool(c)} for a, b, c in rows]

    def set_voc_config(self, cats):
        """全量替换 VOC 分类配置。cats: [{category, keywords, is_risk}]"""
        cleaned = []
        seen = set()
        for c in cats:
            name = (c.get("category") or "").strip()
            kws = ",".join(k.strip() for k in (c.get("keywords") or "").split(",") if k.strip())
            if not name or not kws or name in seen:
                continue
            seen.add(name)
            cleaned.append((name, kws, 1 if c.get("is_risk") else 0))
        if not cleaned:
            return False
        self.conn.execute("DELETE FROM voc_config")
        for i, (name, kws, risk) in enumerate(cleaned):
            self.conn.execute(
                "INSERT INTO voc_config(category,keywords,is_risk,sort) VALUES(?,?,?,?)",
                (name, kws, risk, i))
        self.conn.commit()
        return True

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
