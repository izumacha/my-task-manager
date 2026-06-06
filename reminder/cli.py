"""コンソールエントリーポイント。

`reminder = "reminder:main"`（pyproject の console-scripts）と
`python -m reminder` の双方から利用される `main()` を定義する。

エントリーポイント本体を `__main__` ではなくこのモジュールに置くことで、
パッケージ import 時に `reminder.__main__` を先読みせずに済み、
`python -m reminder` 実行時の RuntimeWarning（__main__ の二重ロード）を避ける。
"""
from __future__ import annotations

import logging
import tkinter as tk

from .app import PlannerApp


def main() -> None:
    """Tk ウィンドウを生成してプランナーのイベントループを起動する。"""
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    PlannerApp(root)
    root.mainloop()
