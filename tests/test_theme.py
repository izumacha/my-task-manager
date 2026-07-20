"""tests/test_theme.py — デザイントークン（reminder.theme）のテスト

theme モジュールは GUI 非依存の純粋な定数・関数なので、tkinter 無しで検証できる。
配色の一貫性（同じキーには常に同じ色）と、パレット定義の健全性を担保する。
"""
import unittest

from reminder import theme


class PaletteIntegrityTests(unittest.TestCase):
    """カラーパレット・絵文字の定義が壊れていないことを検証する。"""

    def test_palette_and_dots_same_length(self):
        # category_index は色数で剰余を取るため、色とドットの数は一致が必須。
        self.assertEqual(len(theme.CATEGORY_COLORS), len(theme.CATEGORY_DOTS))
        self.assertGreater(len(theme.CATEGORY_COLORS), 0)

    def test_colors_are_hex_pairs(self):
        for bg, fg in theme.CATEGORY_COLORS:
            for color in (bg, fg):
                self.assertTrue(color.startswith("#"), color)
                self.assertEqual(len(color), 7, color)
                int(color[1:], 16)  # 16進として解釈できること

    def test_brand_and_state_colors_are_hex(self):
        for color in (theme.BRAND, theme.BRAND_DARK, theme.BRAND_SOFT, theme.BG,
                      theme.CARD, theme.TEXT, theme.TEXT_MUTED, theme.DONE_BG,
                      theme.PAST_BG, theme.PAST_FG):
            self.assertTrue(color.startswith("#") and len(color) == 7, color)
            int(color[1:], 16)


class CategoryIndexTests(unittest.TestCase):
    """category_index の安定性・範囲・フォールバックを検証する。"""

    def test_within_range(self):
        n = len(theme.CATEGORY_COLORS)
        for key in ("abc", "タスク", "x" * 100, "id-12345", "🟢"):
            self.assertIn(theme.category_index(key), range(n))

    def test_deterministic(self):
        # 同じキーは常に同じ色番号（再描画やプラットフォーム間でぶれない）。
        self.assertEqual(theme.category_index("設計レビュー"),
                         theme.category_index("設計レビュー"))

    def test_empty_key_falls_back_to_zero(self):
        self.assertEqual(theme.category_index(""), 0)


class CategoryColorDotTests(unittest.TestCase):
    """category_color / category_dot がインデックスと整合することを検証する。"""

    def test_color_matches_index(self):
        key = "ランチ"
        self.assertEqual(theme.category_color(key),
                         theme.CATEGORY_COLORS[theme.category_index(key)])

    def test_dot_matches_index(self):
        key = "ランチ"
        self.assertEqual(theme.category_dot(key),
                         theme.CATEGORY_DOTS[theme.category_index(key)])

    def test_color_is_member_of_palette(self):
        self.assertIn(theme.category_color("読書"), theme.CATEGORY_COLORS)


class LayoutTokenTests(unittest.TestCase):
    """レイアウト（寸法・余白・間隔）トークンの健全性を検証する。"""

    def test_dimension_tokens_are_positive_ints(self):
        # 寸法トークンはすべて「正の整数（ピクセル）」であること（tkinter に渡せる値）。
        for name in ("WINDOW_MIN_WIDTH", "WINDOW_MIN_HEIGHT", "TIMELINE_PANEL_WIDTH",
                     "BACKLOG_COL_TITLE_WIDTH", "BACKLOG_COL_DUR_WIDTH",
                     "BACKLOG_COL_RECUR_WIDTH", "PAD_LG", "PAD_MD", "PAD_SM",
                     "SPACE_XS", "SPACE_SM", "SPACE_MD", "SPACE_LG", "SPACE_XL",
                     "SPACE_XXL", "HEADER_GROUP_GAP", "PANEL_GAP", "ENTRY_IPADY"):
            value = getattr(theme, name)  # トークン名から実際の値を取り出す
            self.assertIsInstance(value, int, name)  # 値が整数であることを確認する
            self.assertGreater(value, 0, name)  # 値が正（0 より大きい）であることを確認する

    def test_spacing_scale_is_monotonic(self):
        # 間隔スケールは名前の序列どおり単調増加であること（XS < SM < ... < XXL）。
        scale = (theme.SPACE_XS, theme.SPACE_SM, theme.SPACE_MD,
                 theme.SPACE_LG, theme.SPACE_XL, theme.SPACE_XXL)  # 小さい順に並べたスケールのタプル
        self.assertEqual(list(scale), sorted(scale))  # 並びが昇順ソート結果と一致することを確認する

    def test_padding_scale_is_monotonic(self):
        # 余白スケールも名前の序列どおり単調増加であること（SM < MD < LG）。
        pads = (theme.PAD_SM, theme.PAD_MD, theme.PAD_LG)  # 小さい順に並べた余白トークンのタプル
        self.assertEqual(list(pads), sorted(pads))  # 並びが昇順ソート結果と一致することを確認する


if __name__ == "__main__":
    unittest.main()
