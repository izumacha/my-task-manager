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
    parts = text.split(":")  # "HH:MM" を ":" で分割してリストにする
    if len(parts) != 2:  # 分割結果が 2 要素でない場合（形式が不正）
        raise ValueError(f"時刻の形式が不正です: {text!r}")  # 不正な形式として例外を発生させる
    h, m = int(parts[0]), int(parts[1])  # 時と分をそれぞれ整数に変換する
    if not (0 <= h <= 23 and 0 <= m <= 59):  # 時が 0〜23、分が 0〜59 の範囲外なら
        raise ValueError(f"時刻が範囲外です: {text!r}")  # 範囲外として例外を発生させる
    return h * 60 + m  # 時を分に換算して分の値を返す


def min_to_hhmm(minutes: int) -> str:
    """分値を "HH:MM" に整形する（24 時以降は剰余で丸める）。"""
    minutes %= 24 * 60  # 24 時間を超えた場合は剰余を取って 0〜1439 の範囲に収める
    return f"{minutes // 60:02d}:{minutes % 60:02d}"  # 時と分を 2 桁ゼロ埋めで "HH:MM" 形式に整形して返す


def format_duration(minutes: int) -> str:
    """分を「1時間30分」のような日本語表記に整形する。"""
    minutes = max(0, int(minutes))  # 負の値や非整数を 0 以上の整数に正規化する
    h, m = divmod(minutes, 60)  # 分を時間と分に分割する（例: 90 → 1時間30分）
    if h and m:  # 時間も分も両方ある場合
        return f"{h}時間{m}分"  # 「X時間Y分」の形式で返す
    if h:  # 時間だけある場合（分が 0）
        return f"{h}時間"  # 「X時間」の形式で返す
    return f"{m}分"  # 分だけの場合は「X分」の形式で返す


@dataclass
class TimelineRow:
    """タイムライン 1 行分の情報。

    kind が ROW_TASK ならタスク行（task / status が有効）、
    ROW_FREE なら空き時間行（minutes が有効）。start/end は両者共通。
    minutes は表示用に分へ切り捨てた値で、1 分未満の空き行では 0 になる
    （正確な長さが必要な集計は start/end から秒単位で計算する）。
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
    start = datetime.datetime.combine(date, datetime.time(wake_min // 60, wake_min % 60))  # 起床時刻を date と組み合わせて datetime に変換する
    end = datetime.datetime.combine(date, datetime.time(sleep_min // 60, sleep_min % 60))  # 就寝時刻を date と組み合わせて datetime に変換する
    if sleep_min <= wake_min:  # 就寝時刻が起床時刻以前の場合（深夜まわり）
        end += datetime.timedelta(days=1)  # 就寝を翌日として扱うために 1 日加算する
    return start, end  # 起床日時と就寝日時のタプルを返す


def planner_day(moment: datetime.datetime, wake_min: int, sleep_min: int) -> datetime.date:
    """その瞬間が属する「プランナー日」を返す。

    就寝が翌日にまわる夜間レンジ（例: 起床 09:00 / 就寝 01:00）では、
    深夜 0:00〜就寝境界の間はまだ「前日」のプランナー日として扱う。
    こうすることで、日付が変わっても就寝境界まで同じ 1 日の予定を表示できる。
    """
    if sleep_min <= wake_min and (moment.hour * 60 + moment.minute) < sleep_min:  # 夜間レンジかつ就寝境界より前の深夜の場合
        return moment.date() - datetime.timedelta(days=1)  # 前日のプランナー日として返す
    return moment.date()  # 通常は暦の日付をそのままプランナー日として返す


def _task_status(task: Task, now: datetime.datetime) -> str:
    """タスク行の状態を判定する。"""
    if task.completed:  # タスクが完了済みの場合
        return STATUS_DONE  # 「完了」ステータスを返す
    if task.due_dt <= now < task.end_dt:  # 現在時刻が開始〜終了の間にある場合
        return STATUS_NOW  # 「現在進行中」ステータスを返す
    if task.end_dt <= now:  # 終了時刻を過ぎているが未完了の場合
        return STATUS_PAST  # 「期限超過」ステータスを返す
    return STATUS_UPCOMING  # どれにも該当しない場合は「これから」ステータスを返す


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
    now = now or datetime.datetime.now()  # now が None の場合は現在時刻を使う
    day_start, day_end = day_bounds(date, wake_min, sleep_min)  # 指定日の起床・就寝日時を取得する
    prev_date = date - datetime.timedelta(days=1)  # 前のプランナー日（日をまたいで続くタスクの判定用）
    # そのプランナー日に属するタスクに加え、前のプランナー日に属していても
    # 終了が当日の起床時刻より後（＝日をまたいで今も続いている）タスクを含める。
    # これを含めないと、日またぎタスクが翌日の空き時間計算から完全に抜け落ち、
    # 実際は占有中の時間帯を「空き」として過大計上してしまう。
    todays = sorted(
        (t for t in tasks
         if t.is_scheduled and (
             planner_day(t.due_dt, wake_min, sleep_min) == date  # このプランナー日に属するタスク
             or (planner_day(t.due_dt, wake_min, sleep_min) == prev_date  # 前のプランナー日に属し
                 and t.end_dt > day_start)  # かつ終了が当日の起床時刻より後（日をまたいで継続中）のタスク
         )),
        key=lambda t: t.due_dt,  # 開始日時の昇順に並べる
    )
    # 表示窓は基本 [day_start, day_end) だが、起床前・就寝後など範囲外に
    # 始まる/終わるタスクが消えないよう、実タスクを内包するよう窓を広げる。
    start_bound = min([day_start, *(t.due_dt for t in todays)])  # タスクの最早開始か起床日時の小さい方を表示開始とする
    end_bound = max([day_end, *(t.end_dt for t in todays)])  # タスクの最終終了か就寝日時の大きい方を表示終了とする

    rows: list[TimelineRow] = []  # タイムライン行を蓄積するリストを初期化する
    cursor = start_bound  # 行の追加位置（現在位置）を表示開始日時で初期化する
    for task in todays:  # 開始順に並んだ各タスクについてループする
        start, end = task.due_dt, task.end_dt  # タスクの開始・終了日時を取り出す
        _append_free_row(rows, cursor, start)  # cursor からタスク開始までの空き時間行を（あれば）追加する
        rows.append(TimelineRow(ROW_TASK, start, end, task.duration_min,
                                task=task, status=_task_status(task, now)))  # タスク行を追加する
        if end > cursor:  # タスクの終了がカーソルより後ろの場合
            cursor = end  # カーソルをタスクの終了日時に進める

    # 最後のタスク以降、就寝（または最終タスク終了）までの空き時間行を（あれば）追加する
    _append_free_row(rows, cursor, end_bound)
    return rows  # 完成したタイムライン行のリストを返す


def _append_free_row(
    rows: list[TimelineRow], start: datetime.datetime, end: datetime.datetime
) -> None:
    """[start, end) に正の長さがあれば ROW_FREE 行を rows に追加する。

    1 分未満の隙間でも行を必ず出す（minutes は表示用に切り捨てるので 0 になり得る）。
    行を省略すると free_minutes_today がその秒数を合計できず過少計上になるため。
    """
    gap_seconds = (end - start).total_seconds()  # 空き時間の長さ（秒）を計算する
    if gap_seconds > 0:  # 空き時間が 1 秒でもある場合
        rows.append(TimelineRow(ROW_FREE, start, end, int(gap_seconds // 60)))  # 空き時間行を追加する


def free_minutes_today(
    tasks: list[Task],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
    now: datetime.datetime | None = None,
) -> int:
    """指定日の空き時間（分）の合計を返す。

    窓拡張で生じた起床前・就寝後の時間は「空き」に数えない（設定された
    起床〜就寝の窓 [day_start, day_end] に重なる部分のみを対象とする）。
    """
    day_start, day_end = day_bounds(date, wake_min, sleep_min)  # 起床・就寝日時を取得する
    total_seconds = 0.0  # 空き時間の合計「秒数」を 0 で初期化する（分に丸める前に秒で貯める）
    for row in build_day_timeline(tasks, date, wake_min, sleep_min, now):  # 各タイムライン行についてループする
        if row.kind != ROW_FREE:  # 空き時間行でない場合（タスク行）
            continue  # スキップして次の行へ進む
        s, e = max(row.start, day_start), min(row.end, day_end)  # 空き時間を起床〜就寝の窓にクリップする
        if e > s:  # クリップ後にまだ正の長さがある場合
            # 行ごとに分へ丸めず「秒」を貯める。行単位で切り捨てると各行の端数が
            # 独立に捨てられ、秒付き時刻（繰り返しタスクが生成する due）で合計が
            # 実際より数分少なくなるため、丸めは最後にまとめて 1 回だけ行う。
            total_seconds += (e - s).total_seconds()  # その長さ（秒）を合計に加算する
    return int(total_seconds // 60)  # 合計秒を最後に分へ切り捨てて返す（起床〜就寝の窓内の空き時間合計分数）


def max_free_slot(
    tasks: list[Task],
    date: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
    now: datetime.datetime | None = None,
) -> int:
    """指定日で最も長い「これから使える連続した」空き時間（分）を返す。

    タスクの提案は合計ではなくこの最大連続枠を基準にすべき。合計に空きが
    あっても個々の枠に収まらないタスクは置けないため。さらに、既に経過した
    時間と窓外（起床前・就寝後）は除外する。すなわち各空き行を
    [max(now, 起床), 就寝] にクリップして測る。
    """
    now = now or datetime.datetime.now()  # now が None の場合は現在時刻を使う
    day_start, day_end = day_bounds(date, wake_min, sleep_min)  # 起床・就寝日時を取得する
    lower = max(day_start, now)  # 起床日時と現在時刻の遅い方を下限として使う（過去を除外）
    best = 0  # 最大連続空き時間を 0 分で初期化する
    for row in build_day_timeline(tasks, date, wake_min, sleep_min, now):  # 各タイムライン行についてループする
        if row.kind != ROW_FREE:  # 空き時間行でない場合（タスク行）
            continue  # スキップして次の行へ進む
        s, e = max(row.start, lower), min(row.end, day_end)  # 空き時間を「現在以降かつ就寝前」にクリップする
        if e > s:  # クリップ後にまだ正の長さがある場合
            best = max(best, int((e - s).total_seconds() // 60))  # 最大連続空き時間を更新する
    return best  # 最大連続空き時間（分）を返す


def backlog_tasks(tasks: list[Task]) -> list[Task]:
    """「あとでやる」（未スケジュール・未完了）タスクを返す。"""
    return [t for t in tasks if not t.is_scheduled and not t.completed]  # スケジュールなし・未完了のタスクだけ抽出して返す


def suggest_for_free_time(tasks: list[Task], minutes: int) -> list[Task]:
    """与えられた空き時間（分）に収まる「あとでやる」タスクを提案する。

    所要時間が大きい順（空き時間を有効に使える順）に並べて返す。
    """
    fits = [t for t in backlog_tasks(tasks) if t.duration_min <= minutes]  # あとでやるタスクのうち所要時間が空き時間以内のものを抽出する
    return sorted(fits, key=lambda t: t.duration_min, reverse=True)  # 所要時間の降順（長い順）に並べて返す


def _calendar_dt(
    planner_date: datetime.date, t: datetime.time, wake_min: int, sleep_min: int
) -> datetime.datetime:
    """プランナー日 planner_date 上の時刻 t に対応する暦上の日時を返す。

    夜間レンジ（就寝が翌日）の早朝部分（0:00〜就寝境界）は翌暦日になる。
    """
    if sleep_min <= wake_min and (t.hour * 60 + t.minute) < sleep_min:  # 夜間レンジかつ就寝境界前の深夜の場合
        return datetime.datetime.combine(planner_date + datetime.timedelta(days=1), t)  # 翌暦日の同時刻を返す
    return datetime.datetime.combine(planner_date, t)  # 通常はプランナー日の同時刻を返す


def carry_over_overdue(
    tasks: list[Task],
    today: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
) -> int:
    """未完了のまま前のプランナー日になったタスクを当日へ繰り越す。

    判定・配置はプランナー日基準で行う（夜間レンジでは就寝境界まで前日扱い）。
    時刻はそのまま、プランナー日だけ today に更新する。タスクを破壊的に
    書き換え、繰り越した件数を返す。

    Returns:
        繰り越したタスク数。
    """
    moved = 0  # 繰り越したタスク数のカウンタを 0 で初期化する
    for task in tasks:  # 全タスクに対してループする
        if not task.is_scheduled or task.completed:  # スケジュールなしまたは完了済みのタスクは繰り越し対象外
            continue  # スキップして次のタスクへ進む
        start = task.due_dt  # タスクの開始日時を取り出す
        if planner_day(start, wake_min, sleep_min) < today:  # タスクのプランナー日が今日より前の場合
            new_start = _calendar_dt(today, start.time(), wake_min, sleep_min)  # 今日の同時刻を暦日として計算する
            task.due = new_start.strftime(ISO_FMT)  # タスクの開始日時を今日に書き換える
            moved += 1  # 繰り越し件数を 1 増やす
    return moved  # 繰り越したタスク数を返す


def prune_old_completed(
    tasks: list[Task],
    today: datetime.date,
    wake_min: int = DEFAULT_WAKE_MIN,
    sleep_min: int = DEFAULT_SLEEP_MIN,
) -> list[Task]:
    """前日以前に完了したタスクを取り除いた新しいリストを返す。

    今日完了したタスクはタイムライン上に「済」として残す。完了日時が
    不明・不正なものは安全側で残す。

    「いつのタスクか」は暦日ではなく planner_day（起床〜就寝で区切る一日）で
    判定する。stats / carry_over_overdue と同じ区切りに揃えることで、夜更かし
    レンジ（例: 就寝 01:00）で 00:30 に完了したタスクが、統計上は前日扱いなのに
    タイムラインには今日として残り続ける食い違いを防ぐ。
    """
    kept: list[Task] = []  # 残すタスクを蓄積するリストを初期化する
    for task in tasks:  # 全タスクに対してループする
        if task.completed and task.completed_at:  # 完了済みかつ完了日時がある場合
            try:
                done = datetime.datetime.strptime(task.completed_at, ISO_FMT)  # 完了日時の文字列を datetime に変換する
            except (TypeError, ValueError):  # 変換に失敗した場合（不正な形式）
                kept.append(task)  # 安全側で残す（破棄しない）
                continue  # 次のタスクへ進む
            if planner_day(done, wake_min, sleep_min) < today:  # 完了の planner_day が今日より前の場合
                continue  # 過去のプランナー日に完了済み → 破棄（kept に追加しない）
        kept.append(task)  # 上記以外はリストに残す
    return kept  # 古い完了タスクを除いた新しいリストを返す
