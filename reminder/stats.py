"""完了統計の計算（GUI 非依存の純粋関数群）。

完了履歴は「完了日時の ISO 文字列のリスト」として保持し、
今日の完了数や連続達成日数（ストリーク）を算出する。

集計は「プランナー日」単位で行う。起床/就寝が深夜をまたぐ場合、
就寝境界より前の深夜の完了は前日のプランナー日として数える。
"""
from __future__ import annotations

import datetime

from .task import ISO_FMT
from .timeline import DEFAULT_SLEEP_MIN, DEFAULT_WAKE_MIN, planner_day


def _to_days(
    history: list[str], wake_min: int, sleep_min: int
) -> list[datetime.date]:
    """ISO 文字列の履歴をプランナー日のリストへ変換する（不正値は無視）。"""
    days: list[datetime.date] = []
    for item in history:
        try:
            dt = datetime.datetime.strptime(item, ISO_FMT)
        except (TypeError, ValueError):
            continue
        days.append(planner_day(dt, wake_min, sleep_min))
    return days


def completed_count_on(
    history: list[str],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
) -> int:
    """指定プランナー日に完了した件数を返す。"""
    return sum(1 for d in _to_days(history, wake_min, sleep_min) if d == date)


def current_streak(
    history: list[str],
    today: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
) -> int:
    """今日（プランナー日）を末尾とする連続達成日数を返す。

    今日から過去に向かって「1 件以上完了した日」が連続している日数を数える。
    今日の完了が 0 件なら 0 を返す。
    """
    done_days = set(_to_days(history, wake_min, sleep_min))
    streak = 0
    day = today
    while day in done_days:
        streak += 1
        day -= datetime.timedelta(days=1)
    return streak


def total_completed(history: list[str]) -> int:
    """これまでに完了した総件数を返す。"""
    return len(_to_days(history, DEFAULT_WAKE_MIN, DEFAULT_SLEEP_MIN))
