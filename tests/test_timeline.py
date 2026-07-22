"""tests/test_timeline.py — timeline モジュールの単体テスト"""
import datetime
import unittest

from reminder.task import Task
from reminder.timeline import (
    ROW_FREE,
    ROW_TASK,
    STATUS_DONE,
    STATUS_NOW,
    STATUS_PAST,
    STATUS_UPCOMING,
    backlog_tasks,
    build_day_timeline,
    carry_over_overdue,
    day_bounds,
    format_duration,
    free_minutes_today,
    hhmm_to_min,
    max_free_slot,
    min_to_hhmm,
    planner_day,
    prune_old_completed,
    suggest_for_free_time,
)


def _t(title, due, dur=30, **kw):
    return Task(title=title, due=due, duration_min=dur, **kw)


class TimeHelperTests(unittest.TestCase):
    def test_hhmm_to_min(self):
        self.assertEqual(hhmm_to_min("07:00"), 420)
        self.assertEqual(hhmm_to_min("23:30"), 23 * 60 + 30)

    def test_hhmm_to_min_invalid(self):
        for bad in ("7", "24:00", "07:60", "ab:cd", "07:00:00"):
            with self.assertRaises(ValueError):
                hhmm_to_min(bad)

    def test_min_to_hhmm(self):
        self.assertEqual(min_to_hhmm(420), "07:00")
        self.assertEqual(min_to_hhmm(0), "00:00")
        self.assertEqual(min_to_hhmm(24 * 60), "00:00")  # 剰余で丸める

    def test_format_duration(self):
        self.assertEqual(format_duration(30), "30分")
        self.assertEqual(format_duration(60), "1時間")
        self.assertEqual(format_duration(90), "1時間30分")
        self.assertEqual(format_duration(0), "0分")


class DayBoundsTests(unittest.TestCase):
    def test_normal_day(self):
        s, e = day_bounds(datetime.date(2026, 6, 6), 7 * 60, 23 * 60)
        self.assertEqual(s, datetime.datetime(2026, 6, 6, 7, 0))
        self.assertEqual(e, datetime.datetime(2026, 6, 6, 23, 0))

    def test_overnight_sleep_rolls_to_next_day(self):
        s, e = day_bounds(datetime.date(2026, 6, 6), 9 * 60, 1 * 60)
        self.assertEqual(s, datetime.datetime(2026, 6, 6, 9, 0))
        self.assertEqual(e, datetime.datetime(2026, 6, 7, 1, 0))


class BuildTimelineTests(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date(2026, 6, 6)
        self.now = datetime.datetime(2026, 6, 6, 10, 0)

    def test_no_tasks_one_free_row_for_whole_day(self):
        rows = build_day_timeline([], self.today, 7 * 60, 23 * 60, self.now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, ROW_FREE)
        self.assertEqual(rows[0].minutes, 16 * 60)

    def test_free_gaps_between_tasks(self):
        tasks = [
            _t("朝会", "2026-06-06T09:00:00", 30),
            _t("作業", "2026-06-06T13:00:00", 90),
        ]
        rows = build_day_timeline(tasks, self.today, 7 * 60, 23 * 60, self.now)
        kinds = [r.kind for r in rows]
        self.assertEqual(kinds, [ROW_FREE, ROW_TASK, ROW_FREE, ROW_TASK, ROW_FREE])
        # 07:00-09:00 = 120分, 09:30-13:00 = 210分, 14:30-23:00 = 510分
        self.assertEqual([r.minutes for r in rows if r.kind == ROW_FREE], [120, 210, 510])

    def test_task_status(self):
        tasks = [
            _t("済", "2026-06-06T08:00:00", 30, completed=True, completed_at="2026-06-06T08:20:00"),
            _t("進行中", "2026-06-06T09:45:00", 30),  # now=10:00 は 09:45-10:15 の間
            _t("過去未了", "2026-06-06T09:00:00", 30),
            _t("これから", "2026-06-06T15:00:00", 30),
        ]
        rows = [r for r in build_day_timeline(tasks, self.today, 7 * 60, 23 * 60, self.now)
                if r.kind == ROW_TASK]
        status = {r.task.title: r.status for r in rows}
        self.assertEqual(status["済"], STATUS_DONE)
        self.assertEqual(status["進行中"], STATUS_NOW)
        self.assertEqual(status["過去未了"], STATUS_PAST)
        self.assertEqual(status["これから"], STATUS_UPCOMING)

    def test_overlapping_tasks_have_no_free_row_between(self):
        tasks = [
            _t("A", "2026-06-06T09:00:00", 60),
            _t("B", "2026-06-06T09:30:00", 60),  # A と重なる
        ]
        rows = build_day_timeline(tasks, self.today, 7 * 60, 23 * 60, self.now)
        # A と B の間に FREE 行がない
        self.assertEqual([r.kind for r in rows], [ROW_FREE, ROW_TASK, ROW_TASK, ROW_FREE])

    def test_other_day_tasks_excluded(self):
        tasks = [_t("明日", "2026-06-07T09:00:00", 30)]
        rows = build_day_timeline(tasks, self.today, 7 * 60, 23 * 60, self.now)
        self.assertTrue(all(r.kind == ROW_FREE for r in rows))

    def test_free_minutes_today(self):
        tasks = [_t("朝会", "2026-06-06T09:00:00", 60)]
        # 16時間(960分) - 60分 = 900分
        self.assertEqual(free_minutes_today(tasks, self.today, 7 * 60, 23 * 60, self.now), 900)

    def test_free_minutes_exact_with_second_level_task_times(self):
        # 秒付きの due（繰り返しタスクが完了時刻から生成する）でも合計空きが正確であること。
        # 09:00:30-09:30:30 と 10:00:30-10:30:30 の 2 タスクで占有はちょうど 60 分。
        # 窓 07:00-23:00 = 960 分なので空きは 900 分ちょうど。
        # 行ごとに分へ切り捨てると端数が二重に失われて 899 分になってしまうため、
        # 秒で合計してから最後に丸める実装であることをここで担保する。
        tasks = [
            _t("A", "2026-06-06T09:00:30", 30),
            _t("B", "2026-06-06T10:00:30", 30),
        ]
        self.assertEqual(free_minutes_today(tasks, self.today, 7 * 60, 23 * 60, self.now), 900)

    def test_free_minutes_counts_sub_minute_gaps(self):
        # 1 分未満の隙間（秒付き due が作る 60 秒未満の空き）も合計に含まれること。
        # タスク 00:00:20〜00:30:20（30 分）を窓 00:00〜01:00 に置くと、
        # 空きは 20 秒 + 29 分 40 秒 = ちょうど 30 分。隙間の行を省略する実装だと
        # 先頭 20 秒が失われて 29 分に過少計上されるため、ここで担保する。
        tasks = [_t("秒付き", "2026-06-06T00:00:20", 30)]
        self.assertEqual(free_minutes_today(tasks, self.today, 0, 60, self.now), 30)

    def test_sub_minute_gap_emits_zero_minute_free_row(self):
        # 60 秒未満の隙間でも ROW_FREE 行が出力されること（minutes は切り捨てで 0）。
        tasks = [_t("秒付き", "2026-06-06T07:00:30", 30)]
        rows = build_day_timeline(tasks, self.today, 7 * 60, 23 * 60, self.now)
        self.assertEqual(rows[0].kind, ROW_FREE)
        self.assertEqual(rows[0].minutes, 0)
        self.assertEqual((rows[0].end - rows[0].start).total_seconds(), 30)

    def test_sub_minute_tail_gap_emits_zero_minute_free_row(self):
        # 末尾（最終タスク後〜就寝）の 60 秒未満の隙間でも ROW_FREE 行が出力されること。
        # 22:59:30 開始の 30 秒…は duration が分単位なので、22:29:30 開始 30 分
        # （22:59:30 終了）で就寝 23:00 まで残り 30 秒の末尾隙間を作る。
        tasks = [_t("秒付き末尾", "2026-06-06T22:29:30", 30)]
        rows = build_day_timeline(tasks, self.today, 7 * 60, 23 * 60, self.now)
        self.assertEqual(rows[-1].kind, ROW_FREE)
        self.assertEqual(rows[-1].minutes, 0)
        self.assertEqual((rows[-1].end - rows[-1].start).total_seconds(), 30)

    def test_free_minutes_excludes_off_hours(self):
        # 就寝 23:00 の後（23:15）にタスクがあっても、窓外（23:00〜23:15）は
        # 空きに数えない。空きは 07:00〜23:00 = 960 分のみ。
        tasks = [_t("夜の作業", "2026-06-06T23:15:00", 30)]
        self.assertEqual(free_minutes_today(tasks, self.today, 7 * 60, 23 * 60, self.now), 960)

    def test_overnight_window_includes_next_day_task(self):
        # 起床 09:00 / 就寝 01:00（翌日）。翌 00:30 のタスクも窓内として含める
        tasks = [_t("夜更かし作業", "2026-06-07T00:30:00", 30)]
        rows = build_day_timeline(tasks, self.today, 9 * 60, 1 * 60, self.now)
        titles = [r.task.title for r in rows if r.kind == ROW_TASK]
        self.assertIn("夜更かし作業", titles)

    def test_multi_day_spanning_task_shows_on_next_day(self):
        # 前日 22:00 開始・600分（翌 08:00 終了）の日をまたぐタスクは、
        # 翌日のタイムラインにも表示されなければならない（回帰テスト）。
        # これを含めないと、まだ進行中の時間帯が翌日の空きとして扱われてしまう。
        next_day = datetime.date(2026, 6, 7)
        now = datetime.datetime(2026, 6, 7, 7, 30)
        tasks = [_t("夜通し作業", "2026-06-06T22:00:00", 600)]  # 22:00-翌08:00
        rows = build_day_timeline(tasks, next_day, 7 * 60, 23 * 60, now)
        titles = [r.task.title for r in rows if r.kind == ROW_TASK]
        self.assertIn("夜通し作業", titles)

    def test_multi_day_spanning_task_not_double_counted_as_free(self):
        # 前日 22:00 開始・600分（翌 08:00 終了）の日をまたぐタスクがある場合、
        # 翌日 07:00-08:00 は空きとして数えてはいけない（過大計上の回帰テスト）。
        next_day = datetime.date(2026, 6, 7)
        now = datetime.datetime(2026, 6, 7, 7, 0)
        tasks = [_t("夜通し作業", "2026-06-06T22:00:00", 600)]  # 22:00-翌08:00
        # 窓 07:00-23:00 = 960分のうち 07:00-08:00 の60分はタスクで占有されている
        self.assertEqual(free_minutes_today(tasks, next_day, 7 * 60, 23 * 60, now), 900)
        self.assertEqual(max_free_slot(tasks, next_day, 7 * 60, 23 * 60, now), 900)

    def test_cross_midnight_running_task_visible_before_wake(self):
        # 前日 23:00 開始・90分（当日 00:30 終了）のタスクは終了が当日の起床時刻
        # （07:00）より前なので end_dt > day_start に掛からないが、深夜 00:10 に
        # まだ実行中なら当日のデイビューに表示される（回帰テスト）。
        # carry_over_overdue も end_dt > now の実行中保護で繰り越さないため、
        # ここで表示しないと 0:00〜終了の間タスクがどこにも現れず消えてしまう。
        today = datetime.date(2026, 6, 7)  # 表示対象の当日（now が属するプランナー日）
        now = datetime.datetime(2026, 6, 7, 0, 10)  # 深夜 00:10（タスク実行中の時刻）
        tasks = [_t("夜ふかし作業", "2026-06-06T23:00:00", 90)]  # 前日 23:00 開始〜当日 00:30 終了のタスク
        rows = build_day_timeline(tasks, today, 7 * 60, 23 * 60, now)  # 当日のタイムラインを構築する
        task_rows = [r for r in rows if r.kind == ROW_TASK]  # タスク行だけを抜き出す
        self.assertEqual([r.task.title for r in task_rows], ["夜ふかし作業"])  # 実行中のタスクが表示されること
        self.assertEqual(task_rows[0].status, STATUS_NOW)  # 「現在進行中」ステータスで表示されること

    def test_cross_midnight_task_hidden_after_it_finishes(self):
        # 同じタスクでも終了後（now=00:40）は当日ビューに表示されない。終了が起床
        # 時刻より前なので当日の窓には掛からず、以後は carry_over_overdue が
        # 今日への繰り越しを担う（表示と繰り越しの分担の境界を固定する回帰テスト）。
        today = datetime.date(2026, 6, 7)  # 表示対象の当日
        now = datetime.datetime(2026, 6, 7, 0, 40)  # タスク終了（00:30）後の深夜 00:40
        tasks = [_t("夜ふかし作業", "2026-06-06T23:00:00", 90)]  # 前日 23:00 開始〜当日 00:30 終了のタスク
        rows = build_day_timeline(tasks, today, 7 * 60, 23 * 60, now)  # 当日のタイムラインを構築する
        self.assertEqual([r.task.title for r in rows if r.kind == ROW_TASK], [])  # 終了済みタスクは表示されないこと

    def test_running_task_not_leaked_into_other_days_view(self):
        # now 基準の包含は「now が属するプランナー日」の表示に限る。当日 09:00-10:00 の
        # 実行中タスク（now=09:30）が、翌日のビューへ混入しないこと。
        tomorrow = datetime.date(2026, 6, 8)  # 表示対象は翌日（now のプランナー日ではない）
        now = datetime.datetime(2026, 6, 7, 9, 30)  # 当日 09:30（タスク実行中の時刻）
        tasks = [_t("実行中", "2026-06-07T09:00:00", 60)]  # 当日 09:00 開始・60 分のタスク
        rows = build_day_timeline(tasks, tomorrow, 7 * 60, 23 * 60, now)  # 翌日のタイムラインを構築する
        self.assertEqual([r.task.title for r in rows if r.kind == ROW_TASK], [])  # 翌日ビューには混入しないこと


class PlannerDayTests(unittest.TestCase):
    def test_normal_range_uses_calendar_date(self):
        # 通常レンジ（7:00-23:00）は常に暦日
        self.assertEqual(planner_day(datetime.datetime(2026, 6, 6, 2, 0), 7 * 60, 23 * 60),
                         datetime.date(2026, 6, 6))
        self.assertEqual(planner_day(datetime.datetime(2026, 6, 6, 23, 30), 7 * 60, 23 * 60),
                         datetime.date(2026, 6, 6))

    def test_overnight_before_sleep_is_previous_day(self):
        # 夜間レンジ 9:00-1:00 で 00:15 はまだ前日のプランナー日
        self.assertEqual(planner_day(datetime.datetime(2026, 6, 7, 0, 15), 9 * 60, 1 * 60),
                         datetime.date(2026, 6, 6))

    def test_overnight_after_sleep_is_same_day(self):
        # 就寝 01:00 を過ぎた 09:30 は当日
        self.assertEqual(planner_day(datetime.datetime(2026, 6, 7, 9, 30), 9 * 60, 1 * 60),
                         datetime.date(2026, 6, 7))


class WindowExtensionTests(unittest.TestCase):
    def test_task_after_sleep_boundary_still_visible(self):
        # 就寝 23:00 の後（23:15）に置いたタスクも消えずに表示される
        today = datetime.date(2026, 6, 6)
        now = datetime.datetime(2026, 6, 6, 7, 0)
        tasks = [_t("夜の作業", "2026-06-06T23:15:00", 30)]
        rows = build_day_timeline(tasks, today, 7 * 60, 23 * 60, now)
        titles = [r.task.title for r in rows if r.kind == ROW_TASK]
        self.assertIn("夜の作業", titles)

    def test_task_before_wake_still_visible(self):
        # 起床 07:00 の前（06:00）に置いたタスクも表示される
        today = datetime.date(2026, 6, 6)
        now = datetime.datetime(2026, 6, 6, 8, 0)
        tasks = [_t("早朝ラン", "2026-06-06T06:00:00", 30)]
        rows = build_day_timeline(tasks, today, 7 * 60, 23 * 60, now)
        titles = [r.task.title for r in rows if r.kind == ROW_TASK]
        self.assertIn("早朝ラン", titles)


class MaxFreeSlotTests(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date(2026, 6, 6)
        self.now = datetime.datetime(2026, 6, 6, 7, 0)

    def test_max_contiguous_slot(self):
        # 09:00-09:30 と 10:00-10:30 のタスクで 09:30-10:00 に 30 分の枠ができる。
        # ただし最大連続枠は就寝までの末尾（10:30-23:00）。
        tasks = [_t("a", "2026-06-06T09:00:00", 30), _t("b", "2026-06-06T10:00:00", 30)]
        # 末尾 10:30-23:00 = 750分 が最大
        self.assertEqual(max_free_slot(tasks, self.today, 7 * 60, 23 * 60, self.now), 750)

    def test_elapsed_time_excluded_from_slot(self):
        # 20:00 時点・タスクなし・07:00-23:00 の日では、空き行は 16h だが
        # これから使えるのは 20:00-23:00 の 3h（180分）だけ。
        today = datetime.date(2026, 6, 6)
        now = datetime.datetime(2026, 6, 6, 20, 0)
        self.assertEqual(max_free_slot([], today, 7 * 60, 23 * 60, now), 180)

    def test_off_hours_excluded_from_slot(self):
        # 就寝 23:00 後の 23:15 タスクがあっても、最大空きは窓内 07:00-23:00 = 960。
        today = datetime.date(2026, 6, 6)
        now = datetime.datetime(2026, 6, 6, 7, 0)
        tasks = [_t("夜の作業", "2026-06-06T23:15:00", 30)]
        self.assertEqual(max_free_slot(tasks, today, 7 * 60, 23 * 60, now), 960)

    def test_no_60min_slot_between_two_30min_gaps(self):
        # 1日を 30 分枠だけにする: 07:00 から 30 分タスクと 30 分空きを交互に。
        tasks = [
            _t("t1", "2026-06-06T07:30:00", 30),  # 07:00-07:30 空き(30)
            _t("t2", "2026-06-06T08:30:00", 870),  # 08:00-08:30 空き(30), 以降就寝まで埋める
        ]
        # 最大連続空きは 30 分なので、60 分タスクは収まらない
        self.assertEqual(max_free_slot(tasks, self.today, 7 * 60, 23 * 60, self.now), 30)
        fitting = suggest_for_free_time(
            [Task(title="長", due="", duration_min=60)], 30)
        self.assertEqual(fitting, [])


class BacklogTests(unittest.TestCase):
    def test_backlog_excludes_scheduled_and_completed(self):
        tasks = [
            Task(title="あとで1", due=""),
            Task(title="あとで完了", due="", completed=True, completed_at="2026-06-06T08:00:00"),
            _t("予定済", "2026-06-06T09:00:00"),
        ]
        self.assertEqual([t.title for t in backlog_tasks(tasks)], ["あとで1"])

    def test_suggest_fits_and_sorted_desc(self):
        tasks = [
            Task(title="短", due="", duration_min=15),
            Task(title="中", due="", duration_min=45),
            Task(title="長", due="", duration_min=120),
        ]
        # 60分の空きには 短(15) と 中(45) が収まり、大きい順に並ぶ
        result = suggest_for_free_time(tasks, 60)
        self.assertEqual([t.title for t in result], ["中", "短"])


class CarryOverTests(unittest.TestCase):
    def test_overdue_incomplete_moved_to_today_keeping_time(self):
        today = datetime.date(2026, 6, 6)
        tasks = [_t("昨日の宿題", "2026-06-05T09:00:00", 30)]
        moved = carry_over_overdue(tasks, today)
        self.assertEqual(moved, 1)
        self.assertEqual(tasks[0].due_dt, datetime.datetime(2026, 6, 6, 9, 0))

    def test_skips_completed_and_backlog_and_today(self):
        today = datetime.date(2026, 6, 6)
        tasks = [
            _t("昨日完了", "2026-06-05T09:00:00", 30, completed=True, completed_at="2026-06-05T10:00:00"),
            Task(title="あとで", due=""),
            _t("今日", "2026-06-06T09:00:00", 30),
        ]
        self.assertEqual(carry_over_overdue(tasks, today), 0)

    def test_overnight_carry_uses_planner_day(self):
        # 夜間レンジ 9:00-1:00。暦上 6/6 00:30 のタスクは 6/5 のプランナー日に属する。
        # 6/6 のプランナー日へ繰り越すと、6/6 プランナー日の 00:30 = 暦上 6/7 00:30。
        today = datetime.date(2026, 6, 6)
        tasks = [_t("夜更かし", "2026-06-06T00:30:00", 30)]
        moved = carry_over_overdue(tasks, today, 9 * 60, 1 * 60)
        self.assertEqual(moved, 1)
        self.assertEqual(tasks[0].due_dt, datetime.datetime(2026, 6, 7, 0, 30))

    def test_overnight_today_task_not_carried(self):
        # 6/6 プランナー日（暦 6/7 00:30）のタスクは today=6/6 では繰り越さない
        today = datetime.date(2026, 6, 6)
        tasks = [_t("当日深夜", "2026-06-07T00:30:00", 30)]
        self.assertEqual(carry_over_overdue(tasks, today, 9 * 60, 1 * 60), 0)

    def test_in_progress_cross_day_task_not_carried(self):
        # 前日 22:00 開始・所要 600 分（終了 6/7 08:00）の夜通しタスクは、6/7 の
        # 起床時刻（07:00）を跨いでまだ進行中なので繰り越さない。
        # build_day_timeline は end_dt > day_start のタスクを当日に表示する（「夜通し作業」の
        # 回帰テスト参照）ため、ここで繰り越すと表示前に due が +24h 書き換わり永続データが壊れる。
        today = datetime.date(2026, 6, 7)
        tasks = [_t("夜通し作業", "2026-06-06T22:00:00", 600)]
        self.assertEqual(carry_over_overdue(tasks, today), 0)
        self.assertEqual(tasks[0].due_dt, datetime.datetime(2026, 6, 6, 22, 0))  # due は元のまま

    def test_finished_cross_day_task_still_carried(self):
        # 同じ前日 22:00 開始でも所要 60 分（終了 23:00、当日の起床時刻より前）なら
        # もう占有していないので従来どおり繰り越す。
        today = datetime.date(2026, 6, 7)
        tasks = [_t("昨晩の残り", "2026-06-06T22:00:00", 60)]
        self.assertEqual(carry_over_overdue(tasks, today), 1)
        self.assertEqual(tasks[0].due_dt, datetime.datetime(2026, 6, 7, 22, 0))

    def test_in_progress_task_ending_before_wake_not_carried_with_now(self):
        # 深夜跨ぎだが起床時刻より前に終わるタスク（22:30 開始・120 分 → 翌 00:30 終了）は
        # end_dt > day_start の保護に掛からない。now=00:15（まだ実行中）を渡した場合は
        # 繰り越さず、due が +24h 書き換わらないことを確認する。
        today = datetime.date(2026, 7, 22)
        tasks = [_t("夜ふかし作業", "2026-07-21T22:30:00", 120)]  # 終了 7/22 00:30
        now = datetime.datetime(2026, 7, 22, 0, 15)  # タスク実行中の深夜 00:15
        self.assertEqual(carry_over_overdue(tasks, today, now=now), 0)
        self.assertEqual(tasks[0].due_dt, datetime.datetime(2026, 7, 21, 22, 30))  # due は元のまま

    def test_same_task_carried_after_it_finishes(self):
        # 同じタスクでも終了後（now=00:45）は通常どおり今日へ繰り越される。
        today = datetime.date(2026, 7, 22)
        tasks = [_t("夜ふかし作業", "2026-07-21T22:30:00", 120)]  # 終了 7/22 00:30
        now = datetime.datetime(2026, 7, 22, 0, 45)  # タスク終了後の深夜 00:45
        self.assertEqual(carry_over_overdue(tasks, today, now=now), 1)
        self.assertEqual(tasks[0].due_dt, datetime.datetime(2026, 7, 22, 22, 30))  # 今日の同時刻へ移動

    def test_now_none_keeps_legacy_behaviour(self):
        # now を渡さない場合は従来どおり（実行中保護なし）繰り越す。純粋関数としての
        # 後方互換を保証する回帰テスト。
        today = datetime.date(2026, 7, 22)
        tasks = [_t("夜ふかし作業", "2026-07-21T22:30:00", 120)]  # 終了 7/22 00:30
        self.assertEqual(carry_over_overdue(tasks, today), 1)

    def test_task_ending_exactly_at_now_is_carried(self):
        # 境界値: end_dt == now はちょうど終了した瞬間なので繰り越す（厳密比較 end_dt > now）。
        today = datetime.date(2026, 7, 22)
        tasks = [_t("夜ふかし作業", "2026-07-21T22:30:00", 120)]  # 終了 7/22 00:30
        now = datetime.datetime(2026, 7, 22, 0, 30)  # ちょうど終了時刻
        self.assertEqual(carry_over_overdue(tasks, today, now=now), 1)

    def test_task_ending_exactly_at_wake_is_carried(self):
        # 境界値: 終了がちょうど当日の起床時刻（既定 07:00）の場合。
        # 判定は end_dt > day_start の厳密比較なので繰り越す（build_day_timeline も
        # 同じ厳密比較で当日に表示しないため、両者の整合が保たれる）。
        today = datetime.date(2026, 6, 7)
        tasks = [_t("起床時刻ぴったり", "2026-06-06T22:00:00", 540)]  # 終了 6/7 07:00
        self.assertEqual(carry_over_overdue(tasks, today), 1)
        self.assertEqual(tasks[0].due_dt, datetime.datetime(2026, 6, 7, 22, 0))


class PruneCompletedTests(unittest.TestCase):
    def test_drops_past_completed_keeps_today_and_incomplete(self):
        today = datetime.date(2026, 6, 6)
        tasks = [
            _t("昨日完了", "2026-06-05T09:00:00", 30, completed=True, completed_at="2026-06-05T10:00:00"),
            _t("今日完了", "2026-06-06T09:00:00", 30, completed=True, completed_at="2026-06-06T09:30:00"),
            _t("未完了", "2026-06-06T11:00:00", 30),
        ]
        kept = prune_old_completed(tasks, today)
        self.assertEqual([t.title for t in kept], ["今日完了", "未完了"])

    def test_keeps_completed_with_bad_timestamp(self):
        today = datetime.date(2026, 6, 6)
        tasks = [_t("壊れた完了", "2026-06-05T09:00:00", 30, completed=True, completed_at="bad")]
        self.assertEqual(len(prune_old_completed(tasks, today)), 1)

    def test_overnight_completion_pruned_by_planner_day(self):
        # 夜間レンジ 9:00-1:00。暦上 6/6 00:30 の完了は 6/5 のプランナー日に属する。
        # stats も 6/5 扱いにするため、today=6/6 の今日タイムラインからは除去されるべき。
        # （暦日比較のままだと done.date()=6/6 で「今日」と誤判定し残ってしまうのを防ぐ回帰テスト）
        today = datetime.date(2026, 6, 6)
        tasks = [_t("夜更かし完了", "2026-06-05T22:00:00", 30,
                    completed=True, completed_at="2026-06-06T00:30:00")]
        kept = prune_old_completed(tasks, today, 9 * 60, 1 * 60)
        self.assertEqual(kept, [])

    def test_overnight_today_completion_kept_by_planner_day(self):
        # 6/6 プランナー日の深夜（暦 6/7 00:30）に完了したタスクは today=6/6 では残す
        today = datetime.date(2026, 6, 6)
        tasks = [_t("当日深夜完了", "2026-06-06T22:00:00", 30,
                    completed=True, completed_at="2026-06-07T00:30:00")]
        kept = prune_old_completed(tasks, today, 9 * 60, 1 * 60)
        self.assertEqual([t.title for t in kept], ["当日深夜完了"])


if __name__ == "__main__":
    unittest.main()
