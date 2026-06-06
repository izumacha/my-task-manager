# CLAUDE.md — Claude Code 向けプロジェクト情報

このファイルは Claude Code が参照するプロジェクト固有のガイドラインです。

## プロジェクト概要

Python 製の自動化ツールをまとめたリポジトリです。現在は Any Planner 風の GUI タスクプランナーアプリ (`reminder/` パッケージ) が含まれています。1 日のタスクを時間軸（タイムライン）で可視化し、空き時間や「あとでやる」リストを扱います。繰り返しタスクは「完了した時点」を起点に日/週/月/年で再スケジュールされます。

## 言語・スタイル

- Python 3.x
- コメント・変数名は **日本語または英語** どちらでも可
- インデント: スペース 4 つ
- 既存コードのスタイルに合わせること

## テスト

```bash
python -m pytest tests
```

- テストフレームワーク: `pytest`
- テストファイルは `tests/` ディレクトリに配置
- テストは必ず通過させること

## 依存パッケージ

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # 開発・テスト用
```

## 主要ファイル

| ファイル | 説明 |
|---|---|
| `reminder/app.py` | PlannerApp GUI クラス（タイムライン + あとでやるリスト） |
| `reminder/task.py` | Task モデル（開始/所要/繰り返し）・完了時の次回タスク生成 |
| `reminder/timeline.py` | 1日のタイムライン構築・空き時間・繰り越し（純粋ロジック） |
| `reminder/stats.py` | 完了数・連続達成日数の集計（純粋ロジック） |
| `reminder/recurrence.py` | 完了時点からの繰り返し計算（日/週/月/年） |
| `reminder/config.py` | タスク一覧・設定の永続化（JSON） |
| `reminder/notifications.py` | 通知音・デスクトップ通知・アイコン設定 |
| `reminder/time_utils.py` | 開始までの遅延計算・定数 |
| `reminder/cli.py` | `main()`（コンソールスクリプト本体） |
| `reminder/__main__.py` | エントリーポイント（`python -m reminder`） |
| `install_reminder_app.sh` | Linux デスクトップエントリ生成スクリプト |
| `tests/test_*.py` | ユニットテスト（モジュール別） |
| `assets/reminder_icon.svg` | アプリアイコン |

## アーキテクチャ

### reminder パッケージの構成

- **`recurrence.py`**: `next_occurrence()` / `add_period()` と繰り返し単位定数（`RECUR_DAILY` 等）。完了時点を起点に次回期限を算出する純粋ロジック。月末日・うるう年はクランプする。
- **`task.py`**: `Task` dataclass（開始 `due`・所要 `duration_min`・繰り返し。`due` が空文字なら「あとでやる」）と `build_next_task()`（完了時点から次回タスクを生成）、`make_due()`（時刻→開始日時、`roll_if_past` で当日固定可）。
- **`timeline.py`**: `build_day_timeline()`（起床〜就寝に配置しタスク間の空き時間行を生成）、`carry_over_overdue()`（未完了の繰り越し）、`prune_old_completed()`、`suggest_for_free_time()`、時刻整形ヘルパー。GUI 非依存の純粋関数群。
- **`stats.py`**: `completed_count_on()` / `current_streak()` / `total_completed()`。完了履歴（ISO 文字列リスト）から集計する純粋ロジック。
- **`time_utils.py`**: `delay_ms_until()` および定数。GUI から独立したユーティリティ。
- **`notifications.py`**: `play_notification_sound()`, `_set_window_icon()` および OS 別ヘルパー。
- **`config.py`**: `load_tasks()` / `save_tasks()` でタスク配列を、`load_prefs()` / `save_prefs()` で設定（`Prefs`: 起床/就寝/完了履歴）を `~/.config/reminder/` に永続化。壊れたエントリは個別にスキップする。
- **`app.py`**: `PlannerApp` クラス。`__init__` で読み込み→繰り越し/整理→状態初期化→`_build_ui()`→`_refresh()`（タイムライン/バックログ/統計の再描画）→`_schedule_all()`。テスト時は `_build_ui` / `_refresh` / `_schedule_all` をモックして Tk インスタンスなしでテスト可能。`ReminderApp` は後方互換エイリアス。
- **クロスプラットフォーム対応**: macOS (`afplay`), Windows (`winsound`), Linux (`notify-send` + `tk.bell()`) を `platform.system()` で分岐。新しい OS 固有機能を追加する場合も同じパターンに従う。`strftime` の `%-d` 等の非移植な指定子は使わない（Windows で失敗するため）。

## クロスプラットフォーム規約

- OS 固有の処理は `platform.system()` で分岐し、必ずフォールバックを用意する。
- 外部コマンド（`afplay` 等）は `subprocess` で実行し、UI スレッドをブロックしないよう `threading.Thread` で包む。
- `cairosvg` はオプション依存。`ImportError` 時は graceful に degradation する（アイコンなしで動作継続）。

## テスト規約

- テストは `tests/` ディレクトリに `test_<モジュール名>.py` で配置。
- tkinter の `StringVar` / `IntVar` はテスト用の `_DummyVar` クラスで代替する（`tests/test_planner.py` 参照）。
- `_create_app()` ファクトリ関数でモック済みのテストインスタンスを生成する。
- OS 依存の処理は `@patch` でモックし、特定 OS でしか動かないテストを作らない。
- 境界値テスト（0, 23, 59, 空文字列, 非数値）を重視する。

## Git 規約

- コミットメッセージ形式: `type(scope): 説明`
  - type: feat, fix, refactor, test, docs, chore
  - scope: reminder, install, tests 等
- 例: `fix(reminder): afplay を別スレッドで実行して UI ブロック回避`

## コーディング規約（追加）

- `from __future__ import annotations` を各モジュール先頭に記述（型ヒントの前方互換）。
- 公開関数には日本語 docstring を付ける。
- 入力値の検証は `_coerce_int()` パターン（範囲外→クランプ、非数値→デフォルト）に従う。
- 定数はモジュールレベルで `UPPER_SNAKE_CASE` で定義（例: `DEFAULT_SNOOZE_MINUTES = 5`）。
- エラーハンドリング: クラッシュさせず `try-except` で graceful degradation。ログは `logging` モジュールを使用。

## PR・実装ガイドライン

- 変更前にテストが通ることを確認
- GUI に関わる変更は tkinter との互換性を維持
- 新機能追加時は対応するテストも追加
- コミットメッセージは変更内容を明確に記述
