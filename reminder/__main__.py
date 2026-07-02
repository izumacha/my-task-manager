"""`python -m reminder` のエントリーポイント。

実体は `reminder.cli.main` に置き、このモジュールは薄いラッパーに徹する。
こうすることで `reminder.__main__` がパッケージ import 時に先読みされず、
`python -m reminder` 実行時の RuntimeWarning を回避できる。
"""
from __future__ import annotations

from .cli import main  # cli モジュールの main 関数をこのモジュールに取り込む

if __name__ == "__main__":  # このファイルが直接実行されたとき（モジュールとして読み込まれたときは実行しない）
    main()  # プランナーアプリを起動するエントリーポイント関数を呼び出す
