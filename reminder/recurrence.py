"""タスクの繰り返し（リカレンス）計算ユーティリティ。

このモジュールの中心的な役割は「タスクを**完了した時点**を起点に、
次回の期限を日 / 週 / 月 / 年単位で算出する」ことである。
一般的なリマインダーが元の予定日を基準に次回を決めるのに対し、
本アプリは完了時刻を基準にするため、こなしたタイミングから一定間隔で
繰り返すワークフロー（例: 掃除をやった日から 1 週間後に再通知）に向く。

GUI から独立した純粋関数のみで構成し、単体テストしやすくしている。
"""
from __future__ import annotations

import calendar
import datetime

# 繰り返し単位の識別子。設定 JSON にもこの文字列がそのまま保存される
RECUR_NONE = "none"
RECUR_DAILY = "daily"
RECUR_WEEKLY = "weekly"
RECUR_MONTHLY = "monthly"
RECUR_YEARLY = "yearly"

# UI / 永続化で利用する単位の一覧（表示順）
RECUR_UNITS = (RECUR_NONE, RECUR_DAILY, RECUR_WEEKLY, RECUR_MONTHLY, RECUR_YEARLY)

# 単位 → 日本語ラベル。コンボボックス表示とラベル⇔値の相互変換に使用する
RECUR_LABELS = {
    RECUR_NONE: "なし",
    RECUR_DAILY: "日",
    RECUR_WEEKLY: "週",
    RECUR_MONTHLY: "月",
    RECUR_YEARLY: "年",
}

# 繰り返し間隔の下限・上限。UI の Spinbox 範囲と正規化ロジックで共有する
MIN_INTERVAL = 1
MAX_INTERVAL = 99


def label_for_unit(unit: str) -> str:
    """繰り返し単位の識別子に対応する日本語ラベルを返す。未知の値は「なし」。"""
    return RECUR_LABELS.get(unit, RECUR_LABELS[RECUR_NONE])


def unit_for_label(label: str) -> str:
    """日本語ラベルから繰り返し単位の識別子を逆引きする。未知のラベルは RECUR_NONE。"""
    for unit, text in RECUR_LABELS.items():
        if text == label:
            return unit
    return RECUR_NONE


def _add_months(base: datetime.datetime, months: int) -> datetime.datetime:
    """base から months か月後の日時を返す（月末日のクランプ付き）。

    例えば 1/31 の 1 か月後は 2/28（うるう年なら 2/29）に丸める。
    年単位の計算も months=12*年 として本関数に委譲する。
    """
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    # 遷移先の月の日数を超える日付（例: 31 日 → 2 月）は月末にクランプする
    day = min(base.day, calendar.monthrange(year, month)[1])
    return base.replace(year=year, month=month, day=day)


def add_period(base: datetime.datetime, unit: str, interval: int = 1) -> datetime.datetime:
    """base に「interval 個分の unit」を加算した日時を返す。

    Args:
        base: 起点となる日時。
        unit: RECUR_DAILY / RECUR_WEEKLY / RECUR_MONTHLY / RECUR_YEARLY のいずれか。
        interval: 加算する個数（1 以上にクランプ）。

    Returns:
        加算後の日時。

    Raises:
        ValueError: unit が加算可能な単位でない場合（RECUR_NONE を含む）。
    """
    interval = max(MIN_INTERVAL, interval)
    if unit == RECUR_DAILY:
        return base + datetime.timedelta(days=interval)
    if unit == RECUR_WEEKLY:
        return base + datetime.timedelta(weeks=interval)
    if unit == RECUR_MONTHLY:
        return _add_months(base, interval)
    if unit == RECUR_YEARLY:
        return _add_months(base, interval * 12)
    raise ValueError(f"加算できない繰り返し単位です: {unit!r}")


def next_occurrence(
    completed_at: datetime.datetime, unit: str, interval: int = 1
) -> datetime.datetime | None:
    """タスクを完了した時点を起点に、次回の期限日時を算出する。

    Args:
        completed_at: タスクを完了した日時（次回計算の起点）。
        unit: 繰り返し単位。RECUR_NONE の場合は繰り返さない。
        interval: 繰り返し間隔（1 以上にクランプ）。

    Returns:
        次回の期限日時。繰り返しなし（RECUR_NONE）の場合は None。
    """
    if unit == RECUR_NONE:
        return None
    return add_period(completed_at, unit, interval)
