"""時刻計算ユーティリティと UI で共有する定数。

GUI から独立しており、期限までの待機時間（ミリ秒）計算などを提供する。
"""
from __future__ import annotations

import datetime  # 日時計算を行うための標準ライブラリをインポートする

# 通知時刻の入力範囲（時・分）。UI の Spinbox と正規化ロジックで共有する
HOUR_MIN, HOUR_MAX = 0, 23  # 時の入力範囲（0〜23 時）を定数として定義する
MINUTE_MIN, MINUTE_MAX = 0, 59  # 分の入力範囲（0〜59 分）を定数として定義する

# root.after() に渡せる遅延の上限（ミリ秒）。
# Tcl の after は 32bit 符号付き整数を超える遅延を扱えないため、約 24 日でクランプする。
MAX_AFTER_MS = 2_000_000_000  # Tcl の after に渡せる最大ミリ秒数（約 24 日）を定数として定義する

# カレンダー・日付ヘッダ・統計を定期的に最新化する間隔（ミリ秒）。
# タスクの通知ジョブ（root.after）は「次の予定時刻」にしか発火しないため、
# 直近に予定が無い時間帯はアプリを開いたままでも画面が完全に固まってしまう
# （現在時刻ラインが動かない、日付が変わっても carry_over_overdue /
# prune_old_completed による繰り越し・整理が走らない等）。この間隔で
# PlannerApp._tick() が _refresh() を呼び直し、これらを最新に保つ。
REFRESH_INTERVAL_MS = 60_000  # 1 分（ミリ秒）ごとに定期再描画する

# ステータスラベルの定型メッセージ。複数箇所で参照するため定数化する
STATUS_IDLE = "タスクを追加してください。"  # 何もしていない待機状態に表示するメッセージ
# 旧単一リマインダー版で使っていた「タスク 0 件」メッセージ用の STATUS_EMPTY は、
# Any Planner 風のタイムライン UI へ刷新された際にどこからも参照されなくなり、
# 再エクスポートのためだけに残っていた（app.py の status_var 更新箇所は全て
# STATUS_IDLE か動的メッセージのみを使う）。CLAUDE.md §6「デッドコードを残さない」
# に従い削除する（theme.py の NOW_FG 削除と同じ経緯）。


def coerce_int(raw: object, min_value: int, max_value: int, default: int | None = None) -> int:
    """任意の値を整数に変換し、[min_value, max_value] にクランプして返す。

    /code-review ultra 指摘対応: 以前は task.py の coerce_interval/coerce_duration と
    app.py の PlannerApp._coerce_int が、ほぼ同一の「int変換→失敗ならフォールバック→
    min/maxでクランプ」ロジックを別々に実装しており（DRY 違反）、例外の捕捉範囲も
    (TypeError, ValueError) と (TypeError, ValueError, OverflowError) で食い違っていた。
    GUI 非依存のこのモジュールに一元化し、両方から再利用する。

    変換できない値（非数値の文字列や None など）が渡された場合、default が
    指定されていればその値を（範囲内にクランプした上で）採用し、未指定なら
    min_value を返す（例: 起床/就寝の「時」は 0 ではなく保存済みの値に戻したい）。

    Args:
        raw: 変換対象の値（文字列・数値など任意の型）。
        min_value: クランプ下限。
        max_value: クランプ上限。
        default: 変換失敗時のフォールバック値（省略時は min_value）。

    Returns:
        [min_value, max_value] にクランプされた整数。
    """
    try:
        value = int(raw)  # type: ignore[arg-type]  # 文字列や float など任意の型を整数に変換する
    except (TypeError, ValueError, OverflowError):
        # float('inf')/float('-inf') は int() が TypeError/ValueError ではなく
        # OverflowError を送出するため、他の変換不能値と同様にここで捕捉する
        if default is None:  # フォールバック先の指定がなければ
            return min_value  # 従来どおり最小値を返す（非数値のフォールバック）
        value = default  # 指定されたフォールバック値を採用する（この後の行で範囲内にクランプする）
    return max(min_value, min(max_value, value))  # 最小・最大の範囲に収めて返す


def delay_ms_until(now: datetime.datetime, target: datetime.datetime) -> int:
    """現在日時から目標日時までの待機時間（ミリ秒）を返す。

    過去の日時が渡された場合は 0 を返す（即時通知）。Tcl の after が扱える
    上限を超える場合は MAX_AFTER_MS でクランプし、呼び出し側で再スケジュール
    できるようにする。

    Args:
        now: 現在日時。
        target: 目標（期限）日時。

    Returns:
        待機すべきミリ秒数（0 以上 MAX_AFTER_MS 以下）。
    """
    delta_ms = int((target - now).total_seconds() * 1000)  # 目標日時と現在日時の差を秒→ミリ秒に変換して整数にする
    if delta_ms < 0:  # 目標日時が過去の場合（すでに期限を超えている）
        return 0  # 即時通知できるよう待機時間 0 を返す
    return min(delta_ms, MAX_AFTER_MS)  # Tcl の上限を超えないようクランプした値を返す
