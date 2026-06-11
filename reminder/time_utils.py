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

# ステータスラベルの定型メッセージ。複数箇所で参照するため定数化する
STATUS_IDLE = "タスクを追加してください。"  # 何もしていない待機状態に表示するメッセージ
STATUS_EMPTY = "タスクはありません。新しいタスクを追加してください。"  # タスクが 0 件のときに表示するメッセージ


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
