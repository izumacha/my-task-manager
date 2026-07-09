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
        import cairosvg  # type: ignore[import]  # SVG→PNG 変換ライブラリをオプションでインポートする（なければ除外）

        # パッケージの親ディレクトリ（プロジェクトルート）の assets/ を参照する
        svg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets",
            "reminder_icon.svg",
        )  # SVG アイコンファイルの絶対パスを組み立てる
        png_data = cairosvg.svg2png(url=svg_path, output_width=64, output_height=64)  # SVG を 64×64px の PNG バイト列に変換する
        icon = tk.PhotoImage(data=base64.b64encode(png_data))  # PNG バイト列を Base64 エンコードして tkinter の画像オブジェクトを作る
        # Tk 側で画像が解放されないように参照を保持する。
        root._icon_image = icon  # type: ignore[attr-defined]  # ガベージコレクションで解放されないよう root に参照を保持させる
        root.iconphoto(True, icon)  # ウィンドウとその子ウィンドウ全てにアイコンを設定する
    except Exception as e:  # cairosvg がない・ファイルが見つからないなどあらゆるエラーを捕捉する
        logging.debug("ウィンドウアイコンの設定をスキップしました: %s", e)  # デバッグログにスキップ理由を記録する


def _play_macos_sound() -> None:
    """macOS: afplay で Glass.aiff を別スレッド再生する（UI スレッドをブロックしない）。"""
    def _play_and_wait() -> None:
        try:
            proc = subprocess.Popen(
                ["/usr/bin/afplay", "/System/Library/Sounds/Glass.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )  # afplay コマンドをサブプロセスとして起動し、出力を捨てる
            proc.wait()  # 再生が終わるまでサブスレッド内で待機する
        except Exception as e:  # afplay が存在しない等の失敗をこのスレッド内で捕捉する
            # ここで捕まえないと、play_notification_sound() 側の try/except は
            # 既にスレッド起動を終えて抜けた後なので例外を捕捉できず、素の
            # traceback が stderr に出るだけでログにも bell フォールバックにも
            # つながらない（§6: エラーを握り潰さない。フォールバックを用意する）。
            logging.debug("afplay の再生に失敗しました: %s", e)  # デバッグログに失敗理由を記録する

    threading.Thread(target=_play_and_wait, daemon=True).start()  # 再生処理をデーモンスレッドで開始してUIスレッドをブロックしない


def _play_windows_sound() -> None:
    """Windows: winsound.MessageBeep で警告音を再生する。"""
    import winsound  # Windows 専用の音声再生モジュールをインポートする

    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)  # 警告（！）アイコンに対応するシステム音を鳴らす


def _send_linux_notification(body: str = "") -> None:
    """Linux: notify-send でデスクトップ通知を送信する。失敗時はログのみ残す。

    Args:
        body: 通知本文（タスク名など）。空の場合はタイトルのみ表示する。
    """
    # "--" を入れてオプション解析を打ち切る。notify-send（GLib の GOptionContext）は
    # 最初の位置引数で解析を止めず行全体からオプションを拾うため、"--" が無いと
    # ユーザー入力のタスク名（body）が "-t" 等のフラグとして誤解釈される恐れがある。
    # "--" 以降を厳密に位置引数（タイトル・本文）として渡し、引数注入を防ぐ。
    args = ["notify-send", "--urgency=normal", "--", "プランナー"]  # "--" でオプション解析を終端した notify-send の基本引数リスト
    if body:  # 本文テキストが指定されている場合
        args.append(body)  # 引数リストに本文を追加する（"--" 以降なのでフラグ誤認されない）
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )  # notify-send をサブプロセスとして起動し、出力を捨てる（非同期）
    except Exception as e:  # notify-send が存在しないなどのエラーを捕捉する
        # notify-send が利用できない場合はログのみ残し、呼び出し側の bell にフォールバックする
        logging.debug("notify-send の送信に失敗しました: %s", e)  # デバッグログにエラー内容を記録する


def _ring_bell(root: tk.Tk) -> None:
    """tkinter の bell() を安全に鳴らす（TclError は無視する）。"""
    try:
        root.bell()  # tkinter のビープ音（システムベル）を鳴らす
    except tk.TclError:
        # 実行環境によっては bell が利用できないことがあるため無視する。
        pass  # TclError が発生しても何もせず静かに無視する


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
    system_name = platform.system()  # 現在の OS 名（Darwin/Windows/Linux など）を取得する
    try:
        if system_name == "Darwin":  # macOS の場合
            _play_macos_sound()  # afplay で Glass.aiff を別スレッド再生する
            return  # 再生を開始したのでこの関数を終了する
        if system_name == "Windows":  # Windows の場合
            _play_windows_sound()  # winsound で警告音を再生する
            return  # 再生したのでこの関数を終了する
        if system_name == "Linux":  # Linux の場合
            # notify-send は音を伴わないことがあるため、後段の bell も併せて鳴らす
            _send_linux_notification(body)  # デスクトップ通知を送信する
    except Exception as e:  # OS 固有の再生処理でエラーが発生した場合
        # OS 固有の再生に失敗した場合はログを残してフォールバックの bell に委ねる
        logging.debug("通知音の再生をスキップしました: %s", e)  # デバッグログにスキップ理由を記録する

    _ring_bell(root)  # 最終フォールバックとして tkinter のベル音を鳴らす
