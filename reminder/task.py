"""タスクのデータモデルと、完了に伴う次回タスク生成ロジック。

Task は「タイトル・開始日時・所要時間・繰り返し設定・完了状態」を保持する
データクラス。GUI から独立しており、JSON への直列化（dict 化）と
復元（from_dict）に対応する。

Any Planner のように 1 日をタイムラインで可視化するため、タスクは
2 つの状態を取りうる:

* **スケジュール済み**: ``due`` に開始日時を持ち、タイムライン上に
  ``duration_min`` 分のブロックとして配置される。
* **あとでやる（バックログ）**: ``due`` が空文字。時間を割り当てず保管し、
  空き時間に着手する候補とする。
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import asdict, dataclass, field

from .recurrence import (
    MAX_INTERVAL,
    MIN_INTERVAL,
    RECUR_NONE,
    RECUR_UNITS,
    next_occurrence,
)

# 期限日時の保存・復元に使うフォーマット（秒まで保持）
ISO_FMT = "%Y-%m-%dT%H:%M:%S"

# 所要時間（分）の下限・上限と既定値
MIN_DURATION = 5
MAX_DURATION = 24 * 60
DEFAULT_DURATION = 30


def _coerce_interval(value: object) -> int:
    """繰り返し間隔を [MIN_INTERVAL, MAX_INTERVAL] の整数にクランプする。"""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return MIN_INTERVAL
    return max(MIN_INTERVAL, min(MAX_INTERVAL, n))


def _coerce_duration(value: object) -> int:
    """所要時間（分）を [MIN_DURATION, MAX_DURATION] の整数にクランプする。"""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_DURATION
    return max(MIN_DURATION, min(MAX_DURATION, n))


@dataclass
class Task:
    """プランナー上の 1 件のタスク。

    Attributes:
        title: タスク名。
        due: 開始日時の ISO 文字列（ISO_FMT 形式）。空文字なら「あとでやる」。
        duration_min: 所要時間（分）。タイムライン上のブロック長になる。
        recur_unit: 繰り返し単位（recurrence.RECUR_*）。
        recur_interval: 繰り返し間隔（1 以上）。
        completed: 完了済みかどうか。
        completed_at: 完了日時の ISO 文字列。未完了なら None。
        id: タスクを一意に識別する ID。
    """

    title: str
    due: str = ""
    duration_min: int = DEFAULT_DURATION
    recur_unit: str = RECUR_NONE
    recur_interval: int = MIN_INTERVAL
    completed: bool = False
    completed_at: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        # タスク名は非空の文字列でなければならない。非文字列・空は壊れたタスクとして
        # 例外を送出し、load_tasks() 側の個別 try-except でスキップさせる
        # （後段の "✓ " + title や通知でのクラッシュを防ぐ）。
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError(f"タスク名が不正です: {self.title!r}")
        # 不正な単位・間隔・所要時間は安全側へ正規化する
        if self.recur_unit not in RECUR_UNITS:
            self.recur_unit = RECUR_NONE
        self.recur_interval = _coerce_interval(self.recur_interval)
        self.duration_min = _coerce_duration(self.duration_min)
        # due が空文字（あとでやる）の場合は検証しない。
        # 非空の場合のみ、パースできない値は不正なタスクとして例外を送出する。
        # これにより load_tasks() 側の個別 try-except で 1 件だけスキップでき、
        # 壊れた due を持つタスクが 1 件あってもアプリの起動を妨げない。
        if self.due:
            try:
                datetime.datetime.strptime(self.due, ISO_FMT)
            except (TypeError, ValueError) as e:
                raise ValueError(f"開始日時の形式が不正です: {self.due!r}") from e

    @property
    def is_scheduled(self) -> bool:
        """タイムライン上に開始日時を持つか（False なら「あとでやる」）。"""
        return bool(self.due)

    @property
    def due_dt(self) -> datetime.datetime:
        """開始日時を datetime として返す（未スケジュール時は ValueError）。"""
        if not self.due:
            raise ValueError("未スケジュールのタスクには開始日時がありません。")
        return datetime.datetime.strptime(self.due, ISO_FMT)

    @property
    def end_dt(self) -> datetime.datetime:
        """終了日時（開始 + 所要時間）を返す（未スケジュール時は ValueError）。"""
        return self.due_dt + datetime.timedelta(minutes=self.duration_min)

    @property
    def is_recurring(self) -> bool:
        """繰り返し設定があるかどうか。"""
        return self.recur_unit != RECUR_NONE

    def to_dict(self) -> dict:
        """JSON 直列化用に dict へ変換する。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """dict から Task を復元する（未知のキーは無視）。"""
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in fields})


def make_due(
    target_time: datetime.time,
    now: datetime.datetime | None = None,
    roll_if_past: bool = True,
) -> str:
    """指定時刻から開始日時を ISO 文字列で生成する。

    Args:
        target_time: 開始にしたい時刻（時・分）。
        now: 現在日時。省略時は datetime.now()。
        roll_if_past: True なら、今日の指定時刻が既に過ぎている場合は翌日へ繰り越す。
            タイムラインに「今日のタスク」として置きたい場合は False を渡し、
            過去時刻でも当日に配置する。

    Returns:
        ISO_FMT 形式の開始日時文字列。
    """
    now = now or datetime.datetime.now()
    due = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    if roll_if_past and due <= now:
        due += datetime.timedelta(days=1)
    return due.strftime(ISO_FMT)


def build_next_task(task: Task, completed_at: datetime.datetime) -> Task | None:
    """完了したタスクから、繰り返し設定に基づく次回タスクを生成する。

    次回開始は completed_at（完了時点）を起点に算出される。これが本アプリの
    中核要件「完了した時点から日/週/月/年で繰り返す」を実現する部分である。
    所要時間・繰り返し設定は引き継ぐ。

    Args:
        task: 完了したタスク。
        completed_at: 完了日時（次回開始計算の起点）。

    Returns:
        次回分の未完了タスク。繰り返しなしの場合は None。
    """
    nxt = next_occurrence(completed_at, task.recur_unit, task.recur_interval)
    if nxt is None:
        return None
    return Task(
        title=task.title,
        due=nxt.strftime(ISO_FMT),
        duration_min=task.duration_min,
        recur_unit=task.recur_unit,
        recur_interval=task.recur_interval,
    )
