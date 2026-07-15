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
    _coerce_duration,
    build_next_task,
    make_due,
)
from .timeline import (
    DEFAULT_SLEEP_MIN,
    DEFAULT_WAKE_MIN,
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
from .time_utils import (
    HOUR_MAX,
    HOUR_MIN,
    MINUTE_MAX,
    MINUTE_MIN,
    STATUS_IDLE,
    delay_ms_until,
)

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
        self.root = root  # tkinter のルートウィンドウを保持する
        self.tasks: list[Task] = load_tasks()  # 保存済みタスクをファイルから読み込む
        self.prefs: Prefs = load_prefs()  # 起床/就寝時刻などの設定をファイルから読み込む
        self.jobs: dict[str, str] = {}  # タスク ID → 通知ジョブ ID の対応表を空で初期化する

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
        start = self._default_start(self._get_now())  # 現在時刻を _get_now() 経由で取得して既定の開始時刻を計算する
        self.title_var = tk.StringVar()  # タスク名の入力フォームに紐づく変数
        self.hour_var = tk.StringVar(value=f"{start.hour:02d}")  # 開始時刻（時）の入力フォームに紐づく変数
        self.minute_var = tk.StringVar(value=f"{start.minute:02d}")  # 開始時刻（分）の入力フォームに紐づく変数
        self.dur_var = tk.StringVar(value=str(DEFAULT_DURATION))  # 所要時間（分）の入力フォームに紐づく変数
        self.recur_var = tk.StringVar(value=RECUR_LABELS[RECUR_NONE])  # 繰り返し単位の選択に紐づく変数（初期値は「繰り返しなし」）
        self.interval_var = tk.StringVar(value=str(MIN_INTERVAL))  # 繰り返し間隔の入力フォームに紐づく変数
        self.wake_var = tk.StringVar(value=str(self._wake_min() // 60))  # 起床時刻（時）の設定に紐づく変数
        self.sleep_var = tk.StringVar(value=str(self._sleep_min() // 60))  # 就寝時刻（時）の設定に紐づく変数
        self.date_var = tk.StringVar()  # ヘッダに表示する今日の日付文字列に紐づく変数
        self.stats_var = tk.StringVar()  # ヘッダに表示する統計文字列に紐づく変数
        self.status_var = tk.StringVar(value=STATUS_IDLE)  # 画面下部のステータスバーに紐づく変数（文言は time_utils の定数を正本とする）

        self._build_ui()  # ウィンドウとすべての UI コンポーネントを組み立てる
        self._refresh()  # タイムライン・バックログ・統計を初回描画する
        self._schedule_all()  # 起動時点で未来のタスク通知をすべてスケジュールする

    # ------------------------------------------------------------ 設定アクセス

    def _get_now(self) -> datetime.datetime:
        """現在日時を返す。テスト時はこのメソッドをモックして時刻を固定できる。"""
        return datetime.datetime.now()  # システムの現在日時を取得して返す（直接 now() を呼ばずここを経由する）

    @staticmethod
    def _default_start(now: datetime.datetime) -> datetime.datetime:
        """既定の開始時刻（次の 5 分刻み）を返す。時・日も適切に繰り上げる。"""
        add = 5 - (now.minute % 5)  # 1〜5（既に 5 分刻みなら 5 分後）
        return (now + datetime.timedelta(minutes=add)).replace(second=0, microsecond=0)

    def _planner_today(self, now: datetime.datetime | None = None) -> datetime.date:
        """現在のプランナー日を返す（夜間レンジは就寝境界まで前日扱い）。"""
        now = now or self._get_now()  # 引数で現在時刻が渡されなければ _get_now() から取得する
        return planner_day(now, self._wake_min(), self._sleep_min())

    def _wake_min(self) -> int:
        """設定の起床時刻を分で返す（不正値は既定値）。"""
        try:
            return hhmm_to_min(self.prefs.wake)  # 設定の起床時刻文字列を「分」に変換して返す
        except (ValueError, AttributeError):
            return DEFAULT_WAKE_MIN  # 変換に失敗したら timeline.py の既定起床時刻（07:00）を使う

    def _sleep_min(self) -> int:
        """設定の就寝時刻を分で返す（不正値は既定値）。"""
        try:
            return hhmm_to_min(self.prefs.sleep)  # 設定の就寝時刻文字列を「分」に変換して返す
        except (ValueError, AttributeError):
            return DEFAULT_SLEEP_MIN  # 変換に失敗したら timeline.py の既定就寝時刻（23:00）を使う

    # ------------------------------------------------------------------ UI 構築

    def _apply_style(self) -> None:
        """ttk スタイルを theme モジュールのトークンで一括設定する。

        TimeTree 風のポップな配色を実現するため、最も自由に色を変えられる
        ``clam`` テーマを基盤に選ぶ。色・フォントの実値はすべて
        :mod:`reminder.theme` 側に定義し、ここでは割り当てるだけにする。
        """
        style = ttk.Style()  # ttk のスタイルオブジェクトを取得する
        available = style.theme_names()  # この環境で使える ttk テーマ名の一覧を取得する
        # clam は配色を細かく変更できるため最優先。無い環境では既存テーマで継続。
        for base in ("clam", "alt", "default"):  # 優先順でテーマ名を試す
            if base in available:  # 使えるテーマが見つかったら適用して抜ける
                style.theme_use(base)  # 見つかったテーマを ttk に適用する
                break  # 最初に見つかったテーマで確定するのでループを終了する

        # フレーム（ページ背景 / カード）
        style.configure("App.TFrame", background=theme.BG)  # アプリ全体の背景フレームを配色トークンで設定する
        style.configure("Card.TFrame", background=theme.CARD)  # カード型フレームの背景色を設定する
        style.configure("Header.TFrame", background=theme.BG)  # ヘッダ用フレームの背景色を設定する

        # ラベル各種
        style.configure("TLabel", background=theme.BG, foreground=theme.TEXT,
                        font=theme.FONT_BASE)  # 標準ラベルの背景・文字色・フォントを設定する
        style.configure("Card.TLabel", background=theme.CARD, foreground=theme.TEXT,
                        font=theme.FONT_BASE)  # カード上のラベルの背景・文字色・フォントを設定する
        style.configure("Date.TLabel", background=theme.BG, foreground=theme.TEXT,
                        font=theme.FONT_DATE)  # 日付表示ラベルの背景・文字色・フォントを設定する
        style.configure("Heading.TLabel", background=theme.CARD, foreground=theme.TEXT,
                        font=theme.FONT_HEADING)  # セクション見出しラベルの配色・フォントを設定する
        style.configure("Status.TLabel", background=theme.BG, foreground=theme.TEXT_MUTED,
                        font=theme.FONT_SMALL)  # ステータスバーラベルの配色・フォントを設定する
        # 統計はブランド色のピル（バッジ）風に見せる。
        style.configure("Stats.TLabel", background=theme.BRAND_SOFT,
                        foreground=theme.BRAND_DARK, font=theme.FONT_STATS, padding=(12, 6))  # 統計バッジラベルの配色・フォント・内側余白を設定する

        # 入力ウィジェット（白背景・角丸風の余白）
        for name in ("TEntry", "TSpinbox", "TCombobox"):  # テキスト入力系ウィジェットをまとめて設定する
            style.configure(name, fieldbackground=theme.CARD, background=theme.CARD,
                            foreground=theme.TEXT, bordercolor=theme.BORDER,
                            arrowcolor=theme.TEXT_MUTED, padding=4)  # 入力フィールドの背景・文字色・枠線色・内側余白を設定する

        # ボタン: プライマリ（ブランド色）とセカンダリ（白地）の 2 種。
        style.configure("TButton", font=theme.FONT_BASE, padding=(12, 7),
                        relief="flat", background=theme.CARD, foreground=theme.TEXT,
                        bordercolor=theme.BORDER, focuscolor=theme.BRAND_SOFT)  # 標準ボタン（白地）の外観を設定する
        style.map("TButton",
                  background=[("active", theme.BRAND_SOFT)],
                  foreground=[("active", theme.BRAND_DARK)])  # 標準ボタンのホバー時の背景・文字色を設定する
        style.configure("Primary.TButton", font=theme.FONT_BOLD, padding=(14, 8),
                        relief="flat", background=theme.BRAND,
                        foreground=theme.TEXT_ON_BRAND, focuscolor=theme.BRAND)  # プライマリボタン（ブランド色）の外観を設定する
        style.map("Primary.TButton",
                  background=[("active", theme.BRAND_DARK), ("pressed", theme.BRAND_DARK)],
                  foreground=[("active", theme.TEXT_ON_BRAND)])  # プライマリボタンのホバー・押下時の色を設定する

        # Treeview（タイムライン / バックログ）
        style.configure("Treeview", background=theme.CARD, fieldbackground=theme.CARD,
                        foreground=theme.TEXT, rowheight=theme.ROW_HEIGHT,
                        borderwidth=0, font=theme.FONT_BASE)  # Treeview の背景・行高さ・フォントを設定する
        style.configure("Treeview.Heading", background=theme.BG, foreground=theme.TEXT_MUTED,
                        relief="flat", font=theme.FONT_SMALL, padding=(8, 6))  # Treeview の列見出しの配色・フォントを設定する
        style.map("Treeview.Heading", background=[("active", theme.BORDER)])  # Treeview 列見出しのホバー時の背景色を設定する
        style.map("Treeview",
                  background=[("selected", theme.BRAND_SOFT)],
                  foreground=[("selected", theme.BRAND_DARK)])  # Treeview の選択行の背景・文字色を設定する

        # スピンボックスの矢印・スクロールバーも基調に合わせる。
        style.configure("Vertical.TScrollbar", background=theme.BG,
                        troughcolor=theme.BG, bordercolor=theme.BG,
                        arrowcolor=theme.TEXT_MUTED)  # 縦スクロールバーの配色を設定する

    def _build_ui(self) -> None:
        """ウィンドウとすべての UI コンポーネントを構築する。"""
        self.root.title("my-task-manager")  # ウィンドウのタイトルバーにアプリ名を設定する
        _set_window_icon(self.root)  # ウィンドウのアイコン画像を設定する
        self.root.columnconfigure(0, weight=1)  # 列 0 をウィンドウ幅に合わせて伸縮させる
        self.root.rowconfigure(0, weight=1)  # 行 0 をウィンドウ高さに合わせて伸縮させる
        try:
            self.root.configure(bg=theme.BG)  # ウィンドウ全体の背景色をテーマ色に設定する
            self.root.minsize(900, 540)  # ウィンドウを縮小できる最小サイズを設定する
        except Exception as exc:  # 起動を止めないため広めに捕捉する（fail-safe）
            # 原因調査できるよう例外の内容も一緒にデバッグログへ残す
            logging.debug("ルートウィンドウの背景設定に失敗しました: %s", exc)

        self._apply_style()  # ttk のスタイル（配色・フォント）を一括で設定する

        frame = ttk.Frame(self.root, padding=18, style="App.TFrame")  # アプリ全体を包む外側フレームを作る
        frame.grid(sticky="nsew")  # フレームをウィンドウの四辺いっぱいに配置する
        frame.columnconfigure(0, weight=3, uniform="cols")  # 左列（タイムライン）を比率 3 で伸縮させる
        frame.columnconfigure(1, weight=2, uniform="cols")  # 右列（バックログ）を比率 2 で伸縮させる
        frame.rowconfigure(2, weight=1)  # タイムライン/バックログの行だけをウィンドウ高さに合わせて伸縮させる

        self._build_header(frame)   # row 0  # ヘッダ（日付・起床/就寝・統計）を組み立てる
        self._build_input(frame)    # row 1  # タスク追加フォームを組み立てる
        self._build_timeline(frame)  # row 2 col 0  # カレンダー（デイビュー）を組み立てる
        self._build_backlog(frame)  # row 2 col 1  # あとでやるリストを組み立てる
        self._build_status(frame)   # row 3  # ステータスバーを組み立てる

        self.root.bind("<Return>", lambda _e: self.add_to_timeline())  # Enter キーでタスクをタイムラインに追加できるようにする
        self.title_entry.focus_set()  # 起動直後にタスク名入力欄にフォーカスを当てる

    def _build_header(self, frame: ttk.Frame) -> None:
        """日付・起床/就寝・統計を表示するヘッダ（row 0）。"""
        header = ttk.Frame(frame, style="Header.TFrame")  # ヘッダ全体を包むフレームを作る
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))  # ヘッダを 2 列幅で横いっぱいに配置する
        header.columnconfigure(2, weight=1)  # 起床/就寝スピンボックスを右寄せにするため列 2 を伸縮させる

        ttk.Label(header, text="📅", style="Date.TLabel").grid(row=0, column=0, sticky="w")  # カレンダーアイコンを左端に配置する
        ttk.Label(header, textvariable=self.date_var, style="Date.TLabel").grid(
            row=0, column=1, sticky="w", padx=(6, 0))  # 今日の日付ラベルをアイコンの右に配置する

        rng = ttk.Frame(header, style="Header.TFrame")  # 起床/就寝スピンボックスをまとめるフレームを作る
        rng.grid(row=0, column=2, sticky="e", padx=(16, 12))  # 起床/就寝フレームをヘッダ右側に配置する
        ttk.Label(rng, text="🌅 起床").pack(side=tk.LEFT)  # 起床ラベルを左詰めで配置する
        self.wake_menu = ttk.Spinbox(rng, textvariable=self.wake_var, from_=0, to=23,
                                     width=3, format="%02.0f", command=self._on_range_change)  # 起床時刻を 0〜23 時で選ぶスピンボックスを作る
        self.wake_menu.pack(side=tk.LEFT, padx=(4, 12))  # 起床スピンボックスをラベルの右に配置する
        ttk.Label(rng, text="🌙 就寝").pack(side=tk.LEFT)  # 就寝ラベルを左詰めで配置する
        self.sleep_menu = ttk.Spinbox(rng, textvariable=self.sleep_var, from_=0, to=23,
                                      width=3, format="%02.0f", command=self._on_range_change)  # 就寝時刻を 0〜23 時で選ぶスピンボックスを作る
        self.sleep_menu.pack(side=tk.LEFT, padx=(4, 0))  # 就寝スピンボックスをラベルの右に配置する
        self.wake_menu.bind("<FocusOut>", lambda _e: self._on_range_change())  # 起床スピンボックスからフォーカスが外れたとき設定を反映する
        self.sleep_menu.bind("<FocusOut>", lambda _e: self._on_range_change())  # 就寝スピンボックスからフォーカスが外れたとき設定を反映する

        ttk.Label(header, textvariable=self.stats_var, style="Stats.TLabel").grid(
            row=0, column=3, sticky="e")  # 統計バッジをヘッダ右端に配置する

    def _build_input(self, frame: ttk.Frame) -> None:
        """タスク追加フォーム（row 1）。白いカードにまとめる。"""
        card = ttk.Frame(frame, style="Card.TFrame", padding=12)  # タスク追加フォームを包むカードフレームを作る
        card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))  # カードを 2 列幅で横いっぱいに配置する
        card.columnconfigure(0, weight=1)  # タスク名入力欄が残りの幅を占めるよう列 0 を伸縮させる

        self.title_entry = ttk.Entry(card, textvariable=self.title_var, font=theme.FONT_BASE)  # タスク名のテキスト入力欄を作る
        self.title_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10), ipady=3)  # タスク名入力欄を横いっぱいに配置する

        opts = ttk.Frame(card, style="Card.TFrame")  # 時刻・所要時間・繰り返し・ボタンをまとめるフレームを作る
        opts.grid(row=0, column=1)  # オプションフレームをタスク名入力欄の右に配置する
        ttk.Label(opts, text="⏰ 開始", style="Card.TLabel").pack(side=tk.LEFT)  # 「開始」ラベルを左詰めで配置する
        self.hour_menu = ttk.Spinbox(opts, textvariable=self.hour_var, from_=HOUR_MIN, to=HOUR_MAX,
                                     wrap=True, width=3, format="%02.0f")  # 開始時刻の「時」スピンボックスを作る
        self.hour_menu.pack(side=tk.LEFT, padx=(4, 0))  # 「時」スピンボックスをラベルの右に配置する
        ttk.Label(opts, text=":", style="Card.TLabel").pack(side=tk.LEFT)  # 時と分の区切り「:」を配置する
        self.minute_menu = ttk.Spinbox(opts, textvariable=self.minute_var, from_=MINUTE_MIN,
                                       to=MINUTE_MAX, wrap=True, width=3, format="%02.0f")  # 開始時刻の「分」スピンボックスを作る
        self.minute_menu.pack(side=tk.LEFT, padx=(0, 12))  # 「分」スピンボックスを「:」の右に配置する
        ttk.Label(opts, text="⏳ 所要(分)", style="Card.TLabel").pack(side=tk.LEFT)  # 「所要(分)」ラベルを左詰めで配置する
        self.dur_menu = ttk.Spinbox(opts, textvariable=self.dur_var, from_=MIN_DURATION,
                                    to=MAX_DURATION, increment=5, width=5)  # 所要時間（分）のスピンボックスを 5 分刻みで作る
        self.dur_menu.pack(side=tk.LEFT, padx=(4, 12))  # 所要時間スピンボックスをラベルの右に配置する
        ttk.Label(opts, text="🔁 繰り返し", style="Card.TLabel").pack(side=tk.LEFT)  # 「繰り返し」ラベルを左詰めで配置する
        self.recur_menu = ttk.Combobox(opts, textvariable=self.recur_var, state="readonly",
                                       width=5, values=[RECUR_LABELS[u] for u in RECUR_UNITS])  # 繰り返し単位を選ぶドロップダウンを作る
        self.recur_menu.pack(side=tk.LEFT, padx=(4, 0))  # 繰り返しドロップダウンをラベルの右に配置する
        self.interval_menu = ttk.Spinbox(opts, textvariable=self.interval_var, from_=MIN_INTERVAL,
                                         to=MAX_INTERVAL, width=3)  # 繰り返し間隔（何回ごと）のスピンボックスを作る
        self.interval_menu.pack(side=tk.LEFT, padx=(4, 14))  # 繰り返し間隔スピンボックスをドロップダウンの右に配置する

        ttk.Button(opts, text="＋ タイムラインへ", style="Primary.TButton",
                   command=self.add_to_timeline).pack(side=tk.LEFT)  # タイムラインへ追加するプライマリボタンを配置する
        ttk.Button(opts, text="あとでへ", command=self.add_to_backlog).pack(side=tk.LEFT, padx=(8, 0))  # あとでやるリストへ追加するボタンを配置する

    def _build_timeline(self, frame: ttk.Frame) -> None:
        """今日のカレンダー（デイビュー）（row 2, col 0）。

        縦の時間軸（起床〜就寝）に、タスクを所要時間ぶんの高さを持つ
        色付きブロックとして配置する。Google カレンダー / TimeTree の
        1 日表示に近い見た目で、空き時間は「ブロックが無い余白」として
        そのまま見える。
        """
        panel = ttk.Frame(frame, style="Card.TFrame", padding=14)  # カレンダーカード全体を包むフレームを作る
        panel.grid(row=2, column=0, sticky="nsew", padx=(0, 9))  # カレンダーカードを左列に配置する
        panel.columnconfigure(0, weight=1)  # カレンダー本体が横いっぱいに広がるよう列 0 を伸縮させる
        panel.rowconfigure(1, weight=1)  # Canvas 行だけをウィンドウ高さに合わせて伸縮させる

        ttk.Label(panel, text="🗓 今日のカレンダー", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10))  # 「今日のカレンダー」見出しを左上に配置する

        body = ttk.Frame(panel, style="Card.TFrame")  # Canvas とスクロールバーをまとめるフレームを作る
        body.grid(row=1, column=0, sticky="nsew")  # Canvas フレームをカード内に伸縮配置する
        body.columnconfigure(0, weight=1)  # Canvas が横いっぱいに広がるよう列 0 を伸縮させる
        body.rowconfigure(0, weight=1)  # Canvas が縦いっぱいに広がるよう行 0 を伸縮させる
        # timeline_tree という名前は後方互換のため踏襲（実体はカレンダー Canvas）。
        self.timeline_tree = tk.Canvas(body, bg=theme.CARD, highlightthickness=0,
                                       height=12 * theme.HOUR_HEIGHT)  # カレンダーを描く Canvas を作る（初期高さは 12 時間分）
        self.timeline_tree.grid(row=0, column=0, sticky="nsew")  # Canvas を四辺いっぱいに配置する
        sb = ttk.Scrollbar(body, orient="vertical", command=self.timeline_tree.yview)  # Canvas の縦スクロールバーを作る
        self.timeline_tree.configure(yscrollcommand=sb.set)  # スクロールバーと Canvas を連動させる
        sb.grid(row=0, column=1, sticky="ns")  # スクロールバーを Canvas の右端に配置する
        # クリックでブロック選択、リサイズで実幅を反映して再描画する。
        self.timeline_tree.bind("<Button-1>", self._on_timeline_click)  # 左クリックイベントをブロック選択ハンドラに紐づける
        self.timeline_tree.bind("<Configure>", self._on_timeline_resize)  # サイズ変更イベントをリサイズハンドラに紐づける

        actions = ttk.Frame(panel, style="Card.TFrame")  # カレンダー操作ボタンをまとめるフレームを作る
        actions.grid(row=2, column=0, sticky="w", pady=(12, 0))  # 操作ボタンをカレンダー下に左詰めで配置する
        ttk.Button(actions, text="✓ 完了", style="Primary.TButton",
                   command=self.complete_timeline_selected).pack(side=tk.LEFT)  # 選択タスクを完了するプライマリボタンを配置する
        ttk.Button(actions, text="あとでへ", command=self.move_to_backlog).pack(side=tk.LEFT, padx=(8, 0))  # 選択タスクをバックログへ移動するボタンを配置する
        ttk.Button(actions, text="🗑 削除", command=self.delete_timeline_selected).pack(side=tk.LEFT, padx=(8, 0))  # 選択タスクを削除するボタンを配置する

    def _build_backlog(self, frame: ttk.Frame) -> None:
        """あとでやるリスト（row 2, col 1）。白いカードにまとめる。"""
        panel = ttk.Frame(frame, style="Card.TFrame", padding=14)  # あとでやるカード全体を包むフレームを作る
        panel.grid(row=2, column=1, sticky="nsew")  # グリッドの右下エリアに上下左右いっぱい配置する
        panel.columnconfigure(0, weight=1)  # 列 0 を横幅に合わせて伸縮させる
        panel.rowconfigure(1, weight=1)  # 行 1（リスト行）を縦幅に合わせて伸縮させる

        ttk.Label(panel, text="🌙 あとでやる", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10))  # 「あとでやる」セクションの見出しラベルを配置する

        body = ttk.Frame(panel, style="Card.TFrame")  # リスト部分を包む内部フレームを作る
        body.grid(row=1, column=0, sticky="nsew")  # 見出しの下に上下左右いっぱい配置する
        body.columnconfigure(0, weight=1)  # リスト列を横幅に合わせて伸縮させる
        body.rowconfigure(0, weight=1)  # リスト行を縦幅に合わせて伸縮させる
        self.backlog_tree = ttk.Treeview(body, columns=("title", "dur", "info"),
                                         show="headings", height=12)  # あとでやるタスクを表示する Treeview を作る
        self.backlog_tree.heading("title", text="タスク")  # タスク名列の見出しを設定する
        self.backlog_tree.heading("dur", text="所要")  # 所要時間列の見出しを設定する
        self.backlog_tree.heading("info", text="繰り返し")  # 繰り返し設定列の見出しを設定する
        self.backlog_tree.column("title", width=170, anchor="w")  # タスク名列の幅と文字揃えを設定する
        self.backlog_tree.column("dur", width=70, anchor="center", stretch=False)  # 所要時間列の幅を固定して中央揃えにする
        self.backlog_tree.column("info", width=80, anchor="center", stretch=False)  # 繰り返し列の幅を固定して中央揃えにする
        self.backlog_tree.grid(row=0, column=0, sticky="nsew")  # Treeview を body フレームに上下左右いっぱい配置する
        sb = ttk.Scrollbar(body, orient="vertical", command=self.backlog_tree.yview)  # Treeview の縦スクロールバーを作る
        self.backlog_tree.configure(yscrollcommand=sb.set)  # スクロールバーと Treeview を連動させる
        sb.grid(row=0, column=1, sticky="ns")  # スクロールバーを Treeview の右に上下いっぱい配置する
        self._configure_row_tags(self.backlog_tree)  # 提案色・カテゴリ色のタグを Treeview に設定する

        actions = ttk.Frame(panel, style="Card.TFrame")  # 操作ボタンを並べるフレームを作る
        actions.grid(row=2, column=0, sticky="w", pady=(12, 0))  # ボタン行をリストの下に左詰めで配置する
        ttk.Button(actions, text="＋ 予定に追加", style="Primary.TButton",
                   command=self.schedule_backlog_selected).pack(side=tk.LEFT)  # バックログタスクをタイムラインに追加するプライマリボタンを配置する
        ttk.Button(actions, text="✓ 完了", command=self.complete_backlog_selected).pack(side=tk.LEFT, padx=(8, 0))  # バックログタスクを完了するボタンを右隣に配置する
        ttk.Button(actions, text="🗑 削除", command=self.delete_backlog_selected).pack(side=tk.LEFT, padx=(8, 0))  # バックログタスクを削除するボタンを右隣に配置する

    def _configure_row_tags(self, tree: ttk.Treeview) -> None:
        """バックログ（Treeview）の行タグ（提案色・カテゴリ色）を設定する。

        タイムラインはカレンダー Canvas へ移行したため、状態色（done/now/past）の
        スタイリングは `_block_colors` 側に集約している。ここではバックログが使う
        「提案」と「カテゴリ色」のタグだけを設定する。
        """
        tree.tag_configure("suggest", foreground=theme.SUGGEST_FG, font=theme.FONT_BOLD)  # 提案タスクの行を太字・強調色で表示するタグを登録する
        # TimeTree 風のカテゴリ色（タスクごとに安定した彩り）。
        for i, (bg, fg) in enumerate(theme.CATEGORY_COLORS):  # 全カテゴリ色ペアを番号付きでループする
            tree.tag_configure(f"cat{i}", background=bg, foreground=fg)  # カテゴリ番号ごとに背景色と文字色のタグを登録する

    def _build_status(self, frame: ttk.Frame) -> None:
        """ステータスラベル（row 3）。"""
        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))  # ステータスメッセージを表示するラベルを画面下部に配置する

    # ------------------------------------------------------------ 入力正規化

    @staticmethod
    def _coerce_int(raw: str, min_value: int, max_value: int, default: int | None = None) -> int:
        """文字列を整数に変換し、[min_value, max_value] にクランプして返す。

        default を指定すると、非数値のときに最小値ではなくその値へフォールバックする
        （例: 起床/就寝の「時」は 0 ではなく保存済みの値に戻したい）。
        """
        try:
            value = int(raw)  # 文字列を整数に変換する（失敗したら except 節へ）
        except (TypeError, ValueError):
            if default is None:  # フォールバック先の指定がなければ
                return min_value  # 従来どおり最小値を返す（非数値のフォールバック）
            value = default  # 指定されたフォールバック値を採用する（この後の行で範囲内にクランプする）
        return max(min_value, min(max_value, value))  # 最小・最大の範囲に収めて返す

    def _input_start_time(self) -> datetime.time:
        """入力欄の開始時刻を正規化して time として返す。"""
        h = self._coerce_int(self.hour_var.get(), HOUR_MIN, HOUR_MAX)  # 入力欄の「時」を取得して有効範囲にクランプする
        m = self._coerce_int(self.minute_var.get(), MINUTE_MIN, MINUTE_MAX)  # 入力欄の「分」を取得して有効範囲にクランプする
        self.hour_var.set(f"{h:02d}")  # クランプ後の「時」を 2 桁ゼロ埋めで入力欄に書き戻す
        self.minute_var.set(f"{m:02d}")  # クランプ後の「分」を 2 桁ゼロ埋めで入力欄に書き戻す
        return datetime.time(h, m)  # 正規化した時・分を time オブジェクトとして返す

    def _input_duration(self) -> int:
        """入力欄の所要時間（分）を正規化して返す。"""
        # Task.__post_init__ と同じ _coerce_duration を使い、非数値は DEFAULT_DURATION に
        # フォールバックする（task.py が唯一の参照元。CLAUDE.md §6 の定数一元管理）。
        d = _coerce_duration(self.dur_var.get())  # 入力欄の所要時間を取得して正規化する
        self.dur_var.set(str(d))  # クランプ後の値を入力欄に書き戻す
        return d  # 正規化した所要時間（分）を返す

    def _input_recurrence(self) -> tuple[str, int]:
        """入力欄の繰り返し単位・間隔を返す。"""
        interval = self._coerce_int(self.interval_var.get(), MIN_INTERVAL, MAX_INTERVAL)  # 入力欄の繰り返し間隔を取得して有効範囲にクランプする
        self.interval_var.set(str(interval))  # クランプ後の間隔を入力欄に書き戻す
        return unit_for_label(self.recur_var.get()), interval  # 繰り返し単位の内部コードと間隔のタプルを返す

    def _on_range_change(self) -> None:
        """起床/就寝の変更を設定へ反映し、タイムラインを再描画する。

        スピンボックスは「時」単位のため、時が変わっていないときは設定へ
        書き戻さない（settings.json に "07:30" のような分単位の値があっても、
        フォーカス移動だけで "07:00" に切り捨てられるのを防ぐ）。
        """
        stored_wake_hour = self._wake_min() // 60  # 保存済みの起床時刻から「時」を取り出す（比較とフォールバックに使う）
        stored_sleep_hour = self._sleep_min() // 60  # 保存済みの就寝時刻から「時」を取り出す（比較とフォールバックに使う）
        # 非数値・空欄のときは 0 ではなく保存済みの「時」へフォールバックする
        # （空欄のままタブ移動しただけで "00:00" が書き込まれて設定が壊れるのを防ぐ）
        wake = self._coerce_int(self.wake_var.get(), 0, 23, default=stored_wake_hour)  # 起床時刻（時）の入力値を 0〜23 にクランプして取得する
        sleep = self._coerce_int(self.sleep_var.get(), 0, 23, default=stored_sleep_hour)  # 就寝時刻（時）の入力値を 0〜23 にクランプして取得する
        self.wake_var.set(f"{wake:02d}")  # クランプ後の起床時刻を 2 桁で入力欄に書き戻す
        self.sleep_var.set(f"{sleep:02d}")  # クランプ後の就寝時刻を 2 桁で入力欄に書き戻す
        # 注: 保存値が不正な文字列でも _wake_min()/_sleep_min() が既定値に読み替えるため実害はなく、
        # 分単位の値の保全を優先して「時が変わらない限り書き戻さない」仕様とする（自動修復はしない）。
        if wake != stored_wake_hour:  # 起床の「時」が保存済みの値の「時」から実際に変わったときだけ
            self.prefs.wake = min_to_hhmm(wake * 60)  # 起床時刻を「分」→「HH:MM」文字列に変換して設定に保存する
        if sleep != stored_sleep_hour:  # 就寝の「時」が保存済みの値の「時」から実際に変わったときだけ
            self.prefs.sleep = min_to_hhmm(sleep * 60)  # 就寝時刻を「分」→「HH:MM」文字列に変換して設定に保存する
        save_prefs(self.prefs)  # 更新した設定をファイルに永続化する
        self._refresh()  # タイムライン・バックログ・統計を再描画する

    # ------------------------------------------------------------ タスク追加

    def add_to_timeline(self) -> None:
        """入力内容で当日のタイムラインにタスクを追加する。"""
        title = self.title_var.get().strip()  # 入力欄のタスク名を取得して前後の空白を除去する
        if not title:  # タスク名が空のときは
            messagebox.showwarning("入力エラー", "タスク名を入力してください。")  # 警告ダイアログを表示してユーザーに入力を促す
            return  # タスクを追加せずに処理を終える
        start = self._input_start_time()  # 入力欄の開始時刻を正規化して取得する
        duration = self._input_duration()  # 入力欄の所要時間を正規化して取得する
        recur_unit, interval = self._input_recurrence()  # 入力欄の繰り返し単位と間隔を正規化して取得する
        # 過去時刻が選ばれた場合は翌日へ繰り上げ、通知が必ず効くようにする
        # （前方プランナーとしての挙動。深夜 0:00 を選んだ場合も翌日になる）。
        due = make_due(start, now=self._get_now(), roll_if_past=True)  # 過去時刻なら翌日に繰り上げた due 文字列を生成する（基準時刻も _get_now() に一元化する）
        task = Task(title=title, due=due, duration_min=duration,
                    recur_unit=recur_unit, recur_interval=interval)  # 新しい Task オブジェクトを作る
        self.tasks.append(task)  # 作ったタスクをタスクリストに追加する
        self._persist_tasks()  # 更新したタスクリストをファイルに保存する
        self._refresh()  # タイムラインと統計を再描画する
        self._schedule_task(task)  # 開始時刻に通知するジョブを登録する
        self.title_var.set("")  # タスク名入力欄を空にリセットする
        self.status_var.set(f"「{title}」を {start.hour:02d}:{start.minute:02d} に追加しました。")  # 追加完了メッセージをステータスバーに表示する
        logging.info("タイムラインに追加: %s（%s, %d分）", title, due, duration)  # 追加内容をログに記録する

    def add_to_backlog(self) -> None:
        """入力内容で「あとでやる」にタスクを追加する（時間は割り当てない）。"""
        title = self.title_var.get().strip()  # 入力欄のタスク名を取得して前後の空白を除去する
        if not title:  # タスク名が空のときは
            messagebox.showwarning("入力エラー", "タスク名を入力してください。")  # 警告ダイアログを表示する
            return  # タスクを追加せずに処理を終える
        duration = self._input_duration()  # 入力欄の所要時間を正規化して取得する
        recur_unit, interval = self._input_recurrence()  # 入力欄の繰り返し設定を取得する
        task = Task(title=title, due="", duration_min=duration,
                    recur_unit=recur_unit, recur_interval=interval)  # 開始時刻なし（due=""）の Task オブジェクトを作る
        self.tasks.append(task)  # 作ったタスクをタスクリストに追加する
        self._persist_tasks()  # 更新したタスクリストをファイルに保存する
        self._refresh()  # バックログリストと統計を再描画する
        self.title_var.set("")  # タスク名入力欄を空にリセットする
        self.status_var.set(f"「{title}」を「あとでやる」に追加しました。")  # 追加完了メッセージをステータスバーに表示する
        logging.info("あとでやるに追加: %s（%d分）", title, duration)  # 追加内容をログに記録する

    # ------------------------------------------------------------ タスク操作

    def _find(self, task_id: str | None) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)  # task_id が一致するタスクをリストから探して返す（見つからなければ None）

    def _selected(self, tree) -> Task | None:
        selection = tree.selection()  # Treeview で現在選択されている行の ID 一覧を取得する
        if not selection:  # 何も選択されていなければ
            return None  # None を返して呼び出し元に知らせる
        return self._find(selection[0])  # 最初の選択行の ID でタスクを検索して返す

    def _timeline_selected(self) -> Task | None:
        """カレンダーで選択中のタスクを返す（未選択なら None）。"""
        return self._find(self._tl_selected)

    def complete_timeline_selected(self) -> None:
        """カレンダー（タイムライン）で選択中のタスクを完了にする。"""
        task = self._timeline_selected()  # カレンダーで選択中のタスクを取得する
        self._complete(task)  # タスクを完了処理に渡す

    def complete_backlog_selected(self) -> None:
        """あとでやるリストで選択中のタスクを完了にする。"""
        task = self._selected(self.backlog_tree)  # バックログリストで選択中のタスクを取得する
        self._complete(task)  # タスクを完了処理に渡す

    def _complete(self, task: Task | None) -> None:
        """タスクを完了し、統計に記録する。繰り返しなら次回を再登録する。"""
        if task is None:  # 選択中タスクがなければ
            self.status_var.set("完了するタスクを選択してください。")  # 選択を促すメッセージをステータスバーに表示する
            return  # 何もせずに処理を終える
        if task.completed:  # 既に完了済みのタスクなら
            # 完了済みタスクはタイムラインに残るため、再度押下されても
            # 統計の二重計上や繰り返しタスクの重複生成を防ぐ。
            self.status_var.set(f"「{task.title}」は既に完了しています。")  # 既に完了済みである旨をステータスバーに表示する
            return  # 二重完了を防いで処理を終える
        completed_at = self._get_now()  # 完了した瞬間の時刻を _get_now() 経由で取得する
        self._cancel_job(task.id)  # このタスクの保留中通知ジョブをキャンセルする
        task.completed = True  # タスクの完了フラグを立てる
        task.completed_at = completed_at.strftime(ISO_FMT)  # 完了日時を ISO 形式の文字列で記録する

        # 統計（完了履歴）に記録
        self.prefs.completions.append(task.completed_at)  # 完了日時を設定の履歴リストに追加する
        save_prefs(self.prefs)  # 更新した設定（完了履歴）をファイルに保存する

        next_task = build_next_task(task, completed_at)  # 繰り返しタスクの場合は次回タスクを生成する（繰り返しなしなら None）
        if next_task is not None:  # 次回タスクが生成されたなら
            self.tasks.append(next_task)  # 次回タスクをタスクリストに追加する
            self._persist_tasks()  # 更新したタスクリストをファイルに保存する
            self._refresh()  # タイムライン・バックログ・統計を再描画する
            self._schedule_task(next_task)  # 次回タスクの通知をスケジュールする（backlog は _schedule_task 側で対象外）
            if next_task.is_scheduled:  # 次回がタイムラインに予定される（スケジュール済み）場合
                self.status_var.set(
                    f"「{task.title}」を完了。次回は {next_task.due_dt:%m/%d %H:%M} に再設定しました。")  # 次回日時を含む完了メッセージをステータスバーに表示する
            else:  # 次回が「あとでやる」(backlog) として再生成された場合（開始時刻を持たない）
                self.status_var.set(
                    f"「{task.title}」を完了。次回を「あとでやる」に再登録しました。")  # backlog へ再登録した旨をステータスバーに表示する
            logging.info("繰り返しタスクを再登録: %s → %s", task.title, next_task.due)  # 再登録内容をログに記録する
        else:  # 繰り返しなし（次回タスクがない）なら
            self._persist_tasks()  # 完了済みタスクリストをファイルに保存する
            self._refresh()  # タイムライン・バックログ・統計を再描画する
            self.status_var.set(f"「{task.title}」を完了しました。")  # 完了メッセージをステータスバーに表示する
            logging.info("タスクを完了: %s", task.title)  # 完了したタスク名をログに記録する

    def delete_timeline_selected(self) -> None:
        """カレンダー（タイムライン）で選択中のタスクを削除する。"""
        self._delete(self._timeline_selected())  # カレンダーで選択中のタスクを削除処理に渡す

    def delete_backlog_selected(self) -> None:
        """あとでやるリストで選択中のタスクを削除する。"""
        self._delete(self._selected(self.backlog_tree))  # バックログリストで選択中のタスクを削除処理に渡す

    def _delete(self, task: Task | None) -> None:
        if task is None:  # 選択中タスクがなければ
            self.status_var.set("削除するタスクを選択してください。")  # 選択を促すメッセージをステータスバーに表示する
            return  # 何もせずに処理を終える
        self._cancel_job(task.id)  # このタスクの保留中通知ジョブをキャンセルする
        self.tasks = [t for t in self.tasks if t.id != task.id]  # 削除対象以外のタスクだけを残す新しいリストを作る
        if self._tl_selected == task.id:  # 消えたタスクの選択を残さない
            self._tl_selected = None  # カレンダー上の選択状態をクリアする
        self._persist_tasks()  # 更新したタスクリストをファイルに保存する
        self._refresh()  # タイムライン・バックログ・統計を再描画する
        self.status_var.set(f"「{task.title}」を削除しました。")  # 削除完了メッセージをステータスバーに表示する

    def move_to_backlog(self) -> None:
        """タイムライン上のタスクを「あとでやる」へ戻す（時間を外す）。"""
        task = self._timeline_selected()  # カレンダーで選択中のタスクを取得する
        if task is None:  # タスクが選択されていなければ
            self.status_var.set("移動するタスクを選択してください。")  # 選択を促すメッセージをステータスバーに表示する
            return  # 何もせずに処理を終える
        if task.completed:  # 既に完了済みのタスクなら
            # 完了済みタスクの due を空にすると、タイムライン（is_scheduled 条件）からも
            # バックログ（未完了条件）からも外れて UI から完全に消えてしまうため、移動を拒否する。
            self.status_var.set("完了済みのタスクは移動できません。")  # 移動できない旨をステータスバーに表示する
            return  # due を変更せずに処理を終える
        self._cancel_job(task.id)  # このタスクの保留中通知ジョブをキャンセルする
        task.due = ""  # 開始時刻を空にしてバックログ（未予定）扱いにする
        # バックログへ移すとカレンダーから消えるため、タイムラインの選択を解除する。
        # （残すと完了/削除ボタンが見えないバックログ項目を操作してしまう。）
        self._tl_selected = None  # カレンダー上の選択状態をクリアする
        self._persist_tasks()  # 更新したタスクリストをファイルに保存する
        self._refresh()  # タイムライン・バックログ・統計を再描画する
        self.status_var.set(f"「{task.title}」を「あとでやる」へ移動しました。")  # 移動完了メッセージをステータスバーに表示する

    def schedule_backlog_selected(self) -> None:
        """「あとでやる」のタスクを、入力欄の開始時刻で当日のタイムラインへ。"""
        task = self._selected(self.backlog_tree)  # バックログリストで選択中のタスクを取得する
        if task is None:  # タスクが選択されていなければ
            self.status_var.set("予定に追加するタスクを選択してください。")  # 選択を促すメッセージをステータスバーに表示する
            return  # 何もせずに処理を終える
        start = self._input_start_time()  # 入力欄の開始時刻を正規化して取得する
        task.due = make_due(start, now=self._get_now(), roll_if_past=True)  # 過去時刻なら翌日へ繰り上げた due 文字列をタスクに設定する（基準時刻も _get_now() に一元化する）
        self._persist_tasks()  # 更新したタスクリストをファイルに保存する
        self._refresh()  # タイムライン・バックログ・統計を再描画する
        self._schedule_task(task)  # 開始時刻に通知するジョブを登録する
        self.status_var.set(f"「{task.title}」を {start.hour:02d}:{start.minute:02d} に予定しました。")  # 予定設定完了メッセージをステータスバーに表示する

    # ------------------------------------------------------------ 表示

    def _refresh(self) -> None:
        """日付・統計・タイムライン・バックログをすべて再描画する。

        アプリを開いたまま日付（プランナー日）をまたいでも、再描画のたびに
        繰り越し・整理を行うため、未完了タスクが消えることはない。
        """
        now = self._get_now()  # 再描画全体で使う現在時刻を 1 回だけ取得する（描画の途中で時刻がずれて表示が食い違わないようにする）
        today = self._planner_today(now)  # 取得した現在時刻からプランナー日（今日の日付）を計算する
        if self._roll_over(today):  # 繰り越し・整理が発生したなら
            self._persist_tasks()  # 変更後のタスクリストをファイルに保存する
            # 繰り越しでタスクの開始時刻が未来へ移ったので、通知を再登録する
            # （開きっぱなしで日跨ぎしても繰り越し分が通知されるようにする）。
            self._schedule_all()  # 全タスクの通知ジョブを再スケジュールする
        self.date_var.set(f"今日 {today.month}/{today.day}（{_WEEKDAY_JA[today.weekday()]}）")  # ヘッダの日付ラベルを今日の日付に更新する
        self._render_timeline(today, now)  # カレンダー（デイビュー）を同じ現在時刻で再描画する
        self._render_backlog(today, now)  # バックログリストを同じ現在時刻で再描画する
        self._render_stats(today, now)  # 統計ラベルを同じ現在時刻で再計算して更新する

    def _roll_over(self, today: datetime.date) -> bool:
        """プランナー日 today を基準に完了整理・繰り越しを行う。変化があれば True。"""
        before = len(self.tasks)  # 整理前のタスク数を記録して変化を検知するために保存する
        self.tasks = prune_old_completed(self.tasks, today, self._wake_min(), self._sleep_min())  # 古い完了済みタスクを planner_day 基準でリストから除去する
        moved = carry_over_overdue(self.tasks, today, self._wake_min(), self._sleep_min())  # 期限切れタスクを今日の起床後に繰り越し、移動件数を取得する
        return moved > 0 or len(self.tasks) != before  # 繰り越しまたはタスク数に変化があれば True を返す

    def _render_timeline(self, today: datetime.date,
                         now: datetime.datetime | None = None) -> None:
        """カレンダー（デイビュー）を Canvas に描画する。

        起床〜就寝を縦軸に取り、1 時間ごとの罫線と時刻ラベルを引き、
        各タスクを「開始位置 y・所要時間ぶんの高さ」を持つ色付きブロックで
        配置する。重なるタスクは横に並べて見えなくならないようにする。
        """
        cv = self.timeline_tree  # カレンダーを描く Canvas を取得する
        cv.delete("all")  # 前回の描画内容をすべて消去する
        # クリック判定用（x0,y0,x1,y1, チェックボックス領域, task.id, 完了フラグ）。
        self._tl_blocks = []  # ブロックのクリック判定情報リストをリセットする
        wake_min, sleep_min = self._wake_min(), self._sleep_min()  # 起床・就寝時刻を「分」で取得する
        now = now or self._get_now()  # 引数で現在時刻が渡されなければ _get_now() から取得する（_refresh からは同一時刻が渡される）

        rows = build_day_timeline(self.tasks, today, wake_min, sleep_min, now)  # 今日のタイムライン行データを構築する
        task_rows = [r for r in rows if r.kind == ROW_TASK and r.task is not None]  # タスク行だけを抜き出す

        # 表示ウィンドウ（起床前/就寝後に始まる・終わるタスクも可視範囲に含めた範囲）は
        # build_day_timeline 側で計算済みで、rows の先頭行の開始・末尾行の終了と必ず一致する
        # （行は時刻順に隙間なく並び、_append_free_row は正の長さの隙間だけを行にするため）。
        # ここで同じ min/max を再計算せず rows の端から読み取ることで、二重計算によるズレを防ぐ。
        window_start = rows[0].start  # 表示ウィンドウの開始時刻（先頭行の開始）
        window_end = rows[-1].end  # 表示ウィンドウの終了時刻（末尾行の終了）

        scale = theme.HOUR_HEIGHT / 60.0  # 1 分あたりのピクセル数を計算する

        def y_of(dt: datetime.datetime) -> float:
            return theme.CAL_PAD_TOP + (dt - window_start).total_seconds() / 60.0 * scale  # 日時を Canvas の y 座標（ピクセル）に変換する

        width = max(self._tl_width, theme.CAL_GUTTER + 80)  # 描画幅を Canvas の現在幅と最小幅の大きい方にする
        self._draw_time_grid(cv, window_start, window_end, width, y_of)  # 正時の罫線と時刻ラベルを描く

        # 描画時に最低高さ（theme.CAL_MIN_BLOCK_HEIGHT px）へクランプされる極端に
        # 短いタスクは、実際の終了時刻より見た目上は長く描かれる。レーン割り当てが
        # 実時間（row.end）だけで重なりを判定すると、クランプ分だけ隣のタスクと
        # 視覚的に重なってしまうため、最低高さを分に換算した「見た目の占有時間」を
        # 加味してレーンを分ける。
        min_visual_minutes = theme.CAL_MIN_BLOCK_HEIGHT / scale  # 最低高さ（px）を「分」に換算する
        lanes = self._assign_lanes(task_rows, min_visual_minutes)  # 重なるタスクをレーン（横列）に割り当てる
        lane_count = (max(lanes.values()) + 1) if lanes else 1  # 必要なレーン数を計算する（最大レーン番号 +1）
        area_left = theme.CAL_GUTTER  # タスクブロックを置くエリアの左端位置（時刻ラベル分の余白）を設定する
        area_w = width - area_left - theme.CAL_BLOCK_GAP  # タスクブロックを置けるエリアの横幅を計算する
        lane_w = area_w / lane_count  # 1 レーンあたりの幅を計算する
        for row in task_rows:  # タスク行を 1 件ずつループして
            self._draw_task_block(cv, row, y_of, lanes[row.task.id], lane_w, area_left)  # 各タスクのカードブロックを Canvas に描く

        self._draw_now_line(cv, now, window_start, window_end, y_of, width)  # 現在時刻を示す now ラインを描く

        # scrollregion はブロック描画後に確定する。最低高を確保した短いタスクが
        # window_end を超えて伸びても、下端とチェックボックスが見切れないようにする。
        content_bottom = max([y_of(window_end)] + [b[3] for b in self._tl_blocks])  # 全ブロックの下端と表示ウィンドウ終端（window_end）の遅い方をコンテンツ底辺とする
        height = int(content_bottom + theme.CAL_PAD_TOP)  # 下余白を加えた Canvas 総高さを計算する
        cv.configure(scrollregion=(0, 0, width, height))  # Canvas のスクロール可能領域を確定させる

    def _draw_time_grid(self, cv, window_start, window_end, width, y_of) -> None:
        """正時（と 30 分）の罫線・時刻ラベルを、実際の時刻に合わせて描く。

        起床が 07:30 のような非正時でも、罫線は実際の時計の正時に引き、
        ラベルもその時刻（HH:00）を表示するため、ブロック位置とズレない。
        """
        first_hour = window_start.replace(minute=0, second=0, microsecond=0)  # 表示開始時刻の「正時」（HH:00:00）を求める
        if first_hour < window_start:  # 正時が表示開始より前なら（例: 起床が 07:30 なら 07:00 は範囲外）
            first_hour += datetime.timedelta(hours=1)  # 次の正時（08:00）から罫線を引くようにする
        t = first_hour  # 最初に罫線を引く正時を設定する
        while t <= window_end:  # 表示終了時刻まで 1 時間ずつ繰り返す
            y = y_of(t)  # この正時の y 座標を計算する
            cv.create_line(theme.CAL_GUTTER, y, width, y, fill=theme.GRID_LINE)  # 正時の水平罫線を描く
            cv.create_text(theme.CAL_GUTTER - 8, y, anchor="e", text=f"{t.hour:02d}:00",
                           fill=theme.GRID_LABEL, font=theme.FONT_SMALL)  # 罫線の左に時刻ラベル（HH:00）を描く
            half = t + datetime.timedelta(minutes=30)  # 30 分後の時刻を計算する
            if half < window_end:  # 30 分線が表示範囲内なら
                cv.create_line(theme.CAL_GUTTER, y_of(half), width, y_of(half),
                               fill=theme.GRID_LINE_HALF)  # 30 分の補助線（薄い罫線）を描く
            t += datetime.timedelta(hours=1)  # 次の正時に進む

    @staticmethod
    def _assign_lanes(task_rows, min_visual_minutes: float = 0.0) -> dict[str, int]:
        """重なり合うタスクを横レーンに割り当てる（task.id → レーン番号）。

        Args:
            task_rows: レーンを割り当てるタスク行。
            min_visual_minutes: 描画上の最低高さ（theme.CAL_MIN_BLOCK_HEIGHT）を
                「分」に換算した値。実所要時間がこれより短いタスクは見た目上
                この長さぶん描画されるため、レーンの重なり判定にも同じ長さを
                加味し、隣接する短時間タスク同士が同じレーンで視覚的に
                重ならないようにする。
        """
        lanes: dict[str, int] = {}  # タスク ID → レーン番号の対応辞書を初期化する
        min_gap = datetime.timedelta(minutes=min_visual_minutes)  # 最低高さを timedelta に変換する
        active: list[tuple] = []  # (見た目の終了 datetime, lane) 現在進行中のタスクリストを初期化する
        for row in sorted(task_rows, key=lambda r: r.start):  # タスクを開始時刻の早い順に処理する
            visual_end = max(row.end, row.start + min_gap)  # 実終了時刻と最低高さ換算の終了時刻の遅い方を「見た目の終了」とする
            used = {lane for end, lane in active if end > row.start}  # このタスクと見た目上重なっているレーン番号の集合を取得する
            active = [(end, lane) for end, lane in active if end > row.start]  # 見た目上終了済みのタスクをアクティブリストから除去する
            lane = 0  # 最小のレーン番号 0 から探す
            while lane in used:  # そのレーンが使用中なら
                lane += 1  # 次のレーン番号を試す
            lanes[row.task.id] = lane  # このタスクのレーン番号を確定して記録する
            active.append((visual_end, lane))  # 見た目の終了時刻とレーン番号をアクティブリストに追加する
        return lanes  # タスク ID → レーン番号の辞書を返す

    def _draw_task_block(self, cv, row, y_of, lane: int, lane_w: float,
                         area_left: float) -> None:
        """1 件のタスクを Any Planner 風のカードとして描く。

        左端にカテゴリ色のストライプ、その右に丸いチェックボックス（完了は ✓ 入り）、
        さらに右にタイトルと時刻を置く。クリック判定用の座標を記録する。
        """
        task = row.task  # このブロックに対応するタスクオブジェクトを取得する
        y0 = y_of(row.start)  # タスク開始時刻の y 座標を計算する
        y1 = max(y_of(row.end), y0 + theme.CAL_MIN_BLOCK_HEIGHT)  # 最低限の高さを確保（レーン割り当てもこの値を共有する）
        # レーンが狭いと固定隙間 CAL_BLOCK_GAP では幅が負になり消えるため、
        # 隙間はレーン幅の一定割合までに抑えてブロック幅を必ず正に保つ。
        gap = min(theme.CAL_BLOCK_GAP, lane_w * theme.CAL_BLOCK_GAP_MAX_RATIO)  # レーン幅に応じて詰めた左右の隙間（px）
        x0 = area_left + lane * lane_w + gap  # ブロック左端の x 座標を計算する（レーン位置と隙間から）
        x1 = area_left + (lane + 1) * lane_w - gap  # ブロック右端の x 座標を計算する

        fill, accent, text_color = self._block_colors(task, row.status)  # タスクの状態（完了・進行中・過去など）に応じた配色を取得する
        is_selected = task.id == self._tl_selected  # このタスクが現在選択中かどうかを判定する
        outline = theme.BRAND_DARK if is_selected else theme.BORDER  # 選択中なら強調色、それ以外は通常の枠色を使う
        ow = 3 if is_selected else 1  # 選択中は枠線を太く（3px）、それ以外は細く（1px）する
        # カード本体（角丸）とカテゴリ色の左ストライプ。
        self._rounded_rect(cv, x0, y0, x1, y1, r=theme.CAL_RADIUS, fill=fill,
                           outline=outline, width=ow, tags=("task", task.id))  # タスクカード本体（角丸長方形）を描く
        self._rounded_rect(cv, x0 + 3, y0 + 4, x0 + 3 + theme.CAL_STRIPE_W, y1 - 4,
                           r=theme.CAL_STRIPE_W / 2, fill=accent, outline=accent,
                           tags=("task", task.id))  # カードの左端にカテゴリ色のストライプを描く

        tall = (y1 - y0) >= theme.CAL_MIN_TEXT_HEIGHT  # カードの高さがテキスト表示の最低値以上かどうかを判定する
        done = row.status == STATUS_DONE  # このタスクが完了済みかどうかを判定する
        # 丸いチェックボックス（未完了＝枠線のみ / 完了＝塗り＋✓）。
        cb_cx = x0 + theme.CAL_STRIPE_W + 16  # チェックボックスの中心 x 座標を計算する（ストライプ右隣）
        cb_cy = (y0 + 16) if tall else (y0 + y1) / 2  # 高いカードは上寄り、低いカードは縦中央にチェックボックスを置く
        r = theme.CAL_CHECK_R  # チェックボックスの半径をテーマ定数から取得する
        cb_box = (cb_cx - r - 3, cb_cy - r - 3, cb_cx + r + 3, cb_cy + r + 3)  # クリック判定用のチェックボックス領域（少し大きめ）を定義する
        if done:  # 完了済みなら
            cv.create_oval(cb_cx - r, cb_cy - r, cb_cx + r, cb_cy + r,
                           fill=accent, outline=accent, tags=("task", task.id))  # アクセント色で塗りつぶした円を描く
            cv.create_text(cb_cx, cb_cy, text="✓", fill=theme.CARD,
                           font=theme.FONT_SMALL, tags=("task", task.id))  # 円の中にチェックマーク（✓）を描く
        else:  # 未完了なら
            cv.create_oval(cb_cx - r, cb_cy - r, cb_cx + r, cb_cy + r,
                           outline=accent, width=2, tags=("task", task.id))  # 枠線だけの円（空のチェックボックス）を描く

        self._tl_blocks.append((x0, y0, x1, y1, cb_box, task.id, done))  # クリック判定情報をリストに追加する

        # タイトル・時刻（チェックボックスの右）。繰り返しタスクは 🔁 を添える
        # （旧タイムラインの「繰り返し」列で示していた情報をカードでも残す）。
        title = task.title + ("  🔁" if task.recur_unit != RECUR_NONE else "")  # 繰り返しタスクにはタイトルの後ろに 🔁 を付ける
        text_x = cb_cx + r + 8  # テキスト描画位置の x 座標（チェックボックスの右側）を計算する
        text_w = max(int(x1 - text_x - 8), 10)  # テキストの折り返し幅を計算する（最低 10px）
        if tall:  # カードが十分な高さを持つなら
            cv.create_text(text_x, y0 + 8, anchor="nw", text=title, fill=text_color,
                           font=theme.FONT_BOLD, width=text_w, tags=("task", task.id))  # タイトルをカード上部に太字で描く
            cv.create_text(text_x, y1 - 7, anchor="sw",
                           text=f"{row.start:%H:%M}–{row.end:%H:%M}", fill=text_color,
                           font=theme.FONT_SMALL, tags=("task", task.id))  # 開始〜終了時刻をカード下部に小さく描く
        else:  # カードが低くてテキスト 2 行分の高さがないなら
            cv.create_text(text_x, (y0 + y1) / 2, anchor="w", text=title,
                           fill=text_color, font=theme.FONT_BASE, width=text_w,
                           tags=("task", task.id))  # タイトルだけを縦中央に描く

    @staticmethod
    def _block_colors(task: Task, status: str) -> tuple[str, str, str]:
        """ブロックの (塗り, アクセント=ストライプ/枠, 文字) 色を状態に応じて返す。"""
        if status == STATUS_DONE:  # 完了済みなら
            return theme.DONE_BG, theme.DONE_FG, theme.DONE_FG  # 完了色（薄いグレー系）を返す
        if status == STATUS_PAST:  # 過去（未完了の期限切れ）なら
            return theme.PAST_BG, theme.PAST_FG, theme.PAST_FG  # 過去色（薄い赤系）を返す
        bg, fg = theme.category_color(task.id)  # タスク ID からカテゴリ色を取得する
        if status == STATUS_NOW:  # 進行中（現在時刻が開始〜終了の間）なら
            # 進行中はブランド色の淡いカードで強調（Any Planner 風の控えめな塗り）。
            return theme.BRAND_SOFT, theme.BRAND, theme.BRAND_DARK  # ブランド色の配色を返す
        return bg, fg, fg  # 通常（未来タスク）はカテゴリ色の配色を返す

    @staticmethod
    def _rounded_rect(cv, x0, y0, x1, y1, r, **kw):
        """角丸長方形を polygon (smooth) で描く。"""
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)  # 角丸半径を長方形のサイズに収まるよう制限する
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]  # 角丸多角形の制御点リストを作る
        return cv.create_polygon(pts, smooth=True, **kw)  # 制御点をなめらかにつないで角丸長方形を描く

    def _draw_now_line(self, cv, now, window_start, window_end, y_of, width) -> None:
        """現在時刻を示す横線（now ライン）を描く。"""
        if now < window_start or now > window_end:  # 現在時刻が表示ウィンドウ外なら
            return  # now ラインを描かずに処理を終える
        y = y_of(now)  # 現在時刻の y 座標を計算する
        cv.create_line(theme.CAL_GUTTER, y, width, y, fill=theme.NOW_LINE, width=2)  # 現在時刻を示す水平線を描く
        cv.create_oval(theme.CAL_GUTTER - 4, y - 4, theme.CAL_GUTTER + 4, y + 4,
                       fill=theme.NOW_LINE, outline=theme.NOW_LINE)  # 水平線の左端に円（ドット）を描く

    def _on_timeline_resize(self, event) -> None:
        """Canvas の幅変更に合わせてカレンダーだけを再描画する。

        幅に依存するのはカレンダーのジオメトリのみなので、繰り越し・永続化・
        通知再スケジュールを伴う `_refresh()` は呼ばない（リサイズのたびに
        ディスク書き込みや通知ジョブの張り直しが走るのを避ける）。ウィンドウ
        破棄中の `<Configure>` で Canvas が無効でも落ちないよう握りつぶす。"""
        if abs(event.width - self._tl_width) > 2:  # 幅の変化が 2px を超えたときだけ再描画する（微小変化はスキップする）
            self._tl_width = event.width  # 新しい Canvas 幅を記録する
            try:
                now = self._get_now()  # リサイズ時点の現在時刻を 1 回だけ取得する（日付と now ラインのズレを防ぐ）
                self._render_timeline(self._planner_today(now), now)  # カレンダーを新しい幅で再描画する
            except Exception as e:  # リサイズ中の例外を捕捉してクラッシュを防ぐ
                logging.debug("リサイズ時のカレンダー再描画に失敗しました: %s", e)  # 例外を握りつぶさずデバッグログに原因を残す

    def _on_timeline_click(self, event) -> None:
        """カレンダーのクリックを処理する。

        チェックボックスを押せば完了（Any Planner 風）、ブロック本体を押せば選択
        （再クリックで解除）、余白を押せば選択解除する。重なりは最前面を優先。
        """
        cv = self.timeline_tree  # クリックされたカレンダー Canvas を取得する
        x, y = cv.canvasx(event.x), cv.canvasy(event.y)  # クリック座標をスクロール込みの Canvas 座標に変換する
        for x0, y0, x1, y1, cb_box, task_id, done in reversed(self._tl_blocks):  # 最前面（後ろに描かれた）ブロックから順に当たり判定をする
            cbx0, cby0, cbx1, cby1 = cb_box  # チェックボックスの判定領域を取り出す
            in_checkbox = cbx0 <= x <= cbx1 and cby0 <= y <= cby1  # クリック位置がチェックボックス内かどうかを判定する
            in_block = x0 <= x <= x1 and y0 <= y <= y1  # クリック位置がカードブロック内かどうかを判定する
            # チェックボックスは（狭いレーンでカード幅をはみ出しても）独立に判定する。
            if not in_checkbox and not in_block:  # チェックボックスにもカードにも当たらなければ
                continue  # 次のブロックを確認する
            if not done and in_checkbox:  # 未完了タスクのチェックボックスがクリックされたなら
                self._tl_selected = task_id  # そのタスクを選択状態にする
                self._complete(self._find(task_id))  # 内部で再描画される
            else:  # カード本体（または完了済みチェックボックス）がクリックされたなら
                self._tl_selected = None if task_id == self._tl_selected else task_id  # 同じタスクを再クリックで選択解除、別タスクなら選択する
                self._refresh()  # 選択状態の変化をカレンダーに反映する
            return  # 最前面のブロックを処理したら終了する（後ろのブロックは処理しない）
        if self._tl_selected is not None:  # 余白クリックで選択解除
            self._tl_selected = None  # 選択状態をクリアする
            self._refresh()  # カレンダーを再描画して選択解除を反映する

    def _render_backlog(self, today: datetime.date,
                        now: datetime.datetime | None = None) -> None:
        tree = self.backlog_tree  # バックログの Treeview を取得する
        for item in tree.get_children():  # 現在表示されているすべての行を取得してループする
            tree.delete(item)  # 古い行を削除して一覧をクリアする
        now = now or self._get_now()  # 引数で現在時刻が渡されなければ _get_now() から取得する（時刻源を一元化する）
        # 提案は「最大連続空き枠」に収まるものに限る（合計空きでは個々の枠に
        # 置けないタスクまで提案してしまい誤解を招くため）。
        slot = max_free_slot(self.tasks, today,
                             self._wake_min(), self._sleep_min(), now)  # 今日の最大連続空き枠（分）を計算する（基準時刻も _get_now() に揃える）
        suggestions = {t.id for t in suggest_for_free_time(self.tasks, slot)}  # 空き枠に収まる提案タスクの ID セットを作る
        for task in [t for t in self.tasks if not t.is_scheduled and not t.completed]:  # 未予定かつ未完了のタスクをループする
            if task.id in suggestions:  # このタスクが提案対象なら
                title, tag = f"✨ {task.title}", "suggest"  # タイトルに ✨ を付けて提案タグを設定する
            else:  # 提案対象でないなら
                title, tag = f"{theme.category_dot(task.id)} {task.title}", \
                    f"cat{theme.category_index(task.id)}"  # カテゴリカラードットを付けてカテゴリタグを設定する
            tree.insert("", tk.END, iid=task.id,
                        values=(title, format_duration(task.duration_min),
                                self._recur_text(task)),
                        tags=(tag,))  # タスクを Treeview の末尾に追加する

    def _render_stats(self, today: datetime.date,
                      now: datetime.datetime | None = None) -> None:
        wake, sleep = self._wake_min(), self._sleep_min()  # 起床・就寝時刻を「分」で取得する
        now = now or self._get_now()  # 引数で現在時刻が渡されなければ _get_now() から取得する（時刻源を一元化する）
        done = completed_count_on(self.prefs.completions, today, wake, sleep)  # 今日の完了タスク数を集計する
        streak = current_streak(self.prefs.completions, today, wake, sleep)  # 現在の連続達成日数を計算する
        free = free_minutes_today(self.tasks, today, wake, sleep, now)  # 今日の合計空き時間（分）を計算する（基準時刻も _get_now() に揃える）
        self.stats_var.set(
            f"今日の完了 {done}件 ・ 連続 {streak}日 ・ 空き {format_duration(free)}")  # 統計文字列を組み立ててヘッダラベルに設定する

    @staticmethod
    def _recur_text(task: Task) -> str:
        """繰り返し設定を「2週ごと」のような表示文字列にする。"""
        if task.recur_unit == RECUR_NONE:  # 繰り返しなしなら
            return "—"  # ダッシュ記号を返す
        return f"{task.recur_interval}{label_for_unit(task.recur_unit)}ごと"  # 「2週ごと」のような文字列を作って返す

    # ------------------------------------------------------------ スケジュール

    def _schedule_all(self) -> None:
        """起動時に、未来に開始するすべてのタスクの通知をスケジュールする。"""
        for task in self.tasks:  # 全タスクをループする
            try:
                self._schedule_task(task)  # 各タスクの通知ジョブを登録する
            except Exception as e:  # スケジュール登録の例外を捕捉して残りのタスクの処理を続ける
                logging.warning("タスクの通知スケジュールに失敗しました: %s: %s", task.id, e)  # 失敗してもクラッシュさせず警告ログにタスクIDと原因を記録する

    def _schedule_task(self, task: Task, now: datetime.datetime | None = None) -> None:
        """開始時刻に通知するジョブを登録する（未スケジュール/過去/完了は対象外）。

        now を指定すると現在時刻の再取得を行わない。早発火の再登録時に、判定に使った
        時刻と同じ値で遅延を計算するために使う（2 回目の時刻取得までに開始時刻を
        過ぎると過去ガードで登録されず通知が永久に失われるレースを防ぐ）。
        """
        if not task.is_scheduled or task.completed:  # タイムラインに予定されていない、または既に完了済みなら
            return  # 通知登録の対象外なので処理を終える
        if now is None:  # 呼び出し元から現在時刻が渡されていなければ
            now = self._get_now()  # 通知スケジュール登録時点の現在時刻を _get_now() 経由で取得する
        if task.due_dt <= now:  # 開始時刻が既に過去なら
            return  # 通知登録しないで処理を終える
        delay_ms = delay_ms_until(now, task.due_dt)  # 現在時刻から開始時刻までの待ち時間（ミリ秒）を計算する
        self._cancel_job(task.id)  # 既存の古いジョブがあればキャンセルしてから新規登録する
        try:
            self.jobs[task.id] = self.root.after(delay_ms, lambda: self._on_task_due(task.id))  # 指定ミリ秒後に通知コールバックを呼ぶジョブを登録し ID を記録する
        except Exception:
            self.jobs.pop(task.id, None)  # ジョブ登録に失敗したら ID を辞書から除去する
            raise  # 例外を呼び出し元へ再送出する

    def _on_task_due(self, task_id: str) -> None:
        """開始時刻に呼ばれ、デスクトップ通知を出す。"""
        self.jobs.pop(task_id, None)  # 発火済みのジョブ ID を辞書から削除する
        task = self._find(task_id)  # タスク ID でタスクを検索する
        if task is None or task.completed:  # タスクが存在しないか既に完了済みなら
            return  # 通知を出さずに処理を終える
        now = self._get_now()  # 早発火の判定と再登録の遅延計算で同じ現在時刻を使うため 1 回だけ取得する
        if now < task.due_dt:  # 現在時刻が開始時刻前ならスケジュールし直す（クランプや Tcl タイマーのミリ秒切り捨てで発火が早まった場合）
            # ここで取得した now をそのまま渡して再登録する（_schedule_task 内で時刻を
            # 再取得すると、この判定との間に開始時刻を過ぎたとき過去ガードに弾かれて
            # 通知が永久に失われるレースがあるため。登録処理自体は _schedule_task に
            # 一本化し、例外時のジョブ辞書の後始末も同じ経路で行う）
            self._schedule_task(task, now=now)  # 判定に使った時刻で通知ジョブを再登録する
            return  # 今は通知を出さずに処理を終える
        play_notification_sound(self.root, task.title)  # 通知音を再生する
        messagebox.showinfo("my-task-manager", f"⏰ {task.title}")  # 開始時刻を知らせるポップアップダイアログを表示する
        self._refresh()  # タイムライン・バックログ・統計を再描画する
        self.status_var.set(f"「{task.title}」の開始時刻になりました。")  # 開始時刻になったことをステータスバーに表示する

    def _cancel_job(self, task_id: str) -> None:
        """指定タスクの保留中ジョブをキャンセルする。"""
        job_id = self.jobs.pop(task_id, None)  # ジョブ ID を辞書から取り出す（なければ None）
        if job_id is not None:  # キャンセル対象のジョブが存在するなら
            try:
                self.root.after_cancel(job_id)  # tkinter のタイマーコールバックをキャンセルする
            except Exception as e:  # after_cancel が失敗した場合（既に発火済みなど）を捕捉する
                logging.debug("ジョブのキャンセルに失敗しました: %s: %s", task_id, e)  # キャンセル失敗をデバッグログにタスクIDと原因を記録して無視する

    def _persist_tasks(self) -> None:
        """現在のタスク一覧をディスクに保存する。"""
        save_tasks(self.tasks)  # タスクリストを JSON ファイルに書き出して永続化する


# 旧名との後方互換エイリアス
ReminderApp = PlannerApp
