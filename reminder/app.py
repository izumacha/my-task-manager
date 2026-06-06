"""Any Planner 風タスクプランナー GUI クラス（タイムライン版）。

1 日のタスクを時間軸（起床〜就寝）で可視化し、空き時間を明示する。
「あとでやる」リストに未スケジュールのタスクを保管し、空き時間に
合うタスクを提案する。繰り返しタスクは「完了した時点」を起点に
次回開始を再計算して再登録される（日 / 週 / 月 / 年、間隔指定可）。

主要な状態遷移:
    [タイムラインへ追加] → 当日の時間軸に配置・通知スケジュール
    [あとでへ追加]       → 未スケジュールのバックログに保管
                              ↓ 空き時間に
                         [予定に追加] → 時間軸へ
                              ↓ 開始時刻に
                          _on_task_due() → 通知
                              ↓ 完了
                       complete_task() → 統計に記録・繰り返しなら次回を再登録
"""
from __future__ import annotations

import datetime
import logging
import tkinter as tk
from tkinter import messagebox, ttk

from .config import Prefs, load_prefs, load_tasks, save_prefs, save_tasks
from .notifications import _set_window_icon, play_notification_sound
from .recurrence import (
    MAX_INTERVAL,
    MIN_INTERVAL,
    RECUR_LABELS,
    RECUR_NONE,
    RECUR_UNITS,
    label_for_unit,
    unit_for_label,
)
from .stats import completed_count_on, current_streak
from .task import (
    DEFAULT_DURATION,
    ISO_FMT,
    MAX_DURATION,
    MIN_DURATION,
    Task,
    build_next_task,
    make_due,
)
from .timeline import (
    ROW_FREE,
    ROW_TASK,
    STATUS_DONE,
    STATUS_NOW,
    STATUS_PAST,
    build_day_timeline,
    carry_over_overdue,
    format_duration,
    free_minutes_today,
    hhmm_to_min,
    max_free_slot,
    min_to_hhmm,
    planner_day,
    prune_old_completed,
    suggest_for_free_time,
)
from .time_utils import HOUR_MAX, HOUR_MIN, MINUTE_MAX, MINUTE_MIN, delay_ms_until

_WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")


class PlannerApp:
    """タイムライン型タスクプランナーの GUI アプリ。

    Attributes:
        root: tkinter のルートウィンドウ。
        tasks: 管理中のタスク（スケジュール済み + あとでやる）。
        prefs: 起床/就寝時刻・完了履歴などの設定。
        jobs: タスク ID → root.after() のジョブ ID（通知スケジュール）。
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.tasks: list[Task] = load_tasks()
        self.prefs: Prefs = load_prefs()
        self.jobs: dict[str, str] = {}

        # 起動時・再描画時の整理（前日以前の完了破棄・未完了の繰り越し）は
        # _refresh() 内の _roll_over() に集約している。

        # 既定開始時刻は「次の 5 分刻み」。分が繰り上がるときは時・日も繰り上げ、
        # 過去時刻が初期値にならないようにする（add_to_timeline は当日固定のため）。
        start = self._default_start(datetime.datetime.now())
        self.title_var = tk.StringVar()
        self.hour_var = tk.StringVar(value=f"{start.hour:02d}")
        self.minute_var = tk.StringVar(value=f"{start.minute:02d}")
        self.dur_var = tk.StringVar(value=str(DEFAULT_DURATION))
        self.recur_var = tk.StringVar(value=RECUR_LABELS[RECUR_NONE])
        self.interval_var = tk.StringVar(value=str(MIN_INTERVAL))
        self.wake_var = tk.StringVar(value=str(self._wake_min() // 60))
        self.sleep_var = tk.StringVar(value=str(self._sleep_min() // 60))
        self.date_var = tk.StringVar()
        self.stats_var = tk.StringVar()
        self.status_var = tk.StringVar(value="タスクを追加してください。")

        self._build_ui()
        self._refresh()
        self._schedule_all()

    # ------------------------------------------------------------ 設定アクセス

    @staticmethod
    def _default_start(now: datetime.datetime) -> datetime.datetime:
        """既定の開始時刻（次の 5 分刻み）を返す。時・日も適切に繰り上げる。"""
        add = 5 - (now.minute % 5)  # 1〜5（既に 5 分刻みなら 5 分後）
        return (now + datetime.timedelta(minutes=add)).replace(second=0, microsecond=0)

    def _planner_today(self, now: datetime.datetime | None = None) -> datetime.date:
        """現在のプランナー日を返す（夜間レンジは就寝境界まで前日扱い）。"""
        now = now or datetime.datetime.now()
        return planner_day(now, self._wake_min(), self._sleep_min())

    def _wake_min(self) -> int:
        """設定の起床時刻を分で返す（不正値は既定値）。"""
        try:
            return hhmm_to_min(self.prefs.wake)
        except (ValueError, AttributeError):
            return 7 * 60

    def _sleep_min(self) -> int:
        """設定の就寝時刻を分で返す（不正値は既定値）。"""
        try:
            return hhmm_to_min(self.prefs.sleep)
        except (ValueError, AttributeError):
            return 23 * 60

    # ------------------------------------------------------------------ UI 構築

    def _build_ui(self) -> None:
        """ウィンドウとすべての UI コンポーネントを構築する。"""
        self.root.title("Any Planner")
        _set_window_icon(self.root)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        style = ttk.Style()
        available = style.theme_names()
        for theme in ("aqua", "clam", "vista"):
            if theme in available:
                style.theme_use(theme)
                break
        style.configure("TLabel", font=("system", 11))
        style.configure("TButton", font=("system", 11), padding=5)
        style.configure("Status.TLabel", font=("system", 10), foreground="#666")
        style.configure("Stats.TLabel", font=("system", 11, "bold"), foreground="#0a7")
        style.configure("Heading.TLabel", font=("system", 13, "bold"))
        style.configure("Date.TLabel", font=("system", 14, "bold"))

        frame = ttk.Frame(self.root, padding=16)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=3, uniform="cols")
        frame.columnconfigure(1, weight=2, uniform="cols")
        frame.rowconfigure(2, weight=1)

        self._build_header(frame)   # row 0
        self._build_input(frame)    # row 1
        self._build_timeline(frame)  # row 2 col 0
        self._build_backlog(frame)  # row 2 col 1
        self._build_status(frame)   # row 3

        self.root.bind("<Return>", lambda _e: self.add_to_timeline())
        self.title_entry.focus_set()

    def _build_header(self, frame: ttk.Frame) -> None:
        """日付・起床/就寝・統計を表示するヘッダ（row 0）。"""
        header = ttk.Frame(frame)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        header.columnconfigure(2, weight=1)

        ttk.Label(header, textvariable=self.date_var, style="Date.TLabel").grid(
            row=0, column=0, sticky="w")

        rng = ttk.Frame(header)
        rng.grid(row=0, column=1, sticky="w", padx=16)
        ttk.Label(rng, text="起床").pack(side=tk.LEFT)
        self.wake_menu = ttk.Spinbox(rng, textvariable=self.wake_var, from_=0, to=23,
                                     width=3, format="%02.0f", command=self._on_range_change)
        self.wake_menu.pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(rng, text="就寝").pack(side=tk.LEFT)
        self.sleep_menu = ttk.Spinbox(rng, textvariable=self.sleep_var, from_=0, to=23,
                                      width=3, format="%02.0f", command=self._on_range_change)
        self.sleep_menu.pack(side=tk.LEFT, padx=(2, 0))
        self.wake_menu.bind("<FocusOut>", lambda _e: self._on_range_change())
        self.sleep_menu.bind("<FocusOut>", lambda _e: self._on_range_change())

        ttk.Label(header, textvariable=self.stats_var, style="Stats.TLabel").grid(
            row=0, column=2, sticky="e")

    def _build_input(self, frame: ttk.Frame) -> None:
        """タスク追加フォーム（row 1）。"""
        row = ttk.Frame(frame)
        row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        row.columnconfigure(0, weight=1)

        self.title_entry = ttk.Entry(row, textvariable=self.title_var, font=("system", 11))
        self.title_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        opts = ttk.Frame(row)
        opts.grid(row=0, column=1)
        ttk.Label(opts, text="開始").pack(side=tk.LEFT)
        self.hour_menu = ttk.Spinbox(opts, textvariable=self.hour_var, from_=HOUR_MIN, to=HOUR_MAX,
                                     wrap=True, width=3, format="%02.0f")
        self.hour_menu.pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(opts, text=":").pack(side=tk.LEFT)
        self.minute_menu = ttk.Spinbox(opts, textvariable=self.minute_var, from_=MINUTE_MIN,
                                       to=MINUTE_MAX, wrap=True, width=3, format="%02.0f")
        self.minute_menu.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(opts, text="所要(分)").pack(side=tk.LEFT)
        self.dur_menu = ttk.Spinbox(opts, textvariable=self.dur_var, from_=MIN_DURATION,
                                    to=MAX_DURATION, increment=5, width=5)
        self.dur_menu.pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(opts, text="繰り返し").pack(side=tk.LEFT)
        self.recur_menu = ttk.Combobox(opts, textvariable=self.recur_var, state="readonly",
                                       width=5, values=[RECUR_LABELS[u] for u in RECUR_UNITS])
        self.recur_menu.pack(side=tk.LEFT, padx=(2, 0))
        self.interval_menu = ttk.Spinbox(opts, textvariable=self.interval_var, from_=MIN_INTERVAL,
                                         to=MAX_INTERVAL, width=3)
        self.interval_menu.pack(side=tk.LEFT, padx=(2, 8))

        ttk.Button(opts, text="タイムラインへ", command=self.add_to_timeline).pack(side=tk.LEFT)
        ttk.Button(opts, text="あとでへ", command=self.add_to_backlog).pack(side=tk.LEFT, padx=(6, 0))

    def _build_timeline(self, frame: ttk.Frame) -> None:
        """今日のタイムライン（row 2, col 0）。"""
        panel = ttk.Frame(frame)
        panel.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text="今日のタイムライン", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))

        body = ttk.Frame(panel)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.timeline_tree = ttk.Treeview(body, columns=("time", "title", "info"),
                                          show="headings", height=12)
        self.timeline_tree.heading("time", text="時間")
        self.timeline_tree.heading("title", text="タスク")
        self.timeline_tree.heading("info", text="繰り返し")
        self.timeline_tree.column("time", width=110, anchor="w", stretch=False)
        self.timeline_tree.column("title", width=200, anchor="w")
        self.timeline_tree.column("info", width=80, anchor="center", stretch=False)
        self.timeline_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.timeline_tree.yview)
        self.timeline_tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        self.timeline_tree.tag_configure(ROW_FREE, foreground="#9aa0a6")
        self.timeline_tree.tag_configure(STATUS_DONE, foreground="#9aa0a6")
        self.timeline_tree.tag_configure(STATUS_NOW, foreground="#0a7", font=("system", 11, "bold"))
        self.timeline_tree.tag_configure(STATUS_PAST, foreground="#c0392b")

        actions = ttk.Frame(panel)
        actions.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(actions, text="完了", command=self.complete_timeline_selected).pack(side=tk.LEFT)
        ttk.Button(actions, text="あとでへ", command=self.move_to_backlog).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="削除", command=self.delete_timeline_selected).pack(side=tk.LEFT, padx=(6, 0))

    def _build_backlog(self, frame: ttk.Frame) -> None:
        """あとでやるリスト（row 2, col 1）。"""
        panel = ttk.Frame(frame)
        panel.grid(row=2, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text="あとでやる", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6))

        body = ttk.Frame(panel)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.backlog_tree = ttk.Treeview(body, columns=("title", "dur", "info"),
                                         show="headings", height=12)
        self.backlog_tree.heading("title", text="タスク")
        self.backlog_tree.heading("dur", text="所要")
        self.backlog_tree.heading("info", text="繰り返し")
        self.backlog_tree.column("title", width=160, anchor="w")
        self.backlog_tree.column("dur", width=70, anchor="center", stretch=False)
        self.backlog_tree.column("info", width=70, anchor="center", stretch=False)
        self.backlog_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.backlog_tree.yview)
        self.backlog_tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        self.backlog_tree.tag_configure("suggest", foreground="#0a7")

        actions = ttk.Frame(panel)
        actions.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Button(actions, text="予定に追加", command=self.schedule_backlog_selected).pack(side=tk.LEFT)
        ttk.Button(actions, text="完了", command=self.complete_backlog_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="削除", command=self.delete_backlog_selected).pack(side=tk.LEFT, padx=(6, 0))

    def _build_status(self, frame: ttk.Frame) -> None:
        """ステータスラベル（row 3）。"""
        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------ 入力正規化

    @staticmethod
    def _coerce_int(raw: str, min_value: int, max_value: int) -> int:
        """文字列を整数に変換し、[min_value, max_value] にクランプして返す。"""
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return min_value
        return max(min_value, min(max_value, value))

    def _input_start_time(self) -> datetime.time:
        """入力欄の開始時刻を正規化して time として返す。"""
        h = self._coerce_int(self.hour_var.get(), HOUR_MIN, HOUR_MAX)
        m = self._coerce_int(self.minute_var.get(), MINUTE_MIN, MINUTE_MAX)
        self.hour_var.set(f"{h:02d}")
        self.minute_var.set(f"{m:02d}")
        return datetime.time(h, m)

    def _input_duration(self) -> int:
        """入力欄の所要時間（分）を正規化して返す。"""
        d = self._coerce_int(self.dur_var.get(), MIN_DURATION, MAX_DURATION)
        self.dur_var.set(str(d))
        return d

    def _input_recurrence(self) -> tuple[str, int]:
        """入力欄の繰り返し単位・間隔を返す。"""
        interval = self._coerce_int(self.interval_var.get(), MIN_INTERVAL, MAX_INTERVAL)
        self.interval_var.set(str(interval))
        return unit_for_label(self.recur_var.get()), interval

    def _on_range_change(self) -> None:
        """起床/就寝の変更を設定へ反映し、タイムラインを再描画する。"""
        wake = self._coerce_int(self.wake_var.get(), 0, 23)
        sleep = self._coerce_int(self.sleep_var.get(), 0, 23)
        self.wake_var.set(f"{wake:02d}")
        self.sleep_var.set(f"{sleep:02d}")
        self.prefs.wake = min_to_hhmm(wake * 60)
        self.prefs.sleep = min_to_hhmm(sleep * 60)
        save_prefs(self.prefs)
        self._refresh()

    # ------------------------------------------------------------ タスク追加

    def add_to_timeline(self) -> None:
        """入力内容で当日のタイムラインにタスクを追加する。"""
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("入力エラー", "タスク名を入力してください。")
            return
        start = self._input_start_time()
        duration = self._input_duration()
        recur_unit, interval = self._input_recurrence()
        # 過去時刻が選ばれた場合は翌日へ繰り上げ、通知が必ず効くようにする
        # （前方プランナーとしての挙動。深夜 0:00 を選んだ場合も翌日になる）。
        due = make_due(start, roll_if_past=True)
        task = Task(title=title, due=due, duration_min=duration,
                    recur_unit=recur_unit, recur_interval=interval)
        self.tasks.append(task)
        self._persist_tasks()
        self._refresh()
        self._schedule_task(task)
        self.title_var.set("")
        self.status_var.set(f"「{title}」を {start.hour:02d}:{start.minute:02d} に追加しました。")
        logging.info("タイムラインに追加: %s（%s, %d分）", title, due, duration)

    def add_to_backlog(self) -> None:
        """入力内容で「あとでやる」にタスクを追加する（時間は割り当てない）。"""
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("入力エラー", "タスク名を入力してください。")
            return
        duration = self._input_duration()
        recur_unit, interval = self._input_recurrence()
        task = Task(title=title, due="", duration_min=duration,
                    recur_unit=recur_unit, recur_interval=interval)
        self.tasks.append(task)
        self._persist_tasks()
        self._refresh()
        self.title_var.set("")
        self.status_var.set(f"「{title}」を「あとでやる」に追加しました。")
        logging.info("あとでやるに追加: %s（%d分）", title, duration)

    # ------------------------------------------------------------ タスク操作

    def _find(self, task_id: str | None) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def _selected(self, tree) -> Task | None:
        selection = tree.selection()
        if not selection:
            return None
        return self._find(selection[0])

    def complete_timeline_selected(self) -> None:
        task = self._selected(self.timeline_tree)
        self._complete(task)

    def complete_backlog_selected(self) -> None:
        task = self._selected(self.backlog_tree)
        self._complete(task)

    def _complete(self, task: Task | None) -> None:
        """タスクを完了し、統計に記録する。繰り返しなら次回を再登録する。"""
        if task is None:
            self.status_var.set("完了するタスクを選択してください。")
            return
        if task.completed:
            # 完了済みタスクはタイムラインに残るため、再度押下されても
            # 統計の二重計上や繰り返しタスクの重複生成を防ぐ。
            self.status_var.set(f"「{task.title}」は既に完了しています。")
            return
        completed_at = datetime.datetime.now()
        self._cancel_job(task.id)
        task.completed = True
        task.completed_at = completed_at.strftime(ISO_FMT)

        # 統計（完了履歴）に記録
        self.prefs.completions.append(task.completed_at)
        save_prefs(self.prefs)

        next_task = build_next_task(task, completed_at)
        if next_task is not None:
            self.tasks.append(next_task)
            self._persist_tasks()
            self._refresh()
            self._schedule_task(next_task)
            self.status_var.set(
                f"「{task.title}」を完了。次回は {next_task.due_dt:%m/%d %H:%M} に再設定しました。")
            logging.info("繰り返しタスクを再登録: %s → %s", task.title, next_task.due)
        else:
            self._persist_tasks()
            self._refresh()
            self.status_var.set(f"「{task.title}」を完了しました。")
            logging.info("タスクを完了: %s", task.title)

    def delete_timeline_selected(self) -> None:
        self._delete(self._selected(self.timeline_tree))

    def delete_backlog_selected(self) -> None:
        self._delete(self._selected(self.backlog_tree))

    def _delete(self, task: Task | None) -> None:
        if task is None:
            self.status_var.set("削除するタスクを選択してください。")
            return
        self._cancel_job(task.id)
        self.tasks = [t for t in self.tasks if t.id != task.id]
        self._persist_tasks()
        self._refresh()
        self.status_var.set(f"「{task.title}」を削除しました。")

    def move_to_backlog(self) -> None:
        """タイムライン上のタスクを「あとでやる」へ戻す（時間を外す）。"""
        task = self._selected(self.timeline_tree)
        if task is None:
            self.status_var.set("移動するタスクを選択してください。")
            return
        self._cancel_job(task.id)
        task.due = ""
        self._persist_tasks()
        self._refresh()
        self.status_var.set(f"「{task.title}」を「あとでやる」へ移動しました。")

    def schedule_backlog_selected(self) -> None:
        """「あとでやる」のタスクを、入力欄の開始時刻で当日のタイムラインへ。"""
        task = self._selected(self.backlog_tree)
        if task is None:
            self.status_var.set("予定に追加するタスクを選択してください。")
            return
        start = self._input_start_time()
        task.due = make_due(start, roll_if_past=True)
        self._persist_tasks()
        self._refresh()
        self._schedule_task(task)
        self.status_var.set(f"「{task.title}」を {start.hour:02d}:{start.minute:02d} に予定しました。")

    # ------------------------------------------------------------ 表示

    def _refresh(self) -> None:
        """日付・統計・タイムライン・バックログをすべて再描画する。

        アプリを開いたまま日付（プランナー日）をまたいでも、再描画のたびに
        繰り越し・整理を行うため、未完了タスクが消えることはない。
        """
        today = self._planner_today()
        if self._roll_over(today):
            self._persist_tasks()
            # 繰り越しでタスクの開始時刻が未来へ移ったので、通知を再登録する
            # （開きっぱなしで日跨ぎしても繰り越し分が通知されるようにする）。
            self._schedule_all()
        self.date_var.set(f"今日 {today.month}/{today.day}（{_WEEKDAY_JA[today.weekday()]}）")
        self._render_timeline(today)
        self._render_backlog(today)
        self._render_stats(today)

    def _roll_over(self, today: datetime.date) -> bool:
        """プランナー日 today を基準に完了整理・繰り越しを行う。変化があれば True。"""
        before = len(self.tasks)
        self.tasks = prune_old_completed(self.tasks, today)
        moved = carry_over_overdue(self.tasks, today, self._wake_min(), self._sleep_min())
        return moved > 0 or len(self.tasks) != before

    def _render_timeline(self, today: datetime.date) -> None:
        tree = self.timeline_tree
        for item in tree.get_children():
            tree.delete(item)
        now = datetime.datetime.now()
        rows = build_day_timeline(self.tasks, today, self._wake_min(), self._sleep_min(), now)
        for i, row in enumerate(rows):
            span = f"{row.start:%H:%M}–{row.end:%H:%M}"
            if row.kind == ROW_TASK:
                task = row.task
                title = ("✓ " if row.status == STATUS_DONE else "") + task.title
                tree.insert("", tk.END, iid=task.id,
                            values=(span, title, self._recur_text(task)),
                            tags=(row.status,))
            else:  # ROW_FREE
                tree.insert("", tk.END, iid=f"free{i}",
                            values=(span, f"空き {format_duration(row.minutes)}", ""),
                            tags=(ROW_FREE,))

    def _render_backlog(self, today: datetime.date) -> None:
        tree = self.backlog_tree
        for item in tree.get_children():
            tree.delete(item)
        # 提案は「最大連続空き枠」に収まるものに限る（合計空きでは個々の枠に
        # 置けないタスクまで提案してしまい誤解を招くため）。
        slot = max_free_slot(self.tasks, today,
                             self._wake_min(), self._sleep_min())
        suggestions = {t.id for t in suggest_for_free_time(self.tasks, slot)}
        for task in [t for t in self.tasks if not t.is_scheduled and not t.completed]:
            tags = ("suggest",) if task.id in suggestions else ()
            tree.insert("", tk.END, iid=task.id,
                        values=(task.title, format_duration(task.duration_min),
                                self._recur_text(task)),
                        tags=tags)

    def _render_stats(self, today: datetime.date) -> None:
        wake, sleep = self._wake_min(), self._sleep_min()
        done = completed_count_on(self.prefs.completions, today, wake, sleep)
        streak = current_streak(self.prefs.completions, today, wake, sleep)
        free = free_minutes_today(self.tasks, today, wake, sleep)
        self.stats_var.set(
            f"今日の完了 {done}件 ・ 連続 {streak}日 ・ 空き {format_duration(free)}")

    @staticmethod
    def _recur_text(task: Task) -> str:
        """繰り返し設定を「2週ごと」のような表示文字列にする。"""
        if task.recur_unit == RECUR_NONE:
            return "—"
        return f"{task.recur_interval}{label_for_unit(task.recur_unit)}ごと"

    # ------------------------------------------------------------ スケジュール

    def _schedule_all(self) -> None:
        """起動時に、未来に開始するすべてのタスクの通知をスケジュールする。"""
        for task in self.tasks:
            try:
                self._schedule_task(task)
            except Exception:
                logging.warning("タスクの通知スケジュールに失敗しました: %s", task.id)

    def _schedule_task(self, task: Task) -> None:
        """開始時刻に通知するジョブを登録する（未スケジュール/過去/完了は対象外）。"""
        if not task.is_scheduled or task.completed:
            return
        now = datetime.datetime.now()
        if task.due_dt <= now:
            return
        delay_ms = delay_ms_until(now, task.due_dt)
        self._cancel_job(task.id)
        try:
            self.jobs[task.id] = self.root.after(delay_ms, lambda: self._on_task_due(task.id))
        except Exception:
            self.jobs.pop(task.id, None)
            raise

    def _on_task_due(self, task_id: str) -> None:
        """開始時刻に呼ばれ、デスクトップ通知を出す。"""
        self.jobs.pop(task_id, None)
        task = self._find(task_id)
        if task is None or task.completed:
            return
        if datetime.datetime.now() < task.due_dt:  # クランプで早く起きた場合は再登録
            self._schedule_task(task)
            return
        play_notification_sound(self.root, task.title)
        messagebox.showinfo("Any Planner", f"⏰ {task.title}")
        self._refresh()
        self.status_var.set(f"「{task.title}」の開始時刻になりました。")

    def _cancel_job(self, task_id: str) -> None:
        """指定タスクの保留中ジョブをキャンセルする。"""
        job_id = self.jobs.pop(task_id, None)
        if job_id is not None:
            try:
                self.root.after_cancel(job_id)
            except Exception:
                logging.debug("ジョブのキャンセルに失敗しました: %s", task_id)

    def _persist_tasks(self) -> None:
        """現在のタスク一覧をディスクに保存する。"""
        save_tasks(self.tasks)


# 旧名との後方互換エイリアス
ReminderApp = PlannerApp
