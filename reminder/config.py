"""タスク一覧と設定の永続化（JSON）。

タスクは ``~/.config/reminder/tasks.json`` に配列として保存される。
起床/就寝時刻や完了履歴などの設定は ``settings.json`` に保存される。
読み込み時に壊れたエントリは黙ってスキップし、アプリの起動を妨げない。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field

from .task import Task
from .timeline import DEFAULT_SLEEP_MIN, DEFAULT_WAKE_MIN, hhmm_to_min, min_to_hhmm

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "reminder")  # 設定ファイルを置くディレクトリのパスを組み立てる
_TASKS_PATH = os.path.join(_CONFIG_DIR, "tasks.json")  # タスク一覧を保存するJSONファイルのフルパスを定義する
_SETTINGS_PATH = os.path.join(_CONFIG_DIR, "settings.json")  # アプリ設定を保存するJSONファイルのフルパスを定義する
_CORRUPT_SUFFIX = ".corrupt"  # 読めないファイルを退避するときに元のパス末尾へ付ける拡張子

# 設計判断: 一時的な I/O エラー（権限不足・ディスク障害などの OSError）で読み込めなかった
# ファイルのパスを記録しておく集合。壊れた JSON と違い、ファイル自体は健全なまま
# 「読めなかっただけ」の可能性が高いので、.corrupt への退避（改名）はしない。さらに、
# このセッション中に save_* が既定値ベースの内容でそのファイルを上書きすると、ディスク上の
# 健全なデータを丸ごと失ってしまうため、再び読み込みに成功するまで保存を拒否する
# （§9 fail-safe: 「読めなかったファイルには書かない」を安全側の既定とする）。
_failed_load_paths: set[str] = set()  # 読み込みに失敗した（保存を拒否すべき）ファイルパスの集合


def _preserve_corrupt_file(path: str) -> None:
    """読み込めないファイルを ``path + ".corrupt"`` へ退避（改名）して保全する。

    壊れた JSON を読み込めなかった場合、そのまま空データで起動すると次回の
    save_* が壊れたファイルを新しい内容で上書きし、ユーザーが手動で直せた
    はずのデータが完全に失われてしまう。それを防ぐため、フォールバック前に
    元ファイルを退避先へ改名して残す（§9 fail-safe）。

    方針: 退避先に前回の退避ファイルが残っている場合は**上書き**する
    （常に「最新の壊れたファイル」を 1 つだけ残すシンプルな運用。世代管理は
    しない）。退避自体に失敗してもアプリの起動は妨げず、警告ログだけ残して
    続行する。
    """
    backup_path = path + _CORRUPT_SUFFIX  # 退避先のパス（元のパス + ".corrupt"）を組み立てる
    try:
        os.replace(path, backup_path)  # 壊れたファイルを退避先へ改名して保全する（既存の退避ファイルがあれば上書き）
    except OSError as e:  # 改名に失敗した場合（権限不足・ファイルが既に無い等）
        logging.warning("壊れたファイルの退避に失敗しました (%s → %s): %s", path, backup_path, e)  # 退避失敗も握り潰さずログに残す（§6）
        return  # 退避できなくても読み込み処理自体は続行する（fail-safe）
    logging.warning("読み込めないファイルを %s へ退避しました。必要ならこのファイルから手動で復旧できます。", backup_path)  # 退避先の場所をユーザーへ知らせる


def _atomic_write_json(path: str, payload: object) -> None:
    """payload を JSON として path へ原子的（アトミック）に書き出す。

    まず同じディレクトリ内の一時ファイルへ全内容を書き、最後に os.replace で
    本番ファイルへ「一気に」差し替える。こうすると、書き込み途中でクラッシュ・
    電源断・例外が起きても本番ファイルは壊れない。本番パスを直接 "w" で開くと
    開いた瞬間に中身が空に切り詰められ、途中で失敗するとユーザーの全タスク／
    設定を丸ごと失う恐れがあるため、その事故を防ぐのが狙い（§9 fail-safe）。

    一時ファイルを同一ディレクトリに作るのは、os.replace が同じファイルシステム
    上でのみ原子的に働くため。os.replace は POSIX / Windows どちらでも原子的に
    置き換わる（§10 移植性）。失敗時は一時ファイルを後始末し、例外を呼び出し元へ
    再送出して save_* 側でログに残せるようにする。
    """
    directory = os.path.dirname(path) or "."  # 一時ファイルを本番ファイルと同じディレクトリに作るため親ディレクトリを取り出す（空なら現在地）
    os.makedirs(directory, exist_ok=True)  # 保存先ディレクトリが存在しない場合は作成する
    # delete=False ではなく mkstemp を使い、書き込み後に os.replace で本番へ差し替える
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")  # 同一ディレクトリ上に一時ファイルを作成しFDを得る
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:  # 低レベルFDをUTF-8テキストファイルとして開く（with終了時にcloseされる）
            json.dump(payload, f, ensure_ascii=False, indent=2)  # ペイロードをインデント付きJSONとして一時ファイルへ書き出す
            f.flush()  # PythonのバッファをOSへ確実に渡す
            os.fsync(f.fileno())  # OSバッファをディスクへ同期し、置き換え後に中身が空になる事故を防ぐ
        os.replace(tmp_path, path)  # 一時ファイルを本番ファイルへ原子的に差し替える（成功時は一時ファイルは消える）
    except Exception:  # 書き込みまたは置き換えに失敗した場合
        try:
            os.unlink(tmp_path)  # 書きかけの一時ファイルを削除して後始末する（本番ファイルは無傷のまま）
        except OSError:  # 一時ファイルが既に無い等で削除に失敗しても
            pass  # 後始末の失敗は致命的ではないため無視する
        raise  # 元の例外を呼び出し元へ再送出し、save_* 側で警告ログに残せるようにする


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
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as e:  # 中身が JSON / UTF-8 として解釈できない・異常に深いネストで解析不能な場合（本当に壊れたファイル）
        logging.warning("設定ファイルの読み込みに失敗しました (%s): %s", _SETTINGS_PATH, e)  # 失敗したパスと原因例外の両方を残す（§6: 例外を握り潰さない）
        _preserve_corrupt_file(_SETTINGS_PATH)  # 壊れた設定ファイルを退避し、次回 save_prefs での上書き消失を防ぐ
        return Prefs()  # デフォルト設定を返す
    except OSError as e:  # 権限不足・ディスク障害などの一時的な I/O エラーで開けなかった/読めなかった場合
        # ファイルの中身は健全なまま読めなかっただけの可能性が高いので、退避（改名）せず
        # そのまま残し、このセッション中の save_prefs による上書きも拒否する（_failed_load_paths のコメント参照）
        logging.warning("設定ファイルを一時的なI/Oエラーで読み込めませんでした (%s): %s", _SETTINGS_PATH, e)  # 隔離せずに済ませた理由が追えるよう原因を残す（§6）
        _failed_load_paths.add(_SETTINGS_PATH)  # 保存拒否の対象としてこのパスを記録する（fail-safe）
        return Prefs()  # ファイルには一切手を付けず、デフォルト設定で継続する
    _failed_load_paths.discard(_SETTINGS_PATH)  # 読み込みに成功したので、このパスへの保存拒否を解除する

    if not isinstance(data, dict):  # 読み込んだデータが辞書でない場合（不正な形式）
        logging.warning("設定ファイルの形式が不正です (%s): 辞書形式ではありません", _SETTINGS_PATH)  # 形式不正も黙って捨てずログに残す（§6）
        _preserve_corrupt_file(_SETTINGS_PATH)  # 形式不正のファイルも同様に退避してから既定値へフォールバックする
        return Prefs()  # デフォルト設定を返す

    prefs = Prefs(**{k: v for k, v in data.items() if k in Prefs.__dataclass_fields__})  # 既知のフィールドだけを使って Prefs を生成する
    # completions は文字列リストであることを保証する（壊れた値は捨てる）
    if not isinstance(prefs.completions, list):  # completions がリストでない場合（不正な型）
        prefs.completions = []  # 空リストにリセットして不正な値を捨てる
    else:
        prefs.completions = [c for c in prefs.completions if isinstance(c, str)]  # 文字列でない要素を除去して文字列リストだけ保持する
    # /code-review ultra 指摘対応: wake/sleep は completions と異なり検証されておらず、
    # 不正値（数値・null・範囲外の "HH:MM" 等）が settings.json に混入すると、
    # PlannerApp._wake_min()/_sleep_min() 側の例外処理で毎回デフォルトへ黙って
    # フォールバックし続け（ログに残らない）、しかも save_prefs() のたびに壊れた
    # 値がそのまま書き戻され続けてしまう。他のフォールバックと同じく警告ログを
    # 残した上で、ここで一度だけ正規の "HH:MM" 文字列に正規化する
    prefs.wake = _coerce_hhmm(prefs.wake, DEFAULT_WAKE_MIN, "wake")  # 起床時刻を検証し、不正なら既定値へ正規化する
    prefs.sleep = _coerce_hhmm(prefs.sleep, DEFAULT_SLEEP_MIN, "sleep")  # 就寝時刻を検証し、不正なら既定値へ正規化する
    return prefs  # 正常に読み込んだ設定を返す


def _coerce_hhmm(value: object, default_minutes: int, field_name: str) -> str:
    """設定値を "HH:MM" 形式の文字列として検証し、不正なら警告ログを残して既定値へ正規化する。"""
    if isinstance(value, str):  # 文字列型であれば形式・範囲の検証を試みる
        try:
            hhmm_to_min(value)  # "HH:MM" として解釈できるか（0〜23時・0〜59分か）を検証する
            return value  # 検証を通過した値はそのまま採用する
        except ValueError:
            pass  # 形式・範囲が不正な場合は下の警告ログ＋既定値フォールバックへ進む
    # 文字列以外の型（数値・null・リスト等）、または "HH:MM" として解釈できない文字列
    logging.warning(
        "設定ファイルの %s が不正なため既定値を使用します (%s): %r", field_name, _SETTINGS_PATH, value
    )  # 他のフォールバックと同じく、警告ログに壊れた値を残す（§6: 例外を握り潰さない）
    return min_to_hhmm(default_minutes)  # 既定値を "HH:MM" 文字列に整形して返す


def save_prefs(prefs: Prefs) -> None:
    """設定を JSON ファイルに原子的に書き出す（途中失敗で既存設定を壊さない）。"""
    if _SETTINGS_PATH in _failed_load_paths:  # このセッション中に一時的な I/O エラーで読み込めなかったファイルの場合
        logging.warning("設定ファイルは読み込みに失敗しているため、上書き保存を中止しました (%s)", _SETTINGS_PATH)  # 保存を拒否したことを黙って捨てずログに残す（§6）
        return  # ディスク上の健全なデータを既定値ベースの内容で潰さないよう保存しない（fail-safe）
    try:
        _atomic_write_json(_SETTINGS_PATH, asdict(prefs))  # 一時ファイル経由で安全に設定を書き出す
    except Exception as e:  # ファイル書き込みで何らかのエラーが発生した場合
        logging.warning("設定ファイルの保存に失敗しました (%s): %s", _SETTINGS_PATH, e)  # 失敗したパスと原因例外の両方を残す（§6: 例外を握り潰さない）


def load_tasks() -> list[Task]:
    """タスク一覧を読み込む。ファイルが無い/壊れている場合は空リストを返す。"""
    try:
        with open(_TASKS_PATH, encoding="utf-8") as f:  # タスクファイルを UTF-8 で開く
            data = json.load(f)  # JSON として読み込んでリストに変換する
    except FileNotFoundError:  # ファイルが存在しない場合（初回起動など）
        return []  # タスクが存在しないとして空リストを返す
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as e:  # 中身が JSON / UTF-8 として解釈できない・異常に深いネストで解析不能な場合（本当に壊れたファイル）
        logging.warning("タスクファイルの読み込みに失敗しました (%s): %s", _TASKS_PATH, e)  # 失敗したパスと原因例外の両方を残す（§6: 例外を握り潰さない）
        _preserve_corrupt_file(_TASKS_PATH)  # 壊れたタスクファイルを退避し、次回 save_tasks での上書き消失を防ぐ
        return []  # 読み込み失敗なので空リストを返す
    except OSError as e:  # 権限不足・ディスク障害などの一時的な I/O エラーで開けなかった/読めなかった場合
        # ファイルの中身は健全なまま読めなかっただけの可能性が高いので、退避（改名）せず
        # そのまま残し、このセッション中の save_tasks による上書きも拒否する（_failed_load_paths のコメント参照）
        logging.warning("タスクファイルを一時的なI/Oエラーで読み込めませんでした (%s): %s", _TASKS_PATH, e)  # 隔離せずに済ませた理由が追えるよう原因を残す（§6）
        _failed_load_paths.add(_TASKS_PATH)  # 保存拒否の対象としてこのパスを記録する（fail-safe）
        return []  # ファイルには一切手を付けず、空リストで継続する
    _failed_load_paths.discard(_TASKS_PATH)  # 読み込みに成功したので、このパスへの保存拒否を解除する

    if not isinstance(data, list):  # 読み込んだデータがリストでない場合（不正な形式）
        logging.warning("タスクファイルの形式が不正です (%s): リスト形式ではありません", _TASKS_PATH)  # 形式不正も黙って捨てずログに残す（§6）
        _preserve_corrupt_file(_TASKS_PATH)  # 形式不正のファイルも同様に退避してから空リストへフォールバックする
        return []  # 空リストを返して不正なデータを無視する

    tasks: list[Task] = []  # 読み込んだタスクを蓄積するリストを初期化する
    seen_ids: set[str] = set()  # 重複IDを検出するためにすでに見たIDを記録するセットを初期化する
    # スキップは「静かな永久欠損」になり得る（読み込まれなかったエントリは次回 save_tasks で
    # ファイルから消える）ため、debug ではなく warning で残す。アプリは INFO レベルで起動する
    # （cli.py の basicConfig）ので、debug ではユーザーに一切見えないまま消えてしまう。
    # ログにはエントリ全文ではなく「何件目か＋タイトル」だけを載せる（長大な本文でログを埋めない）。
    for index, entry in enumerate(data):  # JSONから読み込んだ各エントリに対して、位置（何件目か）付きでループする
        if not isinstance(entry, dict):  # エントリが辞書でない場合（不正な要素）
            logging.warning("壊れたタスクエントリをスキップしました (%d件目): 辞書形式ではありません", index + 1)  # 何件目が捨てられたかを警告ログで知らせる
            continue  # そのエントリをスキップして次へ進む
        try:
            task = Task.from_dict(entry)  # 辞書からTaskオブジェクトを生成する
        except Exception as e:  # 1 件壊れていても残りは読み込めるよう、個別にスキップする
            logging.warning(
                "壊れたタスクエントリをスキップしました (%d件目, title=%r): %s", index + 1, entry.get("title"), e
            )  # どのエントリが捨てられたか（位置とタイトル）と原因例外を警告ログで知らせる
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
    """タスク一覧を JSON ファイルに原子的に書き出す（途中失敗で既存タスクを壊さない）。"""
    if _TASKS_PATH in _failed_load_paths:  # このセッション中に一時的な I/O エラーで読み込めなかったファイルの場合
        logging.warning("タスクファイルは読み込みに失敗しているため、上書き保存を中止しました (%s)", _TASKS_PATH)  # 保存を拒否したことを黙って捨てずログに残す（§6）
        return  # ディスク上の健全なデータを既定値ベースの内容で潰さないよう保存しない（fail-safe）
    try:
        _atomic_write_json(_TASKS_PATH, [t.to_dict() for t in tasks])  # 一時ファイル経由で安全にタスク一覧を書き出す
    except Exception as e:  # ファイル書き込みで何らかのエラーが発生した場合
        logging.warning("タスクファイルの保存に失敗しました (%s): %s", _TASKS_PATH, e)  # 失敗したパスと原因例外の両方を残す（§6: 例外を握り潰さない）
