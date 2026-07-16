"""tests/test_task.py — task モジュールの単体テスト"""
import datetime
import unittest

from reminder.recurrence import RECUR_DAILY, RECUR_MONTHLY, RECUR_NONE, RECUR_WEEKLY
from reminder.task import (
    DEFAULT_DURATION,
    ISO_FMT,
    MAX_DURATION,
    MIN_DURATION,
    Task,
    build_next_task,
    make_due,
)


class DurationAndBacklogTests(unittest.TestCase):
    def test_default_duration(self):
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00").duration_min, DEFAULT_DURATION)

    def test_duration_clamped(self):
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", duration_min=1).duration_min, MIN_DURATION)
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", duration_min=99999).duration_min, MAX_DURATION)

    def test_duration_non_numeric_defaults(self):
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", duration_min="ab").duration_min, DEFAULT_DURATION)

    def test_duration_infinite_defaults(self):
        # int(float('inf')) は TypeError/ValueError ではなく OverflowError を送出するため、
        # 他の変換不能値と同じく既定値へフォールバックすることを検証する
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", duration_min=float("inf")).duration_min, DEFAULT_DURATION)
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", duration_min=float("-inf")).duration_min, DEFAULT_DURATION)

    def test_backlog_task_is_not_scheduled(self):
        t = Task(title="あとで", due="")
        self.assertFalse(t.is_scheduled)
        with self.assertRaises(ValueError):
            _ = t.due_dt

    def test_default_due_is_backlog(self):
        self.assertFalse(Task(title="あとで").is_scheduled)

    def test_scheduled_task_end_dt(self):
        t = Task(title="x", due="2026-06-06T09:00:00", duration_min=90)
        self.assertTrue(t.is_scheduled)
        self.assertEqual(t.end_dt, datetime.datetime(2026, 6, 6, 10, 30))

    def test_to_dict_round_trip_carries_duration(self):
        t = Task(title="x", due="2026-06-06T09:00:00", duration_min=45)
        self.assertEqual(Task.from_dict(t.to_dict()).duration_min, 45)

    def test_empty_title_raises(self):
        with self.assertRaises(ValueError):
            Task(title="", due="2026-06-06T09:00:00")
        with self.assertRaises(ValueError):
            Task(title="   ", due="2026-06-06T09:00:00")

    def test_non_string_title_raises(self):
        with self.assertRaises(ValueError):
            Task(title=123, due="2026-06-06T09:00:00")

    def test_completed_coerced_to_strict_bool(self):
        # 文字列 "false"（Python では真値）は完了扱いにしない
        self.assertFalse(Task(title="x", due="2026-06-06T09:00:00", completed="false").completed)
        self.assertFalse(Task(title="x", due="2026-06-06T09:00:00", completed=1).completed)
        self.assertTrue(Task(title="x", due="2026-06-06T09:00:00", completed=True).completed)

    def test_from_dict_completed_string_is_not_done(self):
        t = Task.from_dict({"title": "x", "due": "2026-06-06T09:00:00", "completed": "false"})
        self.assertFalse(t.completed)


class TaskModelTests(unittest.TestCase):
    def test_defaults(self):
        t = Task(title="買い物", due="2026-06-06T09:00:00")
        self.assertEqual(t.recur_unit, RECUR_NONE)
        self.assertEqual(t.recur_interval, 1)
        self.assertFalse(t.completed)
        self.assertIsNone(t.completed_at)
        self.assertTrue(t.id)

    def test_unique_ids(self):
        a = Task(title="a", due="2026-06-06T09:00:00")
        b = Task(title="b", due="2026-06-06T09:00:00")
        self.assertNotEqual(a.id, b.id)

    def test_due_dt_property(self):
        t = Task(title="x", due="2026-06-06T09:30:00")
        self.assertEqual(t.due_dt, datetime.datetime(2026, 6, 6, 9, 30))

    def test_is_recurring(self):
        self.assertFalse(Task(title="x", due="2026-06-06T09:00:00").is_recurring)
        self.assertTrue(Task(title="x", due="2026-06-06T09:00:00", recur_unit=RECUR_DAILY).is_recurring)

    def test_invalid_unit_normalized_to_none(self):
        t = Task(title="x", due="2026-06-06T09:00:00", recur_unit="weird")
        self.assertEqual(t.recur_unit, RECUR_NONE)

    def test_interval_clamped(self):
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", recur_interval=0).recur_interval, 1)
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", recur_interval=999).recur_interval, 99)

    def test_non_numeric_interval_defaults(self):
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", recur_interval="abc").recur_interval, 1)

    def test_interval_infinite_defaults(self):
        # int(float('inf')) は TypeError/ValueError ではなく OverflowError を送出するため、
        # 他の変換不能値と同じく既定値（最小値）へフォールバックすることを検証する
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", recur_interval=float("inf")).recur_interval, 1)
        self.assertEqual(Task(title="x", due="2026-06-06T09:00:00", recur_interval=float("-inf")).recur_interval, 1)

    def test_to_dict_from_dict_round_trip(self):
        t = Task(title="運動", due="2026-06-06T18:00:00", recur_unit=RECUR_DAILY, recur_interval=3)
        restored = Task.from_dict(t.to_dict())
        self.assertEqual(restored.title, t.title)
        self.assertEqual(restored.due, t.due)
        self.assertEqual(restored.recur_unit, t.recur_unit)
        self.assertEqual(restored.recur_interval, t.recur_interval)
        self.assertEqual(restored.id, t.id)

    def test_from_dict_ignores_unknown_keys(self):
        t = Task.from_dict({"title": "x", "due": "2026-06-06T09:00:00", "unknown": 1})
        self.assertEqual(t.title, "x")

    def test_unparseable_due_raises(self):
        # 期限がパースできない値の場合は構築時に例外を送出する
        with self.assertRaises(ValueError):
            Task(title="x", due="not-a-date")

    def test_from_dict_unparseable_due_raises(self):
        with self.assertRaises(ValueError):
            Task.from_dict({"title": "x", "due": "2026/06/06 09:00"})


class MakeDueTests(unittest.TestCase):
    def test_future_time_today(self):
        now = datetime.datetime(2026, 6, 6, 8, 0)
        due = make_due(datetime.time(9, 0), now=now)
        self.assertEqual(due, "2026-06-06T09:00:00")

    def test_past_time_rolls_to_next_day(self):
        now = datetime.datetime(2026, 6, 6, 10, 0)
        due = make_due(datetime.time(9, 0), now=now)
        self.assertEqual(due, "2026-06-07T09:00:00")

    def test_equal_time_rolls_to_next_day(self):
        now = datetime.datetime(2026, 6, 6, 9, 0, 30)
        due = make_due(datetime.time(9, 0), now=now)
        self.assertEqual(due, "2026-06-07T09:00:00")

    def test_due_parseable_with_iso_fmt(self):
        now = datetime.datetime(2026, 6, 6, 8, 0)
        due = make_due(datetime.time(23, 59), now=now)
        datetime.datetime.strptime(due, ISO_FMT)  # 例外が出ないこと

    def test_no_roll_keeps_today_even_if_past(self):
        # roll_if_past=False のとき、過去時刻でも当日に配置される
        now = datetime.datetime(2026, 6, 6, 10, 0)
        due = make_due(datetime.time(9, 0), now=now, roll_if_past=False)
        self.assertEqual(due, "2026-06-06T09:00:00")


class BuildNextTaskTests(unittest.TestCase):
    def test_non_recurring_returns_none(self):
        t = Task(title="x", due="2026-06-06T09:00:00", recur_unit=RECUR_NONE)
        self.assertIsNone(build_next_task(t, datetime.datetime(2026, 6, 6, 10, 0)))

    def test_recurring_uses_completion_time_as_origin(self):
        t = Task(title="掃除", due="2026-06-06T09:00:00", recur_unit=RECUR_DAILY, recur_interval=1)
        # 完了が予定より遅れても、次回は「完了時点」基準になる
        completed = datetime.datetime(2026, 6, 8, 22, 0)
        nxt = build_next_task(t, completed)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.due, "2026-06-09T22:00:00")
        self.assertEqual(nxt.title, "掃除")
        self.assertEqual(nxt.recur_unit, RECUR_DAILY)
        self.assertEqual(nxt.recur_interval, 1)
        self.assertFalse(nxt.completed)

    def test_recurring_monthly(self):
        t = Task(title="支払い", due="2026-06-06T09:00:00", recur_unit=RECUR_MONTHLY, recur_interval=1)
        nxt = build_next_task(t, datetime.datetime(2026, 6, 6, 9, 0))
        self.assertEqual(nxt.due, "2026-07-06T09:00:00")

    def test_next_task_has_new_id(self):
        t = Task(title="x", due="2026-06-06T09:00:00", recur_unit=RECUR_DAILY)
        nxt = build_next_task(t, datetime.datetime(2026, 6, 6, 9, 0))
        self.assertNotEqual(nxt.id, t.id)

    def test_next_task_carries_duration(self):
        t = Task(title="x", due="2026-06-06T09:00:00", duration_min=75, recur_unit=RECUR_DAILY)
        nxt = build_next_task(t, datetime.datetime(2026, 6, 6, 9, 0))
        self.assertEqual(nxt.duration_min, 75)

    def test_recurring_backlog_stays_backlog(self):
        # 「あとでやる」(未スケジュール) の繰り返しタスクは、完了しても次回は
        # backlog のまま再生成され、タイムラインへ勝手に固定されない。
        t = Task(title="部屋の片付け", due="", recur_unit=RECUR_WEEKLY, recur_interval=1)  # 時刻未定・週次繰り返しの backlog タスクを用意する
        self.assertFalse(t.is_scheduled)  # 前提: 元タスクは backlog（あとでやる）
        nxt = build_next_task(t, datetime.datetime(2026, 7, 7, 22, 37, 15))  # 22:37:15 に完了したとして次回タスクを生成する
        self.assertIsNotNone(nxt)  # 繰り返し設定があるので次回タスクは生成される
        self.assertEqual(nxt.due, "")  # 次回も backlog（開始時刻なし）で再生成される
        self.assertFalse(nxt.is_scheduled)  # タイムラインへ固定されていないこと
        # 完了時刻の時分秒が due に漏れて予定化されていないこと（回帰防止）
        self.assertNotIn("22:37:15", nxt.due)
        self.assertEqual(nxt.recur_unit, RECUR_WEEKLY)  # 繰り返し単位は引き継ぐ
        self.assertEqual(nxt.recur_interval, 1)  # 繰り返し間隔も引き継ぐ
        self.assertFalse(nxt.completed)  # 次回タスクは未完了で始まる

    def test_recurring_scheduled_still_gets_due(self):
        # 回帰防止: スケジュール済みの繰り返しタスクは従来どおり次回開始時刻を持つ。
        t = Task(title="朝会", due="2026-06-06T09:00:00", recur_unit=RECUR_WEEKLY, recur_interval=1)  # 開始時刻を持つ週次繰り返しの scheduled タスクを用意する
        nxt = build_next_task(t, datetime.datetime(2026, 6, 6, 9, 0))  # 09:00 に完了したとして次回タスクを生成する
        self.assertTrue(nxt.is_scheduled)  # スケジュール済みのまま次回も予定される
        self.assertEqual(nxt.due, "2026-06-13T09:00:00")  # 1 週間後の同時刻に設定される


if __name__ == "__main__":
    unittest.main()
