"""タスク一覧の永続化（JSON）。

タスクは ``~/.config/reminder/tasks.json`` に配列として保存される。
読み込み時に壊れたエントリは黙ってスキップし、アプリの起動を妨げない。
"""
from __future__ import annotations

import json
import logging
import os
import uuid

from .task import Task

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "reminder")
_TASKS_PATH = os.path.join(_CONFIG_DIR, "tasks.json")


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
