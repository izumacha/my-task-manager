"""`python -m reminder` のエントリーポイント。

実体は `reminder.cli.main` に置き、このモジュールは薄いラッパーに徹する。
こうすることで `reminder.__main__` がパッケージ import 時に先読みされず、
`python -m reminder` 実行時の RuntimeWarning を回避できる。
"""
from .cli import main

if __name__ == "__main__":
    main()
