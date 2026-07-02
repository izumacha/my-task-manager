"""Any Planner 風タスクプランナーアプリケーションパッケージ。"""

from __future__ import annotations

from .app import PlannerApp, ReminderApp
from .config import Prefs, load_prefs, load_tasks, save_prefs, save_tasks
from .notifications import _set_window_icon, play_notification_sound
from .recurrence import (
    MAX_INTERVAL,
    MIN_INTERVAL,
    RECUR_DAILY,
    RECUR_LABELS,
    RECUR_MONTHLY,
    RECUR_NONE,
    RECUR_UNITS,
    RECUR_WEEKLY,
    RECUR_YEARLY,
    add_period,
    label_for_unit,
    next_occurrence,
    unit_for_label,
)
from .stats import completed_count_on, current_streak, total_completed
from .task import Task, build_next_task, make_due
from .timeline import (
    backlog_tasks,
    build_day_timeline,
    carry_over_overdue,
    format_duration,
    free_minutes_today,
    prune_old_completed,
    suggest_for_free_time,
)
from .time_utils import (
    STATUS_EMPTY,
    STATUS_IDLE,
    delay_ms_until,
)

# main は cli モジュールに定義。pyproject の scripts エントリ（reminder:main）から
# 参照される。__main__ ではなく cli から import することで、python -m reminder 実行時に
# __main__ が二重ロードされる RuntimeWarning を避ける。
from .cli import main

__all__ = [
    "PlannerApp",
    "ReminderApp",
    "Task",
    "build_next_task",
    "make_due",
    "load_tasks",
    "save_tasks",
    "Prefs",
    "load_prefs",
    "save_prefs",
    "build_day_timeline",
    "carry_over_overdue",
    "prune_old_completed",
    "backlog_tasks",
    "suggest_for_free_time",
    "free_minutes_today",
    "format_duration",
    "completed_count_on",
    "current_streak",
    "total_completed",
    "play_notification_sound",
    "delay_ms_until",
    "add_period",
    "next_occurrence",
    "label_for_unit",
    "unit_for_label",
    "main",
    "RECUR_NONE",
    "RECUR_DAILY",
    "RECUR_WEEKLY",
    "RECUR_MONTHLY",
    "RECUR_YEARLY",
    "RECUR_UNITS",
    "RECUR_LABELS",
    "MIN_INTERVAL",
    "MAX_INTERVAL",
    "STATUS_IDLE",
    "STATUS_EMPTY",
    "_set_window_icon",
]
