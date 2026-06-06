from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import threading
import tkinter as tk


def _set_window_icon(root: tk.Tk) -> None:
    """SVG アイコンをウィンドウに設定する。変換ライブラリが無い場合は無視する。"""
    try:
        import cairosvg  # type: ignore[import]

        # パッケージの親ディレクトリ（プロジェクトルート）の assets/ を参照する
        svg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "reminder_icon.svg",
        )
        png_data = cairosvg.svg2png(url=svg_path, output_width=64, output_height=64)
        icon = tk.PhotoImage(data=base64.b64encode(png_data))
        # Tk 側で画像が解放されないように参照を保持する。
        root._icon_image = icon  # type: ignore[attr-defined]
        root.iconphoto(True, icon)
    except Exception as e:
        logging.debug("ウィンドウアイコンの設定をスキップしました: %s", e)


def _play_macos_sound() -> None:
    """macOS: afplay で Glass.aiff を別スレッド再生する（UI スレッドをブロックしない）。"""
    def _play_and_wait() -> None:
        proc = subprocess.Popen(
            ["/usr/bin/afplay", "/System/Library/Sounds/Glass.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait()

    threading.Thread(target=_play_and_wait, daemon=True).start()


def _play_windows_sound() -> None:
    """Windows: winsound.MessageBeep で警告音を再生する。"""
    import winsound

    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)


def _send_linux_notification(body: str = "") -> None:
    """Linux: notify-send でデスクトップ通知を送信する。失敗時はログのみ残す。

    Args:
        body: 通知本文（タスク名など）。空の場合はタイトルのみ表示する。
    """
    args = ["notify-send", "--urgency=normal", "プランナー"]
    if body:
        args.append(body)
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        # notify-send が利用できない場合はログのみ残し、呼び出し側の bell にフォールバックする
        logging.debug("notify-send の送信に失敗しました: %s", e)


def _ring_bell(root: tk.Tk) -> None:
    """tkinter の bell() を安全に鳴らす（TclError は無視する）。"""
    try:
        root.bell()
    except tk.TclError:
        # 実行環境によっては bell が利用できないことがあるため無視する。
        pass


def play_notification_sound(root: tk.Tk, body: str = "") -> None:
    """通知音を再生する。

    プラットフォームごとに最適な方法を試み、失敗時は tkinter の bell() にフォールバックする。
    - macOS: afplay コマンドで Glass.aiff を再生（別スレッド）
    - Windows: winsound.MessageBeep で警告音を再生
    - Linux: notify-send でデスクトップ通知を送信し、加えて bell を鳴らす
    - その他 / 上記失敗時: root.bell()

    Args:
        root: 鳴動フォールバックに使う Tk ルート。
        body: Linux のデスクトップ通知に載せる本文（タスク名など）。
    """
    system_name = platform.system()
    try:
        if system_name == "Darwin":
            _play_macos_sound()
            return
        if system_name == "Windows":
            _play_windows_sound()
            return
        if system_name == "Linux":
            # notify-send は音を伴わないことがあるため、後段の bell も併せて鳴らす
            _send_linux_notification(body)
    except Exception:
        # OS 固有の再生に失敗した場合は bell にフォールバック
        pass

    _ring_bell(root)
