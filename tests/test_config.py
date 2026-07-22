"""tests/test_config.py — タスク永続化（load_tasks / save_tasks）のテスト"""
import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from reminder import config
from reminder.config import (
    COMPLETION_RETENTION_DAYS,
    Prefs,
    load_prefs,
    load_tasks,
    save_prefs,
    save_tasks,
    set_save_blocked_listener,
)
from reminder.recurrence import RECUR_WEEKLY
from reminder.task import ISO_FMT, Task


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
            with patch("reminder.config._TASKS_PATH", tasks_path):  # タスクファイルのパスをテスト用の一時ファイルへ差し替える
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
            with patch("reminder.config._SETTINGS_PATH", path):  # 設定ファイルのパスをテスト用の一時ファイルへ差し替える
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


class TransientIoErrorTests(unittest.TestCase):
    """一時的な I/O エラー（OSError）を「壊れたファイル」と誤認して隔離・上書きしないことのテスト。"""

    def setUp(self):
        # モジュールレベルの保存拒否フラグが他のテストへ漏れないよう、前後で毎回クリアする
        config._failed_load_paths.clear()  # テスト開始前に保存拒否の記録を空にする
        self.addCleanup(config._failed_load_paths.clear)  # テスト終了後にも保存拒否の記録を空へ戻す

    def test_oserror_on_tasks_read_returns_empty_without_quarantine(self):
        # 権限不足などの OSError では .corrupt へ退避（改名）せず、健全なファイルを
        # 無傷のまま残して空リストへフォールバックすること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            healthy = [{"title": "健全", "due": "2026-06-06T09:00:00"}]  # 中身は正しい JSON（健全なデータ）を用意する
            with open(tasks_path, "w", encoding="utf-8") as f:  # 健全なファイルを書き込み用に開く
                json.dump(healthy, f)  # 健全な内容を書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("builtins.open", side_effect=PermissionError("denied")), \
                 self.assertLogs(level="WARNING") as logs:  # open が権限エラーを起こす状況を再現しつつ警告ログを捕捉する
                self.assertEqual(load_tasks(), [])  # 読み込みは空リストへフォールバックする
            self.assertFalse(os.path.exists(tasks_path + ".corrupt"))  # 退避ファイルが作られていない（隔離されない）こと
            with open(tasks_path, encoding="utf-8") as f:  # 元のファイルを開き直す
                self.assertEqual(json.load(f), healthy)  # 健全な内容が無傷のまま残っていること
            self.assertTrue(any("I/Oエラー" in msg for msg in logs.output))  # I/O エラーとして警告ログに残ること

    def test_oserror_on_prefs_read_returns_defaults_without_quarantine(self):
        # 設定ファイルも同様に、OSError では退避せず既定値へフォールバックし、
        # その後の save_prefs による上書きも拒否されること
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")  # テスト用の設定ファイルパスを組み立てる
            with open(path, "w", encoding="utf-8") as f:  # 健全な設定ファイルを書き込み用に開く
                json.dump({"wake": "06:30", "sleep": "22:00"}, f)  # 健全な設定内容を書き込む
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # 設定ファイルのパスをテスト用に差し替える
                with patch("builtins.open", side_effect=OSError(5, "I/O error")), \
                     self.assertLogs(level="WARNING"):  # open が I/O エラーを起こす状況を再現する
                    self.assertEqual(load_prefs().wake, "07:00")  # 読み込みは既定値へフォールバックする
                self.assertFalse(os.path.exists(path + ".corrupt"))  # 退避ファイルが作られていない（隔離されない）こと
                with self.assertLogs(level="WARNING") as logs:  # 保存拒否の警告ログを捕捉する
                    save_prefs(Prefs(wake="05:00"))  # 既定値ベースの設定で保存を試みる
                self.assertTrue(any("中止" in msg for msg in logs.output))  # 保存が中止された旨がログに残ること
            with open(path, encoding="utf-8") as f:  # 保存試行後の元ファイルを開く
                self.assertEqual(json.load(f)["wake"], "06:30")  # 健全な設定が上書きされずに残っていること

    def test_save_tasks_refused_after_failed_load_until_next_successful_load(self):
        # OSError で読み込みに失敗した後は save_tasks が健全なファイルを上書きせず、
        # 再び読み込みに成功したら保存拒否が解除されること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            healthy = [{"title": "健全", "due": "2026-06-06T09:00:00"}]  # 守られるべき健全なデータを用意する
            with open(tasks_path, "w", encoding="utf-8") as f:  # 健全なファイルを書き込み用に開く
                json.dump(healthy, f)  # 健全な内容を書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # タスクファイルのパスをテスト用に差し替える
                with patch("builtins.open", side_effect=OSError(5, "I/O error")), \
                     self.assertLogs(level="WARNING"):  # open が I/O エラーを起こす状況を再現する
                    self.assertEqual(load_tasks(), [])  # 読み込みは空リストへフォールバックする
                with self.assertLogs(level="WARNING") as logs:  # 保存拒否の警告ログを捕捉する
                    save_tasks([Task(title="新規", due="2026-06-07T09:00:00")])  # 空データからの保存を試みる
                self.assertTrue(any("中止" in msg for msg in logs.output))  # 保存が中止された旨がログに残ること
                with open(tasks_path, encoding="utf-8") as f:  # 保存試行後の元ファイルを開く
                    self.assertEqual(json.load(f), healthy)  # 健全な内容が上書きされずに残っていること
                # 一時エラーが解消して再び読み込みに成功すれば、保存拒否は解除される
                self.assertEqual([t.title for t in load_tasks()], ["健全"])  # 通常の読み込みは成功する
                save_tasks([Task(title="新規", due="2026-06-07T09:00:00")])  # 成功後の保存は拒否されない
                self.assertEqual([t.title for t in load_tasks()], ["新規"])  # 保存した新しい内容が読み込めること

    def test_decode_error_still_quarantines(self):
        # 壊れた JSON（デコードエラー）は従来どおり .corrupt へ退避されること
        # （OSError の扱いを変えても隔離の挙動が退化していないことの確認）
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            with open(tasks_path, "w", encoding="utf-8") as f:  # 壊れたファイルを書き込み用に開く
                f.write("{ this is not json")  # JSON として解釈できない内容を書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                self.assertEqual(load_tasks(), [])  # 読み込みは空リストへフォールバックする
            self.assertTrue(os.path.exists(tasks_path + ".corrupt"))  # 壊れたファイルは退避されていること

    def test_deeply_nested_json_quarantines_instead_of_crashing(self):
        # 異常に深くネストした JSON（RecursionError）でも起動不能にならず、
        # 壊れたファイルとして .corrupt へ退避して空リストへフォールバックすること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            with open(tasks_path, "w", encoding="utf-8") as f:  # 病的にネストしたファイルを書き込み用に開く
                f.write("[" * 100_000)  # JSON パーサの再帰上限を超える深さのネストを書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                self.assertEqual(load_tasks(), [])  # クラッシュせず空リストへフォールバックする
            self.assertTrue(os.path.exists(tasks_path + ".corrupt"))  # 解析不能なファイルは退避されていること


class SaveRefusalRecoveryTests(unittest.TestCase):
    """保存拒否時に変更内容が復旧用ファイルへ退避され、UI 層へ 1 回だけ通知されることのテスト。"""

    def setUp(self):
        # モジュールレベルの保存拒否フラグ・通知コールバックが他のテストへ漏れないよう、前後で毎回リセットする
        config._failed_load_paths.clear()  # テスト開始前に保存拒否の記録を空にする
        self.addCleanup(config._failed_load_paths.clear)  # テスト終了後にも保存拒否の記録を空へ戻す
        set_save_blocked_listener(None)  # コールバック登録と「通知済み」フラグをリセットする
        self.addCleanup(set_save_blocked_listener, None)  # テスト終了後にもコールバック登録を解除する

    def test_refused_task_save_writes_recovery_file_and_reports(self):
        # 保存拒否時、本体ファイルは無傷のまま、変更内容が tasks.json.recovery へ退避され、
        # 登録済みコールバックに (本体パス, 復旧用パス) が通知されること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            healthy = [{"title": "健全", "due": "2026-06-06T09:00:00"}]  # 守られるべき健全なデータを用意する
            with open(tasks_path, "w", encoding="utf-8") as f:  # 健全なファイルを書き込み用に開く
                json.dump(healthy, f)  # 健全な内容を書き込む
            calls = []  # コールバック呼び出しの記録リストを初期化する
            set_save_blocked_listener(lambda p, r: calls.append((p, r)))  # 通知内容を記録するコールバックを登録する
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # タスクファイルのパスをテスト用に差し替える
                config._failed_load_paths.add(tasks_path)  # 起動時の読み込み失敗（保存拒否状態）を再現する
                with self.assertLogs(level="WARNING") as logs:  # 保存中止と退避保存の警告ログを捕捉する
                    save_tasks([Task(title="編集後", due="2026-06-07T09:00:00")])  # 保存拒否状態で保存を試みる
            with open(tasks_path, encoding="utf-8") as f:  # 保存試行後の本体ファイルを開く
                self.assertEqual(json.load(f), healthy)  # 本体ファイルは上書きされず無傷のまま残っていること
            recovery = tasks_path + ".recovery"  # 復旧用ファイルのパスを組み立てる
            self.assertTrue(os.path.exists(recovery))  # 復旧用ファイルが作られていること
            with open(recovery, encoding="utf-8") as f:  # 復旧用ファイルを開く
                self.assertEqual([d["title"] for d in json.load(f)], ["編集後"])  # その日の編集内容が退避保存されていること
            self.assertEqual(calls, [(tasks_path, recovery)])  # 本体パスと復旧用パスが正しく通知されていること
            self.assertTrue(any("退避保存" in msg for msg in logs.output))  # 退避先の場所がログで案内されていること

    def test_refused_prefs_save_writes_recovery_file(self):
        # settings.json も対称に、保存拒否時は settings.json.recovery へ退避されること
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")  # テスト用の設定ファイルパスを組み立てる
            with open(path, "w", encoding="utf-8") as f:  # 健全な設定ファイルを書き込み用に開く
                json.dump({"wake": "06:30", "sleep": "22:00"}, f)  # 健全な設定内容を書き込む
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # 設定ファイルのパスをテスト用に差し替える
                config._failed_load_paths.add(path)  # 起動時の読み込み失敗（保存拒否状態）を再現する
                with self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                    save_prefs(Prefs(wake="05:00"))  # 保存拒否状態で設定の保存を試みる
            with open(path, encoding="utf-8") as f:  # 保存試行後の本体ファイルを開く
                self.assertEqual(json.load(f)["wake"], "06:30")  # 本体の設定は上書きされていないこと
            with open(path + ".recovery", encoding="utf-8") as f:  # 復旧用ファイルを開く
                self.assertEqual(json.load(f)["wake"], "05:00")  # 保存しようとした設定が退避されていること

    def test_recovery_file_is_never_auto_loaded(self):
        # 復旧用ファイルが存在しても、load_tasks は本体ファイルしか読まない
        # （古い退避内容で健全なデータを黙って置き換えないための最小スコープ方針の確認）
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる（本体は作らない）
            with open(tasks_path + ".recovery", "w", encoding="utf-8") as f:  # 復旧用ファイルだけを書き込み用に開く
                json.dump([{"title": "退避分", "due": "2026-06-06T09:00:00"}], f)  # 退避された内容を書き込む
            with patch("reminder.config._TASKS_PATH", tasks_path):  # タスクファイルのパスをテスト用に差し替える
                self.assertEqual(load_tasks(), [])  # 本体が無ければ復旧用ファイルは読まれず空リストになること

    def test_recovery_write_failure_reports_none(self):
        # 退避保存にも失敗した場合は、復旧用パスの代わりに None が通知され、警告ログが残ること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            calls = []  # コールバック呼び出しの記録リストを初期化する
            set_save_blocked_listener(lambda p, r: calls.append((p, r)))  # 通知内容を記録するコールバックを登録する
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # タスクファイルのパスをテスト用に差し替える
                config._failed_load_paths.add(tasks_path)  # 保存拒否状態を再現する
                with patch("reminder.config._atomic_write_json", side_effect=OSError("disk full")), \
                     self.assertLogs(level="WARNING") as logs:  # 退避保存の書き込みも失敗する状況を再現する
                    save_tasks([Task(title="編集後", due="2026-06-07T09:00:00")])  # 保存を試みる
            self.assertEqual(calls, [(tasks_path, None)])  # 復旧用ファイル無し（None）として通知されること
            self.assertTrue(any("退避保存に失敗" in msg for msg in logs.output))  # 退避失敗が警告ログに残ること

    def test_save_blocked_notification_fires_exactly_once_per_session(self):
        # 保存が何度拒否されても（複数ファイルにまたがっても）、通知コールバックは
        # セッション中 1 回しか呼ばれないこと（ダイアログ連発の防止）。
        # 一方で復旧用ファイルへの退避保存は毎回行われ、常に最新の編集内容が残ること。
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            settings_path = os.path.join(tmpdir, "settings.json")  # テスト用の設定ファイルパスを組み立てる
            calls = []  # コールバック呼び出しの記録リストを初期化する
            set_save_blocked_listener(lambda p, r: calls.append((p, r)))  # 通知回数を記録するコールバックを登録する
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._SETTINGS_PATH", settings_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # 両ファイルのパスをテスト用に差し替える
                config._failed_load_paths.update({tasks_path, settings_path})  # 両ファイルとも保存拒否状態を再現する
                with self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                    save_tasks([Task(title="1回目", due="2026-06-07T09:00:00")])  # 1 回目の保存拒否（ここで通知される）
                    save_tasks([Task(title="2回目", due="2026-06-07T10:00:00")])  # 2 回目の保存拒否（通知は増えない）
                    save_prefs(Prefs(wake="05:00"))  # 別ファイルの保存拒否でも通知は増えない
            self.assertEqual(len(calls), 1)  # 通知はセッション中ちょうど 1 回だけであること
            self.assertEqual(calls[0][0], tasks_path)  # 最初に拒否されたファイル（tasks.json）が通知されていること
            with open(tasks_path + ".recovery", encoding="utf-8") as f:  # タスクの復旧用ファイルを開く
                self.assertEqual([d["title"] for d in json.load(f)], ["2回目"])  # 退避保存は毎回行われ最新の内容が残ること
            self.assertTrue(os.path.exists(settings_path + ".recovery"))  # 設定側の退避保存も行われていること

    def test_new_listener_registration_resets_once_per_session(self):
        # 新しいコールバックを登録し直すと「1 回だけ」のカウントもリセットされ、
        # 新しい登録者は改めて 1 回通知を受けられること
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる
            first, second = [], []  # 1 人目・2 人目のコールバック呼び出し記録リストを初期化する
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # タスクファイルのパスをテスト用に差し替える
                config._failed_load_paths.add(tasks_path)  # 保存拒否状態を再現する
                set_save_blocked_listener(lambda p, r: first.append(p))  # 1 人目のコールバックを登録する
                with self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                    save_tasks([])  # 1 人目への通知が発生する保存拒否を起こす
                set_save_blocked_listener(lambda p, r: second.append(p))  # 2 人目のコールバックへ登録し直す
                with self.assertLogs(level="WARNING"):  # 警告ログが出ることも確認する
                    save_tasks([])  # 2 人目への通知が発生する保存拒否を起こす
            self.assertEqual(len(first), 1)  # 1 人目は 1 回だけ通知されていること
            self.assertEqual(len(second), 1)  # 登録し直した 2 人目も改めて 1 回通知されていること

    def test_listener_exception_does_not_break_refused_save(self):
        # 通知コールバック（UI 層）が例外を投げても、退避保存は完了しており、
        # 永続化層はクラッシュせず警告ログを残すだけであること（fail-safe）
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_path = os.path.join(tmpdir, "tasks.json")  # テスト用のタスクファイルパスを組み立てる

            def boom(p, r):  # 必ず失敗する通知コールバックを定義する
                raise RuntimeError("UI 側の不具合")  # UI 層の例外を再現する

            set_save_blocked_listener(boom)  # 失敗するコールバックを登録する
            with patch("reminder.config._TASKS_PATH", tasks_path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir):  # タスクファイルのパスをテスト用に差し替える
                config._failed_load_paths.add(tasks_path)  # 保存拒否状態を再現する
                with self.assertLogs(level="WARNING") as logs:  # 通知失敗の警告ログを捕捉する
                    save_tasks([Task(title="編集後", due="2026-06-07T09:00:00")])  # 例外を漏らさず完了すること
            self.assertTrue(os.path.exists(tasks_path + ".recovery"))  # 退避保存自体は成功していること
            self.assertTrue(any("コールバック" in msg for msg in logs.output))  # 通知失敗が警告ログに残ること


class CompletionsTrimTests(unittest.TestCase):
    """完了履歴（Prefs.completions）が保持期間で刈り込まれることのテスト。"""

    FIXED_NOW = datetime.datetime(2026, 7, 22, 12, 0, 0)  # テスト全体で使う固定の現在日時（実時計に依存しない）

    def _iso(self, delta: datetime.timedelta) -> str:
        """固定の現在日時から delta だけ過去の完了日時を ISO 文字列で返す。"""
        return (self.FIXED_NOW - delta).strftime(ISO_FMT)  # 固定時刻から差し引いた日時を ISO 形式に変換して返す

    def test_load_prunes_old_completions_boundary_inclusive(self):
        # 読み込み時、保持期間より古い履歴は捨てられ、ちょうど境界（730 日前）の履歴は保持されること
        recent = self._iso(datetime.timedelta(days=1))  # 保持される新しい完了（1 日前）を用意する
        boundary = self._iso(datetime.timedelta(days=COMPLETION_RETENTION_DAYS))  # 境界ちょうど（730 日前）の完了を用意する
        too_old = self._iso(datetime.timedelta(days=COMPLETION_RETENTION_DAYS, seconds=1))  # 境界を 1 秒超えた古い完了を用意する
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")  # テスト用の設定ファイルパスを組み立てる
            with open(path, "w", encoding="utf-8") as f:  # 設定ファイルを書き込み用に開く
                json.dump({"completions": [recent, boundary, too_old]}, f)  # 新旧混在の完了履歴を書き込む
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._now", return_value=self.FIXED_NOW):  # パスと現在時刻をテスト用に固定する
                loaded = load_prefs()  # 設定を読み込む
            self.assertEqual(loaded.completions, [recent, boundary])  # 新しい履歴と境界ちょうどの履歴だけが残ること

    def test_save_prunes_old_completions_in_file_and_memory(self):
        # 保存時にも古い履歴が刈り込まれ、ファイルとメモリ上の Prefs の両方が上限内に保たれること
        recent = self._iso(datetime.timedelta(days=30))  # 保持される新しい完了（30 日前）を用意する
        too_old = self._iso(datetime.timedelta(days=COMPLETION_RETENTION_DAYS + 1))  # 保持期間を過ぎた古い完了を用意する
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")  # テスト用の設定ファイルパスを組み立てる
            prefs = Prefs(completions=[recent, too_old])  # 新旧混在の完了履歴を持つ設定を作る
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._CONFIG_DIR", tmpdir), \
                 patch("reminder.config._now", return_value=self.FIXED_NOW):  # パスと現在時刻をテスト用に固定する
                save_prefs(prefs)  # 設定を保存する
            self.assertEqual(prefs.completions, [recent])  # メモリ上の履歴も刈り込まれていること（毎分の統計パース負荷も抑える）
            with open(path, encoding="utf-8") as f:  # 保存されたファイルを開く
                self.assertEqual(json.load(f)["completions"], [recent])  # ファイルにも新しい履歴だけが書かれていること

    def test_prune_drops_unparseable_completion_strings(self):
        # 日時として解釈できない履歴文字列は、壊れたエントリのスキップと同じ方針で捨てられること
        recent = self._iso(datetime.timedelta(days=1))  # 保持される新しい完了を用意する
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")  # テスト用の設定ファイルパスを組み立てる
            with open(path, "w", encoding="utf-8") as f:  # 設定ファイルを書き込み用に開く
                json.dump({"completions": ["not-a-date", recent]}, f)  # 解釈できない文字列を混ぜた履歴を書き込む
            with patch("reminder.config._SETTINGS_PATH", path), \
                 patch("reminder.config._now", return_value=self.FIXED_NOW):  # パスと現在時刻をテスト用に固定する
                loaded = load_prefs()  # 設定を読み込む
            self.assertEqual(loaded.completions, [recent])  # 解釈できない文字列は捨てられ、正常な履歴だけが残ること


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
