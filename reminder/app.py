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
from . import theme
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
    ROW_TASK,
    STATUS_DONE,
    STATUS_NOW,
    STATUS_PAST,
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

        # カレンダー（デイビュー）の選択状態と描画幅。
        # 選択は Treeview ではなく「クリックされたブロックの task.id」で管理する。
        self._tl_selected: str | None = None
        self._tl_width: int = 460  # <Configure> で実幅に更新する
        # クリック判定用のブロック矩形（_render_timeline で毎回作り直す）。
        self._tl_blocks: list = []

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

    def _apply_style(self) -> None:
        """ttk スタイルを theme モジュールのトークンで一括設定する。

        TimeTree 風のポップな配色を実現するため、最も自由に色を変えられる
        ``clam`` テーマを基盤に選ぶ。色・フォントの実値はすべて
        :mod:`reminder.theme` 側に定義し、ここでは割り当てるだけにする。
        """
        style = ttk.Style()
        available = style.theme_names()
        # clam は配色を細かく変更できるため最優先。無い環境では既存テーマで継続。
        for base in ("clam", "alt", "default"):
            if base in available:
                style.theme_use(base)
                break

        # フレーム（ページ背景 / カード）
        style.configure("App.TFrame", background=theme.BG)
        style.configure("Card.TFrame", background=theme.CARD)
        style.configure("Header.TFrame", background=theme.BG)

        # ラベル各種
        style.configure("TLabel", background=theme.BG, foreground=theme.TEXT,
                        font=theme.FONT_BASE)
        style.configure("Card.TLabel", background=theme.CARD, foreground=theme.TEXT,
                        font=theme.FONT_BASE)
        style.configure("Date.TLabel", background=theme.BG, foreground=theme.TEXT,
                        font=theme.FONT_DATE)
        style.configure("Heading.TLabel", background=theme.CARD, foreground=theme.TEXT,
                        font=theme.FONT_HEADING)
        style.configure("Status.TLabel", background=theme.BG, foreground=theme.TEXT_MUTED,
                        font=theme.FONT_SMALL)
        # 統計はブランド色のピル（バッジ）風に見せる。
        style.configure("Stats.TLabel", background=theme.BRAND_SOFT,
                        foreground=theme.BRAND_DARK, font=theme.FONT_STATS, padding=(12, 6))

        # 入力ウィジェット（白背景・角丸風の余白）
        for name in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(name, fieldbackground=theme.CARD, background=theme.CARD,
                            foreground=theme.TEXT, bordercolor=theme.BORDER,
                            arrowcolor=theme.TEXT_MUTED, padding=4)

        # ボタン: プライマリ（ブランド色）とセカンダリ（白地）の 2 種。
        style.configure("TButton", font=theme.FONT_BASE, padding=(12, 7),
                        relief="flat", background=theme.CARD, foreground=theme.TEXT,
                        bordercolor=theme.BORDER, focuscolor=theme.BRAND_SOFT)
        style.map("TButton",
                  background=[("active", theme.BRAND_SOFT)],
                  foreground=[("active", theme.BRAND_DARK)])
        style.configure("Primary.TButton", font=theme.FONT_BOLD, padding=(14, 8),
                        relief="flat", background=theme.BRAND,
                        foreground=theme.TEXT_ON_BRAND, focuscolor=theme.BRAND)
        style.map("Primary.TButton",
                  background=[("active", theme.BRAND_DARK), ("pressed", theme.BRAND_DARK)],
                  foreground=[("active", theme.TEXT_ON_BRAND)])

        # Treeview（タイムライン / バックログ）
        style.configure("Treeview", background=theme.CARD, fieldbackground=theme.CARD,
                        foreground=theme.TEXT, rowheight=theme.ROW_HEIGHT,
                        borderwidth=0, font=theme.FONT_BASE)
        style.configure("Treeview.Heading", background=theme.BG, foreground=theme.TEXT_MUTED,
                        relief="flat", font=theme.FONT_SMALL, padding=(8, 6))
        style.map("Treeview.Heading", background=[("active", theme.BORDER)])
        style.map("Treeview",
                  background=[("selected", theme.BRAND_SOFT)],
                  foreground=[("selected", theme.BRAND_DARK)])

        # スピンボックスの矢印・スクロールバーも基調に合わせる。
        style.configure("Vertical.TScrollbar", background=theme.BG,
                        troughcolor=theme.BG, bordercolor=theme.BG,
                        arrowcolor=theme.TEXT_MUTED)

    def _build_ui(self) -> None:
        """ウィンドウとすべての UI コンポーネントを構築する。"""
        self.root.title("my-task-manager")
        _set_window_icon(self.root)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        try:
            self.root.configure(bg=theme.BG)
            self.root.minsize(900, 540)
        except Exception:
            logging.debug("ルートウィンドウの背景設定に失敗しました。")

        self._apply_style()

        frame = ttk.Frame(self.root, padding=18, style="App.TFrame")
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
        header = ttk.Frame(frame, style="Header.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        header.columnconfigure(2, weight=1)

        ttk.Label(header, text="📅", style="Date.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.date_var, style="Date.TLabel").grid(
            row=0, column=1, sticky="w", padx=(6, 0))

        rng = ttk.Frame(header, style="Header.TFrame")
        rng.grid(row=0, column=2, sticky="e", padx=(16, 12))
        ttk.Label(rng, text="🌅 起床").pack(side=tk.LEFT)
        self.wake_menu = ttk.Spinbox(rng, textvariable=self.wake_var, from_=0, to=23,
                                     width=3, format="%02.0f", command=self._on_range_change)
        self.wake_menu.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(rng, text="🌙 就寝").pack(side=tk.LEFT)
        self.sleep_menu = ttk.Spinbox(rng, textvariable=self.sleep_var, from_=0, to=23,
                                      width=3, format="%02.0f", command=self._on_range_change)
        self.sleep_menu.pack(side=tk.LEFT, padx=(4, 0))
        self.wake_menu.bind("<FocusOut>", lambda _e: self._on_range_change())
        self.sleep_menu.bind("<FocusOut>", lambda _e: self._on_range_change())

        ttk.Label(header, textvariable=self.stats_var, style="Stats.TLabel").grid(
            row=0, column=3, sticky="e")

    def _build_input(self, frame: ttk.Frame) -> None:
        """タスク追加フォーム（row 1）。白いカードにまとめる。"""
        card = ttk.Frame(frame, style="Card.TFrame", padding=12)
        card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)

        self.title_entry = ttk.Entry(card, textvariable=self.title_var, font=theme.FONT_BASE)
        self.title_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10), ipady=3)

        opts = ttk.Frame(card, style="Card.TFrame")
        opts.grid(row=0, column=1)
        ttk.Label(opts, text="⏰ 開始", style="Card.TLabel").pack(side=tk.LEFT)
        self.hour_menu = ttk.Spinbox(opts, textvariable=self.hour_var, from_=HOUR_MIN, to=HOUR_MAX,
                                     wrap=True, width=3, format="%02.0f")
        self.hour_menu.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(opts, text=":", style="Card.TLabel").pack(side=tk.LEFT)
        self.minute_menu = ttk.Spinbox(opts, textvariable=self.minute_var, from_=MINUTE_MIN,
                                       to=MINUTE_MAX, wrap=True, width=3, format="%02.0f")
        self.minute_menu.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(opts, text="⏳ 所要(分)", style="Card.TLabel").pack(side=tk.LEFT)
        self.dur_menu = ttk.Spinbox(opts, textvariable=self.dur_var, from_=MIN_DURATION,
                                    to=MAX_DURATION, increment=5, width=5)
        self.dur_menu.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(opts, text="🔁 繰り返し", style="Card.TLabel").pack(side=tk.LEFT)
        self.recur_menu = ttk.Combobox(opts, textvariable=self.recur_var, state="readonly",
                                       width=5, values=[RECUR_LABELS[u] for u in RECUR_UNITS])
        self.recur_menu.pack(side=tk.LEFT, padx=(4, 0))
        self.interval_menu = ttk.Spinbox(opts, textvariable=self.interval_var, from_=MIN_INTERVAL,
                                         to=MAX_INTERVAL, width=3)
        self.interval_menu.pack(side=tk.LEFT, padx=(4, 14))

        ttk.Button(opts, text="＋ タイムラインへ", style="Primary.TButton",
                   command=self.add_to_timeline).pack(side=tk.LEFT)
        ttk.Button(opts, text="あとでへ", command=self.add_to_backlog).pack(side=tk.LEFT, padx=(8, 0))

    def _build_timeline(self, frame: ttk.Frame) -> None:
        """今日のカレンダー（デイビュー）（row 2, col 0）。

        縦の時間軸（起床〜就寝）に、タスクを所要時間ぶんの高さを持つ
        色付きブロックとして配置する。Google カレンダー / TimeTree の
        1 日表示に近い見た目で、空き時間は「ブロックが無い余白」として
        そのまま見える。
        """
        panel = ttk.Frame(frame, style="Card.TFrame", padding=14)
        panel.grid(row=2, column=0, sticky="nsew", padx=(0, 9))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text="🗓 今日のカレンダー", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        body = ttk.Frame(panel, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        # timeline_tree という名前は後方互換のため踏襲（実体はカレンダー Canvas）。
        self.timeline_tree = tk.Canvas(body, bg=theme.CARD, highlightthickness=0,
                                       height=12 * theme.HOUR_HEIGHT)
        self.timeline_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.timeline_tree.yview)
        self.timeline_tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        # クリックでブロック選択、リサイズで実幅を反映して再描画する。
        self.timeline_tree.bind("<Button-1>", self._on_timeline_click)
        self.timeline_tree.bind("<Configure>", self._on_timeline_resize)

        actions = ttk.Frame(panel, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Button(actions, text="✓ 完了", style="Primary.TButton",
                   command=self.complete_timeline_selected).pack(side=tk.LEFT)
        ttk.Button(actions, text="あとでへ", command=self.move_to_backlog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="🗑 削除", command=self.delete_timeline_selected).pack(side=tk.LEFT, padx=(8, 0))

    def _build_backlog(self, frame: ttk.Frame) -> None:
        """あとでやるリスト（row 2, col 1）。白いカードにまとめる。"""
        panel = ttk.Frame(frame, style="Card.TFrame", padding=14)
        panel.grid(row=2, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Label(panel, text="🌙 あとでやる", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        body = ttk.Frame(panel, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.backlog_tree = ttk.Treeview(body, columns=("title", "dur", "info"),
                                         show="headings", height=12)
        self.backlog_tree.heading("title", text="タスク")
        self.backlog_tree.heading("dur", text="所要")
        self.backlog_tree.heading("info", text="繰り返し")
        self.backlog_tree.column("title", width=170, anchor="w")
        self.backlog_tree.column("dur", width=70, anchor="center", stretch=False)
        self.backlog_tree.column("info", width=80, anchor="center", stretch=False)
        self.backlog_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.backlog_tree.yview)
        self.backlog_tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        self._configure_row_tags(self.backlog_tree)

        actions = ttk.Frame(panel, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Button(actions, text="＋ 予定に追加", style="Primary.TButton",
                   command=self.schedule_backlog_selected).pack(side=tk.LEFT)
        ttk.Button(actions, text="✓ 完了", command=self.complete_backlog_selected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="🗑 削除", command=self.delete_backlog_selected).pack(side=tk.LEFT, padx=(8, 0))

    def _configure_row_tags(self, tree: ttk.Treeview) -> None:
        """バックログ（Treeview）の行タグ（提案色・カテゴリ色）を設定する。

        タイムラインはカレンダー Canvas へ移行したため、状態色（done/now/past）の
        スタイリングは `_block_colors` 側に集約している。ここではバックログが使う
        「提案」と「カテゴリ色」のタグだけを設定する。
        """
        tree.tag_configure("suggest", foreground=theme.SUGGEST_FG, font=theme.FONT_BOLD)
        # TimeTree 風のカテゴリ色（タスクごとに安定した彩り）。
        for i, (bg, fg) in enumerate(theme.CATEGORY_COLORS):
            tree.tag_configure(f"cat{i}", background=bg, foreground=fg)

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

    def _timeline_selected(self) -> Task | None:
        """カレンダーで選択中のタスクを返す（未選択なら None）。"""
        return self._find(self._tl_selected)

    def complete_timeline_selected(self) -> None:
        task = self._timeline_selected()
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
        self._delete(self._timeline_selected())

    def delete_backlog_selected(self) -> None:
        self._delete(self._selected(self.backlog_tree))

    def _delete(self, task: Task | None) -> None:
        if task is None:
            self.status_var.set("削除するタスクを選択してください。")
            return
        self._cancel_job(task.id)
        self.tasks = [t for t in self.tasks if t.id != task.id]
        if self._tl_selected == task.id:  # 消えたタスクの選択を残さない
            self._tl_selected = None
        self._persist_tasks()
        self._refresh()
        self.status_var.set(f"「{task.title}」を削除しました。")

    def move_to_backlog(self) -> None:
        """タイムライン上のタスクを「あとでやる」へ戻す（時間を外す）。"""
        task = self._timeline_selected()
        if task is None:
            self.status_var.set("移動するタスクを選択してください。")
            return
        self._cancel_job(task.id)
        task.due = ""
        # バックログへ移すとカレンダーから消えるため、タイムラインの選択を解除する。
        # （残すと完了/削除ボタンが見えないバックログ項目を操作してしまう。）
        self._tl_selected = None
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
        """カレンダー（デイビュー）を Canvas に描画する。

        起床〜就寝を縦軸に取り、1 時間ごとの罫線と時刻ラベルを引き、
        各タスクを「開始位置 y・所要時間ぶんの高さ」を持つ色付きブロックで
        配置する。重なるタスクは横に並べて見えなくならないようにする。
        """
        cv = self.timeline_tree
        cv.delete("all")
        # クリック判定用（x0,y0,x1,y1, チェックボックス領域, task.id, 完了フラグ）。
        self._tl_blocks = []
        wake_min, sleep_min = self._wake_min(), self._sleep_min()
        now = datetime.datetime.now()
        # 論理的な 1 日の範囲（夜間レンジの翌日跨ぎ込み）は build_day_timeline と
        # 同じ day_bounds を使い、窓の算出元を一本化する（ズレ防止）。
        day_start, day_end = day_bounds(today, wake_min, sleep_min)

        rows = build_day_timeline(self.tasks, today, wake_min, sleep_min, now)
        task_rows = [r for r in rows if r.kind == ROW_TASK and r.task is not None]

        # 起床前/就寝後に始まる・終わるタスクも必ず可視範囲に含める。
        # （設定変更や時間外スケジュールでブロックが見切れて操作不能になるのを防ぐ。）
        window_start = min([day_start] + [r.start for r in task_rows])
        window_end = max([day_end] + [r.end for r in task_rows])

        scale = theme.HOUR_HEIGHT / 60.0

        def y_of(dt: datetime.datetime) -> float:
            return theme.CAL_PAD_TOP + (dt - window_start).total_seconds() / 60.0 * scale

        width = max(self._tl_width, theme.CAL_GUTTER + 80)
        self._draw_time_grid(cv, window_start, window_end, width, y_of)

        lanes = self._assign_lanes(task_rows)
        lane_count = (max(lanes.values()) + 1) if lanes else 1
        area_left = theme.CAL_GUTTER
        area_w = width - area_left - theme.CAL_BLOCK_GAP
        lane_w = area_w / lane_count
        for row in task_rows:
            self._draw_task_block(cv, row, y_of, lanes[row.task.id], lane_w, area_left)

        self._draw_now_line(cv, now, window_start, window_end, y_of, width)

        # scrollregion はブロック描画後に確定する。最低高を確保した短いタスクが
        # window_end を超えて伸びても、下端とチェックボックスが見切れないようにする。
        content_bottom = max([y_of(window_end)] + [b[3] for b in self._tl_blocks])
        height = int(content_bottom + theme.CAL_PAD_TOP)
        cv.configure(scrollregion=(0, 0, width, height))

    def _draw_time_grid(self, cv, window_start, window_end, width, y_of) -> None:
        """正時（と 30 分）の罫線・時刻ラベルを、実際の時刻に合わせて描く。

        起床が 07:30 のような非正時でも、罫線は実際の時計の正時に引き、
        ラベルもその時刻（HH:00）を表示するため、ブロック位置とズレない。
        """
        first_hour = window_start.replace(minute=0, second=0, microsecond=0)
        if first_hour < window_start:
            first_hour += datetime.timedelta(hours=1)
        t = first_hour
        while t <= window_end:
            y = y_of(t)
            cv.create_line(theme.CAL_GUTTER, y, width, y, fill=theme.GRID_LINE)
            cv.create_text(theme.CAL_GUTTER - 8, y, anchor="e", text=f"{t.hour:02d}:00",
                           fill=theme.GRID_LABEL, font=theme.FONT_SMALL)
            half = t + datetime.timedelta(minutes=30)
            if half < window_end:
                cv.create_line(theme.CAL_GUTTER, y_of(half), width, y_of(half),
                               fill=theme.GRID_LINE_HALF)
            t += datetime.timedelta(hours=1)

    @staticmethod
    def _assign_lanes(task_rows) -> dict[str, int]:
        """重なり合うタスクを横レーンに割り当てる（task.id → レーン番号）。"""
        lanes: dict[str, int] = {}
        active: list[tuple] = []  # (end_datetime, lane)
        for row in sorted(task_rows, key=lambda r: r.start):
            used = {lane for end, lane in active if end > row.start}
            active = [(end, lane) for end, lane in active if end > row.start]
            lane = 0
            while lane in used:
                lane += 1
            lanes[row.task.id] = lane
            active.append((row.end, lane))
        return lanes

    def _draw_task_block(self, cv, row, y_of, lane: int, lane_w: float,
                         area_left: float) -> None:
        """1 件のタスクを Any Planner 風のカードとして描く。

        左端にカテゴリ色のストライプ、その右に丸いチェックボックス（完了は ✓ 入り）、
        さらに右にタイトルと時刻を置く。クリック判定用の座標を記録する。
        """
        task = row.task
        y0 = y_of(row.start)
        y1 = max(y_of(row.end), y0 + 24)  # 最低限の高さを確保
        x0 = area_left + lane * lane_w + theme.CAL_BLOCK_GAP
        x1 = area_left + (lane + 1) * lane_w - theme.CAL_BLOCK_GAP

        fill, accent, text_color = self._block_colors(task, row.status)
        is_selected = task.id == self._tl_selected
        outline = theme.BRAND_DARK if is_selected else theme.BORDER
        ow = 3 if is_selected else 1
        # カード本体（角丸）とカテゴリ色の左ストライプ。
        self._rounded_rect(cv, x0, y0, x1, y1, r=theme.CAL_RADIUS, fill=fill,
                           outline=outline, width=ow, tags=("task", task.id))
        self._rounded_rect(cv, x0 + 3, y0 + 4, x0 + 3 + theme.CAL_STRIPE_W, y1 - 4,
                           r=theme.CAL_STRIPE_W / 2, fill=accent, outline=accent,
                           tags=("task", task.id))

        tall = (y1 - y0) >= theme.CAL_MIN_TEXT_HEIGHT
        done = row.status == STATUS_DONE
        # 丸いチェックボックス（未完了＝枠線のみ / 完了＝塗り＋✓）。
        cb_cx = x0 + theme.CAL_STRIPE_W + 16
        cb_cy = (y0 + 16) if tall else (y0 + y1) / 2
        r = theme.CAL_CHECK_R
        cb_box = (cb_cx - r - 3, cb_cy - r - 3, cb_cx + r + 3, cb_cy + r + 3)
        if done:
            cv.create_oval(cb_cx - r, cb_cy - r, cb_cx + r, cb_cy + r,
                           fill=accent, outline=accent, tags=("task", task.id))
            cv.create_text(cb_cx, cb_cy, text="✓", fill=theme.CARD,
                           font=theme.FONT_SMALL, tags=("task", task.id))
        else:
            cv.create_oval(cb_cx - r, cb_cy - r, cb_cx + r, cb_cy + r,
                           outline=accent, width=2, tags=("task", task.id))

        self._tl_blocks.append((x0, y0, x1, y1, cb_box, task.id, done))

        # タイトル・時刻（チェックボックスの右）。繰り返しタスクは 🔁 を添える
        # （旧タイムラインの「繰り返し」列で示していた情報をカードでも残す）。
        title = task.title + ("  🔁" if task.recur_unit != RECUR_NONE else "")
        text_x = cb_cx + r + 8
        text_w = max(int(x1 - text_x - 8), 10)
        if tall:
            cv.create_text(text_x, y0 + 8, anchor="nw", text=title, fill=text_color,
                           font=theme.FONT_BOLD, width=text_w, tags=("task", task.id))
            cv.create_text(text_x, y1 - 7, anchor="sw",
                           text=f"{row.start:%H:%M}–{row.end:%H:%M}", fill=text_color,
                           font=theme.FONT_SMALL, tags=("task", task.id))
        else:
            cv.create_text(text_x, (y0 + y1) / 2, anchor="w", text=title,
                           fill=text_color, font=theme.FONT_BASE, width=text_w,
                           tags=("task", task.id))

    @staticmethod
    def _block_colors(task: Task, status: str) -> tuple[str, str, str]:
        """ブロックの (塗り, アクセント=ストライプ/枠, 文字) 色を状態に応じて返す。"""
        if status == STATUS_DONE:
            return theme.DONE_BG, theme.DONE_FG, theme.DONE_FG
        if status == STATUS_PAST:
            return theme.PAST_BG, theme.PAST_FG, theme.PAST_FG
        bg, fg = theme.category_color(task.id)
        if status == STATUS_NOW:
            # 進行中はブランド色の淡いカードで強調（Any Planner 風の控えめな塗り）。
            return theme.BRAND_SOFT, theme.BRAND, theme.BRAND_DARK
        return bg, fg, fg

    @staticmethod
    def _rounded_rect(cv, x0, y0, x1, y1, r, **kw):
        """角丸長方形を polygon (smooth) で描く。"""
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return cv.create_polygon(pts, smooth=True, **kw)

    def _draw_now_line(self, cv, now, window_start, window_end, y_of, width) -> None:
        """現在時刻を示す横線（now ライン）を描く。"""
        if now < window_start or now > window_end:
            return
        y = y_of(now)
        cv.create_line(theme.CAL_GUTTER, y, width, y, fill=theme.NOW_LINE, width=2)
        cv.create_oval(theme.CAL_GUTTER - 4, y - 4, theme.CAL_GUTTER + 4, y + 4,
                       fill=theme.NOW_LINE, outline=theme.NOW_LINE)

    def _on_timeline_resize(self, event) -> None:
        """Canvas の幅変更に合わせてカレンダーだけを再描画する。

        幅に依存するのはカレンダーのジオメトリのみなので、繰り越し・永続化・
        通知再スケジュールを伴う `_refresh()` は呼ばない（リサイズのたびに
        ディスク書き込みや通知ジョブの張り直しが走るのを避ける）。ウィンドウ
        破棄中の `<Configure>` で Canvas が無効でも落ちないよう握りつぶす。"""
        if abs(event.width - self._tl_width) > 2:
            self._tl_width = event.width
            try:
                self._render_timeline(self._planner_today())
            except Exception:
                logging.debug("リサイズ時のカレンダー再描画に失敗しました。")

    def _on_timeline_click(self, event) -> None:
        """カレンダーのクリックを処理する。

        チェックボックスを押せば完了（Any Planner 風）、ブロック本体を押せば選択
        （再クリックで解除）、余白を押せば選択解除する。重なりは最前面を優先。
        """
        cv = self.timeline_tree
        x, y = cv.canvasx(event.x), cv.canvasy(event.y)
        for x0, y0, x1, y1, cb_box, task_id, done in reversed(self._tl_blocks):
            cbx0, cby0, cbx1, cby1 = cb_box
            in_checkbox = cbx0 <= x <= cbx1 and cby0 <= y <= cby1
            in_block = x0 <= x <= x1 and y0 <= y <= y1
            # チェックボックスは（狭いレーンでカード幅をはみ出しても）独立に判定する。
            if not in_checkbox and not in_block:
                continue
            if not done and in_checkbox:
                self._tl_selected = task_id
                self._complete(self._find(task_id))  # 内部で再描画される
            else:
                self._tl_selected = None if task_id == self._tl_selected else task_id
                self._refresh()
            return
        if self._tl_selected is not None:  # 余白クリックで選択解除
            self._tl_selected = None
            self._refresh()

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
            if task.id in suggestions:
                title, tag = f"✨ {task.title}", "suggest"
            else:
                title, tag = f"{theme.category_dot(task.id)} {task.title}", \
                    f"cat{theme.category_index(task.id)}"
            tree.insert("", tk.END, iid=task.id,
                        values=(title, format_duration(task.duration_min),
                                self._recur_text(task)),
                        tags=(tag,))

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
        messagebox.showinfo("my-task-manager", f"⏰ {task.title}")
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
