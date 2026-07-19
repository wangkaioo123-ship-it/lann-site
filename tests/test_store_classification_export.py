import unittest

from scripts.export_store_classification_from_feishu import normalize_rows


class StoreClassificationExportTests(unittest.TestCase):
    def test_normalizes_formula_results_and_excel_date(self):
        values = [
            ["门店名称"],
            [
                "测试店",
                "上海",
                "加盟",
                45282,
                "A",
                "A",
                "中高",
                "中",
                "按摩",
                "商圈店",
                "成熟店",
                208.3,
                48.9,
                587,
                2500,
                9,
                "A",
            ],
        ]

        rows = normalize_rows(values, "https://example.test")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["开业日期"], "2023-12-22")
        self.assertEqual(rows[0]["月均新客"], 208.3)
        self.assertEqual(rows[0]["月均营业额_万元"], 48.9)
        self.assertEqual(rows[0]["门店2026分类"], "A")
        self.assertEqual(rows[0]["来源链接"], "https://example.test")


if __name__ == "__main__":
    unittest.main()
