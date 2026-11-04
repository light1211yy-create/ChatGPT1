"""Manual facility research; additive SQLite tables, no remote requests."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from studio.db import ConflictError, Store, now

CANDIDATE_STATUSES = ("検討中", "優先候補", "見送り")
PERMISSIONS = ("未確認", "利用可", "利用不可", "期限切れ")


def today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def text(value, label, limit=2000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"{label}は{'1〜' if required else ''}{limit}文字以内で入力してください。")
    return value.strip()


def url(value):
    value = text(value, "URL", 2000, True)
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        _ = parsed.port
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError
    except ValueError:
        raise ValueError("認証情報を含まないhttp/httpsのURLを入力してください。") from None
    return value


def checked_date(value):
    if type(value) is not date or value > today():
        raise ValueError("確認日は今日以前の日付を指定してください。")
    return value.isoformat()


def effective_permission(photo, on=None):
    on = on or today()
    if photo["permission_status"] == "利用可" and photo["expires_on"] and date.fromisoformat(photo["expires_on"]) < on:
        return "期限切れ"
    return photo["permission_status"]


class ResearchStore:
    def __init__(self, store: Store):
        self.store = store
        with store.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS facilities (
                    id INTEGER PRIMARY KEY, theme_id INTEGER NOT NULL REFERENCES themes(id),
                    name TEXT NOT NULL, address TEXT NOT NULL, official_url TEXT NOT NULL,
                    summary TEXT NOT NULL, price_note TEXT NOT NULL, checked_on TEXT NOT NULL,
                    candidate_status TEXT NOT NULL CHECK(candidate_status IN ('検討中','優先候補','見送り')),
                    notes TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facility_sources (
                    id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL REFERENCES facilities(id),
                    label TEXT NOT NULL, fact TEXT NOT NULL, url TEXT NOT NULL,
                    checked_on TEXT NOT NULL, notes TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facility_photos (
                    id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL REFERENCES facilities(id),
                    label TEXT NOT NULL, url TEXT NOT NULL, owner TEXT NOT NULL,
                    permission_status TEXT NOT NULL CHECK(permission_status IN ('未確認','利用可','利用不可','期限切れ')),
                    evidence TEXT NOT NULL, usage_scope TEXT NOT NULL, credit TEXT NOT NULL,
                    expires_on TEXT, notes TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS facilities_theme ON facilities(theme_id);
                CREATE INDEX IF NOT EXISTS sources_facility ON facility_sources(facility_id);
                CREATE INDEX IF NOT EXISTS photos_facility ON facility_photos(facility_id);
            """)

    @contextmanager
    def write(self):
        with self.store.connect() as conn:
            # Serialize theme approval checks and writes with Phase 1 reviews.
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    @staticmethod
    def require_approved(conn, theme_id):
        row = conn.execute("SELECT status FROM themes WHERE id=?", (theme_id,)).fetchone()
        if row is None or row["status"] != "承認":
            raise ValueError("承認済みテーマだけに施設候補を登録・更新できます。")

    def require_facility(self, conn, facility_id):
        row = conn.execute("SELECT theme_id FROM facilities WHERE id=?", (facility_id,)).fetchone()
        if row is None:
            raise ValueError("施設候補が見つかりません。")
        self.require_approved(conn, row["theme_id"])

    @staticmethod
    def updated(cursor):
        if cursor.rowcount != 1:
            raise ConflictError("別の操作で更新されました。画面を再読み込みしてください。")

    def save_facility(self, theme_id, *, name, address, official_url, summary, price_note,
                      checked_on, candidate_status="検討中", notes="", facility_id=None, version=0):
        values = (text(name, "施設名", 150, True), text(address, "住所", 500, True), url(official_url),
                  text(summary, "施設情報"), text(price_note, "料金条件"), checked_date(checked_on),
                  candidate_status, text(notes, "比較メモ"), now())
        if candidate_status not in CANDIDATE_STATUSES:
            raise ValueError("候補の状態が不正です。")
        with self.write() as conn:
            self.require_approved(conn, theme_id)
            if facility_id is None:
                return conn.execute("""INSERT INTO facilities(name,address,official_url,summary,price_note,
                    checked_on,candidate_status,notes,updated_at,theme_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    values + (theme_id, now())).lastrowid
            self.updated(conn.execute("""UPDATE facilities SET name=?,address=?,official_url=?,summary=?,
                price_note=?,checked_on=?,candidate_status=?,notes=?,updated_at=?,version=version+1
                WHERE id=? AND theme_id=? AND version=?""", values + (facility_id, theme_id, version)))
            return facility_id

    def facilities(self, theme_id):
        with self.store.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM facilities WHERE theme_id=? ORDER BY id", (theme_id,))]

    def sources(self, facility_id):
        with self.store.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM facility_sources WHERE facility_id=? ORDER BY id", (facility_id,))]

    def save_source(self, facility_id, *, label, fact, source_url, checked_on, notes="", source_id=None, version=0):
        values = (text(label, "確認項目", 150, True), text(fact, "確認した情報", required=True),
                  url(source_url), checked_date(checked_on), text(notes, "出典メモ"), now())
        with self.write() as conn:
            self.require_facility(conn, facility_id)
            if source_id is None:
                return conn.execute("""INSERT INTO facility_sources(label,fact,url,checked_on,notes,updated_at,facility_id)
                    VALUES(?,?,?,?,?,?,?)""", values + (facility_id,)).lastrowid
            self.updated(conn.execute("""UPDATE facility_sources SET label=?,fact=?,url=?,checked_on=?,notes=?,
                updated_at=?,version=version+1 WHERE id=? AND facility_id=? AND version=?""",
                values + (source_id, facility_id, version)))
            return source_id

    def photos(self, facility_id):
        with self.store.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM facility_photos WHERE facility_id=? ORDER BY id", (facility_id,))]

    def save_photo(self, facility_id, *, label, photo_url, owner="", permission_status="未確認", evidence="",
                   usage_scope="", credit="", expires_on=None, notes="", photo_id=None, version=0):
        if permission_status not in PERMISSIONS:
            raise ValueError("利用許諾状況が不正です。")
        owner = text(owner, "権利者", 300)
        evidence = text(evidence, "許諾の根拠")
        usage_scope = text(usage_scope, "許諾された用途")
        if permission_status == "利用可" and not all((owner, evidence, usage_scope)):
            raise ValueError("「利用可」には権利者・許諾の根拠・許諾された用途が必要です。")
        if expires_on is not None and type(expires_on) is not date:
            raise ValueError("利用期限の日付が不正です。")
        if permission_status == "利用可" and expires_on and expires_on < today():
            raise ValueError("利用期限が過ぎています。「期限切れ」として保存してください。")
        values = (text(label, "写真名", 150, True), url(photo_url), owner, permission_status,
                  evidence, usage_scope, text(credit, "クレジット", 500),
                  expires_on.isoformat() if expires_on else None, text(notes, "写真メモ"), now())
        with self.write() as conn:
            self.require_facility(conn, facility_id)
            if photo_id is None:
                return conn.execute("""INSERT INTO facility_photos(label,url,owner,permission_status,evidence,
                    usage_scope,credit,expires_on,notes,updated_at,facility_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    values + (facility_id,)).lastrowid
            self.updated(conn.execute("""UPDATE facility_photos SET label=?,url=?,owner=?,permission_status=?,
                evidence=?,usage_scope=?,credit=?,expires_on=?,notes=?,updated_at=?,version=version+1
                WHERE id=? AND facility_id=? AND version=?""", values + (photo_id, facility_id, version)))
            return photo_id

    def usable_photos(self, facility_id, on=None):
        return [p for p in self.photos(facility_id) if effective_permission(p, on) == "利用可"]
