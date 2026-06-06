"""アプリケーションのエントリーポイント。Tk ウィンドウを生成してイベントループを起動する。"""
import logging
import tkinter as tk

from .app import PlannerApp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    PlannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
