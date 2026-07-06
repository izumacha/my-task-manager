"""tests/test_stats.py — stats モジュールの単体テスト"""
import datetime
import unittest

from reminder.stats import completed_count_on, current_streak, total_completed


def _iso(y, m, d, hh=9, mm=0):
    return datetime.datetime(y, m, d, hh, mm).strftime("%Y-%m-%dT%H:%M:%S")


class CompletedCountTests(unittest.TestCase):
    def test_counts_only_given_date(self):
        history = [_iso(2026, 6, 6, 9), _iso(2026, 6, 6, 18), _iso(2026, 6, 5, 12)]
        self.assertEqual(completed_count_on(history, datetime.date(2026, 6, 6)), 2)
        self.assertEqual(completed_count_on(history, datetime.date(2026, 6, 5)), 1)
        self.assertEqual(completed_count_on(history, datetime.date(2026, 6, 4)), 0)

    def test_ignores_invalid_entries(self):
        history = [_iso(2026, 6, 6), "bad", None, 123]
        self.assertEqual(completed_count_on(history, datetime.date(2026, 6, 6)), 1)


class StreakTests(unittest.TestCase):
    def test_consecutive_days_ending_today(self):
        today = datetime.date(2026, 6, 6)
        history = [_iso(2026, 6, 6), _iso(2026, 6, 5), _iso(2026, 6, 4)]
        self.assertEqual(current_streak(history, today), 3)

    def test_today_empty_but_yesterday_continues_streak(self):
        # 今日まだ未完了でも、昨日まで連続していれば継続中として数える（6/5・6/4 で streak=2）
        today = datetime.date(2026, 6, 6)
        history = [_iso(2026, 6, 5), _iso(2026, 6, 4)]
        self.assertEqual(current_streak(history, today), 2)

    def test_today_empty_and_single_yesterday_is_one(self):
        # 今日は未完了でも昨日 1 件あれば継続中（streak=1）
        today = datetime.date(2026, 6, 6)
        history = [_iso(2026, 6, 5)]
        self.assertEqual(current_streak(history, today), 1)

    def test_today_and_yesterday_both_empty_is_zero(self):
        # 今日と昨日の両方が 0 件のときだけ連続が途切れて 0 を返す（6/4 のみ完了）
        today = datetime.date(2026, 6, 6)
        history = [_iso(2026, 6, 4)]
        self.assertEqual(current_streak(history, today), 0)

    def test_gap_breaks_streak(self):
        today = datetime.date(2026, 6, 6)
        # 6/6 と 6/5 は連続、6/3 は飛んでいるので streak=2
        history = [_iso(2026, 6, 6), _iso(2026, 6, 5), _iso(2026, 6, 3)]
        self.assertEqual(current_streak(history, today), 2)

    def test_multiple_completions_same_day_count_once_for_streak(self):
        today = datetime.date(2026, 6, 6)
        history = [_iso(2026, 6, 6, 9), _iso(2026, 6, 6, 18), _iso(2026, 6, 5, 10)]
        self.assertEqual(current_streak(history, today), 2)


class PlannerDayStatsTests(unittest.TestCase):
    def test_overnight_completion_counts_for_previous_planner_day(self):
        # 夜間レンジ 9:00-1:00。暦 6/6 00:30 の完了は 6/5 のプランナー日に数える。
        history = [datetime.datetime(2026, 6, 6, 0, 30).strftime("%Y-%m-%dT%H:%M:%S")]
        self.assertEqual(completed_count_on(history, datetime.date(2026, 6, 5), 9 * 60, 1 * 60), 1)
        self.assertEqual(completed_count_on(history, datetime.date(2026, 6, 6), 9 * 60, 1 * 60), 0)

    def test_overnight_streak_uses_planner_day(self):
        history = [
            datetime.datetime(2026, 6, 6, 0, 30).strftime("%Y-%m-%dT%H:%M:%S"),  # 6/5 planner
            datetime.datetime(2026, 6, 5, 10, 0).strftime("%Y-%m-%dT%H:%M:%S"),  # 6/5 planner
            datetime.datetime(2026, 6, 5, 0, 30).strftime("%Y-%m-%dT%H:%M:%S"),  # 6/4 planner
        ]
        self.assertEqual(current_streak(history, datetime.date(2026, 6, 5), 9 * 60, 1 * 60), 2)


class TotalTests(unittest.TestCase):
    def test_total_counts_valid_entries(self):
        history = [_iso(2026, 6, 6), _iso(2026, 6, 5), "bad"]
        self.assertEqual(total_completed(history), 2)


if __name__ == "__main__":
    unittest.main()
