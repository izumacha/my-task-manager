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
            ["notify-send", "--urgency=normal", "プランナー", "会議の準備"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @patch("reminder.notifications.subprocess.Popen", side_effect=FileNotFoundError)
    @patch("reminder.notifications.platform.system", return_value="Linux")
    def test_notify_send_not_found_still_rings_bell(self, _mock_system, _mock_popen):
        root = Mock()
        play_notification_sound(root)
        root.bell.assert_called_once_with()

    @patch("reminder.notifications.threading.Thread")
    @patch("reminder.notifications.platform.system", return_value="Darwin")
    def test_plays_afplay_on_darwin(self, _mock_system, mock_thread_cls):
        root = Mock()
        play_notification_sound(root)
        mock_thread_cls.assert_called_once()
        mock_thread_cls.return_value.start.assert_called_once()
        root.bell.assert_not_called()

    @patch("reminder.notifications.platform.system", return_value="Windows")
    def test_falls_back_to_bell_when_winsound_unavailable(self, _mock_system):
        root = Mock()
        play_notification_sound(root)
        root.bell.assert_called_once_with()


class SendLinuxNotificationTests(unittest.TestCase):
    @patch("reminder.notifications.subprocess.Popen")
    def test_invokes_notify_send_without_body(self, mock_popen):
        _send_linux_notification()
        mock_popen.assert_called_once_with(
            ["notify-send", "--urgency=normal", "プランナー"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @patch("reminder.notifications.subprocess.Popen")
    def test_invokes_notify_send_with_body(self, mock_popen):
        _send_linux_notification("掃除")
        mock_popen.assert_called_once_with(
            ["notify-send", "--urgency=normal", "プランナー", "掃除"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @patch("reminder.notifications.subprocess.Popen", side_effect=FileNotFoundError)
    def test_swallows_missing_command(self, _mock_popen):
        _send_linux_notification("x")


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
    @patch("reminder.notifications.threading.Thread")
    def test_starts_daemon_thread(self, mock_thread_cls):
        _play_macos_sound()
        mock_thread_cls.assert_called_once()
        self.assertTrue(mock_thread_cls.call_args.kwargs.get("daemon"))
        mock_thread_cls.return_value.start.assert_called_once()


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
