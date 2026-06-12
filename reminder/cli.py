"""コンソールエントリーポイント。

`reminder = "reminder:main"`（pyproject の console-scripts）と
`python -m reminder` の双方から利用される `main()` を定義する。

エントリーポイント本体を `__main__` ではなくこのモジュールに置くことで、
パッケージ import 時に `reminder.__main__` を先読みせずに済み、
`python -m reminder` 実行時の RuntimeWarning（__main__ の二重ロード）を避ける。
"""
from __future__ import annotations

import logging  # ログ出力を行うための標準ライブラリをインポートする
import tkinter as tk  # GUI ウィンドウを作成するための tkinter をインポートする

from .app import PlannerApp  # アプリ本体の PlannerApp クラスを読み込む


def main() -> None:
    """Tk ウィンドウを生成してプランナーのイベントループを起動する。"""
    logging.basicConfig(level=logging.INFO)  # INFO レベル以上のログをコンソールに出力するよう設定する
    root = tk.Tk()  # Tk のルートウィンドウ（アプリの親ウィンドウ）を生成する
    PlannerApp(root)  # PlannerApp を生成してルートウィンドウにアタッチする
    root.mainloop()  # GUI イベントループを開始する（ウィンドウが閉じられるまでここで待機する）
