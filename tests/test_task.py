"""tests/test_task.py — task モジュールの単体テスト"""
import datetime
import unittest

from reminder.recurrence import RECUR_DAILY, RECUR_MONTHLY, RECUR_NONE
from reminder.task import ISO_FMT, Task, build_next_task, make_due


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


if __name__ == "__main__":
    unittest.main()
