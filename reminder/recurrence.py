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
RECUR_NONE = "none"  # 繰り返しなしを表す識別子文字列
RECUR_DAILY = "daily"  # 毎日繰り返しを表す識別子文字列
RECUR_WEEKLY = "weekly"  # 毎週繰り返しを表す識別子文字列
RECUR_MONTHLY = "monthly"  # 毎月繰り返しを表す識別子文字列
RECUR_YEARLY = "yearly"  # 毎年繰り返しを表す識別子文字列

# UI / 永続化で利用する単位の一覧（表示順）
RECUR_UNITS = (RECUR_NONE, RECUR_DAILY, RECUR_WEEKLY, RECUR_MONTHLY, RECUR_YEARLY)  # 繰り返し単位を UI 表示順に並べたタプル

# 単位 → 日本語ラベル。コンボボックス表示とラベル⇔値の相互変換に使用する
RECUR_LABELS = {  # 単位識別子 → 日本語ラベルのマッピング辞書
    RECUR_NONE: "なし",  # 繰り返しなしの日本語表示
    RECUR_DAILY: "日",  # 毎日繰り返しの日本語表示
    RECUR_WEEKLY: "週",  # 毎週繰り返しの日本語表示
    RECUR_MONTHLY: "月",  # 毎月繰り返しの日本語表示
    RECUR_YEARLY: "年",  # 毎年繰り返しの日本語表示
}

# 繰り返し間隔の下限・上限。UI の Spinbox 範囲と正規化ロジックで共有する
MIN_INTERVAL = 1  # 繰り返し間隔の最小値（1 以上にクランプ）
MAX_INTERVAL = 99  # 繰り返し間隔の最大値（Spinbox の上限）


def label_for_unit(unit: str) -> str:
    """繰り返し単位の識別子に対応する日本語ラベルを返す。未知の値は「なし」。"""
    return RECUR_LABELS.get(unit, RECUR_LABELS[RECUR_NONE])  # 辞書から日本語ラベルを取得し、未知の単位は「なし」を返す


def unit_for_label(label: str) -> str:
    """日本語ラベルから繰り返し単位の識別子を逆引きする。未知のラベルは RECUR_NONE。"""
    for unit, text in RECUR_LABELS.items():  # すべての単位とラベルの組み合わせをループする
        if text == label:  # ラベルが一致した単位を見つけたら
            return unit  # その単位の識別子文字列を返す
    return RECUR_NONE  # 一致するラベルがなければ「繰り返しなし」を返す


def _add_months(base: datetime.datetime, months: int) -> datetime.datetime:
    """base から months か月後の日時を返す（月末日のクランプ付き）。

    例えば 1/31 の 1 か月後は 2/28（うるう年なら 2/29）に丸める。
    年単位の計算も months=12*年 として本関数に委譲する。
    """
    month_index = base.month - 1 + months  # 0 始まりの月インデックスに変換して加算する（例: 1 月=0, 12 月=11）
    year = base.year + month_index // 12  # インデックスが 12 以上なら年を繰り上げる（例: 14 → 翌年 2 月）
    month = month_index % 12 + 1  # 0 始まりインデックスを 1〜12 の月番号に戻す
    # 遷移先の月の日数を超える日付（例: 31 日 → 2 月）は月末にクランプする
    day = min(base.day, calendar.monthrange(year, month)[1])  # その月の最終日を超えないよう日付を切り詰める
    return base.replace(year=year, month=month, day=day)  # 年・月・日だけ差し替えた新しい日時オブジェクトを返す


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
    interval = max(MIN_INTERVAL, interval)  # 間隔が 1 未満にならないよう下限でクランプする
    if unit == RECUR_DAILY:  # 単位が「日」なら指定日数を加算する
        return base + datetime.timedelta(days=interval)  # timedelta で日数を足した日時を返す
    if unit == RECUR_WEEKLY:  # 単位が「週」なら指定週数を加算する
        return base + datetime.timedelta(weeks=interval)  # timedelta で週数を足した日時を返す
    if unit == RECUR_MONTHLY:  # 単位が「月」なら月末クランプ付きで月数を加算する
        return _add_months(base, interval)  # _add_months に委譲して月末超えを防ぐ
    if unit == RECUR_YEARLY:  # 単位が「年」なら年数×12 か月分を加算する
        return _add_months(base, interval * 12)  # 年を月に換算して _add_months に委譲する
    raise ValueError(f"加算できない繰り返し単位です: {unit!r}")  # 未対応の単位は例外を送出する


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
    if unit == RECUR_NONE:  # 繰り返しなしの場合は次回なし（None を返す）
        return None  # 呼び出し元で繰り返し不要と判断できるよう None を返す
    return add_period(completed_at, unit, interval)  # 完了日時を起点に次回期限を計算して返す
