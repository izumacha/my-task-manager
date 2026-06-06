"""完了統計の計算（GUI 非依存の純粋関数群）。

完了履歴は「完了日時の ISO 文字列のリスト」として保持し、
今日の完了数や連続達成日数（ストリーク）を算出する。
"""
from __future__ import annotations

import datetime

from .task import ISO_FMT


def _to_dates(history: list[str]) -> list[datetime.date]:
    """ISO 文字列の履歴を date のリストへ変換する（不正値は無視）。"""
    dates: list[datetime.date] = []
    for item in history:
        try:
            dates.append(datetime.datetime.strptime(item, ISO_FMT).date())
        except (TypeError, ValueError):
            continue
    return dates


def completed_count_on(history: list[str], date: datetime.date) -> int:
    """指定日に完了した件数を返す。"""
    return sum(1 for d in _to_dates(history) if d == date)


def current_streak(history: list[str], today: datetime.date) -> int:
    """今日を末尾とする連続達成日数を返す。

    今日から過去に向かって「1 件以上完了した日」が連続している日数を数える。
    今日の完了が 0 件なら 0 を返す。
    """
    done_days = set(_to_dates(history))
    streak = 0
    day = today
    while day in done_days:
        streak += 1
        day -= datetime.timedelta(days=1)
    return streak


def total_completed(history: list[str]) -> int:
    """これまでに完了した総件数を返す。"""
    return len(_to_dates(history))
