"""tests/test_planner.py — PlannerApp（タイムライン版）/ main のテスト

GUI 依存を避けるため _build_ui・_refresh・_schedule_all をパッチして
ロジック層（タスク追加・完了・削除・あとで⇄予定の移動・通知スケジュール）を検証する。
"""
import datetime
import unittest
from unittest.mock import Mock, patch

from reminder import theme
from reminder.app import PlannerApp, ReminderApp
from reminder.config import Prefs
from reminder.recurrence import RECUR_DAILY, RECUR_LABELS
from reminder.task import DEFAULT_DURATION, ISO_FMT, Task


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

    def test_stale_default_refreshes_to_current_time_when_untouched(self):
        # アプリを起動したまま時間が経過しても、開始時刻欄に触れていなければ
        # 「＋タイムラインへ」実行時に最新時刻基準の既定値へ更新され、
        # 古い既定値のまま翌日へ意図せず繰り上がるのを防ぐ（回帰防止）。
        app, _ = self._app()
        app.title_var.set("メール確認")
        # real wall-clock に依存しないよう、起動時刻を固定値にして入力欄と
        # 追跡値をその時刻の既定値に合わせておく（起動直後を模擬する）
        launch = datetime.datetime(2026, 6, 1, 9, 0)
        launch_default = PlannerApp._default_start(launch)
        app.hour_var.set(f"{launch_default.hour:02d}")
        app.minute_var.set(f"{launch_default.minute:02d}")
        app._auto_start_default = (launch_default.hour, launch_default.minute)
        # 起動から時間が経ち 15:00 になっても、ユーザーは入力欄に触れていない
        later = datetime.datetime(2026, 6, 1, 15, 0)
        app._get_now = lambda: later
        app.add_to_timeline()
        # 起動時刻(9:05)基準ではなく 15:00 基準の既定値が使われ、当日の未来時刻として登録される
        self.assertEqual(app.tasks[0].due_dt.date(), later.date())
        self.assertGreaterEqual(app.tasks[0].due_dt, later)

    def test_manual_start_time_is_not_overwritten_by_stale_refresh(self):
        # ユーザーが開始時刻を手で書き換えていれば、時間が経過しても
        # _input_start_time() はその値を上書きしない
        app, _ = self._app()
        launch = datetime.datetime(2026, 6, 1, 9, 0)
        launch_default = PlannerApp._default_start(launch)
        app._auto_start_default = (launch_default.hour, launch_default.minute)
        # ユーザーが開始時刻を手で書き換える（自動補完値とは異なる値にする）
        app.hour_var.set("22")
        app.minute_var.set("15")
        app._get_now = lambda: datetime.datetime(2026, 6, 1, 15, 0)
        t = app._input_start_time()
        self.assertEqual((t.hour, t.minute), (22, 15))

    def test_duration_normalized(self):
        app, _ = self._app()
        app.dur_var.set("100000")
        self.assertEqual(app._input_duration(), 24 * 60)

    def test_duration_non_numeric_defaults(self):
        # 非数値の所要時間は task.py の _coerce_duration と同じ DEFAULT_DURATION に
        # フォールバックする（UI 入力と tasks.json 復元でフォールバック値を統一）。
        app, _ = self._app()
        app.dur_var.set("ab")
        self.assertEqual(app._input_duration(), DEFAULT_DURATION)

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

    def test_range_change_unchanged_hour_preserves_minutes(self):
        # スピンボックスは「時」単位のため、時が変わらないフォーカス移動だけで
        # settings.json の分単位の値（"07:30" 等）が "07:00" に切り捨てられないことを確認する
        app, _ = self._app(prefs=Prefs(wake="07:30", sleep="22:15"))  # 分単位の設定値でアプリを生成する
        app.wake_var.set("7")  # 起床スピンボックスの表示値（時のみ）をそのままにする
        app.sleep_var.set("22")  # 就寝スピンボックスの表示値（時のみ）をそのままにする
        app._on_range_change()  # FocusOut と同じ経路で設定反映処理を呼ぶ
        self.assertEqual(app.prefs.wake, "07:30")  # 起床時刻の分（:30）が保持される
        self.assertEqual(app.prefs.sleep, "22:15")  # 就寝時刻の分（:15）が保持される

    def test_range_change_blank_input_falls_back_to_stored_hour(self):
        # スピンボックスを空にしたままタブ移動しても、0 時ではなく保存済みの「時」へ
        # フォールバックし、設定が "00:00" に破壊されないことを確認する
        app, _ = self._app(prefs=Prefs(wake="07:30", sleep="22:15"))  # 分単位の設定値でアプリを生成する
        app.wake_var.set("")  # 起床スピンボックスを空欄にする（全選択して削除した状態を再現）
        app.sleep_var.set("abc")  # 就寝スピンボックスに非数値を入力した状態を再現する
        app._on_range_change()  # FocusOut と同じ経路で設定反映処理を呼ぶ
        self.assertEqual(app.prefs.wake, "07:30")  # 起床時刻は保存済みの値のまま破壊されない
        self.assertEqual(app.prefs.sleep, "22:15")  # 就寝時刻も保存済みの値のまま破壊されない
        self.assertEqual(app.wake_var.get(), "07")  # 入力欄には保存済みの「時」が書き戻される
        self.assertEqual(app.sleep_var.get(), "22")  # 入力欄には保存済みの「時」が書き戻される

    def test_range_change_new_hour_persists(self):
        # 時が実際に変わったときは新しい「HH:00」で設定が更新されることを確認する
        app, _ = self._app(prefs=Prefs(wake="07:30", sleep="22:15"))  # 分単位の設定値でアプリを生成する
        app.wake_var.set("8")  # 起床スピンボックスを 8 時に変更する
        app.sleep_var.set("22")  # 就寝スピンボックスは変更しない
        app._on_range_change()  # FocusOut と同じ経路で設定反映処理を呼ぶ
        self.assertEqual(app.prefs.wake, "08:00")  # 変更した起床時刻は「08:00」で保存される
        self.assertEqual(app.prefs.sleep, "22:15")  # 変更していない就寝時刻の分は保持される


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

    def test_status_message_includes_date_when_same_time_rolls_to_next_day(self):
        # test_equal_time_rolls_to_next_day と同じ状況(今の時:分を選んだが秒未満の
        # 差で「過去」判定され翌日へ繰り上がる)を再現する。このとき確認メッセージが
        # HH:MM だけだと、実際は翌日に追加されたことが利用者に伝わらず、今日のカレンダー
        # に表示されないタスクを「追加した」と誤解させてしまう(回帰防止)
        app, _ = self._app()
        fixed = datetime.datetime(2026, 6, 1, 9, 0, 30)  # 9:00 から 30 秒経過した時刻
        app._get_now = lambda: fixed
        app.title_var.set("掃除")
        app.hour_var.set("09")
        app.minute_var.set("00")
        app.add_to_timeline()
        # 実際には翌日(6/2)の 9:00 に繰り上がっている
        self.assertEqual(app.tasks[0].due_dt, datetime.datetime(2026, 6, 2, 9, 0))
        # メッセージにも日付(06/02)が含まれ、今日ではないことが分かるようになっている
        self.assertIn("06/02 09:00", app.status_var.get())


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

    def test_move_to_backlog_rejects_completed(self):
        # 完了済みタスクの due を空にすると、タイムライン（is_scheduled 条件）からも
        # バックログ（未完了条件）からも外れて UI から消失するため、移動を拒否する
        due = _iso(datetime.datetime.now() + datetime.timedelta(hours=1))  # 1 時間後の開始時刻文字列を作る
        task = Task(title="x", due=due, completed=True,
                    completed_at=_iso(datetime.datetime.now()))  # 完了済みのスケジュール済みタスクを作る
        app, _ = self._app([task])  # タスク 1 件でアプリを生成する
        app._tl_selected = task.id  # カレンダー上でこのタスクを選択状態にする
        app.move_to_backlog()  # バックログへの移動を試みる
        self.assertEqual(task.due, due)  # due は変更されずに保持される
        self.assertIn(task, app.tasks)  # タスクはリストに残っている
        self.assertIn("完了済み", app.status_var.get())  # 移動できない旨のメッセージが表示される

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

    def test_status_message_includes_date_when_same_time_rolls_to_next_day(self):
        # add_to_timeline と同じ回帰防止(§ test_equal_time_rolls_to_next_day の状況):
        # 今の時:分を選ぶと秒未満の差で翌日へ繰り上がるため、確認メッセージにも
        # 日付を含めないと今日予定されたと誤解される
        task = Task(title="x", due="")
        app, _ = self._app([task])
        app.backlog_tree.selection.return_value = (task.id,)
        fixed = datetime.datetime(2026, 6, 1, 9, 0, 30)  # 9:00 から 30 秒経過した時刻
        app._get_now = lambda: fixed
        app.hour_var.set("09")
        app.minute_var.set("00")
        app.schedule_backlog_selected()
        # 実際には翌日(6/2)の 9:00 に繰り上がっている
        self.assertEqual(task.due_dt, datetime.datetime(2026, 6, 2, 9, 0))
        # メッセージにも日付(06/02)が含まれる
        self.assertIn("06/02 09:00", app.status_var.get())


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
    def test_early_fire_rearms_even_if_due_passes(self, mock_sound, mock_info):
        # Tcl タイマーはミリ秒切り捨てで約 1ms 早く発火し得る。再登録時に時刻を
        # 取り直すと、早発火判定との間に開始時刻を過ぎた場合に過去ガードで弾かれて
        # 通知が永久に失われるため、判定に使った now を _schedule_task へ渡して
        # 境界（1ms 前 → due 到達）でもジョブが必ず再登録されることを確認する
        due = datetime.datetime.now().replace(microsecond=0) + datetime.timedelta(hours=1)  # 1 時間後の開始時刻を作る
        task = Task(title="x", due=_iso(due))  # その時刻に予定されたタスクを作る
        app, root = self._app([task])  # タスク 1 件でアプリを生成する
        # 1 回目の時刻取得は due の 1ms 前（早発火）、もし時刻を取り直す実装なら due ちょうどが返り
        # 過去ガードで再登録されなくなる（このテストが失敗する）
        with patch.object(app, "_get_now",
                          side_effect=[due - datetime.timedelta(milliseconds=1), due]):
            app._on_task_due(task.id)  # 早発火したコールバックを実行する
        mock_info.assert_not_called()  # まだ開始時刻前なので通知は出ない
        root.after.assert_called_once()  # ジョブが再登録される（時刻を取り直さないので過去ガードで落とされない）
        self.assertEqual(root.after.call_args[0][0], 1)  # 残り 1ms の遅延で再登録されている
        self.assertIn(task.id, app.jobs)  # ジョブ ID が辞書に記録されている

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

    def test_many_overlapping_tasks_stay_visible(self):
        # 多数のタスクが同時刻に重なり、かつ Canvas 幅が狭いとき（最悪条件）でも
        # 各ブロックは「正の幅」を持つ（反転・消失しない）ことを保証する。
        # タイムライン Canvas は横スクロールを持たず、重なりレーンは可視幅を分割して
        # 並べるため、レーンが多いと 1 レーン幅が狭まり、左右の固定隙間で
        # ブロック幅が負になってタスクが見えず・押せなくなる回帰を防ぐ。
        today = datetime.date.today()
        base = datetime.datetime.combine(today, datetime.time(10, 0))  # 同一開始時刻に重ねる基準時刻
        tasks = [Task(title=f"会議{i}", due=_iso(base), duration_min=60) for i in range(12)]  # 12 件すべて重なるタスク
        app, _ = self._app(tasks)
        app._tl_width = theme.CAL_GUTTER + 80  # 描画幅を最小幅に固定して最悪条件を再現する
        app._render_timeline(today)
        self.assertEqual(len(app._tl_blocks), len(tasks))  # 全タスクが描画される（欠落しない）
        for x0, _y0, x1, _y1, _cb, _tid, _done in app._tl_blocks:  # 各ブロックの矩形を検査する
            self.assertGreater(x1, x0)  # ブロック幅は常に正（反転・ゼロ幅で消えない）

    def test_checkbox_stays_within_own_block_when_lanes_are_narrow(self):
        # 回帰テスト: チェックボックスの中心 x はストライプ右隣の固定オフセットで
        # 計算されるため、同時刻に多数のタスクが重なりレーン幅が狭くなると、
        # 固定オフセットが自分のブロック右端(x1)を超えて隣のレーンまで
        # はみ出していた。すると描画上ずれるだけでなく、クリック判定用の
        # cb_box も隣のタスクの領域へ流出し、チェックボックスをクリックしたつもり
        # が別タスクを完了させてしまう恐れがあった。
        # チェックボックス（半径 CAL_CHECK_R + 判定余白 3px）がブロック自身の
        # 右端に収まる程度の重なり数(14件)・幅(460px 既定)で検証する。
        # ブロック幅がチェックボックスの判定直径未満まで狭まる、さらに極端な
        # 条件（15 件以上）は test_checkbox_hit_area_never_leaks_even_when_block_narrower_than_checkbox
        # で別途検証する。
        today = datetime.date.today()
        base = datetime.datetime.combine(today, datetime.time(10, 0))  # 同一開始時刻に重ねる基準時刻
        tasks = [Task(title=f"会議{i}", due=_iso(base), duration_min=60) for i in range(14)]  # 14 件すべて重なるタスク
        app, _ = self._app(tasks)
        app._tl_width = 460  # 既定の Canvas 幅で検証する（極端な最小幅ではない現実的な条件）
        app._render_timeline(today)
        self.assertEqual(len(app._tl_blocks), len(tasks))  # 全タスクが描画される（欠落しない）
        block_x1 = {}  # task.id → ブロック右端(x1) の対応表（後段のテキスト位置検証で使う）
        for x0, _y0, x1, _y1, cb_box, tid, _done in app._tl_blocks:  # 各ブロックとそのチェックボックス領域を検査する
            cb_left, _cb_top, cb_right, _cb_bottom = cb_box  # チェックボックスの判定領域の左右端を取り出す
            self.assertGreaterEqual(cb_left, x0 - 1e-6)  # チェックボックスがブロック左端より内側にあること
            self.assertLessEqual(cb_right, x1 + 1e-6)  # チェックボックスがブロック右端を超えて隣のレーンへはみ出さないこと
            block_x1[tid] = x1  # 後段でタイトル文字の描画開始位置と突き合わせるため記録する
        # チェックボックス位置をクランプしても、そこからさらに右へオフセットした
        # タイトル／時刻テキストの描画開始 x が自ブロックの右端(x1)を超えて隣の
        # レーン(隣のタスクのカード)へはみ出して表示されないことも確認する
        # （cb_cx だけクランプして text_x をクランプし忘れる回帰の防止）。
        for call in app.timeline_tree.create_text.call_args_list:  # Canvas に発行された全 create_text 呼び出しをループする
            tags = call.kwargs.get("tags")  # このテキストがどのタスクに属するかのタグを取り出す
            if not tags or tags[0] != "task" or tags[1] not in block_x1:  # タスク用テキスト（時刻グリッドのラベル等を除く）でなければ
                continue  # 対象外なのでスキップする
            text_x_used = call.args[0]  # create_text に渡された描画開始 x 座標を取り出す
            self.assertLessEqual(text_x_used, block_x1[tags[1]] + 1e-6)  # 自ブロックの右端を超えて隣のレーンへはみ出さないこと

    def test_checkbox_hit_area_never_leaks_even_when_block_narrower_than_checkbox(self):
        # 回帰テスト: cb_cx（チェックボックス中心）を自ブロックの x 範囲へ
        # クランプするだけでは、ブロック幅 (x1-x0) がチェックボックスの判定
        # 直径 2*(CAL_CHECK_R+3) 未満まで狭まった場合に不十分だった。
        # 中心を左端(x0+r+3)へ寄せても、そこから右へ r+3 だけ離れた cb_box の
        # 右端は x1 を超えたまま残り、隣のレーンへ判定領域が流出してしまう
        # （既定幅 460px では 15 件重なりから発生。修正前に実測して確認済み）。
        # チェックボックスの判定領域そのものを x0/x1 で個別にクランプすることで、
        # レーンがどれだけ狭くなっても隣タスクの完了操作を誤爆しないことを検証する。
        today = datetime.date.today()
        base = datetime.datetime.combine(today, datetime.time(10, 0))  # 同一開始時刻に重ねる基準時刻
        tasks = [Task(title=f"会議{i}", due=_iso(base), duration_min=60) for i in range(20)]  # 20 件すべて重なるタスク（ブロック幅がチェックボックス判定直径を下回る条件）
        app, _ = self._app(tasks)
        app._tl_width = 460  # 既定の Canvas 幅で検証する
        app._render_timeline(today)
        self.assertEqual(len(app._tl_blocks), len(tasks))  # 全タスクが描画される（欠落しない）
        for x0, _y0, x1, _y1, cb_box, _tid, _done in app._tl_blocks:  # 各ブロックとそのチェックボックス領域を検査する
            cb_left, _cb_top, cb_right, _cb_bottom = cb_box  # チェックボックスの判定領域の左右端を取り出す
            self.assertGreaterEqual(cb_left, x0 - 1e-6)  # 判定領域がブロック左端より内側にあること
            self.assertLessEqual(cb_right, x1 + 1e-6)  # 判定領域がブロック右端を超えて隣のレーンへはみ出さないこと（誤爆防止）

    def test_short_consecutive_tasks_do_not_visually_overlap(self):
        # 所要時間が短いタスク（描画時に theme.CAL_MIN_BLOCK_HEIGHT へクランプされる）が
        # 隙間なく連続すると、実終了時刻を超えて描かれたクランプ分が次のタスクの
        # 開始位置に食い込み、カードが重なって隠れてしまう回帰を防ぐ。
        # レーン割り当て（_assign_lanes）が見た目の高さを考慮していれば、
        # 同じ x 範囲・重なる y 範囲のカードにはならない。
        today = datetime.date.today()
        start1 = datetime.datetime.combine(today, datetime.time(9, 0))
        start2 = datetime.datetime.combine(today, datetime.time(9, 5))  # 前のタスクの実終了直後に開始（隙間ゼロ）
        t1 = Task(title="短いA", due=_iso(start1), duration_min=5)  # 実際の高さはクランプされるほど短い所要時間
        t2 = Task(title="短いB", due=_iso(start2), duration_min=5)
        app, _ = self._app([t1, t2])
        app._render_timeline(today)
        blocks = {b[5]: b for b in app._tl_blocks}  # task.id をキーにブロック矩形を引けるようにする
        x0_a, y0_a, x1_a, y1_a, _cb_a, _id_a, _done_a = blocks[t1.id]
        x0_b, y0_b, x1_b, y1_b, _cb_b, _id_b, _done_b = blocks[t2.id]
        x_overlap = x0_a < x1_b and x0_b < x1_a  # 2 つのカードの x 範囲が重なっているか判定する
        y_overlap = y0_a < y1_b and y0_b < y1_a  # 2 つのカードの y 範囲が重なっているか判定する
        self.assertFalse(x_overlap and y_overlap)  # x も y も重なる（＝カード同士が重なって見える）状態にはならない

    def test_long_early_task_extends_grid_past_shorter_later_task(self):
        # 表示ウィンドウ終端は「rows の全行中の最大終了時刻」から決める必要がある。
        # 先に始まって遅くまで続く長いタスク（B）の後に、後から始まって早く終わる
        # 短いタスク（A）が来ると、B の行が rows の末尾ではなくなる。
        # window_end を rows[-1].end のような「末尾行だけ」から取ると、この場合に
        # B の実際の終了時刻より手前で罫線が止まってしまう回帰を防ぐ。
        # 既定の就寝時刻(23:00)を超えて続く B を使い、trailing free row が
        # 追加されない（cursor が end_bound に一致してしまう）条件を再現する。
        # これにより rows の末尾行が B ではなく A になり、rows[-1].end だけを見ると
        # 誤って A の終了時刻(09:30)を window_end としてしまう。
        today = datetime.date.today()
        start_b = datetime.datetime.combine(today, datetime.time(8, 0))
        start_a = datetime.datetime.combine(today, datetime.time(9, 0))
        task_b = Task(title="長時間タスク", due=_iso(start_b), duration_min=15 * 60 + 30)  # 08:00 - 23:30
        task_a = Task(title="短時間タスク", due=_iso(start_a), duration_min=30)  # 09:00 - 09:30（B に内包される）
        app, _ = self._app([task_b, task_a])
        app._render_timeline(today)
        texts = [c.kwargs.get("text") for c in app.timeline_tree.create_text.call_args_list]
        # B の終了(23:30)を跨ぐ正時(23:00)の罫線ラベルが描かれているはず。
        # window_end が誤って task_a の終了(09:30)相当に縮んでいると、これより
        # 後の正時ラベルは一切描かれない。
        self.assertIn("23:00", texts)

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
