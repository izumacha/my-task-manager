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
    days: list[datetime.date] = []  # 変換後のプランナー日を蓄積するリストを初期化する
    for item in history:  # 完了履歴の各 ISO 文字列に対してループする
        try:
            dt = datetime.datetime.strptime(item, ISO_FMT)  # ISO 文字列を datetime オブジェクトに変換する
        except (TypeError, ValueError):  # 変換できない不正な値が来た場合
            continue  # そのエントリは無視して次へ進む
        days.append(planner_day(dt, wake_min, sleep_min))  # プランナー日に変換してリストに追加する
    return days  # プランナー日のリストを返す


def completed_count_on(
    history: list[str],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
) -> int:
    """指定プランナー日に完了した件数を返す。"""
    return sum(1 for d in _to_days(history, wake_min, sleep_min) if d == date)  # 指定日と一致するプランナー日の数を合計して返す


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
    done_days = set(_to_days(history, wake_min, sleep_min))  # 完了があった日の集合（重複なし）を作る
    streak = 0  # 連続達成日数のカウンタを 0 で初期化する
    day = today  # 今日から過去に向かって検索するための変数に今日の日付を代入する
    while day in done_days:  # 当日に 1 件以上完了があれば連続日として数える
        streak += 1  # 連続達成日数を 1 増やす
        day -= datetime.timedelta(days=1)  # 1 日前に移動して連続を確認し続ける
    return streak  # 連続達成日数を返す


def total_completed(history: list[str]) -> int:
    """これまでに完了した総件数を返す。"""
    return len(_to_days(history, DEFAULT_WAKE_MIN, DEFAULT_SLEEP_MIN))  # プランナー日リストの要素数が総完了件数になる
