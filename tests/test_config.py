"""tests/test_config.py — タスク永続化（load_tasks / save_tasks）のテスト"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from reminder.config import Prefs, load_prefs, load_tasks, save_prefs, save_tasks
from reminder.recurrence import RECUR_WEEKLY
from reminder.task import Task


class PrefsPersistenceTests(unittest.TestCase):
    def test_default_prefs(self):
        p = Prefs()
        self.assertEqual(p.wake, "07:00")
        self.assertEqual(p.sleep, "23:00")
        self.assertEqual(p.completions, [])

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            original = Prefs(wake="06:30", sleep="22:00",
                             completions=["2026-06-06T09:00:00", "2026-06-05T18:00:00"])
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):
                save_prefs(original)
                loaded = load_prefs()
            self.assertEqual(loaded.wake, "06:30")
            self.assertEqual(loaded.sleep, "22:00")
            self.assertEqual(len(loaded.completions), 2)

    def test_load_missing_returns_defaults(self):
        with patch("reminder.config._SETTINGS_PATH", "/nonexistent/settings.json"):
            self.assertEqual(load_prefs().wake, "07:00")

    def test_load_non_dict_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump([1, 2, 3], f)
            with patch("reminder.config._SETTINGS_PATH", path):
                self.assertEqual(load_prefs().sleep, "23:00")

    def test_load_sanitizes_completions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"wake": "08:00", "completions": ["2026-06-06T09:00:00", 123, None]}, f)
            with patch("reminder.config._SETTINGS_PATH", path):
                loaded = load_prefs()
            self.assertEqual(loaded.wake, "08:00")
            self.assertEqual(loaded.completions, ["2026-06-06T09:00:00"])

    def test_load_sanitizes_invalid_wake_and_sleep(self):
        # /code-review ultra 指摘対応: wake/sleep に不正値（数値・範囲外・非文字列）が
        # 混入していても既定値へフォールバックし、警告ログが残ること（§6 例外を握り潰さない）
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"wake": 700, "sleep": "25:99"}, f)
            with patch("reminder.config._SETTINGS_PATH", path), \
                 self.assertLogs(level="WARNING") as logs:
                loaded = load_prefs()
            self.assertEqual(loaded.wake, "07:00")
            self.assertEqual(loaded.sleep, "23:00")
            self.assertTrue(any("wake" in msg for msg in logs.output))
            self.assertTrue(any("sleep" in msg for msg in logs.output))

    def test_load_keeps_valid_wake_and_sleep(self):
        # 正しい "HH:MM" 形式の値はそのまま採用され、既定値へ上書きされないこと
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"wake": "06:15", "sleep": "22:45"}, f)
            with patch("reminder.config._SETTINGS_PATH", path):
                loaded = load_prefs()
            self.assertEqual(loaded.wake, "06:15")
            self.assertEqual(loaded.sleep, "22:45")

    def test_load_ignores_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"wake": "05:00", "unknown": "x"}, f)
            with patch("reminder.config._SETTINGS_PATH", path):
                self.assertEqual(load_prefs().wake, "05:00")


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

    def test_load_regenerates_duplicate_ids(self):
        # 同じ id を持つ 2 件を読み込んでも、iid 衝突を防ぐため id は一意化される
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                json.dump([
                    {"title": "a", "due": "2026-06-06T09:00:00", "id": "dup"},
                    {"title": "b", "due": "2026-06-07T09:00:00", "id": "dup"},
                ], f)
            with patch("reminder.config._TASKS_PATH", tasks_path):
                loaded = load_tasks()
            self.assertEqual(len(loaded), 2)
            self.assertNotEqual(loaded[0].id, loaded[1].id)
            # 最初のエントリは元の id を維持する
            self.assertEqual(loaded[0].id, "dup")

    def test_load_regenerates_empty_id(self):
        # 空文字 id は Treeview ルートと衝突するため再採番される
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                json.dump([{"title": "a", "due": "2026-06-06T09:00:00", "id": ""}], f)
            with patch("reminder.config._TASKS_PATH", tasks_path):
                loaded = load_tasks()
            self.assertEqual(len(loaded), 1)
            self.assertIsInstance(loaded[0].id, str)
            self.assertTrue(loaded[0].id)

    def test_load_regenerates_non_string_id(self):
        # 非文字列 id は選択時に文字列化されてマッチしなくなるため再採番される
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                json.dump([{"title": "a", "due": "2026-06-06T09:00:00", "id": 123}], f)
            with patch("reminder.config._TASKS_PATH", tasks_path):
                loaded = load_tasks()
            self.assertEqual(len(loaded), 1)
            self.assertIsInstance(loaded[0].id, str)
            self.assertNotEqual(loaded[0].id, 123)

    def test_load_skips_non_string_title(self):
        # タイトルが非文字列の壊れたエントリはスキップされる
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with open(tasks_path, "w", encoding="utf-8") as f:
                json.dump([
                    {"title": "ok", "due": "2026-06-06T09:00:00"},
                    {"title": 123, "due": "2026-06-07T09:00:00"},
                    {"title": "", "due": "2026-06-08T09:00:00"},
                ], f)
            with patch("reminder.config._TASKS_PATH", tasks_path):
                loaded = load_tasks()
            self.assertEqual([t.title for t in loaded], ["ok"])

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


class AtomicWriteDurabilityTests(unittest.TestCase):
    """原子的書き込みが「途中失敗で既存ファイルを壊さない」ことを保証するテスト。"""

    def test_failed_task_save_preserves_existing_file(self):
        # 書き込み途中で例外が起きても、既存の tasks.json が壊れない（全消失しない）こと
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):
                # まず正常なタスクを保存しておく（これが守られるべき既存データ）
                save_tasks([Task(title="既存", due="2026-06-06T09:00:00")])
                # 次の保存中に json.dump が失敗する状況を再現する
                with patch("reminder.config.json.dump", side_effect=RuntimeError("disk full")):
                    save_tasks([Task(title="新規", due="2026-06-07T09:00:00")])
                # 失敗後も既存ファイルは元の内容のまま読み込めること
                loaded = load_tasks()
            self.assertEqual([t.title for t in loaded], ["既存"])

    def test_failed_save_leaves_no_temp_files(self):
        # 書き込み失敗時に一時ファイル（.tmp-*.json）が残らず後始末されること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):
                with patch("reminder.config.json.dump", side_effect=RuntimeError("disk full")):
                    save_tasks([Task(title="新規", due="2026-06-07T09:00:00")])
                leftovers = [n for n in os.listdir(tmpdir) if n.startswith(".tmp-")]
            self.assertEqual(leftovers, [])

    def test_failed_prefs_save_preserves_existing_file(self):
        # 設定ファイルも同様に、途中失敗で既存設定を壊さないこと
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):
                save_prefs(Prefs(wake="06:30", sleep="22:00"))
                with patch("reminder.config.json.dump", side_effect=RuntimeError("disk full")):
                    save_prefs(Prefs(wake="05:00", sleep="21:00"))
                loaded = load_prefs()
            self.assertEqual(loaded.wake, "06:30")
            self.assertEqual(loaded.sleep, "22:00")


if __name__ == "__main__":
    unittest.main()
