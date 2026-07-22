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
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 self.assertLogs(level="WARNING") as logs:  # スキップが警告レベルでログに残ることも確認する
                loaded = load_tasks()
            self.assertEqual([t.title for t in loaded], ["ok", "ok2"])
            # スキップは次回保存でエントリが永久に消えるため、INFO 起動でも見える
            # warning で「何件目か」が分かる形で通知されること（debug では見えない）
            self.assertTrue(any("2件目" in msg for msg in logs.output))  # 捨てられた位置がログに含まれること

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
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 self.assertLogs(level="WARNING") as logs:  # スキップが警告レベルでログに残ることも確認する
                loaded = load_tasks()
            self.assertEqual([t.title for t in loaded], ["ok", "ok2"])
            self.assertTrue(any("broken" in msg for msg in logs.output))  # 捨てられたエントリのタイトルがログに含まれること

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


class CorruptFilePreservationTests(unittest.TestCase):
    """壊れた JSON ファイルが .corrupt へ退避され、次回保存で消失しないことのテスト。"""

    def test_corrupt_tasks_json_is_preserved_and_survives_save(self):
        # 壊れた tasks.json は空リストへフォールバックしつつ .corrupt へ退避され、
        # その後の save_tasks でも退避ファイルが破壊されないこと
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            broken = "{ this is not json"  # JSON として解釈できない壊れた内容を用意する
            with open(tasks_path, "w", encoding="utf-8") as f:  # 壊れたファイルを書き込み用に開く
                f.write(broken)  # 壊れた内容をそのまま書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):
                with self.assertLogs(level="WARNING") as logs:  # 警告ログが出ることを捕捉する
                    self.assertEqual(load_tasks(), [])  # 読み込みは空リストへフォールバックする
                backup = tasks_path + ".corrupt"  # 退避先（元パス + .corrupt）のパスを組み立てる
                self.assertTrue(os.path.exists(backup))  # 壊れたファイルが退避されていること
                with open(backup, encoding="utf-8") as f:  # 退避ファイルを開く
                    self.assertEqual(f.read(), broken)  # 元の壊れた内容がそのまま保全されていること
                self.assertTrue(any(backup in msg for msg in logs.output))  # ログで退避先の場所が案内されていること
                # フォールバック後に新しいタスクを保存しても、退避ファイルは破壊されないこと
                save_tasks([Task(title="新規", due="2026-06-07T09:00:00")])  # 空データからの保存を実行する
                with open(backup, encoding="utf-8") as f:  # 保存後にもう一度退避ファイルを開く
                    self.assertEqual(f.read(), broken)  # 退避ファイルは元の内容のまま残っていること
                self.assertEqual([t.title for t in load_tasks()], ["新規"])  # 本番ファイルは新しい内容で読み込めること

    def test_corrupt_settings_json_is_preserved_and_survives_save(self):
        # 壊れた settings.json も同様に、既定値へフォールバックしつつ .corrupt へ退避され、
        # その後の save_prefs でも退避ファイルが破壊されないこと
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")  # テスト用の設定ファイルパスを組み立てる
            broken = "not json at all"  # JSON として解釈できない壊れた内容を用意する
            with open(path, "w", encoding="utf-8") as f:  # 壊れたファイルを書き込み用に開く
                f.write(broken)  # 壊れた内容をそのまま書き込む
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):
                with self.assertLogs(level="WARNING") as logs:  # 警告ログが出ることを捕捉する
                    self.assertEqual(load_prefs().wake, "07:00")  # 読み込みは既定値へフォールバックする
                backup = path + ".corrupt"  # 退避先のパスを組み立てる
                self.assertTrue(os.path.exists(backup))  # 壊れたファイルが退避されていること
                with open(backup, encoding="utf-8") as f:  # 退避ファイルを開く
                    self.assertEqual(f.read(), broken)  # 元の壊れた内容がそのまま保全されていること
                self.assertTrue(any(backup in msg for msg in logs.output))  # ログで退避先の場所が案内されていること
                # フォールバック後に設定を保存しても、退避ファイルは破壊されないこと
                save_prefs(Prefs(wake="06:00"))  # 既定値からの保存を実行する
                with open(backup, encoding="utf-8") as f:  # 保存後にもう一度退避ファイルを開く
                    self.assertEqual(f.read(), broken)  # 退避ファイルは元の内容のまま残っていること
                self.assertEqual(load_prefs().wake, "06:00")  # 本番ファイルは新しい内容で読み込めること

    def test_existing_backup_is_overwritten_by_newer_corrupt_file(self):
        # 退避先に前回の .corrupt が残っている場合は「最新の壊れたファイル」で上書きする
        # （世代管理はしないシンプルな方針の確認）
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            backup = tasks_path + ".corrupt"  # 退避先のパスを組み立てる
            with open(backup, "w", encoding="utf-8") as f:  # 前回の退避ファイルを作っておく
                f.write("old corrupt")  # 前回退避時の古い内容を書き込む
            with open(tasks_path, "w", encoding="utf-8") as f:  # 今回の壊れたファイルを書き込み用に開く
                f.write("new corrupt")  # 今回の壊れた内容を書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                self.assertEqual(load_tasks(), [])  # 読み込みは空リストへフォールバックする
            with open(backup, encoding="utf-8") as f:  # 上書き後の退避ファイルを開く
                self.assertEqual(f.read(), "new corrupt")  # 最新の壊れた内容で上書きされていること

    def test_non_list_tasks_json_is_preserved(self):
        # 有効な JSON でも形式が不正（リストでない）な場合は、同様に退避してから空リストを返す
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            with open(tasks_path, "w", encoding="utf-8") as f:  # 形式不正のファイルを書き込み用に開く
                json.dump({"not": "a list"}, f)  # リストでない JSON を書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                self.assertEqual(load_tasks(), [])  # 読み込みは空リストへフォールバックする
            self.assertTrue(os.path.exists(tasks_path + ".corrupt"))  # 形式不正のファイルも退避されていること


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
