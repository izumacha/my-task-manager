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
    days: list[datetime.date] = []  # 変換後のプランナー日を格納するリストを空で初期化する
    for item in history:  # 完了履歴の各 ISO 文字列に対してループする
        try:
            dt = datetime.datetime.strptime(item, ISO_FMT)  # ISO 文字列を datetime オブジェクトに変換する
        except (TypeError, ValueError):  # 型エラーや形式不正の文字列は無視する
            continue  # 壊れたエントリは読み飛ばして次へ進む
        days.append(planner_day(dt, wake_min, sleep_min))  # datetime をプランナー日（date）に変換してリストへ追加する
    return days  # 変換済みのプランナー日リストを返す


def completed_count_on(
    history: list[str],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
) -> int:
    """指定プランナー日に完了した件数を返す。"""
    return sum(1 for d in _to_days(history, wake_min, sleep_min) if d == date)  # 指定日と一致するプランナー日の数を数えて返す


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
    done_days = set(_to_days(history, wake_min, sleep_min))  # 完了があった日の集合を作る（重複を排除して高速検索できるようにする）
    streak = 0  # 連続達成日数のカウンタを 0 で初期化する
    day = today  # 今日から過去へ向かって調べるため、調査対象の日を今日に設定する
    while day in done_days:  # 調査中の日に 1 件以上の完了があれば連続とみなしてループを続ける
        streak += 1  # 連続達成日数を 1 増やす
        day -= datetime.timedelta(days=1)  # 調査対象を 1 日前に移す
    return streak  # 連続達成日数を返す


def total_completed(history: list[str]) -> int:
    """これまでに完了した総件数を返す。"""
    return len(_to_days(history, DEFAULT_WAKE_MIN, DEFAULT_SLEEP_MIN))  # 全履歴を日付リストに変換したときの要素数が総完了件数になる
