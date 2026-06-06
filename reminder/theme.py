"""アプリ全体のデザイントークン（配色・フォント・余白）を集約するモジュール。

TimeTree を参考にした「ポップで親しみやすい」見た目を、ここで定義した
トークンだけで再現できるようにしている。色やフォントを変えたいときは
このファイルだけを編集すればよく、Web 版・アプリ版・スマホ版へ展開する
際も同じトークン表を共有することで**プラットフォーム間の見た目の差異**を
最小化することを狙う（CLAUDE.md「クロスプラットフォーム設計」を参照）。

GUI フレームワーク（tkinter）に依存しない純粋な定数・関数のみを置く。
"""
from __future__ import annotations

# ------------------------------------------------------------ ブランド / 基調色

# TimeTree 風のさわやかなティールグリーンをブランドカラーにする。
BRAND = "#2BC4A8"          # プライマリ（主要ボタン・現在進行中の強調）
BRAND_DARK = "#1FA890"     # プライマリの押下/ホバー相当
BRAND_SOFT = "#E5F8F4"     # ブランド色の淡いトーン（バッジ背景など）

# ページ背景は淡いグレー、カードは白にして「浮いた」印象を出す。
BG = "#F4F6F8"             # ウィンドウ全体の背景
CARD = "#FFFFFF"           # カード（パネル）の背景
BORDER = "#E3E7EC"         # カードの境界線・区切り線

# テキスト色（コントラストを確保しつつ柔らかく）
TEXT = "#2B3038"           # 主要テキスト
TEXT_MUTED = "#8A94A6"     # 補助テキスト・空き時間など
TEXT_ON_BRAND = "#FFFFFF"  # ブランド色背景の上に載せる文字

# 状態色
DONE_BG = "#EEF1F4"        # 完了タスクの背景
DONE_FG = "#A7B0BE"        # 完了タスクの文字
PAST_BG = "#FDECEC"        # 期限超過（未完了）の背景
PAST_FG = "#E0524B"        # 期限超過の文字
NOW_FG = TEXT_ON_BRAND     # 現在進行中の文字
SUGGEST_FG = BRAND_DARK    # 「あとでやる」の空き時間提案

# ------------------------------------------------------------ タスクのカラーパレット

# TimeTree のように 1 つ 1 つの予定を色分けするためのポップなパレット。
# （背景色, その上に載せる文字色）の組で持つ。
CATEGORY_COLORS: tuple[tuple[str, str], ...] = (
    ("#FFE2E0", "#C0392B"),  # コーラル
    ("#FFF1D6", "#B9770E"),  # イエロー
    ("#E3F1FF", "#2266A8"),  # スカイブルー
    ("#E8E6FF", "#5B4BC4"),  # パープル
    ("#E3F8E8", "#1E9E54"),  # グリーン
    ("#FFE6F1", "#C2417E"),  # ピンク
    ("#FFEAD9", "#C46314"),  # オレンジ
    ("#DCF5F2", "#0E8C7C"),  # ティール
)

# 各タスク色の先頭に付ける「丸ポチ」相当の絵文字（凡例的な彩り）。
CATEGORY_DOTS: tuple[str, ...] = ("🔴", "🟡", "🔵", "🟣", "🟢", "🩷", "🟠", "🩵")

# ------------------------------------------------------------ フォント

# tkinter のフォント指定で使うファミリ。OS 既定の "system" を基本にする。
FONT_FAMILY = "system"
FONT_BASE = (FONT_FAMILY, 11)
FONT_SMALL = (FONT_FAMILY, 10)
FONT_HEADING = (FONT_FAMILY, 13, "bold")
FONT_DATE = (FONT_FAMILY, 16, "bold")
FONT_STATS = (FONT_FAMILY, 11, "bold")
FONT_BOLD = (FONT_FAMILY, 11, "bold")

# Treeview の行の高さ（ゆったり見せて可読性を上げる）。
ROW_HEIGHT = 30


def category_index(key: str) -> int:
    """タスクを表す文字列（id 等）から安定したカラー番号を返す。

    同じ key には常に同じ色を割り当てるため、再描画やプラットフォームを
    またいでも配色がぶれない。
    """
    if not key:
        return 0
    total = sum(ord(ch) for ch in key)
    return total % len(CATEGORY_COLORS)


def category_color(key: str) -> tuple[str, str]:
    """key に対応する (背景色, 文字色) を返す。"""
    return CATEGORY_COLORS[category_index(key)]


def category_dot(key: str) -> str:
    """key に対応する丸ポチ絵文字を返す。"""
    return CATEGORY_DOTS[category_index(key)]
