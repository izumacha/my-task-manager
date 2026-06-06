# automation

自動化ツールをまとめたリポジトリです。

## ツール一覧

### Any Planner — タスクプランナーアプリ

Any.do のようにタスクを一覧で管理する GUI アプリです。タスクを追加し、期限時刻に
デスクトップ通知で知らせます。繰り返しタスクは **完了した時点を起点** に次回期限を
自動で再計算して登録します。

- **起動方法**

  ```bash
  python -m reminder
  ```

- **pipx でインストールして起動（推奨）**

  ```bash
  pipx install git+https://github.com/izumacha/automation.git
  reminder
  ```

- **.svg アイコンから起動できるアプリ化（Linux）**

  ```bash
  ./install_reminder_app.sh
  ```

  実行後、`~/.local/share/applications/reminder.desktop` が生成され、
  `assets/reminder_icon.svg` をアイコンにした「Any Planner」アプリとして起動できます。

- **機能**
  - タスク名と期限時刻（時・分）を入力してタスクを追加
  - タスク一覧（Treeview）で期限・繰り返し設定を一覧表示（期限切れは赤字で強調）
  - 期限時刻になるとダイアログと通知音／デスクトップ通知で知らせる
  - **繰り返し設定（完了時点から）**: なし / 日 / 週 / 月 / 年 を間隔（1〜99）付きで指定
  - タスクの「完了」「削除」に対応。繰り返しタスクを完了すると、**完了した瞬間** を
    起点に次回タスクが自動で再登録される
  - タスク一覧の自動保存・復元（`~/.config/reminder/tasks.json`）
  - OS ネイティブテーマによるモダンな UI
  - `assets/reminder_icon.svg` をウィンドウアイコンとして表示（`cairosvg` が必要）

#### 「完了時点からの繰り返し」とは

一般的なリマインダーは「元の予定日」を基準に次回を決めますが、本アプリは
**タスクを完了した日時** を基準に次回期限を算出します。

例: 「掃除（毎週）」を予定の 2 日遅れで完了した場合でも、次回は *完了した日* から
1 週間後に設定されます。こなしたタイミングから一定間隔をあけたいタスク
（掃除・運動・水やり・支払いなど）に向いています。

| 単位 | 例（完了が 6/6 22:00 の場合） |
|---|---|
| 日（間隔 1） | 6/7 22:00 |
| 週（間隔 2） | 6/20 22:00 |
| 月（間隔 1） | 7/6 22:00（月末日は短い月の末日にクランプ） |
| 年（間隔 1） | 翌年 6/6 22:00（2/29 は平年 2/28 にクランプ） |

---

## セットアップ

```bash
pip install -r requirements.txt
```

デスクトップアプリとして使う場合は、上記インストール後に `./install_reminder_app.sh` を実行してください。

| パッケージ | 用途 |
|---|---|
| `cairosvg` | SVG アイコンの PNG 変換（ウィンドウアイコン表示） |

---

## リマインダーアプリをデスクトップアプリとして使う手順（Linux）

以下の手順で、ターミナルを開かずにランチャーから使えるアプリとして利用できます。

1. 依存パッケージをインストール

   ```bash
   pip install -r requirements.txt
   ```

2. アプリをインストール（`.desktop` 作成）

   ```bash
   ./install_reminder_app.sh
   ```

3. アプリ一覧で **Any Planner** を検索して起動
   - 作成されるファイル: `~/.local/share/applications/reminder.desktop`
   - アイコン: `assets/reminder_icon.svg`

4. 初回起動後の使い方
   - タスク名を入力
   - 期限の「時」「分」を選択
   - 必要なら **繰り返し（完了時点から）** で 日/週/月/年 と間隔を指定
   - **追加** を押す（または Enter キー）
   - 期限時刻になるとダイアログと通知音で知らせる

5. タスクを完了・削除したい場合
   - 一覧でタスクを選択し、**完了** または **削除** を押す
   - 繰り返しタスクを **完了** すると、完了した時点を起点に次回タスクが自動登録される

> 補足: ターミナルから `python -m reminder` で直接起動することもできます。

---

## タスクファイル（自動保存）

タスク一覧は自動的に保存/復元されます。

- **Linux**: `~/.config/reminder/tasks.json`
- **macOS / Windows**: 同等のユーザーディレクトリ配下に保存します（詳細は `reminder/config.py` を参照）

### バックアップ

タスクを退避したい場合は `tasks.json` をコピーしてください。

```bash
cp ~/.config/reminder/tasks.json ~/.config/reminder/tasks.json.bak
```

### 互換性

将来キーが増えても、未知のキーは無視されます。また、壊れたタスクエントリが 1 件あっても
残りのタスクは読み込まれ、アプリの起動を妨げません。

---

## 配布（ワンクリック起動）案

GUI アプリとして「配布してダブルクリックで起動したい」場合は、`pyinstaller` を使う案があります。

- メリット: Python 未導入の環境でも配布しやすい
- デメリット: バイナリが大きくなる、OSごとにビルドが必要

例（macOS / Linux のイメージ）:

```bash
pip install pyinstaller
pyinstaller -F -w -n reminder reminder/__main__.py
```

> 将来的に GitHub Actions で各OS向けにビルドして Release に添付する運用も可能です。

---

## テスト

```bash
python -m pytest tests
```

`tests/` では以下を検証しています。

- `test_recurrence.py` — 完了時点からの繰り返し計算（日/週/月/年・間隔）、月末/うるう年クランプ、ラベル⇔単位変換
- `test_task.py` — Task の既定値・正規化・直列化、`make_due`（翌日ロールオーバー）、`build_next_task`（完了時点起点の次回生成）
- `test_config.py` — タスクの永続化・読み込み、ファイル欠損・非リスト・壊れたエントリ・不正 JSON のハンドリング
- `test_notifications.py` — `play_notification_sound` の各 OS パスと `TclError` の無視、`notify-send` の本文付与、`_set_window_icon`
- `test_planner.py` — `delay_ms_until` の境界値、`_coerce_int` / 入力正規化、`add_task` / `complete_selected`（繰り返し再登録）/ `delete_selected`、通知スケジュール、`main`

---

## ファイル構成

```
automation/
├── reminder/                       # タスクプランナーアプリ パッケージ
│   ├── __init__.py                 # パッケージ公開 API
│   ├── __main__.py                 # エントリーポイント (python -m reminder)
│   ├── app.py                      # PlannerApp GUI クラス
│   ├── task.py                     # Task モデル・完了時の次回タスク生成
│   ├── recurrence.py               # 完了時点からの繰り返し計算（日/週/月/年）
│   ├── config.py                   # タスク一覧の永続化 (JSON)
│   ├── notifications.py            # 通知音・デスクトップ通知・アイコン設定
│   └── time_utils.py               # 期限までの遅延計算・定数
├── install_reminder_app.sh         # Linux 向けデスクトップエントリ生成
├── requirements.txt
├── requirements-dev.txt            # 開発・テスト用依存
├── assets/
│   └── reminder_icon.svg           # アプリ用アイコン
└── tests/
    ├── __init__.py
    ├── conftest.py                 # tkinter モック設定
    ├── test_recurrence.py
    ├── test_task.py
    ├── test_config.py
    ├── test_notifications.py
    └── test_planner.py
```
