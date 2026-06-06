"""tests/test_recurrence.py — recurrence モジュールの単体テスト

中核要件「完了時点を起点に日/週/月/年で繰り返す」計算を重点的に検証する。
"""
import datetime
import unittest

from reminder.recurrence import (
    MAX_INTERVAL,
    MIN_INTERVAL,
    RECUR_DAILY,
    RECUR_LABELS,
    RECUR_MONTHLY,
    RECUR_NONE,
    RECUR_UNITS,
    RECUR_WEEKLY,
    RECUR_YEARLY,
    add_period,
    label_for_unit,
    next_occurrence,
    unit_for_label,
)


class AddPeriodTests(unittest.TestCase):
    """add_period() の各単位の加算結果を検証する。"""

    def setUp(self):
        self.base = datetime.datetime(2026, 6, 6, 9, 30, 0)

    def test_daily(self):
        self.assertEqual(add_period(self.base, RECUR_DAILY, 1), datetime.datetime(2026, 6, 7, 9, 30))

    def test_daily_multiple(self):
        self.assertEqual(add_period(self.base, RECUR_DAILY, 10), datetime.datetime(2026, 6, 16, 9, 30))

    def test_weekly(self):
        self.assertEqual(add_period(self.base, RECUR_WEEKLY, 2), datetime.datetime(2026, 6, 20, 9, 30))

    def test_monthly(self):
        self.assertEqual(add_period(self.base, RECUR_MONTHLY, 1), datetime.datetime(2026, 7, 6, 9, 30))

    def test_monthly_crosses_year(self):
        self.assertEqual(add_period(self.base, RECUR_MONTHLY, 8), datetime.datetime(2027, 2, 6, 9, 30))

    def test_yearly(self):
        self.assertEqual(add_period(self.base, RECUR_YEARLY, 1), datetime.datetime(2027, 6, 6, 9, 30))

    def test_yearly_multiple(self):
        self.assertEqual(add_period(self.base, RECUR_YEARLY, 3), datetime.datetime(2029, 6, 6, 9, 30))

    def test_month_end_clamps_to_shorter_month(self):
        # 1/31 の 1 か月後は 2 月末（2026 は平年なので 2/28）にクランプされる
        jan31 = datetime.datetime(2026, 1, 31, 8, 0)
        self.assertEqual(add_period(jan31, RECUR_MONTHLY, 1), datetime.datetime(2026, 2, 28, 8, 0))

    def test_month_end_clamps_to_leap_february(self):
        # うるう年 2028 の 2 月末は 2/29
        jan31 = datetime.datetime(2028, 1, 31, 8, 0)
        self.assertEqual(add_period(jan31, RECUR_MONTHLY, 1), datetime.datetime(2028, 2, 29, 8, 0))

    def test_yearly_leap_day_clamps(self):
        # 2/29 の 1 年後は平年の 2/28 にクランプされる
        leap = datetime.datetime(2028, 2, 29, 12, 0)
        self.assertEqual(add_period(leap, RECUR_YEARLY, 1), datetime.datetime(2029, 2, 28, 12, 0))

    def test_interval_below_min_is_clamped(self):
        # 0 や負値は最小間隔 1 として扱う
        self.assertEqual(add_period(self.base, RECUR_DAILY, 0), datetime.datetime(2026, 6, 7, 9, 30))

    def test_invalid_unit_raises(self):
        with self.assertRaises(ValueError):
            add_period(self.base, RECUR_NONE, 1)


class NextOccurrenceTests(unittest.TestCase):
    """next_occurrence() が完了時点を起点に算出することを検証する。"""

    def test_none_returns_none(self):
        completed = datetime.datetime(2026, 6, 6, 9, 0)
        self.assertIsNone(next_occurrence(completed, RECUR_NONE, 1))

    def test_daily_from_completion(self):
        completed = datetime.datetime(2026, 6, 6, 22, 15)
        self.assertEqual(next_occurrence(completed, RECUR_DAILY, 1), datetime.datetime(2026, 6, 7, 22, 15))

    def test_weekly_from_completion(self):
        completed = datetime.datetime(2026, 6, 6, 7, 0)
        self.assertEqual(next_occurrence(completed, RECUR_WEEKLY, 1), datetime.datetime(2026, 6, 13, 7, 0))

    def test_monthly_from_completion(self):
        completed = datetime.datetime(2026, 6, 6, 7, 0)
        self.assertEqual(next_occurrence(completed, RECUR_MONTHLY, 2), datetime.datetime(2026, 8, 6, 7, 0))

    def test_yearly_from_completion(self):
        completed = datetime.datetime(2026, 6, 6, 7, 0)
        self.assertEqual(next_occurrence(completed, RECUR_YEARLY, 1), datetime.datetime(2027, 6, 6, 7, 0))


class LabelConversionTests(unittest.TestCase):
    """ラベル⇔単位の相互変換を検証する。"""

    def test_label_for_known_unit(self):
        self.assertEqual(label_for_unit(RECUR_WEEKLY), "週")

    def test_label_for_unknown_unit_returns_none_label(self):
        self.assertEqual(label_for_unit("bogus"), "なし")

    def test_unit_for_label_round_trip(self):
        for unit in RECUR_UNITS:
            self.assertEqual(unit_for_label(RECUR_LABELS[unit]), unit)

    def test_unit_for_unknown_label_returns_none(self):
        self.assertEqual(unit_for_label("???"), RECUR_NONE)


class ConstantsTests(unittest.TestCase):
    def test_interval_bounds(self):
        self.assertEqual(MIN_INTERVAL, 1)
        self.assertGreater(MAX_INTERVAL, MIN_INTERVAL)

    def test_all_units_have_labels(self):
        for unit in RECUR_UNITS:
            self.assertIn(unit, RECUR_LABELS)


if __name__ == "__main__":
    unittest.main()
