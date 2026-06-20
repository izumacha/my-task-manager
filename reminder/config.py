"""タスク一覧と設定の永続化（JSON）。

タスクは ``~/.config/reminder/tasks.json`` に配列として保存される。
起床/就寝時刻や完了履歴などの設定は ``settings.json`` に保存される。
読み込み時に壊れたエントリは黙ってスキップし、アプリの起動を妨げない。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field

from .task import Task
from .timeline import DEFAULT_SLEEP_MIN, DEFAULT_WAKE_MIN, min_to_hhmm

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "reminder")  # 設定ファイルを置くディレクトリのパスを組み立てる
_TASKS_PATH = os.path.join(_CONFIG_DIR, "tasks.json")  # タスク一覧を保存するJSONファイルのフルパスを定義する
_SETTINGS_PATH = os.path.join(_CONFIG_DIR, "settings.json")  # アプリ設定を保存するJSONファイルのフルパスを定義する


@dataclass
class Prefs:
    """永続化するアプリ設定。

    Attributes:
        wake: 起床時刻（"HH:MM"）。タイムラインの開始境界。
        sleep: 就寝時刻（"HH:MM"）。タイムラインの終了境界。
        completions: 完了日時（ISO 文字列）の履歴。統計に使用する。
    """

    wake: str = field(default_factory=lambda: min_to_hhmm(DEFAULT_WAKE_MIN))  # 起床時刻のデフォルト値をデフォルト起床分から生成する
    sleep: str = field(default_factory=lambda: min_to_hhmm(DEFAULT_SLEEP_MIN))  # 就寝時刻のデフォルト値をデフォルト就寝分から生成する
    completions: list[str] = field(default_factory=list)  # 完了履歴リストを空リストで初期化する


def load_prefs() -> Prefs:
    """設定を読み込む。存在しない/壊れている場合は既定値を返す。"""
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:  # 設定ファイルを UTF-8 で開く
            data = json.load(f)  # JSON として読み込んで辞書に変換する
    except FileNotFoundError:  # ファイルが存在しない場合
        return Prefs()  # デフォルト設定を返す
    except Exception as e:  # その他のエラー（壊れたJSONなど）が発生した場合
        logging.warning("設定ファイルの読み込みに失敗しました (%s): %s", _SETTINGS_PATH, e)  # 失敗したパスと原因例外の両方を残す（§6: 例外を握り潰さない）
        return Prefs()  # デフォルト設定を返す

    if not isinstance(data, dict):  # 読み込んだデータが辞書でない場合（不正な形式）
        return Prefs()  # デフォルト設定を返す

    prefs = Prefs(**{k: v for k, v in data.items() if k in Prefs.__dataclass_fields__})  # 既知のフィールドだけを使って Prefs を生成する
    # completions は文字列リストであることを保証する（壊れた値は捨てる）
    if not isinstance(prefs.completions, list):  # completions がリストでない場合（不正な型）
        prefs.completions = []  # 空リストにリセットして不正な値を捨てる
    else:
        prefs.completions = [c for c in prefs.completions if isinstance(c, str)]  # 文字列でない要素を除去して文字列リストだけ保持する
    return prefs  # 正常に読み込んだ設定を返す


def save_prefs(prefs: Prefs) -> None:
    """設定を JSON ファイルに書き出す。"""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)  # 設定ディレクトリが存在しない場合は作成する
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:  # 設定ファイルを書き込みモードで開く
            json.dump(asdict(prefs), f, ensure_ascii=False, indent=2)  # Prefs を辞書に変換してインデント付きJSONとして書き出す
    except Exception as e:  # ファイル書き込みで何らかのエラーが発生した場合
        logging.warning("設定ファイルの保存に失敗しました: %s", e)  # 警告ログにエラー内容を記録する


def load_tasks() -> list[Task]:
    """タスク一覧を読み込む。ファイルが無い/壊れている場合は空リストを返す。"""
    try:
        with open(_TASKS_PATH, encoding="utf-8") as f:  # タスクファイルを UTF-8 で開く
            data = json.load(f)  # JSON として読み込んでリストに変換する
    except FileNotFoundError:  # ファイルが存在しない場合（初回起動など）
        return []  # タスクが存在しないとして空リストを返す
    except Exception as e:  # その他のエラー（壊れたJSONなど）が発生した場合
        logging.warning("タスクファイルの読み込みに失敗しました (%s): %s", _TASKS_PATH, e)  # 失敗したパスと原因例外の両方を残す（§6: 例外を握り潰さない）
        return []  # 読み込み失敗なので空リストを返す

    if not isinstance(data, list):  # 読み込んだデータがリストでない場合（不正な形式）
        return []  # 空リストを返して不正なデータを無視する

    tasks: list[Task] = []  # 読み込んだタスクを蓄積するリストを初期化する
    seen_ids: set[str] = set()  # 重複IDを検出するためにすでに見たIDを記録するセットを初期化する
    for entry in data:  # JSONから読み込んだ各エントリに対してループする
        if not isinstance(entry, dict):  # エントリが辞書でない場合（不正な要素）
            continue  # そのエントリをスキップして次へ進む
        try:
            task = Task.from_dict(entry)  # 辞書からTaskオブジェクトを生成する
        except Exception:
            # 1 件壊れていても残りは読み込めるよう、個別にスキップする
            logging.debug("壊れたタスクエントリをスキップしました: %r", entry)  # デバッグログにスキップしたエントリを記録する
            continue  # このエントリをスキップして次のエントリへ進む
        # Treeview の iid には task.id を使うため「空でない一意な文字列」でなければならない。
        # 手編集や不正なマージで id が空文字・非文字列（例: 123）・重複になっていると、
        # 空文字は Treeview のルート item と衝突し、非文字列は選択時に文字列化されて
        # _selected_task() がマッチできない。これらの場合は再採番して起動不能を防ぐ。
        if not isinstance(task.id, str) or not task.id or task.id in seen_ids:  # IDが不正（非文字列・空・重複）な場合
            task.id = uuid.uuid4().hex  # ランダムな一意IDを新たに割り当てる
        seen_ids.add(task.id)  # このIDを「使用済み」として記録する
        tasks.append(task)  # 正常なタスクをリストに追加する
    return tasks  # 読み込んだタスクのリストを返す


def save_tasks(tasks: list[Task]) -> None:
    """タスク一覧を JSON ファイルに書き出す。"""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)  # 設定ディレクトリが存在しない場合は作成する
        with open(_TASKS_PATH, "w", encoding="utf-8") as f:  # タスクファイルを書き込みモードで開く
            json.dump([t.to_dict() for t in tasks], f, ensure_ascii=False, indent=2)  # 全タスクを辞書リストに変換してインデント付きJSONとして書き出す
    except Exception as e:  # ファイル書き込みで何らかのエラーが発生した場合
        logging.warning("タスクファイルの保存に失敗しました: %s", e)  # 警告ログにエラー内容を記録する
