# CLAUDE.md — Claude Code 向けプロジェクト情報

このファイルは Claude Code が参照するプロジェクト固有のガイドラインです。

## プロジェクト概要

Python 製の自動化ツールをまとめたリポジトリです。現在は Any Planner 風の GUI タスクプランナーアプリ (`reminder/` パッケージ) が含まれています。1 日のタスクを**カレンダー（デイビュー）**で可視化し、空き時間や「あとでやる」リストを扱います。繰り返しタスクは「完了した時点」を起点に日/週/月/年で再スケジュールされます。

UI は TimeTree / Google カレンダーを参考にした「ポップで親しみやすい」デザインを採用しています。今日のタスクは縦の時間軸（起床〜就寝）に、所要時間ぶんの高さを持つ色付きブロックとして配置され、空き時間は「ブロックの無い余白」としてそのまま見えます。配色・フォント・余白・カレンダーの寸法などのデザイントークンは `reminder/theme.py` に一元化しています。

## 開発ハーネス（必達方針）

以下はこのプロジェクトのすべての変更が満たすべき横断的な方針です。**新機能・リファクタ・バグ修正のいずれでも常に意識し、レビュー時の合否基準とします。**

### 1. セキュリティを堅牢に

- **入力は信用しない**: 外部入力（ユーザー入力・設定ファイル・JSON・環境変数など）は必ず検証し、`_coerce_int()` パターンのように範囲外はクランプ・不正値はデフォルトへフォールバックする。壊れたデータでクラッシュさせない。
- **最小権限・最小公開**: 読み書きするファイルは想定パス配下（`~/.config/reminder/` 等）に限定する。パス結合は `os.path.join` を使い、外部由来の値をそのままパスに連結しない（パストラバーサル防止）。
- **危険な実行を避ける**: `eval`/`exec`/`pickle`/`shell=True` を使わない。外部コマンドは引数配列で `subprocess` 実行し、ユーザー入力を文字列連結でシェルに渡さない。設定の永続化は JSON のみ（任意オブジェクトの復元をしない）。
- **秘密情報を残さない**: 認証情報・トークン・個人情報をコード・ログ・コミットに含めない。ログは `logging` を使い、機微情報を出力しない。
- **依存を最小・既知に保つ**: 新規依存の追加は慎重に行い、オプション依存は `ImportError` で graceful degradation する（例: `cairosvg`）。
- **失敗しても安全側に倒す**: 例外時はクラッシュや権限昇格ではなく、機能を縮退して継続する（fail-safe）。

### 2. 初めてリポジトリを見る人でも分かる説明と構成

- **前提知識ゼロを想定**: README とコメントは、このリポジトリ・ドメイン・ツールを初めて見る人が読んで理解・実行できる粒度で書く。専門用語には一言の補足を添える。
- **「動かし方」を最優先で明記**: セットアップ・実行・テストの手順を、コピペで動くコマンドとして README 冒頭付近に置く。
- **自己説明的な構成**: モジュールは単一責務に分割し、ファイル名・関数名から役割が推測できるようにする。公開関数には日本語 docstring を必須とする。
- **地図を維持する**: ファイルを追加・改名・削除したら、この CLAUDE.md の「主要ファイル」表と「アーキテクチャ」節、および README を必ず同時に更新する（ドキュメントとコードの乖離を許さない）。
- **設計判断を残す**: 非自明な実装やトレードオフには「なぜそうしたか」をコメントで残す。

### 3. Web 版・アプリ版・スマホ版で差異ゼロを目指す設計

- **ロジックと UI を分離する**: ビジネスロジックは GUI 非依存の純粋関数として保つ（`timeline.py` / `stats.py` / `recurrence.py` / `task.py` の方針を踏襲）。表示層を差し替えてもロジックは共有できる状態を維持する。
- **デザイントークンを一元化する**: 配色・フォント・余白・文言は `reminder/theme.py` のような単一の参照元に集約し、各プラットフォームの表示層はそれを読むだけにする。見た目の値をコードに直書きしない。
- **プラットフォーム差を 1 か所に閉じ込める**: OS / 実行環境固有の処理は `platform.system()` 分岐などで局所化し、必ずフォールバックを用意する（既存のクロスプラットフォーム規約を厳守）。
- **同一の振る舞いを保証する**: 同じ操作は Web・デスクトップ・モバイルで同じ結果になるよう、判定ロジックは共有層に置きテストで担保する。プラットフォーム専用の分岐を表示層以外に増やさない。
- **移植可能な書き方をする**: `strftime` の `%-d` など非移植な指定子を避けるなど、特定 OS でしか動かない記述を持ち込まない。

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
| `reminder/app.py` | PlannerApp GUI クラス（カレンダー Canvas + あとでやるリスト） |
| `reminder/theme.py` | デザイントークン（配色・フォント・余白・カレンダー寸法）の一元定義。TimeTree 風のポップな見た目とプラットフォーム差異ゼロ設計の基盤 |
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
- **`theme.py`**: 配色（ブランド色・状態色・タスクのカテゴリパレット）・フォント・余白・カレンダー寸法（`HOUR_HEIGHT` 等）などのデザイントークンと、タスクへ安定した色を割り当てる `category_color()` / `category_dot()`。GUI 非依存の純粋定数・関数。見た目を変えるときはここだけを編集すればよく、表示層（`app.py`）はトークンを参照するだけにする。
- **`app.py` のカレンダー描画**: 今日のタスクは Treeview ではなく `tk.Canvas` で「デイビュー」として描画する（`_render_timeline` と補助の `_draw_time_grid` / `_draw_task_block` / `_draw_now_line` / `_assign_lanes`）。位置・高さは分→px 換算（`HOUR_HEIGHT`）で算出し、Canvas の実サイズに依存しない（テストで Canvas をモックしても算術が壊れない）。ブロックの選択はクリックされた `task.id` を `self._tl_selected` に保持する方式で、`build_day_timeline()` の純粋ロジックをそのまま再利用する。
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
