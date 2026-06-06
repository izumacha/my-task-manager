"""タスクのデータモデルと、完了に伴う次回タスク生成ロジック。

Task は「タイトル・期限・繰り返し設定・完了状態」を保持するイミュータブル寄りの
データクラス。GUI から独立しており、JSON への直列化（dict 化）と
復元（from_dict）に対応する。
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


def _coerce_interval(value: object) -> int:
    """繰り返し間隔を [MIN_INTERVAL, MAX_INTERVAL] の整数にクランプする。"""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return MIN_INTERVAL
    return max(MIN_INTERVAL, min(MAX_INTERVAL, n))


@dataclass
class Task:
    """プランナー上の 1 件のタスク。

    Attributes:
        title: タスク名。
        due: 期限日時の ISO 文字列（ISO_FMT 形式）。
        recur_unit: 繰り返し単位（recurrence.RECUR_*）。
        recur_interval: 繰り返し間隔（1 以上）。
        completed: 完了済みかどうか。
        completed_at: 完了日時の ISO 文字列。未完了なら None。
        id: タスクを一意に識別する ID。
    """

    title: str
    due: str
    recur_unit: str = RECUR_NONE
    recur_interval: int = MIN_INTERVAL
    completed: bool = False
    completed_at: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        # 不正な単位・間隔は安全側（繰り返しなし・最小間隔）へ正規化する
        if self.recur_unit not in RECUR_UNITS:
            self.recur_unit = RECUR_NONE
        self.recur_interval = _coerce_interval(self.recur_interval)
        # 期限がパースできない場合は不正なタスクとして例外を送出する。
        # これにより load_tasks() 側の個別 try-except で 1 件だけスキップでき、
        # 壊れた due を持つタスクが 1 件あってもアプリの起動を妨げない。
        try:
            datetime.datetime.strptime(self.due, ISO_FMT)
        except (TypeError, ValueError) as e:
            raise ValueError(f"期限の形式が不正です: {self.due!r}") from e

    @property
    def due_dt(self) -> datetime.datetime:
        """期限日時を datetime として返す。"""
        return datetime.datetime.strptime(self.due, ISO_FMT)

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


def make_due(target_time: datetime.time, now: datetime.datetime | None = None) -> str:
    """指定時刻から「直近の未来の期限日時」を ISO 文字列で生成する。

    今日の指定時刻が既に過ぎていれば翌日に繰り越す（元のリマインダーと同じ挙動）。

    Args:
        target_time: 期限にしたい時刻（時・分）。
        now: 現在日時。省略時は datetime.now()。

    Returns:
        ISO_FMT 形式の期限日時文字列。
    """
    now = now or datetime.datetime.now()
    due = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    if due <= now:
        due += datetime.timedelta(days=1)
    return due.strftime(ISO_FMT)


def build_next_task(task: Task, completed_at: datetime.datetime) -> Task | None:
    """完了したタスクから、繰り返し設定に基づく次回タスクを生成する。

    次回期限は completed_at（完了時点）を起点に算出される。これが本アプリの
    中核要件「完了した時点から日/週/月/年で繰り返す」を実現する部分である。

    Args:
        task: 完了したタスク。
        completed_at: 完了日時（次回期限計算の起点）。

    Returns:
        次回分の未完了タスク。繰り返しなしの場合は None。
    """
    nxt = next_occurrence(completed_at, task.recur_unit, task.recur_interval)
    if nxt is None:
        return None
    return Task(
        title=task.title,
        due=nxt.strftime(ISO_FMT),
        recur_unit=task.recur_unit,
        recur_interval=task.recur_interval,
    )
