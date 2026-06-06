"""tests/test_planner.py — PlannerApp / time_utils / main のテスト

GUI 依存を避けるため _build_ui・_render_tasks・_schedule_all をパッチして
ロジック層（タスク追加・完了・削除・繰り返し再登録・通知スケジュール）を検証する。
"""
import datetime
import unittest
from unittest.mock import Mock, patch

import tkinter as tk

from reminder.app import PlannerApp, ReminderApp
from reminder.recurrence import RECUR_DAILY, RECUR_LABELS, RECUR_NONE
from reminder.task import ISO_FMT, Task
from reminder.time_utils import (
    MAX_AFTER_MS,
    STATUS_EMPTY,
    delay_ms_until,
)


class _DummyVar:
    """tk.StringVar のテスト用代替。Tk インスタンスなしで動作する。"""

    def __init__(self, value: str = ""):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value) -> None:
        self.value = value


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime(ISO_FMT)


def _create_app(tasks=None):
    """UI 構築を伴わない PlannerApp を生成する。"""
    root = Mock()
    root.after.return_value = "job-1"
    with patch.object(PlannerApp, "_build_ui"), \
         patch.object(PlannerApp, "_render_tasks"), \
         patch.object(PlannerApp, "_schedule_all"), \
         patch("reminder.app.load_tasks", return_value=list(tasks or [])), \
         patch("reminder.app.tk.StringVar", side_effect=lambda value="": _DummyVar(value)):
        app = PlannerApp(root)
    # 以降のテストで実メソッドが触れる Treeview をモックに差し替える
    app.tree = Mock()
    app.tree.selection.return_value = ()
    app.tree.get_children.return_value = ()
    return app, root


class DelayMsUntilTests(unittest.TestCase):
    def test_past_returns_zero(self):
        now = datetime.datetime(2026, 6, 6, 10, 0)
        target = datetime.datetime(2026, 6, 6, 9, 0)
        self.assertEqual(delay_ms_until(now, target), 0)

    def test_future_returns_delta(self):
        now = datetime.datetime(2026, 6, 6, 9, 0)
        target = datetime.datetime(2026, 6, 6, 9, 1)
        self.assertEqual(delay_ms_until(now, target), 60_000)

    def test_clamps_to_max(self):
        now = datetime.datetime(2026, 1, 1, 0, 0)
        target = datetime.datetime(2030, 1, 1, 0, 0)
        self.assertEqual(delay_ms_until(now, target), MAX_AFTER_MS)


class CoerceIntTests(unittest.TestCase):
    def test_within_range(self):
        self.assertEqual(PlannerApp._coerce_int("10", 0, 23), 10)

    def test_below_min(self):
        self.assertEqual(PlannerApp._coerce_int("-5", 0, 23), 0)

    def test_above_max(self):
        self.assertEqual(PlannerApp._coerce_int("99", 0, 23), 23)

    def test_non_numeric_returns_min(self):
        self.assertEqual(PlannerApp._coerce_int("abc", 1, 99), 1)

    def test_empty_returns_min(self):
        self.assertEqual(PlannerApp._coerce_int("", 1, 99), 1)


class NormalizeInputTests(unittest.TestCase):
    def test_normalize_time_pads_and_clamps(self):
        app, _ = _create_app()
        app.hour_var.set("30")
        app.minute_var.set("5")
        app._normalize_time_inputs()
        self.assertEqual(app.hour_var.get(), "23")
        self.assertEqual(app.minute_var.get(), "05")

    def test_normalize_interval_clamps(self):
        app, _ = _create_app()
        app.interval_var.set("999")
        self.assertEqual(app._normalize_interval_input(), 99)
        self.assertEqual(app.interval_var.get(), "99")

    def test_normalize_interval_non_numeric(self):
        app, _ = _create_app()
        app.interval_var.set("abc")
        self.assertEqual(app._normalize_interval_input(), 1)


class AddTaskTests(unittest.TestCase):
    @patch("reminder.app.messagebox.showwarning")
    def test_empty_title_warns(self, mock_warn):
        app, root = _create_app()
        app.title_var.set("   ")
        app.add_task()
        mock_warn.assert_called_once()
        self.assertEqual(app.tasks, [])
        root.after.assert_not_called()

    @patch("reminder.app.save_tasks")
    def test_add_creates_task_and_schedules(self, mock_save):
        app, root = _create_app()
        app.title_var.set("会議の準備")
        app.hour_var.set("09")
        app.minute_var.set("30")
        app.recur_var.set(RECUR_LABELS[RECUR_DAILY])
        app.interval_var.set("2")
        app.add_task()

        self.assertEqual(len(app.tasks), 1)
        task = app.tasks[0]
        self.assertEqual(task.title, "会議の準備")
        self.assertEqual(task.recur_unit, RECUR_DAILY)
        self.assertEqual(task.recur_interval, 2)
        # make_due により期限は常に未来 → 通知がスケジュールされる
        root.after.assert_called_once()
        mock_save.assert_called_once()
        # 入力欄はクリアされる
        self.assertEqual(app.title_var.get(), "")

    @patch("reminder.app.save_tasks")
    def test_add_non_recurring(self, _mock_save):
        app, _ = _create_app()
        app.title_var.set("買い物")
        app.recur_var.set(RECUR_LABELS[RECUR_NONE])
        app.add_task()
        self.assertEqual(app.tasks[0].recur_unit, RECUR_NONE)


class CompleteTaskTests(unittest.TestCase):
    @patch("reminder.app.save_tasks")
    def test_complete_non_recurring_removes_task(self, mock_save):
        task = Task(title="買い物", due="2026-06-06T09:00:00")
        app, root = _create_app([task])
        app.tree.selection.return_value = (task.id,)
        app.complete_selected()
        self.assertEqual(app.tasks, [])
        mock_save.assert_called_once()

    @patch("reminder.app.save_tasks")
    def test_complete_recurring_reschedules_from_now(self, _mock_save):
        task = Task(title="掃除", due=_iso(datetime.datetime.now() - datetime.timedelta(days=1)),
                    recur_unit=RECUR_DAILY, recur_interval=1)
        app, root = _create_app([task])
        app.tree.selection.return_value = (task.id,)

        before = datetime.datetime.now()
        app.complete_selected()
        after = datetime.datetime.now()

        # 元タスクは消え、次回タスクが 1 件再登録される
        self.assertEqual(len(app.tasks), 1)
        nxt = app.tasks[0]
        self.assertNotEqual(nxt.id, task.id)
        self.assertEqual(nxt.title, "掃除")
        self.assertEqual(nxt.recur_unit, RECUR_DAILY)
        # 次回期限は「完了時点（今）+ 1 日」付近
        expected_low = before + datetime.timedelta(days=1) - datetime.timedelta(seconds=2)
        expected_high = after + datetime.timedelta(days=1) + datetime.timedelta(seconds=2)
        self.assertTrue(expected_low <= nxt.due_dt <= expected_high)
        # 次回分の通知がスケジュールされる
        root.after.assert_called_once()

    def test_complete_without_selection_sets_status(self):
        app, _ = _create_app()
        app.status_var = _DummyVar()
        app.tree.selection.return_value = ()
        app.complete_selected()
        self.assertIn("選択", app.status_var.get())


class DeleteTaskTests(unittest.TestCase):
    @patch("reminder.app.save_tasks")
    def test_delete_removes_selected(self, mock_save):
        task = Task(title="x", due="2026-06-06T09:00:00")
        app, _ = _create_app([task])
        app.tree.selection.return_value = (task.id,)
        app.delete_selected()
        self.assertEqual(app.tasks, [])
        mock_save.assert_called_once()

    def test_delete_without_selection(self):
        app, _ = _create_app()
        app.status_var = _DummyVar()
        app.delete_selected()
        self.assertIn("選択", app.status_var.get())


class SelectedTaskTests(unittest.TestCase):
    def test_returns_matching_task(self):
        task = Task(title="x", due="2026-06-06T09:00:00")
        app, _ = _create_app([task])
        app.tree.selection.return_value = (task.id,)
        self.assertIs(app._selected_task(), task)

    def test_returns_none_when_no_selection(self):
        app, _ = _create_app()
        app.tree.selection.return_value = ()
        self.assertIsNone(app._selected_task())


class ScheduleTaskTests(unittest.TestCase):
    def test_past_task_not_scheduled(self):
        task = Task(title="x", due=_iso(datetime.datetime.now() - datetime.timedelta(hours=1)))
        app, root = _create_app()
        app._schedule_task(task)
        root.after.assert_not_called()
        self.assertNotIn(task.id, app.jobs)

    def test_future_task_scheduled(self):
        task = Task(title="x", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=1)))
        app, root = _create_app()
        app._schedule_task(task)
        root.after.assert_called_once()
        self.assertIn(task.id, app.jobs)

    def test_cancel_job_calls_after_cancel(self):
        app, root = _create_app()
        app.jobs["abc"] = "job-9"
        app._cancel_job("abc")
        root.after_cancel.assert_called_once_with("job-9")
        self.assertNotIn("abc", app.jobs)


class OnTaskDueTests(unittest.TestCase):
    @patch("reminder.app.messagebox.showinfo")
    @patch("reminder.app.play_notification_sound")
    def test_notifies_when_due(self, mock_sound, mock_showinfo):
        task = Task(title="運動", due=_iso(datetime.datetime.now() - datetime.timedelta(minutes=1)))
        app, root = _create_app([task])
        app._on_task_due(task.id)
        mock_sound.assert_called_once_with(root, "運動")
        mock_showinfo.assert_called_once()

    @patch("reminder.app.messagebox.showinfo")
    @patch("reminder.app.play_notification_sound")
    def test_reschedules_when_fired_early(self, mock_sound, mock_showinfo):
        task = Task(title="x", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=2)))
        app, root = _create_app([task])
        app._on_task_due(task.id)
        mock_showinfo.assert_not_called()
        mock_sound.assert_not_called()
        # 再スケジュールされる
        root.after.assert_called_once()

    @patch("reminder.app.messagebox.showinfo")
    @patch("reminder.app.play_notification_sound")
    def test_missing_task_is_noop(self, mock_sound, mock_showinfo):
        app, _ = _create_app()
        app._on_task_due("nonexistent")
        mock_sound.assert_not_called()
        mock_showinfo.assert_not_called()


class FormatTests(unittest.TestCase):
    def test_format_due(self):
        self.assertEqual(
            PlannerApp._format_due(datetime.datetime(2026, 6, 6, 9, 5)), "06/06 09:05"
        )

    def test_format_recur_none(self):
        self.assertEqual(PlannerApp._format_recur(Task(title="x", due="2026-06-06T09:00:00")), "—")

    def test_format_recur_with_interval(self):
        task = Task(title="x", due="2026-06-06T09:00:00", recur_unit=RECUR_DAILY, recur_interval=2)
        self.assertEqual(PlannerApp._format_recur(task), "2日ごと")


class RenderTasksTests(unittest.TestCase):
    def test_empty_sets_status(self):
        app, _ = _create_app()
        app.status_var = _DummyVar()
        app.tree.get_children.return_value = ()
        app._render_tasks()
        self.assertEqual(app.status_var.get(), STATUS_EMPTY)

    def test_inserts_rows_for_tasks(self):
        task = Task(title="x", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=1)))
        app, _ = _create_app([task])
        app.tree.get_children.return_value = ()
        app._render_tasks()
        app.tree.insert.assert_called_once()


class BackwardCompatTests(unittest.TestCase):
    def test_reminder_app_alias(self):
        self.assertIs(ReminderApp, PlannerApp)


class MainTests(unittest.TestCase):
    @patch("reminder.__main__.PlannerApp")
    @patch("reminder.__main__.tk.Tk")
    def test_main_creates_app_and_runs_mainloop(self, mock_tk_cls, mock_app_cls):
        mock_root = Mock()
        mock_tk_cls.return_value = mock_root
        from reminder.__main__ import main
        main()
        mock_tk_cls.assert_called_once()
        mock_app_cls.assert_called_once_with(mock_root)
        mock_root.mainloop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
