"""tests/test_notifications.py — 通知音・デスクトップ通知・アイコン設定のテスト"""
import subprocess
import types
import unittest
from unittest.mock import Mock, patch

import tkinter as tk

from reminder.notifications import (
    _play_macos_sound,
    _ring_bell,
    _send_linux_notification,
    _set_window_icon,
    play_notification_sound,
)


class PlayNotificationSoundTests(unittest.TestCase):
    """play_notification_sound() のプラットフォーム別フォールバックを検証する。"""

    @patch("reminder.notifications.subprocess.Popen")
    @patch("reminder.notifications.platform.system", return_value="Linux")
    def test_calls_root_bell_on_linux(self, _mock_system, _mock_popen):
        root = Mock()
        play_notification_sound(root)
        root.bell.assert_called_once_with()

    @patch("reminder.notifications.subprocess.Popen")
    @patch("reminder.notifications.platform.system", return_value="Linux")
    def test_ignores_tcl_error(self, _mock_system, _mock_popen):
        root = Mock()
        root.bell.side_effect = tk.TclError("bell is not available")
        play_notification_sound(root)
        root.bell.assert_called_once_with()

    @patch("reminder.notifications.subprocess.Popen")
    @patch("reminder.notifications.platform.system", return_value="Linux")
    def test_sends_notify_send_with_task_body(self, _mock_system, mock_popen):
        root = Mock()
        play_notification_sound(root, "会議の準備")
        mock_popen.assert_called_once_with(
            ["notify-send", "--urgency=normal", "--", "プランナー", "会議の準備"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @patch("reminder.notifications.subprocess.Popen", side_effect=FileNotFoundError)
    @patch("reminder.notifications.platform.system", return_value="Linux")
    def test_notify_send_not_found_still_rings_bell(self, _mock_system, _mock_popen):
        root = Mock()
        play_notification_sound(root)
        root.bell.assert_called_once_with()

    @patch("reminder.notifications.subprocess.Popen")
    @patch("reminder.notifications.threading.Thread")
    @patch("reminder.notifications.platform.system", return_value="Darwin")
    def test_plays_afplay_on_darwin(self, _mock_system, mock_thread_cls, _mock_popen):
        root = Mock()
        play_notification_sound(root)
        mock_thread_cls.assert_called_once()
        mock_thread_cls.return_value.start.assert_called_once()
        root.bell.assert_not_called()

    @patch("reminder.notifications.subprocess.Popen", side_effect=FileNotFoundError("no afplay"))
    @patch("reminder.notifications.platform.system", return_value="Darwin")
    def test_missing_afplay_still_rings_bell(self, _mock_system, _mock_popen):
        # 回帰テスト: 以前は afplay の起動失敗(FileNotFoundError)がバックグラウンド
        # スレッド内でログにだけ残されて握り潰され、play_notification_sound() の
        # try/except には一切伝わらなかったため、Windows/Linux と異なり macOS だけ
        # bell へのフォールバックが起きなかった。今は Popen をこの呼び出し元スレッドで
        # 同期的に呼ぶため、起動失敗が play_notification_sound() の try/except まで
        # 伝播し、他プラットフォームと同様に bell へフォールバックする。
        root = Mock()
        play_notification_sound(root)
        root.bell.assert_called_once_with()

    @patch("reminder.notifications._play_windows_sound", side_effect=ImportError("no winsound"))
    @patch("reminder.notifications.platform.system", return_value="Windows")
    def test_falls_back_to_bell_when_winsound_unavailable(self, _mock_system, _mock_win):
        # winsound が使えない（= 例外）場合は bell にフォールバックする。
        # 実際の Windows ランナーでも決定的に検証できるよう、明示的に失敗させる。
        root = Mock()
        play_notification_sound(root)
        root.bell.assert_called_once_with()


class SendLinuxNotificationTests(unittest.TestCase):
    @patch("reminder.notifications.subprocess.Popen")
    def test_invokes_notify_send_without_body(self, mock_popen):
        _send_linux_notification()
        mock_popen.assert_called_once_with(
            ["notify-send", "--urgency=normal", "--", "プランナー"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @patch("reminder.notifications.subprocess.Popen")
    def test_invokes_notify_send_with_body(self, mock_popen):
        _send_linux_notification("掃除")
        mock_popen.assert_called_once_with(
            ["notify-send", "--urgency=normal", "--", "プランナー", "掃除"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @patch("reminder.notifications.subprocess.Popen")
    def test_flag_like_body_is_passed_after_double_dash(self, mock_popen):
        # ユーザーが "-t" のようなフラグ風のタスク名を付けても、"--" 以降の
        # 位置引数として渡され、notify-send のオプションに誤解釈されないことを保証する。
        _send_linux_notification("-t 1 --expire-time=0")
        args = mock_popen.call_args.args[0]
        # "--" が本文より前に存在し、フラグ風の本文が "--" の後ろに来ることを検証する
        self.assertIn("--", args)
        self.assertLess(args.index("--"), args.index("-t 1 --expire-time=0"))

    @patch("reminder.notifications.subprocess.Popen", side_effect=FileNotFoundError)
    def test_swallows_missing_command(self, _mock_popen):
        _send_linux_notification("x")

    @patch("reminder.notifications.threading.Thread")
    @patch("reminder.notifications.subprocess.Popen")
    def test_reaps_child_process_via_daemon_thread(self, mock_popen, mock_thread_cls):
        # notify-send の子プロセスを wait() で回収しないとゾンビプロセスとして
        # 蓄積してしまうため、_play_macos_sound と同様にデーモンスレッドで
        # proc.wait() を呼んで回収していることを検証する。
        mock_proc = Mock()  # Popen が返す偽のプロセスオブジェクト
        mock_popen.return_value = mock_proc
        _send_linux_notification("会議")
        # threading.Thread がデーモンスレッドとして起動されること
        mock_thread_cls.assert_called_once()
        self.assertTrue(mock_thread_cls.call_args.kwargs.get("daemon"))
        mock_thread_cls.return_value.start.assert_called_once_with()
        # スレッドのターゲット関数を実行すると proc.wait() が呼ばれ、子プロセスが回収されること
        target = mock_thread_cls.call_args.kwargs["target"]
        target()
        mock_proc.wait.assert_called_once_with()

    @patch("reminder.notifications.logging.debug")
    @patch("reminder.notifications.subprocess.Popen")
    def test_reap_failure_is_logged_not_raised(self, mock_popen, mock_debug):
        # _play_macos_sound の _reap と同様、wait() 自体が失敗する
        # まれなケースでも例外を外へ伝播させずログに残すことを検証する。
        # threading.Thread を、start() 呼び出し時にターゲット関数をその場（同一スレッド）で
        # 実行するフェイクに差し替える（実スレッド+sleep 待ちはタイミング依存で不安定なため避ける）。
        def _run_target_on_start(target=None, daemon=None):
            thread = Mock()  # 実スレッドの代わりに使う Mock オブジェクトを作る
            thread.start.side_effect = target  # start() 呼び出しでターゲットをその場実行する
            return thread  # フェイクのスレッドオブジェクトを返す

        mock_proc = Mock()  # Popen が返す偽のプロセスオブジェクト
        mock_proc.wait.side_effect = OSError("reap failed")  # wait() が失敗するケースを模す
        mock_popen.return_value = mock_proc
        with patch("reminder.notifications.threading.Thread", side_effect=_run_target_on_start):
            _send_linux_notification("会議")  # 例外が外へ伝播していればこの呼び出し自体が失敗する
        mock_debug.assert_called_once()  # 失敗がデバッグログに記録されている


class RingBellTests(unittest.TestCase):
    def test_ring_bell_invokes_root_bell(self):
        root = Mock()
        _ring_bell(root)
        root.bell.assert_called_once_with()

    def test_ring_bell_swallows_tcl_error(self):
        root = Mock()
        root.bell.side_effect = tk.TclError("bell unavailable")
        _ring_bell(root)


class PlayMacosSoundTests(unittest.TestCase):
    @patch("reminder.notifications.subprocess.Popen")
    @patch("reminder.notifications.threading.Thread")
    def test_starts_daemon_thread(self, mock_thread_cls, _mock_popen):
        _play_macos_sound()
        mock_thread_cls.assert_called_once()
        self.assertTrue(mock_thread_cls.call_args.kwargs.get("daemon"))
        mock_thread_cls.return_value.start.assert_called_once()

    @patch("reminder.notifications.subprocess.Popen", side_effect=FileNotFoundError("no afplay"))
    def test_missing_afplay_propagates_to_caller(self, _mock_popen):
        # Popen(起動)自体はこのメソッドの呼び出し元スレッドで同期的に行うため、
        # 起動失敗はここで(スレッド内に隠れず)例外として呼び出し元へ伝播しなければならない。
        # play_notification_sound() 側の try/except がこれを捕捉して bell へ
        # フォールバックできるようにするための契約(test_missing_afplay_still_rings_bell 参照)。
        with self.assertRaises(FileNotFoundError):
            _play_macos_sound()

    @patch("reminder.notifications.logging.debug")
    @patch("reminder.notifications.subprocess.Popen")
    def test_reap_failure_is_logged_not_raised(self, mock_popen, mock_debug):
        # 起動(Popen)には成功したが、再生完了を待つ(reap する)別スレッド内で
        # wait() が失敗するまれなケースでも、例外を外へ伝播させずログに残すことを検証する。
        # threading.Thread を、start() 呼び出し時にターゲット関数をその場（同一スレッド）で
        # 実行するフェイクに差し替える（実スレッド+sleep 待ちはタイミング依存で不安定なため避ける）。
        def _run_target_on_start(target=None, daemon=None):
            thread = Mock()  # 実スレッドの代わりに使う Mock オブジェクトを作る
            thread.start.side_effect = target  # start() 呼び出しでターゲットをその場実行する
            return thread  # フェイクのスレッドオブジェクトを返す

        mock_proc = Mock()  # Popen が返す偽のプロセスオブジェクト
        mock_proc.wait.side_effect = OSError("reap failed")  # wait() が失敗するケースを模す
        mock_popen.return_value = mock_proc
        with patch("reminder.notifications.threading.Thread", side_effect=_run_target_on_start):
            _play_macos_sound()  # 例外が外へ伝播していればこの呼び出し自体が失敗する
        mock_debug.assert_called_once()  # 失敗がデバッグログに記録されている


class SetWindowIconTests(unittest.TestCase):
    def test_does_not_raise_when_cairosvg_unavailable(self):
        root = Mock()
        _set_window_icon(root)

    @patch("reminder.notifications.tk.PhotoImage")
    @patch.dict("sys.modules", {"cairosvg": types.SimpleNamespace(svg2png=Mock(return_value=b"png-data"))})
    def test_keeps_icon_reference_on_root(self, mock_photo_image):
        root = Mock()
        icon = Mock()
        mock_photo_image.return_value = icon
        _set_window_icon(root)
        self.assertIs(root._icon_image, icon)
        root.iconphoto.assert_called_once_with(True, icon)


if __name__ == "__main__":
    unittest.main()
