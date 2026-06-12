"""tests/test_planner.py — PlannerApp（タイムライン版）/ main のテスト

GUI 依存を避けるため _build_ui・_refresh・_schedule_all をパッチして
ロジック層（タスク追加・完了・削除・あとで⇄予定の移動・通知スケジュール）を検証する。
"""
import datetime
import unittest
from unittest.mock import Mock, patch

from reminder.app import PlannerApp, ReminderApp
from reminder.config import Prefs
from reminder.recurrence import RECUR_DAILY, RECUR_LABELS, RECUR_NONE
from reminder.task import ISO_FMT, Task


class _DummyVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _iso(dt):
    return dt.strftime(ISO_FMT)


class AppTestCase(unittest.TestCase):
    """save/load をモックし、GUI 無しで PlannerApp を生成する基底クラス。"""

    def setUp(self):
        self.save_tasks = self._start("reminder.app.save_tasks")
        self.save_prefs = self._start("reminder.app.save_prefs")
        # 起動時整理はテストでは無効化（提供したタスクをそのまま使う）
        self.prune = self._start("reminder.app.prune_old_completed",
                                 side_effect=lambda tasks, *a, **k: tasks)
        self.carry = self._start("reminder.app.carry_over_overdue",
                                 side_effect=lambda *a, **k: 0)

    def _start(self, target, **kw):
        p = patch(target, **kw)
        mock = p.start()
        self.addCleanup(p.stop)
        return mock

    def _app(self, tasks=None, prefs=None):
        root = Mock()
        root.after.return_value = "job-1"
        with patch.object(PlannerApp, "_build_ui"), \
             patch.object(PlannerApp, "_refresh"), \
             patch.object(PlannerApp, "_schedule_all"), \
             patch("reminder.app.load_tasks", return_value=list(tasks or [])), \
             patch("reminder.app.load_prefs", return_value=prefs or Prefs()), \
             patch("reminder.app.tk.StringVar", side_effect=lambda value="": _DummyVar(value)):
            app = PlannerApp(root)
        app.timeline_tree = Mock()
        app.timeline_tree.selection.return_value = ()
        app.timeline_tree.get_children.return_value = ()
        app.backlog_tree = Mock()
        app.backlog_tree.selection.return_value = ()
        app.backlog_tree.get_children.return_value = ()
        app.status_var = _DummyVar()
        return app, root


class CoerceIntTests(unittest.TestCase):
    def test_within(self):
        self.assertEqual(PlannerApp._coerce_int("10", 0, 23), 10)

    def test_clamps_and_nonnumeric(self):
        self.assertEqual(PlannerApp._coerce_int("99", 0, 23), 23)
        self.assertEqual(PlannerApp._coerce_int("-1", 0, 23), 0)
        self.assertEqual(PlannerApp._coerce_int("ab", 5, 99), 5)


class InputNormalizeTests(AppTestCase):
    def test_start_time_normalized(self):
        app, _ = self._app()
        app.hour_var.set("30")
        app.minute_var.set("7")
        t = app._input_start_time()
        self.assertEqual((t.hour, t.minute), (23, 7))
        self.assertEqual(app.hour_var.get(), "23")
        self.assertEqual(app.minute_var.get(), "07")

    def test_duration_normalized(self):
        app, _ = self._app()
        app.dur_var.set("100000")
        self.assertEqual(app._input_duration(), 24 * 60)

    def test_recurrence_parsed(self):
        app, _ = self._app()
        app.recur_var.set(RECUR_LABELS[RECUR_DAILY])
        app.interval_var.set("3")
        self.assertEqual(app._input_recurrence(), (RECUR_DAILY, 3))


class WakeSleepTests(AppTestCase):
    def test_reads_from_prefs(self):
        app, _ = self._app(prefs=Prefs(wake="06:00", sleep="22:00"))
        self.assertEqual(app._wake_min(), 360)
        self.assertEqual(app._sleep_min(), 22 * 60)

    def test_invalid_prefs_fall_back(self):
        app, _ = self._app(prefs=Prefs(wake="bad", sleep="??"))
        self.assertEqual(app._wake_min(), 7 * 60)
        self.assertEqual(app._sleep_min(), 23 * 60)


class AddToTimelineTests(AppTestCase):
    @patch("reminder.app.messagebox.showwarning")
    def test_empty_title_warns(self, mock_warn):
        app, root = self._app()
        app.title_var.set("   ")
        app.add_to_timeline()
        mock_warn.assert_called_once()
        self.assertEqual(app.tasks, [])

    def test_adds_scheduled_future_task(self):
        app, _ = self._app()
        app.title_var.set("会議")
        app.hour_var.set("23")
        app.minute_var.set("59")
        app.dur_var.set("45")
        app.recur_var.set(RECUR_LABELS[RECUR_DAILY])
        app.interval_var.set("2")
        app.add_to_timeline()

        self.assertEqual(len(app.tasks), 1)
        task = app.tasks[0]
        self.assertTrue(task.is_scheduled)
        # 入力した時刻が保持され、過去なら翌日へ繰り上がって未来になる
        self.assertEqual((task.due_dt.hour, task.due_dt.minute), (23, 59))
        self.assertGreaterEqual(task.due_dt, datetime.datetime.now() - datetime.timedelta(seconds=5))
        self.assertEqual(task.duration_min, 45)
        self.assertEqual(task.recur_unit, RECUR_DAILY)
        self.assertEqual(task.recur_interval, 2)
        self.assertEqual(app.title_var.get(), "")  # クリアされる
        self.save_tasks.assert_called()

    def test_due_uses_get_now_clock(self):
        # _get_now() を固定すると、due の繰り上げ判定も固定時刻基準になる
        # （実時計に依存せず、時刻源が _get_now() に一元化されていることの検証）
        app, _ = self._app()
        fixed = datetime.datetime(2026, 6, 1, 12, 0)
        app._get_now = lambda: fixed
        app.title_var.set("朝活")
        app.hour_var.set("10")
        app.minute_var.set("00")
        app.add_to_timeline()
        # 固定時刻 12:00 から見て 10:00 は過去なので翌日 6/2 に繰り上がる
        self.assertEqual(app.tasks[0].due_dt, datetime.datetime(2026, 6, 2, 10, 0))


class AddToBacklogTests(AppTestCase):
    def test_adds_backlog_task(self):
        app, _ = self._app()
        app.title_var.set("資料を読む")
        app.dur_var.set("60")
        app.add_to_backlog()
        self.assertEqual(len(app.tasks), 1)
        self.assertFalse(app.tasks[0].is_scheduled)
        self.assertEqual(app.tasks[0].duration_min, 60)
        self.assertEqual(app.title_var.get(), "")


class DefaultStartTests(unittest.TestCase):
    def test_rounds_up_to_next_5_min(self):
        self.assertEqual(PlannerApp._default_start(datetime.datetime(2026, 6, 6, 10, 31)),
                         datetime.datetime(2026, 6, 6, 10, 35))

    def test_carries_hour_when_minute_wraps(self):
        # 10:57 → 11:00（時が繰り上がる）。過去時刻にならない。
        self.assertEqual(PlannerApp._default_start(datetime.datetime(2026, 6, 6, 10, 57)),
                         datetime.datetime(2026, 6, 6, 11, 0))

    def test_on_5_min_boundary_advances_by_5(self):
        self.assertEqual(PlannerApp._default_start(datetime.datetime(2026, 6, 6, 10, 30, 12)),
                         datetime.datetime(2026, 6, 6, 10, 35))

    def test_carries_day_at_end_of_day(self):
        self.assertEqual(PlannerApp._default_start(datetime.datetime(2026, 6, 6, 23, 58)),
                         datetime.datetime(2026, 6, 7, 0, 0))


class CompleteTests(AppTestCase):
    def test_complete_none_selected(self):
        app, _ = self._app()
        app.complete_timeline_selected()
        self.assertIn("選択", app.status_var.get())

    def test_complete_already_completed_is_noop(self):
        task = Task(title="済タスク", due=_iso(datetime.datetime.now().replace(microsecond=0)),
                    recur_unit=RECUR_DAILY, completed=True,
                    completed_at=_iso(datetime.datetime.now()))
        app, _ = self._app([task])
        app._tl_selected = task.id
        app.complete_timeline_selected()
        # 統計に二重計上されず、繰り返しの重複生成もない
        self.assertEqual(len(app.prefs.completions), 0)
        self.assertEqual(len(app.tasks), 1)
        self.assertIn("既に完了", app.status_var.get())

    def test_complete_non_recurring_marks_and_records(self):
        task = Task(title="買い物", due=_iso(datetime.datetime.now().replace(microsecond=0)))
        app, _ = self._app([task])
        app._tl_selected = task.id
        app.complete_timeline_selected()
        self.assertTrue(task.completed)
        self.assertIsNotNone(task.completed_at)
        self.assertIn(task, app.tasks)  # 完了タスクは残る（タイムラインに済表示）
        self.assertEqual(len(app.prefs.completions), 1)
        self.save_prefs.assert_called()

    def test_complete_recurring_appends_next(self):
        task = Task(title="掃除", due=_iso(datetime.datetime.now().replace(microsecond=0)),
                    recur_unit=RECUR_DAILY, recur_interval=1)
        app, root = self._app([task])
        app._tl_selected = task.id
        before = datetime.datetime.now()
        app.complete_timeline_selected()
        # 元タスク(完了) + 次回タスク = 2 件
        self.assertEqual(len(app.tasks), 2)
        nxt = [t for t in app.tasks if not t.completed][0]
        self.assertEqual(nxt.title, "掃除")
        self.assertGreaterEqual(nxt.due_dt, before + datetime.timedelta(days=1) - datetime.timedelta(seconds=2))
        root.after.assert_called_once()  # 次回分がスケジュールされる


class DeleteTests(AppTestCase):
    def test_delete_removes(self):
        task = Task(title="x", due=_iso(datetime.datetime.now().replace(microsecond=0)))
        app, _ = self._app([task])
        app._tl_selected = task.id
        app.delete_timeline_selected()
        self.assertEqual(app.tasks, [])

    def test_delete_none_selected(self):
        app, _ = self._app()
        app.delete_backlog_selected()
        self.assertIn("選択", app.status_var.get())


class MoveTests(AppTestCase):
    def test_move_to_backlog_clears_due(self):
        task = Task(title="x", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=1)))
        app, _ = self._app([task])
        app.jobs[task.id] = "job-9"
        app._tl_selected = task.id
        app.move_to_backlog()
        self.assertEqual(task.due, "")
        self.assertNotIn(task.id, app.jobs)  # 通知ジョブが解除される

    def test_schedule_backlog_sets_due_today(self):
        task = Task(title="x", due="")
        app, _ = self._app([task])
        app.backlog_tree.selection.return_value = (task.id,)
        app.hour_var.set("10")
        app.minute_var.set("30")
        app.schedule_backlog_selected()
        self.assertTrue(task.is_scheduled)
        # 入力時刻を保持し、過去なら翌日へ繰り上がって未来になる
        self.assertEqual((task.due_dt.hour, task.due_dt.minute), (10, 30))
        self.assertGreaterEqual(task.due_dt, datetime.datetime.now() - datetime.timedelta(seconds=5))


class ScheduleTaskTests(AppTestCase):
    def test_backlog_not_scheduled(self):
        app, root = self._app()
        app._schedule_task(Task(title="x", due=""))
        root.after.assert_not_called()

    def test_completed_not_scheduled(self):
        app, root = self._app()
        task = Task(title="x", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=1)),
                    completed=True, completed_at=_iso(datetime.datetime.now()))
        app._schedule_task(task)
        root.after.assert_not_called()

    def test_past_not_scheduled(self):
        app, root = self._app()
        app._schedule_task(Task(title="x", due=_iso(datetime.datetime.now() - datetime.timedelta(hours=1))))
        root.after.assert_not_called()

    def test_future_scheduled(self):
        app, root = self._app()
        task = Task(title="x", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=1)))
        app._schedule_task(task)
        root.after.assert_called_once()
        self.assertIn(task.id, app.jobs)

    def test_cancel_job(self):
        app, root = self._app()
        app.jobs["a"] = "job-9"
        app._cancel_job("a")
        root.after_cancel.assert_called_once_with("job-9")
        self.assertNotIn("a", app.jobs)

    def test_schedule_all_survives_failure(self):
        t1 = Task(title="a", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=1)))
        t2 = Task(title="b", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=2)))
        app, root = self._app()
        app.tasks = [t1, t2]
        root.after.side_effect = [RuntimeError("fail"), "job-2"]
        app._schedule_all()
        self.assertNotIn(t1.id, app.jobs)
        self.assertEqual(app.jobs.get(t2.id), "job-2")


class OnTaskDueTests(AppTestCase):
    @patch("reminder.app.messagebox.showinfo")
    @patch("reminder.app.play_notification_sound")
    def test_notifies_when_due(self, mock_sound, mock_info):
        task = Task(title="運動", due=_iso(datetime.datetime.now() - datetime.timedelta(minutes=1)))
        app, root = self._app([task])
        app._on_task_due(task.id)
        mock_sound.assert_called_once_with(root, "運動")
        mock_info.assert_called_once()

    @patch("reminder.app.messagebox.showinfo")
    @patch("reminder.app.play_notification_sound")
    def test_reschedules_when_early(self, mock_sound, mock_info):
        task = Task(title="x", due=_iso(datetime.datetime.now() + datetime.timedelta(hours=2)))
        app, root = self._app([task])
        app._on_task_due(task.id)
        mock_info.assert_not_called()
        root.after.assert_called_once()

    @patch("reminder.app.messagebox.showinfo")
    @patch("reminder.app.play_notification_sound")
    def test_completed_task_is_noop(self, mock_sound, mock_info):
        task = Task(title="x", due=_iso(datetime.datetime.now() - datetime.timedelta(minutes=1)),
                    completed=True, completed_at=_iso(datetime.datetime.now()))
        app, _ = self._app([task])
        app._on_task_due(task.id)
        mock_sound.assert_not_called()

    @patch("reminder.app.messagebox.showinfo")
    @patch("reminder.app.play_notification_sound")
    def test_missing_task_is_noop(self, mock_sound, mock_info):
        app, _ = self._app()
        app._on_task_due("nope")
        mock_sound.assert_not_called()


class RenderTests(AppTestCase):
    def test_refresh_runs_without_error(self):
        # 実際の _refresh を Mock ツリー上で動かし、例外が出ないことを確認
        task = Task(title="朝会", due=_iso(datetime.datetime.now().replace(microsecond=0)))
        backlog = Task(title="あとで", due="")
        app, _ = self._app([task, backlog])
        app.date_var = _DummyVar()
        app.stats_var = _DummyVar()
        app._refresh()
        # カレンダー（Canvas）には時刻グリッドが描かれ、バックログには insert が走る
        self.assertTrue(app.timeline_tree.delete.called)
        self.assertTrue(app.timeline_tree.create_line.called)
        self.assertTrue(app.backlog_tree.insert.called)
        self.assertIn("完了", app.stats_var.get())


class CalendarRenderTests(AppTestCase):
    """カレンダー（デイビュー）の描画ジオメトリと操作の検証。"""

    def test_offhours_task_stays_in_view(self):
        # 起床(07:00)より前に始まるタスクも負の座標にならず可視範囲に入る
        today = datetime.date.today()
        due = datetime.datetime.combine(today, datetime.time(5, 0))
        task = Task(title="早朝", due=_iso(due), duration_min=30)
        app, _ = self._app([task])
        app._render_timeline(today)
        blocks = [b for b in app._tl_blocks if b[5] == task.id]
        self.assertTrue(blocks)  # ブロックが描かれている
        _x0, y0, _x1, y1, _cb, _tid, _done = blocks[0]
        self.assertGreaterEqual(y0, 0)   # 負の y に描かれない（見切れない）
        self.assertGreater(y1, y0)

    def test_grid_labels_respect_minute_offset(self):
        # 起床が 07:30（非正時）でも罫線ラベルは実際の正時（08:00〜）になる
        today = datetime.date.today()
        app, _ = self._app(prefs=Prefs(wake="07:30", sleep="23:00"))
        app._render_timeline(today)
        texts = [c.kwargs.get("text") for c in app.timeline_tree.create_text.call_args_list]
        self.assertIn("08:00", texts)
        self.assertNotIn("07:00", texts)  # 起床が 07:30 なので 07:00 の誤ラベルは出ない

    def test_checkbox_click_completes(self):
        # チェックボックス領域のクリックでタスクが完了する（Any Planner 風）
        today = datetime.date.today()
        now = datetime.datetime.now().replace(microsecond=0)
        task = Task(title="掃除", due=_iso(now))
        app, _ = self._app([task])
        app.date_var = _DummyVar()
        app.stats_var = _DummyVar()
        app._render_timeline(today)
        blocks = [b for b in app._tl_blocks if b[5] == task.id]
        self.assertTrue(blocks)
        cb = blocks[0][4]
        ev = Mock()
        ev.x = (cb[0] + cb[2]) / 2
        ev.y = (cb[1] + cb[3]) / 2
        app.timeline_tree.canvasx.side_effect = lambda v: v
        app.timeline_tree.canvasy.side_effect = lambda v: v
        app._on_timeline_click(ev)
        self.assertTrue(task.completed)


class RolloverTests(AppTestCase):
    def test_refresh_runs_rollover(self):
        # 再描画のたびに繰り越し・整理が走る（日跨ぎで開きっぱなしでも消えない）
        app, _ = self._app()
        app.date_var = _DummyVar()
        app.stats_var = _DummyVar()
        self.carry.reset_mock()
        self.prune.reset_mock()
        app._refresh()
        self.assertTrue(self.carry.called)
        self.assertTrue(self.prune.called)

    def test_reschedule_after_rollover(self):
        # 繰り越しが発生したら通知を再登録する
        app, _ = self._app()
        app.date_var = _DummyVar()
        app.stats_var = _DummyVar()
        app._schedule_all = Mock()
        self.carry.side_effect = lambda *a, **k: 1  # 繰り越し 1 件発生
        app._refresh()
        app._schedule_all.assert_called_once()
        self.save_tasks.assert_called()

    def test_no_reschedule_without_rollover(self):
        # 繰り越しが無ければ再スケジュールしない（無駄な再登録を避ける）
        app, _ = self._app()
        app.date_var = _DummyVar()
        app.stats_var = _DummyVar()
        app._schedule_all = Mock()
        app._refresh()
        app._schedule_all.assert_not_called()


class BackwardCompatTests(unittest.TestCase):
    def test_reminder_app_alias(self):
        self.assertIs(ReminderApp, PlannerApp)


class MainTests(unittest.TestCase):
    @patch("reminder.cli.PlannerApp")
    @patch("reminder.cli.tk.Tk")
    def test_main_creates_app_and_runs_mainloop(self, mock_tk_cls, mock_app_cls):
        mock_root = Mock()
        mock_tk_cls.return_value = mock_root
        from reminder.cli import main
        main()
        mock_tk_cls.assert_called_once()
        mock_app_cls.assert_called_once_with(mock_root)
        mock_root.mainloop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
