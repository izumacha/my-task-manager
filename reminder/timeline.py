"""1 日のタイムライン構築ロジック（GUI 非依存の純粋関数群）。

Any Planner のように「1 日のタスクを時間軸で可視化」するための計算を担う。
起床〜就寝の範囲にスケジュール済みタスクを並べ、タスク間の**空き時間**を
明示的な行として返す。未完了のまま日付をまたいだタスクの当日繰り越しや、
空き時間に着手できる「あとでやる」タスクの提案もここで扱う。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from .task import ISO_FMT, Task

# タイムライン行の種別
ROW_TASK = "task"
ROW_FREE = "free"

# タスク行の状態
STATUS_DONE = "done"        # 完了済み
STATUS_NOW = "now"          # 現在進行中（開始〜終了の間）
STATUS_PAST = "past"        # 終了時刻を過ぎたが未完了
STATUS_UPCOMING = "upcoming"  # これから

# 既定の起床・就寝時刻（分）
DEFAULT_WAKE_MIN = 7 * 60     # 07:00
DEFAULT_SLEEP_MIN = 23 * 60   # 23:00


def hhmm_to_min(text: str) -> int:
    """"HH:MM" を 0〜1439 の分値へ変換する（不正値は ValueError）。"""
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"時刻の形式が不正です: {text!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"時刻が範囲外です: {text!r}")
    return h * 60 + m


def min_to_hhmm(minutes: int) -> str:
    """分値を "HH:MM" に整形する（24 時以降は剰余で丸める）。"""
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def format_duration(minutes: int) -> str:
    """分を「1時間30分」のような日本語表記に整形する。"""
    minutes = max(0, int(minutes))
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}時間{m}分"
    if h:
        return f"{h}時間"
    return f"{m}分"


@dataclass
class TimelineRow:
    """タイムライン 1 行分の情報。

    kind が ROW_TASK ならタスク行（task / status が有効）、
    ROW_FREE なら空き時間行（minutes が有効）。start/end は両者共通。
    """

    kind: str
    start: datetime.datetime
    end: datetime.datetime
    minutes: int
    task: Task | None = None
    status: str = ""


def day_bounds(
    date: datetime.date, wake_min: int, sleep_min: int
) -> tuple[datetime.datetime, datetime.datetime]:
    """指定日の起床・就寝日時を返す。

    就寝が起床以前（深夜まわり）の場合は翌日扱いにする。
    """
    start = datetime.datetime.combine(date, datetime.time(wake_min // 60, wake_min % 60))
    end = datetime.datetime.combine(date, datetime.time(sleep_min // 60, sleep_min % 60))
    if sleep_min <= wake_min:
        end += datetime.timedelta(days=1)
    return start, end


def planner_day(moment: datetime.datetime, wake_min: int, sleep_min: int) -> datetime.date:
    """その瞬間が属する「プランナー日」を返す。

    就寝が翌日にまわる夜間レンジ（例: 起床 09:00 / 就寝 01:00）では、
    深夜 0:00〜就寝境界の間はまだ「前日」のプランナー日として扱う。
    こうすることで、日付が変わっても就寝境界まで同じ 1 日の予定を表示できる。
    """
    if sleep_min <= wake_min and (moment.hour * 60 + moment.minute) < sleep_min:
        return moment.date() - datetime.timedelta(days=1)
    return moment.date()


def _task_status(task: Task, now: datetime.datetime) -> str:
    """タスク行の状態を判定する。"""
    if task.completed:
        return STATUS_DONE
    if task.due_dt <= now < task.end_dt:
        return STATUS_NOW
    if task.end_dt <= now:
        return STATUS_PAST
    return STATUS_UPCOMING


def scheduled_on(tasks: list[Task], date: datetime.date) -> list[Task]:
    """指定日に開始するスケジュール済みタスクを開始順で返す。"""
    todays = [t for t in tasks if t.is_scheduled and t.due_dt.date() == date]
    return sorted(todays, key=lambda t: t.due_dt)


def scheduled_in_window(
    tasks: list[Task], start: datetime.datetime, end: datetime.datetime
) -> list[Task]:
    """[start, end) の窓に開始するスケジュール済みタスクを開始順で返す。

    就寝が翌日にまわる夜間レンジ（例: 起床 09:00 / 就寝 01:00）でも、窓内に
    開始するタスク（例: 翌 00:30）を取りこぼさない。
    """
    inside = [t for t in tasks if t.is_scheduled and start <= t.due_dt < end]
    return sorted(inside, key=lambda t: t.due_dt)


def build_day_timeline(
    tasks: list[Task],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
    now: datetime.datetime | None = None,
) -> list[TimelineRow]:
    """指定日のタイムライン行（タスク + 空き時間）を生成する。

    起床〜就寝の窓の中で、タスクの隙間を ROW_FREE 行として埋める。
    タスクが重なる場合は空き行を作らず順番に並べる。

    Args:
        tasks: 全タスク（スケジュール済み・未スケジュール混在で可）。
        date: 対象日。
        wake_min: 起床時刻（分）。
        sleep_min: 就寝時刻（分）。
        now: 現在日時（状態判定用）。省略時は datetime.now()。

    Returns:
        TimelineRow のリスト（時間順）。
    """
    now = now or datetime.datetime.now()
    day_start, day_end = day_bounds(date, wake_min, sleep_min)
    # そのプランナー日に属するタスクを抽出（夜間レンジの翌 00:30 等も
    # planner_day により前日側に正しく割り当てられる）。
    todays = sorted(
        (t for t in tasks
         if t.is_scheduled and planner_day(t.due_dt, wake_min, sleep_min) == date),
        key=lambda t: t.due_dt,
    )
    # 表示窓は基本 [day_start, day_end) だが、起床前・就寝後など範囲外に
    # 始まる/終わるタスクが消えないよう、実タスクを内包するよう窓を広げる。
    start_bound = min([day_start, *(t.due_dt for t in todays)])
    end_bound = max([day_end, *(t.end_dt for t in todays)])

    rows: list[TimelineRow] = []
    cursor = start_bound
    for task in todays:
        start, end = task.due_dt, task.end_dt
        gap = int((start - cursor).total_seconds() // 60)
        if gap > 0:
            rows.append(TimelineRow(ROW_FREE, cursor, start, gap))
        rows.append(TimelineRow(ROW_TASK, start, end, task.duration_min,
                                task=task, status=_task_status(task, now)))
        if end > cursor:
            cursor = end

    # 最後のタスク以降、就寝（または最終タスク終了）までの空き時間
    tail = int((end_bound - cursor).total_seconds() // 60)
    if tail > 0:
        rows.append(TimelineRow(ROW_FREE, cursor, end_bound, tail))
    return rows


def free_minutes_today(
    tasks: list[Task],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
    now: datetime.datetime | None = None,
) -> int:
    """指定日の空き時間（分）の合計を返す。"""
    return sum(
        row.minutes
        for row in build_day_timeline(tasks, date, wake_min, sleep_min, now)
        if row.kind == ROW_FREE
    )


def max_free_slot(
    tasks: list[Task],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
    now: datetime.datetime | None = None,
) -> int:
    """指定日で最も長い「連続した」空き時間（分）を返す。

    タスクの提案は合計ではなくこの最大連続枠を基準にすべき。合計に空きが
    あっても、個々の枠に収まらないタスクは実際には置けないため。
    """
    frees = [
        row.minutes
        for row in build_day_timeline(tasks, date, wake_min, sleep_min, now)
        if row.kind == ROW_FREE
    ]
    return max(frees, default=0)


def backlog_tasks(tasks: list[Task]) -> list[Task]:
    """「あとでやる」（未スケジュール・未完了）タスクを返す。"""
    return [t for t in tasks if not t.is_scheduled and not t.completed]


def suggest_for_free_time(tasks: list[Task], minutes: int) -> list[Task]:
    """与えられた空き時間（分）に収まる「あとでやる」タスクを提案する。

    所要時間が大きい順（空き時間を有効に使える順）に並べて返す。
    """
    fits = [t for t in backlog_tasks(tasks) if t.duration_min <= minutes]
    return sorted(fits, key=lambda t: t.duration_min, reverse=True)


def carry_over_overdue(tasks: list[Task], today: datetime.date) -> int:
    """未完了のまま前日以前になったスケジュール済みタスクを当日へ繰り越す。

    時刻はそのまま、日付だけ today に更新する（その日のうちに片付ける運用に合わせる）。
    タスクを破壊的に書き換え、繰り越した件数を返す。

    Returns:
        繰り越したタスク数。
    """
    moved = 0
    for task in tasks:
        if not task.is_scheduled or task.completed:
            continue
        start = task.due_dt
        if start.date() < today:
            new_start = datetime.datetime.combine(today, start.time())
            task.due = new_start.strftime(ISO_FMT)
            moved += 1
    return moved


def prune_old_completed(tasks: list[Task], today: datetime.date) -> list[Task]:
    """前日以前に完了したタスクを取り除いた新しいリストを返す。

    今日完了したタスクはタイムライン上に「済」として残す。完了日時が
    不明・不正なものは安全側で残す。
    """
    kept: list[Task] = []
    for task in tasks:
        if task.completed and task.completed_at:
            try:
                done = datetime.datetime.strptime(task.completed_at, ISO_FMT)
            except (TypeError, ValueError):
                kept.append(task)
                continue
            if done.date() < today:
                continue  # 過去日に完了済み → 破棄
        kept.append(task)
    return kept
