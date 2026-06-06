"""tests/test_recurrence_contract.py — 言語非依存の契約ケースで recurrence を検証する。

`contract/recurrence_cases.json` は「入力 → 期待出力」を言語非依存の JSON として
固定した『真実の源』である。本テストはその JSON を読み込み、Python 実装の
``next_occurrence()`` が契約どおりの結果を返すことをケースごとに検証する。
将来 Web 版 / スマホ版を実装する際も同じ JSON を読めば同一の振る舞いを保証できる
（1コア全プラットフォーム差異ゼロの担保）。

既存の tests/test_recurrence.py はそのまま残し、回帰の二重防御とする。
"""
from __future__ import annotations

import datetime  # ISO 文字列と datetime を相互変換するために使う
import json  # 契約ケースの JSON を読み込むために使う
from pathlib import Path  # OS 非依存でファイルパスを組み立てるために使う

import pytest  # パラメトライズ実行のために使う

from reminder.recurrence import next_occurrence  # 検証対象の繰り返し計算関数
from reminder.task import ISO_FMT  # 日時文字列の書式（%Y-%m-%dT%H:%M:%S）を共有する

# このテストファイルからリポジトリ直下の contract/recurrence_cases.json への絶対パスを解決する
# （__file__ は tests/ 配下にあるため parents[1] がリポジトリルートになる）
_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contract" / "recurrence_cases.json"


def _load_cases() -> list[dict]:
    """契約 JSON を読み込み、ケースの配列（リスト）を返す。

    JSON のみを読み込む安全な入力経路であり、任意オブジェクトの復元は行わない。
    """
    # JSON ファイルを UTF-8 として開いて読み込む（日本語のケース名を含むため）
    with _CONTRACT_PATH.open(encoding="utf-8") as fp:
        # JSON 全体を Python の辞書に変換する
        data = json.load(fp)
    # トップレベルの "cases" キーにケース配列が入っているので、それを取り出して返す
    return data["cases"]


# モジュール読み込み時に一度だけ契約ケースを読み込んでおく（パラメトライズに渡すため）
_CASES = _load_cases()


def _parse(value: str | None) -> datetime.datetime | None:
    """ISO 文字列を datetime に変換する。null（None）はそのまま None を返す。"""
    # 期待値が null（繰り返しなし）の場合は変換せず None を返す
    if value is None:
        return None
    # ISO_FMT に従って文字列を datetime に変換して返す
    return datetime.datetime.strptime(value, ISO_FMT)


# 各ケースを 1 件ずつテスト関数に流し込む。id にはケース名を使い、失敗時に特定しやすくする
@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_next_occurrence_matches_contract(case: dict) -> None:
    """next_occurrence の実出力が契約 JSON の expected と一致することを検証する。"""
    # 起点となる完了日時の ISO 文字列を datetime に変換する
    completed_at = _parse(case["completed_at"])
    # 期待される次回日時（または None）を datetime に変換する
    expected = _parse(case["expected"])
    # 実装を呼び出して実際の次回日時を計算する（引数順は completed_at, unit, interval）
    actual = next_occurrence(completed_at, case["unit"], case["interval"])
    # 実出力と期待値が完全に一致することを表明する（不一致ならケース名付きで失敗する）
    assert actual == expected


def test_contract_file_has_cases() -> None:
    """契約ファイルが空でない（最低限のケース数を備える）ことを保証する。"""
    # ケースが 1 件も無いと契約が空洞化するため、十分な件数があることを確認する
    assert len(_CASES) >= 10
