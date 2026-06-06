"""Any Planner 風タスクプランナー GUI クラス。

タスクの追加・完了・削除を一覧で管理し、期限時刻にデスクトップ通知を出す。
繰り返しタスクは「完了した時点」を起点に次回期限を再計算して自動で再登録される
（日 / 週 / 月 / 年、間隔指定可）。tkinter を使用したシングルウィンドウ構成。

主要な状態遷移:
    [タスク追加] → add_task() → 一覧に未完了タスクとして表示・通知スケジュール
                                      ↓ 期限到達
                                _on_task_due() → デスクトップ通知
                                      ↓ ユーザーが「完了」
                              complete_selected() → 繰り返しありなら次回タスクを再登録
"""
from __future__ import annotations

import datetime
import logging
import tkinter as tk
from tkinter import messagebox, ttk

from .config import load_tasks, save_tasks
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
from .task import Task, build_next_task, make_due
from .time_utils import (
    HOUR_MAX,
    HOUR_MIN,
    MINUTE_MAX,
    MINUTE_MIN,
    STATUS_EMPTY,
    STATUS_IDLE,
    delay_ms_until,
)


class PlannerApp:
    """タスクプランナーの GUI アプリ。

    Attributes:
        root: tkinter のルートウィンドウ。
        tasks: 現在管理しているタスクのリスト。
        jobs: タスク ID → root.after() のジョブ ID のマッピング（通知スケジュール）。
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.tasks: list[Task] = load_tasks()
        # タスク ID ごとに保留中の after ジョブ ID を保持する
        self.jobs: dict[str, str] = {}

        # 既定の期限時刻は「次の分」にする。現在の分のままだと make_due() が
        # 秒を :00 に切り捨てたうえで due <= now と判定して翌日送りになり、
        # 開いた直後に時刻を変えずに追加すると意図せず翌日のタスクになってしまうため。
        default_time = datetime.datetime.now() + datetime.timedelta(minutes=1)
        self.title_var = tk.StringVar()
        self.hour_var = tk.StringVar(value=f"{default_time.hour:02d}")
        self.minute_var = tk.StringVar(value=f"{default_time.minute:02d}")
        # 繰り返し単位はラベル（「なし」「日」…）で UI に保持する
        self.recur_var = tk.StringVar(value=RECUR_LABELS[RECUR_NONE])
        self.interval_var = tk.StringVar(value=str(MIN_INTERVAL))
        self.status_var = tk.StringVar(value=STATUS_IDLE)

        self._build_ui()
        self._render_tasks()
        self._schedule_all()

    # ------------------------------------------------------------------ UI 構築

    def _build_ui(self) -> None:
        """ウィンドウとすべての UI コンポーネントを構築する。"""
        self.root.title("Any Planner")
        _set_window_icon(self.root)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # OS ネイティブに近いテーマを選択
        style = ttk.Style()
        available = style.theme_names()
        for theme in ("aqua", "clam", "vista"):
            if theme in available:
                style.theme_use(theme)
                break

        style.configure("TLabel", font=("system", 11))
        style.configure("TButton", font=("system", 11), padding=6)
        style.configure("Status.TLabel", font=("system", 10), foreground="#666")
        style.configure("Heading.TLabel", font=("system", 13, "bold"))

        frame = ttk.Frame(self.root, padding=18)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        self._build_input_section(frame)   # row 0: 入力フォーム
        self._build_recur_section(frame)   # row 1: 繰り返し設定
        self._build_list_section(frame)    # row 2-3: 見出し + タスク一覧
        self._build_action_section(frame)  # row 4: 完了・削除ボタン
        self._build_status_section(frame)  # row 5: ステータスラベル

        # Enter キーでタスクを追加できるようにする
        self.root.bind("<Return>", lambda _event: self.add_task())
        self.title_entry.focus_set()

    def _build_input_section(self, frame: ttk.Frame) -> None:
        """タスク名と期限時刻の入力欄、追加ボタンを生成する（row 0）。"""
        row = ttk.Frame(frame)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)

        self.title_entry = ttk.Entry(row, textvariable=self.title_var, font=("system", 11))
        self.title_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        time_box = ttk.Frame(row)
        time_box.grid(row=0, column=1, padx=(0, 8))
        self.hour_menu = ttk.Spinbox(
            time_box, textvariable=self.hour_var,
            from_=HOUR_MIN, to=HOUR_MAX, wrap=True, width=3, format="%02.0f",
        )
        self.hour_menu.pack(side=tk.LEFT)
        ttk.Label(time_box, text=":", font=("system", 13, "bold")).pack(side=tk.LEFT, padx=2)
        self.minute_menu = ttk.Spinbox(
            time_box, textvariable=self.minute_var,
            from_=MINUTE_MIN, to=MINUTE_MAX, wrap=True, width=3, format="%02.0f",
        )
        self.minute_menu.pack(side=tk.LEFT)
        self.hour_menu.bind("<FocusOut>", lambda _event: self._normalize_time_inputs())
        self.minute_menu.bind("<FocusOut>", lambda _event: self._normalize_time_inputs())

        self.add_button = ttk.Button(row, text="追加", command=self.add_task)
        self.add_button.grid(row=0, column=2)

    def _build_recur_section(self, frame: ttk.Frame) -> None:
        """繰り返し単位・間隔の入力欄を生成する（row 1）。"""
        row = ttk.Frame(frame)
        row.grid(row=1, column=0, sticky="w", pady=(10, 12))

        ttk.Label(row, text="繰り返し（完了時点から）").pack(side=tk.LEFT, padx=(0, 8))
        # 「なし」を含む単位ラベルの選択肢
        self.recur_menu = ttk.Combobox(
            row, textvariable=self.recur_var, state="readonly", width=6,
            values=[RECUR_LABELS[u] for u in RECUR_UNITS],
        )
        self.recur_menu.pack(side=tk.LEFT)

        ttk.Label(row, text="間隔").pack(side=tk.LEFT, padx=(12, 4))
        self.interval_menu = ttk.Spinbox(
            row, textvariable=self.interval_var,
            from_=MIN_INTERVAL, to=MAX_INTERVAL, wrap=False, width=4,
        )
        self.interval_menu.pack(side=tk.LEFT)
        self.interval_menu.bind("<FocusOut>", lambda _event: self._normalize_interval_input())

    def _build_list_section(self, frame: ttk.Frame) -> None:
        """見出しラベル（row 2）とタスク一覧 Treeview（row 3）を生成する。

        見出しと一覧コンテナを別々の行に配置することで、拡張行（row 3）に
        見出しが重なって表示される問題を避ける。
        """
        ttk.Label(frame, text="タスク一覧", style="Heading.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 6)
        )
        container = ttk.Frame(frame)
        container.grid(row=3, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        columns = ("title", "due", "recur")
        self.tree = ttk.Treeview(container, columns=columns, show="headings", height=8)
        self.tree.heading("title", text="タスク")
        self.tree.heading("due", text="期限")
        self.tree.heading("recur", text="繰り返し")
        self.tree.column("title", width=200, anchor="w")
        self.tree.column("due", width=120, anchor="center")
        self.tree.column("recur", width=90, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        # 期限切れタスクを薄赤で強調表示する
        self.tree.tag_configure("overdue", foreground="#c0392b")

    def _build_action_section(self, frame: ttk.Frame) -> None:
        """「完了」「削除」ボタンを生成する（row 4）。"""
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, sticky="w", pady=(12, 8))
        self.complete_button = ttk.Button(buttons, text="完了", command=self.complete_selected)
        self.complete_button.pack(side=tk.LEFT)
        self.delete_button = ttk.Button(buttons, text="削除", command=self.delete_selected)
        self.delete_button.pack(side=tk.LEFT, padx=(8, 0))

    def _build_status_section(self, frame: ttk.Frame) -> None:
        """ステータスメッセージを表示するラベルを生成する（row 5）。"""
        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").grid(
            row=5, column=0, sticky="w", pady=(4, 0)
        )

    # ------------------------------------------------------------ 入力正規化

    def _normalize_time_inputs(self) -> None:
        """時刻入力値を範囲内に正規化して 2 桁表示にそろえる。"""
        self.hour_var.set(f"{self._coerce_int(self.hour_var.get(), HOUR_MIN, HOUR_MAX):02d}")
        self.minute_var.set(f"{self._coerce_int(self.minute_var.get(), MINUTE_MIN, MINUTE_MAX):02d}")

    def _normalize_interval_input(self) -> int:
        """繰り返し間隔を [MIN_INTERVAL, MAX_INTERVAL] に正規化し、正規化後の値を返す。"""
        value = self._coerce_int(self.interval_var.get(), MIN_INTERVAL, MAX_INTERVAL)
        self.interval_var.set(str(value))
        return value

    @staticmethod
    def _coerce_int(raw: str, min_value: int, max_value: int) -> int:
        """文字列を整数に変換し、[min_value, max_value] の範囲にクランプして返す。

        Args:
            raw: 変換対象の文字列。数値以外・空文字は min_value として扱う。
            min_value: 返値の最小値（変換失敗時のフォールバック値にもなる）。
            max_value: 返値の最大値。

        Returns:
            範囲内にクランプされた整数値。
        """
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return min_value
        return max(min_value, min(max_value, value))

    # ------------------------------------------------------------ タスク操作

    def add_task(self) -> None:
        """入力内容を検証し、新しいタスクを一覧に追加して通知をスケジュールする。

        タイトルが空の場合は警告ダイアログを表示して処理を中断する。
        """
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("入力エラー", "タスク名を入力してください。")
            return

        self._normalize_time_inputs()
        interval = self._normalize_interval_input()
        target_time = datetime.time(int(self.hour_var.get()), int(self.minute_var.get()))
        recur_unit = unit_for_label(self.recur_var.get())

        task = Task(
            title=title,
            due=make_due(target_time),
            recur_unit=recur_unit,
            recur_interval=interval,
        )
        self.tasks.append(task)
        self._persist()
        self._render_tasks()
        self._schedule_task(task)

        # 入力欄をクリアして次のタスク入力に備える
        self.title_var.set("")
        self.status_var.set(f"「{title}」を {self._format_due(task.due_dt)} に追加しました。")
        logging.info("タスクを追加: %s（期限 %s, 繰り返し %s/%d）",
                     title, task.due, task.recur_unit, task.recur_interval)

    def complete_selected(self) -> None:
        """選択中のタスクを完了する。繰り返し設定があれば次回タスクを再登録する。

        次回期限は「完了した時点（現在時刻）」を起点に算出される。
        """
        task = self._selected_task()
        if task is None:
            self.status_var.set("完了するタスクを選択してください。")
            return

        completed_at = datetime.datetime.now()
        self._cancel_job(task.id)
        self._remove_task(task.id)

        next_task = build_next_task(task, completed_at)
        if next_task is not None:
            self.tasks.append(next_task)
            self._persist()
            self._render_tasks()
            self._schedule_task(next_task)
            self.status_var.set(
                f"「{task.title}」を完了。次回は {self._format_due(next_task.due_dt)} に再設定しました。"
            )
            logging.info("繰り返しタスクを再登録: %s → %s", task.title, next_task.due)
        else:
            self._persist()
            self._render_tasks()
            self.status_var.set(f"「{task.title}」を完了しました。")
            logging.info("タスクを完了: %s", task.title)

    def delete_selected(self) -> None:
        """選択中のタスクを削除する。"""
        task = self._selected_task()
        if task is None:
            self.status_var.set("削除するタスクを選択してください。")
            return
        self._cancel_job(task.id)
        self._remove_task(task.id)
        self._persist()
        self._render_tasks()
        self.status_var.set(f"「{task.title}」を削除しました。")
        logging.info("タスクを削除: %s", task.title)

    def _remove_task(self, task_id: str) -> None:
        """指定 ID のタスクを内部リストから取り除く（永続化・再描画は呼び出し側）。"""
        self.tasks = [t for t in self.tasks if t.id != task_id]

    def _selected_task(self) -> Task | None:
        """Treeview で選択中のタスクを返す。未選択なら None。"""
        selection = self.tree.selection()
        if not selection:
            return None
        task_id = selection[0]
        return next((t for t in self.tasks if t.id == task_id), None)

    # ------------------------------------------------------------ 表示

    def _render_tasks(self) -> None:
        """Treeview を現在のタスク一覧で再描画する（期限昇順）。"""
        for item in self.tree.get_children():
            self.tree.delete(item)

        now = datetime.datetime.now()
        for task in sorted(self.tasks, key=lambda t: t.due):
            tags = ("overdue",) if task.due_dt <= now else ()
            self.tree.insert(
                "", tk.END, iid=task.id,
                values=(task.title, self._format_due(task.due_dt), self._format_recur(task)),
                tags=tags,
            )

        if not self.tasks:
            self.status_var.set(STATUS_EMPTY)

    @staticmethod
    def _format_due(due: datetime.datetime) -> str:
        """期限日時を「MM/DD HH:MM」形式の文字列にする。"""
        return due.strftime("%m/%d %H:%M")

    @staticmethod
    def _format_recur(task: Task) -> str:
        """繰り返し設定を「2週ごと」のような表示文字列にする。"""
        if task.recur_unit == RECUR_NONE:
            return "—"
        return f"{task.recur_interval}{label_for_unit(task.recur_unit)}ごと"

    # ------------------------------------------------------------ スケジュール

    def _schedule_all(self) -> None:
        """起動時に、未来に期限が来るすべてのタスクの通知をスケジュールする。"""
        for task in self.tasks:
            self._schedule_task(task)

    def _schedule_task(self, task: Task) -> None:
        """1 件のタスクについて、期限時刻に通知するジョブを登録する。

        既に期限切れのタスクは通知をスケジュールしない（一覧上で強調表示するのみ）。
        """
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
        """期限到達時に呼ばれ、デスクトップ通知を出す。

        after の遅延上限クランプにより期限前に発火した場合は再スケジュールする。
        """
        self.jobs.pop(task_id, None)
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task is None:
            return

        # クランプで早く起きた場合は、残り時間で再スケジュールして抜ける
        if datetime.datetime.now() < task.due_dt:
            self._schedule_task(task)
            return

        play_notification_sound(self.root, task.title)
        messagebox.showinfo("Any Planner", f"⏰ {task.title}")
        self._render_tasks()
        self.status_var.set(f"「{task.title}」の期限になりました。")
        logging.info("タスク期限通知: %s", task.title)

    def _cancel_job(self, task_id: str) -> None:
        """指定タスクの保留中ジョブをキャンセルする（存在しなければ何もしない）。"""
        job_id = self.jobs.pop(task_id, None)
        if job_id is not None:
            try:
                self.root.after_cancel(job_id)
            except Exception:
                logging.debug("ジョブのキャンセルに失敗しました: %s", task_id)

    def _persist(self) -> None:
        """現在のタスク一覧をディスクに保存する。"""
        save_tasks(self.tasks)


# 旧名との後方互換エイリアス（外部から ReminderApp 参照していた場合に備える）
ReminderApp = PlannerApp
