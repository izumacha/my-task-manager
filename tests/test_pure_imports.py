"""パッケージ ``reminder`` の公開エクスポート面（``reminder/__init__.py``）の回帰テスト。

このファイルが守る契約は 2 つある。

1. **GUI（tkinter）非搭載環境でも純粋ロジックが import できること。**
   conftest.py は tkinter が無い環境で MagicMock を注入するため、この検証は
   モック注入の効かない「素の子プロセス」で行う。パッケージの ``__init__`` が
   GUI モジュール（app / notifications / cli）を eager import してしまうと、
   契約共有先（Web/スマホ版）やヘッドレス CI が recurrence / timeline 等の
   純粋ロジックを再利用できなくなる（CLAUDE.md §10）。

2. **``__all__`` ・ eager 再エクスポート ・ ``_LAZY_GUI_EXPORTS`` の 3 つが食い違わないこと。**
   ``reminder/__init__.py`` は「どの名前を公開するか」を手書きの一覧 3 つで表しており、
   ずれても実行時まで何も起きない。以下はいずれも **修正前は全件緑のまま通った**（実測）:

   - ``__all__`` に実在しない名前（綴り間違い・削除された関数）を 1 件足す
     → ``from reminder import *`` が AttributeError で落ちるのに 339 件すべて緑。
   - ``_LAZY_GUI_EXPORTS`` の値（定義元モジュール名）を壊す
     → 例えば ``"main": "cli"`` を壊すと、pyproject の console-scripts
       （``reminder = "reminder:main"``）が解決できなくなり **pipx / pip install した
       利用者のコマンドが起動時に失敗する**のに、339 件すべて緑。

   従来の検査は純粋シンボル 3 件（free_minutes_today / next_occurrence /
   current_streak）と GUI シンボル 1 件（PlannerApp）を**名指しで**確かめるだけ
   だったため、名指ししていない公開名はどれだけ壊しても検出できなかった。
   名指しをやめ、``__all__`` から対象を導出して 1 件残らず参照できることを確かめる。
"""

from __future__ import annotations

import ast  # __init__.py の import 文を「__all__ とは独立な手がかり」として読むために使う
import subprocess  # 子プロセスで素の Python を起動するために使う
import sys  # 現在のインタープリタのパスを得るために使う
import unittest  # 標準のテストフレームワークを使う
from pathlib import Path  # リポジトリルートのパス計算に使う

import reminder  # 検査対象のパッケージ本体（conftest が tkinter のモックを注入済み）

# リポジトリのルートディレクトリ（このファイルの親の親）を求める
REPO_ROOT = Path(__file__).resolve().parent.parent

# 子プロセスで実行するスクリプト。tkinter の import を強制的に失敗させた上で、
# パッケージ本体と純粋ロジック一式を import できること、公開名のうち GUI 依存として
# 宣言されたものだけが ImportError になることを検証する。
#
# 検査対象を名前で並べず ``__all__`` と ``_LAZY_GUI_EXPORTS`` から導出するのが要点。
# 名指しだと「名指ししていない公開名が GUI モジュールへ移動した」変更を検出できず、
# ヘッドレス環境で初めて壊れる（このファイルが防ごうとしている事故そのもの）。
# 導出は「対象 0 件なら常に緑」になりうるので、空の一覧は先に落とす（fail-closed）。
_PROBE_SCRIPT = """
import sys
# sys.modules に None を入れると、以後の `import tkinter` は ImportError になる
sys.modules["tkinter"] = None

# パッケージ本体と純粋ロジックの import が tkinter 無しで成立すること
import reminder
import reminder.config
import reminder.recurrence
import reminder.stats
import reminder.task
import reminder.theme
import reminder.time_utils
import reminder.timeline

# GUI 依存として宣言されている名前の対応表を取り出す（モジュール変数なので __getattr__ は通らない）
from reminder import _LAZY_GUI_EXPORTS

# パッケージが公開すると宣言している名前の一覧
public = list(reminder.__all__)
# そのうち GUI（tkinter）依存として宣言されているもの
gui = [name for name in public if name in _LAZY_GUI_EXPORTS]
# 残り（＝tkinter 無しでも参照できなければならないもの）
pure = [name for name in public if name not in _LAZY_GUI_EXPORTS]

# 見つかった問題を貯めるリスト（最後にまとめて報告する）
problems = []

# 検査対象が 0 件だと「違反ゼロ＝緑」になってしまうので、空の一覧はそれ自体を失敗とする
if not public:
    problems.append("__all__ が空です（検査対象 0 件では常に緑になります）")
if not gui:
    problems.append("GUI 依存として宣言された公開名が 0 件です（遅延読み込みの検査が空振りします）")
if not pure:
    problems.append("GUI 非依存の公開名が 0 件です（純粋ロジックの検査が空振りします）")

# GUI 依存でない公開名は、tkinter が無くても 1 件残らず参照できなければならない
for name in pure:
    try:
        getattr(reminder, name)
    except Exception as exc:
        problems.append(
            f"{name}: tkinter 無しで参照できません ({type(exc).__name__}: {exc})"
        )

# GUI 依存として宣言した公開名は、tkinter が無い環境では ImportError になるのが正しい
for name in gui:
    try:
        getattr(reminder, name)
    except ImportError:
        # 期待どおり（遅延読み込みが効いていて、実際に tkinter を必要としている）
        pass
    except Exception as exc:
        # AttributeError 等は対応表の綴り間違い（定義元モジュール名・シンボル名）を意味する
        problems.append(
            f"{name}: ImportError 以外で失敗しました ({type(exc).__name__}: {exc})"
        )
    else:
        # 参照できてしまう＝eager import に戻ったか、そもそも GUI 依存ではない
        problems.append(
            f"{name}: tkinter 無しで参照できてしまいました（eager import に戻っていませんか）"
        )

# 問題が無ければ "OK" を、あれば 1 行 1 件で報告する
print("OK" if not problems else "\\n".join(problems))
"""


def _eagerly_reexported_names() -> list[str]:
    """``reminder/__init__.py`` が冒頭で相対 import している再エクスポート名を返す。

    ``__all__`` と突き合わせる相手は、``__all__`` 自身とは**独立な手がかり**でなければ
    ならない（同じ一覧から導出すると、一覧が縮んだときに検査も一緒に縮んで無力化する）。
    ここではソースの import 文そのものを読むので、片方だけを編集した差分が必ず現れる。
    """
    # パッケージの __init__.py のパスを取得する（インストール形態に依存しないよう __file__ から引く）
    init_path = Path(reminder.__file__)
    # ソースを構文木として読む（正規表現ではなく本物のパーサで読むので書き方に左右されない）
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    # 収集した再エクスポート名を貯めるリスト
    names: list[str] = []
    # モジュール直下の文だけを見る（関数の中の import は再エクスポートではない）
    for node in tree.body:
        # 相対 import（`from .xxx import yyy`）だけが再エクスポートの形
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            # `as` があればその別名が、なければ元の名前がパッケージ属性になる
            names.extend(alias.asname or alias.name for alias in node.names)
    # 収集した名前の一覧を返す
    return names


class PureImportTests(unittest.TestCase):
    """tkinter をブロックした子プロセスで公開名の解決可否を検証する。"""

    def test_public_names_resolve_as_declared_without_tkinter(self):
        """tkinter 無しでも「GUI 依存でない公開名」が 1 件残らず参照できることを担保する。"""
        # 素の Python 子プロセスで検証スクリプトを実行する（conftest のモック注入を回避）
        result = subprocess.run(
            [sys.executable, "-c", _PROBE_SCRIPT],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        # import 失敗があれば stderr にトレースバックが出るので、メッセージに含めて報告する
        self.assertEqual(
            result.returncode, 0,
            f"純粋ロジックの import が tkinter 無しで失敗しました:\n{result.stderr}",
        )
        # 公開名ごとの検査結果を確認する（問題があれば 1 行 1 件で標準出力に出ている）
        self.assertEqual(
            result.stdout.strip(), "OK",
            "tkinter 無しでの公開名の解決に問題があります:\n" + result.stdout,
        )


class PublicExportSurfaceTests(unittest.TestCase):
    """``__all__`` ・ eager 再エクスポート ・ ``_LAZY_GUI_EXPORTS`` の整合を検証する。"""

    def test_every_public_name_resolves(self):
        """``__all__`` の全ての名前が実際に参照できることを担保する。

        tkinter はモック済み（conftest）なので GUI 依存シンボルもここでは解決できる。
        ``_LAZY_GUI_EXPORTS`` の定義元モジュール名・シンボル名の綴り間違いは、
        この検査でしか捕まらない（子プロセス側は ImportError を期待しているため、
        モジュールが見つからない失敗も同じ「参照できない」に見えてしまう）。
        """
        # 検査対象が 0 件だと常に緑になるので、空の __all__ はそれ自体を失敗とする（fail-closed）
        self.assertTrue(reminder.__all__, "__all__ が空です（検査対象 0 件では常に緑になります）")
        # 公開すると宣言した名前を 1 件ずつ実際に参照してみる
        for name in reminder.__all__:
            # どの名前で落ちたかが分かるようサブテストとして実行する
            with self.subTest(name=name):
                try:
                    # パッケージ属性として取得できるかを試す（遅延読み込みもここで走る）
                    getattr(reminder, name)
                except Exception as exc:  # noqa: BLE001 - 失敗の型を問わず「参照できない」として報告したい
                    # 参照できない公開名は `from reminder import *` を壊すので失敗させる
                    self.fail(
                        f"__all__ に載っている {name!r} を参照できません "
                        f"({type(exc).__name__}: {exc})。"
                        "__all__ の綴り、_LAZY_GUI_EXPORTS の定義元モジュール名、"
                        "定義元から削除されていないかを確認してください。"
                    )

    def test_lazy_gui_exports_are_declared_public(self):
        """``_LAZY_GUI_EXPORTS`` のキーが全て ``__all__`` に載っていることを担保する。"""
        # 遅延読み込みの対応表が空だと検査が空振りするので、まず空でないことを確かめる
        self.assertTrue(
            reminder._LAZY_GUI_EXPORTS,
            "_LAZY_GUI_EXPORTS が空です（検査対象 0 件では常に緑になります）",
        )
        # 対応表にあるのに公開宣言されていない名前を洗い出す
        undeclared = sorted(set(reminder._LAZY_GUI_EXPORTS) - set(reminder.__all__))
        # 1 件でもあれば、公開したつもりの GUI シンボルが `import *` から漏れている
        self.assertEqual(
            undeclared, [],
            f"_LAZY_GUI_EXPORTS にあるのに __all__ へ載っていない名前があります: {undeclared}",
        )

    def test_eager_reexports_are_declared_public(self):
        """冒頭で相対 import している再エクスポート名が全て ``__all__`` に載っていることを担保する。"""
        # ソースの import 文から再エクスポート名を導出する（__all__ とは独立な手がかり）
        eager = _eagerly_reexported_names()
        # 再エクスポートが 1 件も読めないなら導出側が壊れているので、その時点で失敗させる（fail-closed）
        self.assertTrue(
            eager,
            "reminder/__init__.py から再エクスポートを 1 件も読み取れませんでした"
            "（検査対象 0 件では常に緑になります）",
        )
        # 再エクスポートしているのに公開宣言されていない名前を洗い出す
        undeclared = sorted(set(eager) - set(reminder.__all__))
        # 1 件でもあれば、`import *` から漏れる公開シンボルができている
        self.assertEqual(
            undeclared, [],
            f"再エクスポートしているのに __all__ へ載っていない名前があります: {undeclared}。"
            "__all__ へ追加するか、パッケージ直下での再エクスポートをやめてください。",
        )

    def test_all_has_no_duplicates(self):
        """``__all__`` に同じ名前が二重に載っていないことを担保する。

        重複は実害こそ小さいが、上の 2 つの検査が集合（set）で突き合わせるため
        重複だけでは落ちない。名前を移動する編集で「消したつもりが残っている」状態を
        見逃さないよう、ここで明示的に落とす。
        """
        # 出現回数が 2 回以上の名前を重複として集める
        duplicates = sorted({name for name in reminder.__all__ if reminder.__all__.count(name) > 1})
        # 1 件でもあれば重複として報告する
        self.assertEqual(duplicates, [], f"__all__ に重複した名前があります: {duplicates}")


if __name__ == "__main__":  # このファイルを直接実行した場合
    unittest.main()  # ユニットテストを起動する
