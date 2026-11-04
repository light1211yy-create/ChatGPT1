"""SQLite persistence and business rules. Connections are short-lived."""
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from studio.generator import CATEGORIES, PlanningContext, ThemeDraft

STATUSES = ("未承認", "修正済み", "承認", "却下")
PROGRESS = ("未着手", "構成作成", "素材準備", "編集", "確認待ち", "完成", "投稿済み")


def now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("MAKASE_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "studio.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                    context TEXT NOT NULL, provider TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS themes (
                    id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batches(id),
                    title TEXT NOT NULL, category TEXT NOT NULL,
                    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
                    reason TEXT NOT NULL, outline TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '未承認' CHECK(status IN ('未承認','修正済み','承認','却下')),
                    progress TEXT NOT NULL DEFAULT '未着手' CHECK(progress IN ('未着手','構成作成','素材準備','編集','確認待ち','完成','投稿済み')),
                    note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0,
                    CHECK(status = '承認' OR progress = '未着手')
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, theme_id INTEGER NOT NULL REFERENCES themes(id),
                    created_at TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS performance (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
                    posted_on TEXT NOT NULL, views INTEGER NOT NULL CHECK(views >= 0),
                    likes INTEGER NOT NULL CHECK(likes >= 0), saves INTEGER NOT NULL CHECK(saves >= 0)
                );
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save_batch(self, context: PlanningContext, provider: str, drafts: list[ThemeDraft]):
        if len(drafts) != 10:
            raise ValueError("テーマは10案必要です。")
        for draft in drafts:
            self.validate_text(draft.title, draft.outline, "")
            if draft.category not in CATEGORIES or not 0 <= draft.score <= 100:
                raise ValueError("テーマのジャンルまたはスコアが不正です。")
        with self.connect() as conn:
            batch_id = conn.execute("INSERT INTO batches(created_at, context, provider) VALUES(?,?,?)",
                                    (now(), json.dumps(asdict(context), ensure_ascii=False, default=str), provider)).lastrowid
            conn.executemany("""INSERT INTO themes(batch_id,title,category,score,reason,outline,updated_at)
                                VALUES(?,?,?,?,?,?,?)""",
                             [(batch_id, d.title.strip(), d.category, d.score, d.reason, d.outline.strip(), now()) for d in drafts])
            return batch_id

    def batches(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM batches ORDER BY id DESC")]

    def themes(self, batch_id=None):
        with self.connect() as conn:
            query = "SELECT * FROM themes"
            return [dict(r) for r in conn.execute(query + (" WHERE batch_id=?" if batch_id is not None else "") + " ORDER BY id DESC",
                                                  (batch_id,) if batch_id is not None else ())]

    @staticmethod
    def validate_text(title, outline, note):
        if not title.strip() or len(title) > 150:
            raise ValueError("テーマ名は1〜150文字で入力してください。")
        if not outline.strip() or len(outline) > 2000 or len(note) > 1000:
            raise ValueError("構成は1〜2,000文字、メモは1,000文字以内で入力してください。")

    def review(self, theme_id, version, title, outline, note, status):
        self.validate_text(title, outline, note)
        if status not in STATUSES:
            raise ValueError("承認状態が不正です。")
        with self.connect() as conn:
            cursor = conn.execute("""UPDATE themes SET title=?,outline=?,note=?,status=?,
                progress=CASE WHEN ?='承認' THEN progress ELSE '未着手' END,
                updated_at=?,version=version+1 WHERE id=? AND version=?""",
                (title.strip(), outline.strip(), note.strip(), status, status, now(), theme_id, version))
            if cursor.rowcount != 1:
                raise ConflictError("別の操作で更新されました。画面を再読み込みしてからやり直してください。")
            conn.execute("INSERT INTO audit(theme_id,created_at,action,details) VALUES(?,?,?,?)",
                         (theme_id, now(), status, json.dumps({"title": title.strip(), "outline": outline.strip(), "note": note.strip()}, ensure_ascii=False)))

    def set_progress(self, theme_id, version, progress, note):
        if progress not in PROGRESS or len(note) > 1000:
            raise ValueError("進捗またはメモが不正です。")
        with self.connect() as conn:
            cursor = conn.execute("""UPDATE themes SET progress=?,note=?,updated_at=?,version=version+1
                WHERE id=? AND version=? AND status='承認'""", (progress, note.strip(), now(), theme_id, version))
            if cursor.rowcount != 1:
                raise ConflictError("承認状態またはデータが更新されました。再読み込みしてください。")
            conn.execute("INSERT INTO audit(theme_id,created_at,action,details) VALUES(?,?,?,?)",
                         (theme_id, now(), "進捗更新", json.dumps({"progress": progress, "note": note.strip()}, ensure_ascii=False)))

    def audit(self, theme_id):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit WHERE theme_id=? ORDER BY id DESC", (theme_id,))]

    def add_performance(self, title, category, posted_on, views, likes, saves):
        if not title.strip() or len(title) > 150 or category not in CATEGORIES:
            raise ValueError("投稿名（1〜150文字）とジャンルを確認してください。")
        if any(not isinstance(n, int) or n < 0 for n in (views, likes, saves)):
            raise ValueError("実績は0以上の整数で入力してください。")
        if likes > views or saves > views:
            raise ValueError("いいね数・保存数はそれぞれ再生数以下で入力してください。")
        with self.connect() as conn:
            conn.execute("INSERT INTO performance(title,category,posted_on,views,likes,saves) VALUES(?,?,?,?,?,?)",
                         (title.strip(), category, posted_on.isoformat(), views, likes, saves))

    def performance(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM performance ORDER BY posted_on DESC,id DESC")]
