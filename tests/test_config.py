"""tests/test_config.py — タスク永続化（load_tasks / save_tasks）のテスト"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from reminder.config import load_tasks, save_tasks
from reminder.recurrence import RECUR_WEEKLY
from reminder.task import Task


class TaskPersistenceTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            original = [
                Task(title="運動", due="2026-06-06T18:00:00", recur_unit=RECUR_WEEKLY, recur_interval=2),
                Task(title="買い物", due="2026-06-07T10:00:00"),
            ]
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):
                save_tasks(original)
                loaded = load_tasks()
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].title, "運動")
            self.assertEqual(loaded[0].recur_unit, RECUR_WEEKLY)
            self.assertEqual(loaded[0].recur_interval, 2)
            self.assertEqual(loaded[1].title, "買い物")

    def test_load_missing_file_returns_empty(self):
        with patch("reminder.config._TASKS_PATH", "/nonexistent/tasks.json"):
            self.assertEqual(load_tasks(), [])

    def test_load_non_list_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                json.dump({"not": "a list"}, f)
            with patch("reminder.config._TASKS_PATH", tasks_path):
                self.assertEqual(load_tasks(), [])

    def test_load_skips_corrupt_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                # 2 件目は dict ではないのでスキップされる
                json.dump([
                    {"title": "ok", "due": "2026-06-06T09:00:00"},
                    "broken",
                    {"title": "ok2", "due": "2026-06-07T09:00:00"},
                ], f)
            with patch("reminder.config._TASKS_PATH", tasks_path):
                loaded = load_tasks()
            self.assertEqual([t.title for t in loaded], ["ok", "ok2"])

    def test_load_skips_entries_with_unparseable_due(self):
        # 壊れた due を持つタスクが 1 件あっても、残りは読み込めること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                json.dump([
                    {"title": "ok", "due": "2026-06-06T09:00:00"},
                    {"title": "broken", "due": "not-a-date"},
                    {"title": "ok2", "due": "2026-06-07T09:00:00"},
                ], f)
            with patch("reminder.config._TASKS_PATH", tasks_path):
                loaded = load_tasks()
            self.assertEqual([t.title for t in loaded], ["ok", "ok2"])

    def test_load_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                f.write("{ this is not json")
            with patch("reminder.config._TASKS_PATH", tasks_path):
                self.assertEqual(load_tasks(), [])

    def test_save_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "sub", "dir")
            tasks_path = os.path.join(nested, "tasks.json")
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", nested):
                save_tasks([Task(title="x", due="2026-06-06T09:00:00")])
            self.assertTrue(os.path.exists(tasks_path))


if __name__ == "__main__":
    unittest.main()
