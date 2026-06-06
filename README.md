# automation

自動化ツールをまとめたリポジトリです。

## ツール一覧

### Any Planner — タイムライン型タスクプランナーアプリ

[Any Planner](https://apps.apple.com/jp/app/any-planner-%E3%82%BF%E3%82%B9%E3%82%AF%E7%AE%A1%E7%90%86-todo%E3%83%AA%E3%82%B9%E3%83%88/id6758033935)
のように **1 日のタスクを時間軸（タイムライン）で可視化** する GUI アプリです。
起床〜就寝の範囲にタスクを配置し、**空き時間**を一目で把握できます。今すぐやらない
タスクは「**あとでやる**」リストに保管し、空き時間に収まる候補を提案します。
開始時刻になるとデスクトップ通知で知らせ、繰り返しタスクは **完了した時点を起点** に
次回開始を自動で再計算して登録します。

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

- **デザイン**
  - **TimeTree を参考にしたポップで親しみやすい UI**: 淡いグレー背景に白いカードを
    重ね、ティールグリーンのブランドカラーを差し色にした明るい配色。タスクは
    1 件ずつ色分け（カテゴリ色）して直感的に見分けられます。
  - 配色・フォント・余白は `reminder/theme.py` に一元化しており、ここを編集するだけで
    アプリ全体の見た目を調整できます。

- **機能**
  - **今日のタイムライン**: 起床〜就寝の時間軸にタスクを配置し、タスク間の
    **空き時間**を「空き 2時間10分」のように行で可視化。予定タスクは TimeTree 風に
    色分け（完了＝✓グレー、進行中＝ティール太字、過去未了＝赤、これから＝カテゴリ色）
  - **所要時間**: タスクごとに開始時刻＋所要（分）を設定し、時間ブロックとして扱う
  - **あとでやるリスト**: 時間を割り当てない未スケジュールタスクを保管。今の空き時間に
    収まる候補を緑で提案。「予定に追加」でタイムラインへ、「あとでへ」で逆方向へ移動
  - **起床・就寝時刻**: タイムラインの範囲を生活リズムに合わせて設定（自動保存）
  - **統計**: 今日の完了件数・連続達成日数（ストリーク）・本日の空き時間をヘッダに表示
  - 開始時刻になるとダイアログと通知音／デスクトップ通知で知らせる
  - **繰り返し設定（完了時点から）**: なし / 日 / 週 / 月 / 年 を間隔（1〜99）付きで指定
  - タスクの「完了」「削除」に対応。繰り返しタスクを完了すると、**完了した瞬間** を
    起点に次回タスクが自動で再登録される
  - 未完了のまま日付をまたいだタスクは当日へ繰り越し、前日以前の完了タスクは整理
  - タスク・設定の自動保存・復元（`~/.config/reminder/tasks.json`, `settings.json`）
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
   - **開始**の「時」「分」と**所要(分)**を選択（必要なら **繰り返し** で 日/週/月/年 と間隔を指定）
   - **タイムラインへ** を押すと今日の時間軸に配置（または Enter キー）。時間を決めずに
     保管するときは **あとでへ** を押して「あとでやる」に追加
   - 「あとでやる」のタスクは **予定に追加** で開始時刻を付けてタイムラインへ移せる
   - 開始時刻になるとダイアログと通知音で知らせる

5. タスクを完了・削除したい場合
   - タイムライン／あとでやるリストでタスクを選択し、**完了** または **削除** を押す
   - 繰り返しタスクを **完了** すると、完了した時点を起点に次回タスクが自動登録される
   - ヘッダの **起床／就寝** を変えるとタイムラインの範囲と空き時間表示が更新される

> 補足: ターミナルから `python -m reminder` で直接起動することもできます。

---

## タスク・設定ファイル（自動保存）

タスク一覧と設定（起床/就寝時刻・完了履歴）は自動的に保存/復元されます。

- **Linux**: `~/.config/reminder/tasks.json` / `~/.config/reminder/settings.json`
- **macOS / Windows**: 同等のユーザーディレクトリ配下に保存します（詳細は `reminder/config.py` を参照）

### バックアップ

タスク・設定を退避したい場合は両ファイルをコピーしてください。

```bash
cp ~/.config/reminder/tasks.json    ~/.config/reminder/tasks.json.bak
cp ~/.config/reminder/settings.json ~/.config/reminder/settings.json.bak
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
- `test_timeline.py` — タイムライン構築（空き時間・タスク状態・重なり）、起床/就寝境界、当日繰り越し、完了タスク整理、空き時間提案、時刻整形
- `test_stats.py` — 今日の完了件数・連続達成日数（ストリーク）・総完了数、不正エントリの無視
- `test_task.py` — Task の既定値・所要時間クランプ・あとでやる（未スケジュール）・直列化、`make_due`、`build_next_task`（完了時点起点の次回生成）
- `test_config.py` — タスク/設定の永続化・読み込み、ファイル欠損・非リスト・壊れたエントリ・不正 JSON のハンドリング
- `test_notifications.py` — `play_notification_sound` の各 OS パスと `TclError` の無視、`notify-send` の本文付与、`_set_window_icon`
- `test_planner.py` — 入力正規化、タイムライン/あとでへの追加・完了（繰り返し再登録・統計記録）・削除・移動、通知スケジュール、`main`

---

## ファイル構成

```
automation/
├── reminder/                       # タスクプランナーアプリ パッケージ
│   ├── __init__.py                 # パッケージ公開 API
│   ├── __main__.py                 # エントリーポイント (python -m reminder)
│   ├── cli.py                      # main()（コンソールスクリプト本体）
│   ├── app.py                      # PlannerApp GUI クラス（タイムライン + あとでやる）
│   ├── task.py                     # Task モデル（開始/所要/繰り返し）・次回タスク生成
│   ├── timeline.py                 # 1日のタイムライン構築・空き時間・繰り越し（純粋ロジック）
│   ├── stats.py                    # 完了数・連続達成日数の集計（純粋ロジック）
│   ├── recurrence.py               # 完了時点からの繰り返し計算（日/週/月/年）
│   ├── config.py                   # タスク一覧・設定の永続化 (JSON)
│   ├── notifications.py            # 通知音・デスクトップ通知・アイコン設定
│   ├── time_utils.py               # 開始までの遅延計算・定数
│   └── theme.py                    # デザイントークン（配色・フォント・余白）の一元定義
├── install_reminder_app.sh         # Linux 向けデスクトップエントリ生成
├── requirements.txt
├── requirements-dev.txt            # 開発・テスト用依存
├── assets/
│   └── reminder_icon.svg           # アプリ用アイコン
└── tests/
    ├── __init__.py
    ├── conftest.py                 # tkinter モック設定
    ├── test_recurrence.py
    ├── test_timeline.py
    ├── test_stats.py
    ├── test_task.py
    ├── test_config.py
    ├── test_notifications.py
    ├── test_planner.py
    └── test_theme.py
```
