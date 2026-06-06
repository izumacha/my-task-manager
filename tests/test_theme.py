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


if __name__ == "__main__":
    unittest.main()
