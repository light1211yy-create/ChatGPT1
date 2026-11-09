import json
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
                CREATE TABLE IF NOT EXISTS ai_research_runs (
                    id INTEGER PRIMARY KEY,
                    theme_id INTEGER NOT NULL REFERENCES themes(id),
                    area TEXT NOT NULL,
                    model TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    imported_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ai_research_theme ON ai_research_runs(theme_id);
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


    def save_ai_draft(self, theme_id, draft):
        """Persist an AI proposal separately from verified/manual facility records."""
        if not isinstance(draft, dict) or not isinstance(draft.get("selected"), list) or len(draft["selected"]) != 5:
            raise ValueError("AI調査の候補5件を確認できませんでした。保存しません。")
        if not isinstance(draft.get("area"), str) or not 2 <= len(draft["area"]) <= 65:
            raise ValueError("AI調査の検索地域が不正です。")
        data = json.dumps(draft, ensure_ascii=False)
        if len(data) > 200000:
            raise ValueError("AI調査結果が大きすぎます。保存しません。")
        with self.write() as conn:
            self.require_approved(conn, theme_id)
            return conn.execute(
                "INSERT INTO ai_research_runs(theme_id,area,model,payload,created_at) VALUES(?,?,?,?,?)",
                (theme_id, draft["area"], draft.get("model", ""), data, now())
            ).lastrowid

    def latest_ai_draft(self, theme_id):
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_research_runs WHERE theme_id=? ORDER BY id DESC LIMIT 1",
                (theme_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["data"] = json.loads(result.pop("payload"))
        return result

    def import_ai_draft(self, run_id):
        """One atomic, explicit human-initiated import. Never mark photos usable."""
        with self.write() as conn:
            record = conn.execute("SELECT * FROM ai_research_runs WHERE id=?", (run_id,)).fetchone()
            if record is None or record["imported_at"]:
                raise ValueError("AI調査案がないか、すでに登録済みです。")
            self.require_approved(conn, record["theme_id"])
            draft = json.loads(record["payload"])
            picks = draft.get("selected") or []
            if len(picks) != 5 or len({p.get("id") for p in picks}) != 5:
                raise ValueError("AI調査案の5件が不正です。")
            count = 0
            for pick in picks:
                # Existing names are never overwritten; source remains a preliminary source.
                name = text(pick.get("name"), "施設名", 150, True)
                found = conn.execute("SELECT id FROM facilities WHERE theme_id=? AND name=?",
                                     (record["theme_id"], name)).fetchone()
                if found:
                    continue
                website = pick.get("official_url") or ""
                if website:
                    website = url(website)  # May be OSM's website field; still unverified.
                source_link = url(pick["source_url"])
                note = text("AI調査候補：公式情報・価格・営業時間・写真の利用権は未確認。"
                            "登録元：OpenStreetMap。選定理由：" + str(pick.get("reason", "")), "比較メモ")
                address = text(pick.get("address") or "", "住所", 500)
                description = text(pick.get("description") or "", "施設情報")
                fid = conn.execute(
                    """INSERT INTO facilities(name,address,official_url,summary,price_note,
                    checked_on,candidate_status,notes,updated_at,theme_id,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, address, website, description, "未確認", today().isoformat(),
                     "優先候補", note, now(), record["theme_id"], now())
                ).lastrowid
                conn.execute(
                    """INSERT INTO facility_sources(label,fact,url,checked_on,notes,updated_at,facility_id)
                    VALUES(?,?,?,?,?,?,?)""",
                    ("候補発見元", "OpenStreetMapの公開登録情報。施設の公式確認ではありません。",
                     source_link, today().isoformat(), "© OpenStreetMap contributors / ODbL", now(), fid)
                )
                for photo in pick.get("photos", [])[:2]:
                    photo_link = url(photo["url"])
                    conn.execute(
                        """INSERT INTO facility_photos(label,url,owner,permission_status,evidence,
                        usage_scope,credit,expires_on,notes,updated_at,facility_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (text(photo.get("label", "写真候補"), "写真名", 150, True),
                         photo_link, text(photo.get("owner", ""), "権利者", 300),
                         "未確認", "", "", "", None,
                         "Wikimedia Commons検索候補。施設との一致・商用利用・改変条件・帰属表示を人が確認。",
                         now(), fid)
                    )
                count += 1
            conn.execute("UPDATE ai_research_runs SET imported_at=? WHERE id=?", (now(), run_id))
            return count
