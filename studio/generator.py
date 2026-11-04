"""Replace ThemeGenerator with a free model adapter without changing the UI/DB.

This implementation is a deterministic offline fixture provider, NOT an AI model.
Scores are planning heuristics, never forecasts of views or engagement.
"""
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

CATEGORIES = ("暮らし", "グルメ", "おでかけ", "仕事・学び", "美容・健康")
EVENTS = {
    1: "お正月・成人の日", 2: "節分・バレンタイン", 3: "卒業・新生活準備",
    4: "入学・新生活", 5: "ゴールデンウィーク", 6: "梅雨・父の日",
    7: "七夕・夏休み", 8: "お盆・夏祭り", 9: "防災・秋の連休",
    10: "ハロウィン・秋の行楽", 11: "紅葉・年末準備", 12: "クリスマス・年末",
}


@dataclass(frozen=True)
class PlanningContext:
    target_date: date
    focus: str = "暮らし"
    brief: str = ""
    audience: str = "日本在住18〜34歳"

    def __post_init__(self):
        if self.focus not in CATEGORIES:
            raise ValueError("対象ジャンルが不正です。")
        if len(self.brief) > 500:
            raise ValueError("企画メモは500文字以内にしてください。")


@dataclass(frozen=True)
class ThemeDraft:
    title: str
    category: str
    score: int
    reason: str
    outline: str


class ThemeGenerator(Protocol):
    name: str

    def generate(self, context: PlanningContext, history: Sequence[dict]) -> list[ThemeDraft]: ...


class OfflineThemeGenerator:
    name = "無料テストデータ（ルールベース・AI未接続）"

    def generate(self, context: PlanningContext, history: Sequence[dict]) -> list[ThemeDraft]:
        month = context.target_date.month
        season = ("冬" if month in (12, 1, 2) else "春" if month <= 5 else "夏" if month <= 8 else "秋")
        event = EVENTS[month]
        # Aggregate engagement by category, weighted by views rather than post count.
        totals = {}
        for post in history:
            category = post["category"]
            totals.setdefault(category, [0, 0])
            totals[category][0] += post["views"]
            totals[category][1] += post["likes"] + post["saves"]
        templates = [
            ("暮らし", f"{season}の暮らしを整える、帰宅後5分の習慣", "悩みの提示 → 3つの習慣を実演 → 保存を呼びかけ"),
            ("グルメ", f"{event}に楽しむ、予算1,000円のおうちごはん", "材料と価格の実測 → 調理 → 食卓の完成"),
            ("おでかけ", f"{season}の休日、近所で楽しむ半日プラン", "移動時間 → 立ち寄り先3つ → 予算のまとめ"),
            ("仕事・学び", f"{month}月から始める、スマホで10分の学び直し", "よくある課題 → 無料の学習手順 → 続けるコツ"),
            ("美容・健康", f"{season}の朝に取り入れたい、無理のないリフレッシュ", "起床時の悩み → 軽い動きを実演 → 無理をしない注意点"),
            ("暮らし", f"{event}前に見直す、買いすぎ防止チェック", "買う前の確認 → 手持ち品の活用 → チェックリスト"),
            ("グルメ", f"忙しい18〜34歳向け、{season}の作り置き3選", "3品の完成形 → 作業順 → 衛生と保存の注意"),
            ("おでかけ", f"{event}、混雑を避けるおでかけ準備", "公式情報の確認方法 → 持ち物 → 代替プラン"),
            ("仕事・学び", f"新社会人にも、{season}の週末リセット術", "週明けの悩み → 15分の整理 → 翌週の目標"),
            ("美容・健康", f"{month}月の生活リズム、寝る前のスマホ時間を見直す", "自身の利用時間 → 通知設定の実演 → 1週間の振り返り"),
        ]
        drafts = []
        for category, title, outline in templates:
            views, reactions = totals.get(category, (0, 0))
            performance = min(20, round(100 * reactions / views)) if views else 0
            focus_bonus = 10 if category == context.focus else 0
            score = 65 + focus_bonus + performance
            evidence = (f"過去実績の反応率 {(reactions / views):.1%}（いいね＋保存／再生、{views:,}再生）を加点。"
                        if views else "このジャンルの実績なし。実績加点は0点。")
            reason = (f"{context.audience}向けに短時間・身近な予算で試せる企画。"
                      f"季節：{season}、企画時期：{event}。{evidence} "
                      f"スコア内訳：基本65＋重点ジャンル{focus_bonus}＋実績{performance}。")
            if context.brief.strip():
                reason += f" 追加の企画条件（制作時に確認）：{context.brief.strip()}"
            drafts.append(ThemeDraft(title, category, score, reason, outline))
        return sorted(drafts, key=lambda item: item.score, reverse=True)
