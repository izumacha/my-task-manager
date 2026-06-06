"""タスク一覧と設定の永続化（JSON）。

タスクは ``~/.config/reminder/tasks.json`` に配列として保存される。
起床/就寝時刻や完了履歴などの設定は ``settings.json`` に保存される。
読み込み時に壊れたエントリは黙ってスキップし、アプリの起動を妨げない。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field

from .task import Task
from .timeline import DEFAULT_SLEEP_MIN, DEFAULT_WAKE_MIN, min_to_hhmm

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "reminder")
_TASKS_PATH = os.path.join(_CONFIG_DIR, "tasks.json")
_SETTINGS_PATH = os.path.join(_CONFIG_DIR, "settings.json")


@dataclass
class Prefs:
    """永続化するアプリ設定。

    Attributes:
        wake: 起床時刻（"HH:MM"）。タイムラインの開始境界。
        sleep: 就寝時刻（"HH:MM"）。タイムラインの終了境界。
        completions: 完了日時（ISO 文字列）の履歴。統計に使用する。
    """

    wake: str = field(default_factory=lambda: min_to_hhmm(DEFAULT_WAKE_MIN))
    sleep: str = field(default_factory=lambda: min_to_hhmm(DEFAULT_SLEEP_MIN))
    completions: list[str] = field(default_factory=list)


def load_prefs() -> Prefs:
    """設定を読み込む。存在しない/壊れている場合は既定値を返す。"""
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return Prefs()
    except Exception:
        logging.warning("設定ファイルの読み込みに失敗しました: %s", _SETTINGS_PATH)
        return Prefs()

    if not isinstance(data, dict):
        return Prefs()

    prefs = Prefs(**{k: v for k, v in data.items() if k in Prefs.__dataclass_fields__})
    # completions は文字列リストであることを保証する（壊れた値は捨てる）
    if not isinstance(prefs.completions, list):
        prefs.completions = []
    else:
        prefs.completions = [c for c in prefs.completions if isinstance(c, str)]
    return prefs


def save_prefs(prefs: Prefs) -> None:
    """設定を JSON ファイルに書き出す。"""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(prefs), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning("設定ファイルの保存に失敗しました: %s", e)


def load_tasks() -> list[Task]:
    """タスク一覧を読み込む。ファイルが無い/壊れている場合は空リストを返す。"""
    try:
        with open(_TASKS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception:
        logging.warning("タスクファイルの読み込みに失敗しました: %s", _TASKS_PATH)
        return []

    if not isinstance(data, list):
        return []

    tasks: list[Task] = []
    seen_ids: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            task = Task.from_dict(entry)
        except Exception:
            # 1 件壊れていても残りは読み込めるよう、個別にスキップする
            logging.debug("壊れたタスクエントリをスキップしました: %r", entry)
            continue
        # Treeview の iid には task.id を使うため「空でない一意な文字列」でなければならない。
        # 手編集や不正なマージで id が空文字・非文字列（例: 123）・重複になっていると、
        # 空文字は Treeview のルート item と衝突し、非文字列は選択時に文字列化されて
        # _selected_task() がマッチできない。これらの場合は再採番して起動不能を防ぐ。
        if not isinstance(task.id, str) or not task.id or task.id in seen_ids:
            task.id = uuid.uuid4().hex
        seen_ids.add(task.id)
        tasks.append(task)
    return tasks


def save_tasks(tasks: list[Task]) -> None:
    """タスク一覧を JSON ファイルに書き出す。"""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_TASKS_PATH, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in tasks], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning("タスクファイルの保存に失敗しました: %s", e)
