"""パッケージ ``reminder`` の公開エクスポート面（``reminder/__init__.py``）の回帰テスト。

このファイルが守る契約は 2 つある。

1. **GUI（tkinter）非搭載環境でも純粋ロジックが import できること。**
   conftest.py は tkinter が無い環境で MagicMock を注入するため、この検証は
   モック注入の効かない「素の子プロセス」で行う。パッケージの ``__init__`` が
   GUI モジュール（app / notifications / cli）を eager import してしまうと、
   契約共有先（Web/スマホ版）やヘッドレス CI が recurrence / timeline 等の
   純粋ロジックを再利用できなくなる（CLAUDE.md §10）。

2. **``__all__`` ・ eager 再エクスポート ・ ``_LAZY_GUI_EXPORTS`` の 3 つが食い違わないこと。**
   さらに、pyproject の console-scripts が指す名前が実在すること（4 つ目の一覧）。
   ``reminder/__init__.py`` は「どの名前を公開するか」を手書きの一覧 3 つで表しており、
   ずれても実行時まで何も起きない。以下はいずれも **修正前は全件緑のまま通った**（実測）:

   - ``__all__`` に実在しない名前（綴り間違い・削除された関数）を 1 件足す
     → ``from reminder import *`` が AttributeError で落ちるのに 339 件すべて緑。
   - ``_LAZY_GUI_EXPORTS`` の値（定義元モジュール名）を壊す
     → 例えば ``"main": "cli"`` を壊すと、pyproject の console-scripts
       （``reminder = "reminder:main"``）が解決できなくなり **pipx / pip install した
       利用者のコマンドが起動時に失敗する**のに、339 件すべて緑。
   - ``_LAZY_GUI_EXPORTS`` の ``"main"`` 行と ``__all__`` の ``"main"`` を**同じ
     変更セットで**消す（＝上記 3 一覧は整合したまま）→ `pipx install` した利用者の
     ``reminder`` コマンドだけが起動時に失敗するのに全件緑。console-scripts は
     3 一覧のどれでもない**4 つ目の手書き一覧**なので、突き合わせる相手として
     pyproject 側も読む。

   従来の検査は純粋シンボル 3 件（free_minutes_today / next_occurrence /
   current_streak）と GUI シンボル 1 件（PlannerApp）を**名指しで**確かめるだけ
   だったため、名指ししていない公開名はどれだけ壊しても検出できなかった。
   名指しをやめ、``__all__`` から対象を導出して 1 件残らず参照できることを確かめる。

**なぜ ``__all__`` を導出（``eager 名 + list(_LAZY_GUI_EXPORTS)``）にして一覧そのものを
1 つに畳まないか**: ``__all__`` はリテラルの一覧であることに意味がある。リンタ・IDE・
``help()`` はソースの ``__all__`` を静的に読んで補完や未使用検出を行うため、計算式にすると
「このパッケージが何を公開しているか」がファイルを読んでも実行してみるまで分からなくなる。
公開面は人が意図して決めるものなので、**畳まずに一覧のままにして、ずれを機械で落とす**側を
選んでいる（CLAUDE.md §6 の「意図が読み取れない値を散らさない」と同じ向き）。
"""

from __future__ import annotations

import ast  # __init__.py の import 文を「__all__ とは独立な手がかり」として読むために使う
import importlib  # console-scripts が指すモジュールを名前から読み込むために使う
import subprocess  # 子プロセスで素の Python を起動するために使う
import sys  # 現在のインタープリタのパスを得るために使う
import unittest  # 標準のテストフレームワークを使う
from pathlib import Path  # リポジトリルートのパス計算に使う

import reminder  # 検査対象のパッケージ本体（conftest が tkinter のモックを注入済み）

# tomllib は Python 3.11 以降の標準ライブラリ。pyproject の requires-python は >=3.10 なので、
# 3.10 では読めない（CI の test マトリクスは 3.11 / 3.12 / 3.13 なので常に読める）。
# 読めない環境では console-scripts の検査だけをスキップする（他の検査は動かす）。
try:
    import tomllib  # TOML を標準ライブラリで解釈する（3.11+）
except ModuleNotFoundError:  # pragma: no cover - 3.10 でのみ通る枝
    tomllib = None  # type: ignore[assignment]  # スキップ判定に使う番兵として None を入れる

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


# `from . import theme` のようにサブモジュール自体を束縛する形は「公開シンボルの
# 再エクスポート」ではないので導出から外す。外さないと、`reminder/app.py` が既に使っている
# 慣用形を `__init__.py` へ足しただけで「__all__ へ追加するか、再エクスポートをやめろ」と
# 案内されてしまう（壊れていないコードで赤くなる検査はいずれ緩められる）。
#
# 逆に、相対 import だけ・モジュール直下だけに絞ると**照合対象が黙って縮む**。実測では
# `from .timeline import (...)` を `from reminder.timeline import (...)` へ書き換えたり、
# import を try/except で包んだりするだけで、その行の名前が導出から丸ごと消え、
# `__all__` から公開名を削る退行が全件緑（テスト件数も不変）で通った。書き方に左右されない
# よう、自パッケージのサブモジュールからの from-import を、関数・クラスの外であれば
# 制御構文の内側まで含めて拾う。


def _package_level_statements(node: ast.AST):
    """関数・クラスの本体へは降りずに、モジュールレベルの文を再帰的に列挙する。

    `if` / `try` / `with` の内側に置かれた import も「パッケージ属性を作る」点では
    直書きと同じなので拾う。関数・クラスの中の import はローカル束縛なので降りない。
    """
    # 直下の子ノードを 1 つずつ見る
    for child in ast.iter_child_nodes(node):
        # 関数・クラスの中はローカルスコープなので、そこから先は辿らない
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        # この子ノード自身を列挙する
        yield child
        # 制御構文の内側にある文も同じ規則で辿る
        yield from _package_level_statements(child)


def _is_submodule_import(node: ast.ImportFrom) -> bool:
    """`from <自パッケージのサブモジュール> import ...` の形かどうかを判定する。"""
    # `from . import theme` は module が None（サブモジュール束縛）なので対象外
    if node.module is None:
        return False
    # 相対 import（`from .task import ...`）は必ず自パッケージのサブモジュール
    if node.level > 0:
        return True
    # 絶対 import（`from reminder.task import ...`）も同じ再エクスポートの形として扱う
    return node.module.startswith(f"{reminder.__name__}.")


def _eagerly_reexported_names() -> list[str]:
    """``reminder/__init__.py`` が eager に再エクスポートしているシンボル名を返す。

    ``__all__`` と突き合わせる相手は、``__all__`` 自身とは**独立な手がかり**でなければ
    ならない（同じ一覧から導出すると、一覧が縮んだときに検査も一緒に縮んで無力化する）。
    ここではソースの import 文そのものを読むので、片方だけを編集した差分が必ず現れる。

    ``from .x import *`` は導出できる名前が ``"*"`` しかないので、そのまま返して
    呼び出し側が専用の失敗として報告する（ここで黙って捨てると、公開面がまるごと
    照合から外れる fail-open になる）。
    """
    # パッケージの __init__.py のパスを取得する（インストール形態に依存しないよう __file__ から引く）
    init_path = Path(reminder.__file__)
    # ソースを構文木として読む（正規表現ではなく本物のパーサで読むので書き方に左右されない）
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    # 収集した再エクスポート名を貯めるリスト
    names: list[str] = []
    # 関数・クラスの外にあるすべての文を見る（制御構文の内側も含む）
    for node in _package_level_statements(tree):
        # 自パッケージのサブモジュールからの from-import だけが再エクスポートの形
        if isinstance(node, ast.ImportFrom) and _is_submodule_import(node):
            # `as` があればその別名が、なければ元の名前がパッケージ属性になる
            names.extend(alias.asname or alias.name for alias in node.names)
    # 収集した名前の一覧を返す
    return names


def _console_script_targets() -> dict[str, str]:
    """pyproject の ``[project.scripts]``（console-scripts）の定義を返す。

    戻り値は「コマンド名 → ``module:attr``」の対応。`pip install` / `pipx install` が
    作る実行ファイルはこの右辺を import して呼ぶだけなので、ここが指す名前が実在しないと
    **インストールした利用者のコマンドだけが起動時に失敗する**（リポジトリ内の
    ``python -m reminder`` も CI も緑のまま）。
    """
    # pyproject.toml を読み込んで TOML として解釈する
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # [project.scripts] テーブル（未定義なら空）を返す
    return data.get("project", {}).get("scripts", {})


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
                # 失敗の型は問わない（AttributeError も ImportError も「参照できない」で一括して報告したい）
                except Exception as exc:
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

    def test_package_init_does_not_use_star_imports(self):
        """``reminder/__init__.py`` が ``from .x import *`` を使っていないことを担保する。

        星取り込みは「何を公開しているか」がソースから読めず、下の照合でも導出できる名前が
        ``"*"`` しかないため、公開面がまるごと検査から外れる（fail-open）。
        """
        # ソースの import 文から再エクスポート名を導出する
        eager = _eagerly_reexported_names()
        # 星取り込みが 1 つでもあれば、公開面が照合できない状態として落とす
        self.assertNotIn(
            "*", eager,
            "reminder/__init__.py で `from .x import *` が使われています。"
            "公開する名前を明示的に列挙してください"
            "（星取り込みは公開面を照合できなくします）。",
        )

    def test_console_script_entry_points_resolve(self):
        """pyproject の console-scripts が指す名前が実際に解決できることを担保する。

        console-scripts は ``__all__`` ・ eager 再エクスポート ・ ``_LAZY_GUI_EXPORTS`` の
        どれでもない **4 つ目の手書き一覧**で、3 つを整合させたまま ``main`` を消しても
        リポジトリ内では何も壊れない（``python -m reminder`` は ``reminder/__main__.py``
        を通るため）。壊れるのは ``pip install`` / ``pipx install`` した利用者の
        ``reminder`` コマンドだけなので、ここで突き合わせておく。
        """
        # 3.10 には tomllib が無いので、その環境ではこの検査だけをスキップする
        if tomllib is None:  # pragma: no cover - 3.10 でのみ通る枝
            self.skipTest("tomllib が無い（Python 3.10）ため console-scripts を読めない")
        # pyproject の [project.scripts] を読み取る
        scripts = _console_script_targets()
        # 定義が 0 件だと常に緑になるため、空の場合はそれ自体を失敗とする（fail-closed）
        self.assertTrue(
            scripts,
            "pyproject.toml に [project.scripts] がありません"
            "（検査対象 0 件では常に緑になります）。",
        )
        # 定義されたコマンドを 1 件ずつ解決してみる
        for command, target in scripts.items():
            # どのコマンドで落ちたかが分かるようサブテストとして実行する
            with self.subTest(command=command):
                # "module:attr" の形を分解する（":" が無ければ attr が空になる）
                module_path, separator, attribute = target.partition(":")
                # console-scripts は必ず "module:attr" の形でなければ呼び出せない
                self.assertTrue(
                    separator and attribute,
                    f"console-script {command!r} の指定 {target!r} が "
                    '"module:attr" の形になっていません。',
                )
                try:
                    # 左辺のモジュールを読み込み、右辺の属性を取得できるか試す
                    getattr(importlib.import_module(module_path), attribute)
                # 失敗の型は問わない（モジュール不在も属性不在も「コマンドが起動できない」で同じ）
                except Exception as exc:
                    # 解決できない console-script はインストール後に必ず起動時エラーになる
                    self.fail(
                        f"console-script {command!r} が指す {target!r} を解決できません "
                        f"({type(exc).__name__}: {exc})。"
                        "pip install / pipx install した利用者のコマンドが起動時に失敗します。"
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
