"""tests/test_time_utils.py — time_utils モジュールの単体テスト。

delay_ms_until() の境界値・通常ケース・過去の日時などを検証する。
tkinter・OS 依存処理には一切依存しないため、全プラットフォームで実行できる。
"""
from __future__ import annotations  # Python 3.9 以前でも型ヒントを文字列として扱う

import datetime  # 日時オブジェクトを生成するための標準ライブラリをインポートする
import unittest  # Python 標準のユニットテストフレームワークをインポートする

from reminder.time_utils import MAX_AFTER_MS, delay_ms_until  # テスト対象の関数と定数をインポートする


class DelayMsUntilNormalCaseTests(unittest.TestCase):
    """通常ケース: 未来の日時を渡した場合の動作を検証する。"""

    def test_future_target_returns_positive_ms(self) -> None:
        """目標日時が現在より 1 秒後なら 1000ms が返ること。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在日時を固定値で用意する
        target = datetime.datetime(2026, 6, 12, 10, 0, 1)  # 現在の 1 秒後を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertEqual(result, 1000)  # 1 秒 = 1000ms であることを確認する

    def test_future_target_60_seconds(self) -> None:
        """目標日時が 60 秒後なら 60000ms が返ること。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在日時を固定値で用意する
        target = datetime.datetime(2026, 6, 12, 10, 1, 0)  # 現在の 60 秒後を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertEqual(result, 60_000)  # 60 秒 = 60000ms であることを確認する

    def test_future_target_returns_nonnegative(self) -> None:
        """未来の目標日時に対して 0 以上の値が返ること。"""
        now = datetime.datetime(2026, 6, 12, 9, 0, 0)  # 現在日時を固定値で用意する
        target = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 1 時間後を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertGreaterEqual(result, 0)  # 戻り値が 0 以上（負にならない）ことを確認する


class DelayMsUntilPastTargetTests(unittest.TestCase):
    """過去の日時ケース: すでに期限を過ぎている場合は 0 が返ることを検証する。"""

    def test_past_target_returns_zero(self) -> None:
        """目標日時が現在より 1 秒前なら 0 が返ること（即時通知）。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 1)  # 現在日時を固定値で用意する
        target = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在の 1 秒前を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertEqual(result, 0)  # 過去の日時なので即時通知（0ms）が返ることを確認する

    def test_far_past_target_returns_zero(self) -> None:
        """目標日時が 1 日前でも 0 が返ること（負値にならない）。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在日時を固定値で用意する
        target = datetime.datetime(2026, 6, 11, 10, 0, 0)  # 1 日前を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertEqual(result, 0)  # 過去の日時なので 0 が返ることを確認する

    def test_result_never_negative(self) -> None:
        """どんな過去の日時を渡しても戻り値が負にならないこと。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在日時を固定値で用意する
        target = datetime.datetime(2000, 1, 1, 0, 0, 0)  # 遥か過去を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertGreaterEqual(result, 0)  # 戻り値が 0 以上であることを確認する（負値禁止）


class DelayMsUntilBoundaryTests(unittest.TestCase):
    """境界値ケース: 0ms・上限クランプ・同一日時などを検証する。"""

    def test_same_datetime_returns_zero(self) -> None:
        """now と target が全く同じ日時なら 0 が返ること。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在日時を固定値で用意する
        target = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 同じ日時を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertEqual(result, 0)  # 差がゼロなので 0ms が返ることを確認する

    def test_clamp_at_max_after_ms(self) -> None:
        """非常に遠い未来の日時は MAX_AFTER_MS でクランプされること。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在日時を固定値で用意する
        # MAX_AFTER_MS を超える差になるよう 1 年後を目標日時とする（約 31 日 > 約 24 日の上限）
        target = datetime.datetime(2027, 6, 12, 10, 0, 0)  # 約 1 年後を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertEqual(result, MAX_AFTER_MS)  # MAX_AFTER_MS でクランプされることを確認する

    def test_result_never_exceeds_max_after_ms(self) -> None:
        """戻り値が MAX_AFTER_MS を超えないこと（任意の遠い未来でも上限を守る）。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0)  # 現在日時を固定値で用意する
        target = datetime.datetime(2100, 1, 1, 0, 0, 0)  # 約 74 年後という極端な未来を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertLessEqual(result, MAX_AFTER_MS)  # 戻り値が上限を超えないことを確認する

    def test_one_ms_before_is_positive(self) -> None:
        """目標日時が 1 ミリ秒後なら正の値（1ms）が返ること。"""
        now = datetime.datetime(2026, 6, 12, 10, 0, 0, 0)  # 現在日時をマイクロ秒まで固定して用意する
        target = datetime.datetime(2026, 6, 12, 10, 0, 0, 1000)  # 1 ミリ秒（1000 マイクロ秒）後を目標日時とする
        result = delay_ms_until(now, target)  # 待機ミリ秒数を計算する
        self.assertEqual(result, 1)  # 1ms 後なので 1 が返ることを確認する


if __name__ == "__main__":
    unittest.main()  # このファイルを直接実行したときにテストを走らせる
