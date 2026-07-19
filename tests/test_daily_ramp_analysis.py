import unittest

from scripts.build_daily_ramp_analysis import attach_peer_benchmarks, build, classification_by_site, stage


class DailyRampAnalysisTests(unittest.TestCase):
    def test_stage_uses_7_14_28_day_boundaries(self):
        self.assertEqual(stage(6), "数据不足")
        self.assertEqual(stage(7), "7日爬坡观察")
        self.assertEqual(stage(14), "14日爬坡观察")
        self.assertEqual(stage(28), "28日滚动观察")

    def test_classification_requires_unique_match(self):
        base = [{"点位ID": "L1", "门店名称": "上海万科天空之城店"}]
        rows = [{"门店名称": "万科天空", "门店2026分类": "B"}]
        self.assertEqual(classification_by_site(base, rows), {"L1": "B"})

    def test_classification_can_use_confirmed_hanson_alias(self):
        base = [{"点位ID": "L1", "门店名称": "名称不同"}]
        rows = [{"门店名称": "天空之城", "门店2026分类": "B"}]
        mapping = [{"site_id": "L1", "hanson_store_name": "上海天空之城店"}]
        self.assertEqual(classification_by_site(base, rows, mapping), {"L1": "B"})

    def test_classification_can_use_confirmed_business_alias(self):
        rows = [{"门店名称": "龙湖虹桥天街店", "门店2026分类": "B"}]
        aliases = {"龙湖虹桥天街店": "L24"}
        self.assertEqual(classification_by_site([], rows, [], aliases), {"L24": "B"})

    def test_build_outputs_windows_without_good_store_label(self):
        daily = [
            {"data_date": f"2026-07-{day:02d}", "store_name": "测试店", "prod_amt": "100"}
            for day in range(1, 29)
        ]
        mapping = [{"hanson_store_name": "测试店", "site_id": "L1", "status": "confirmed"}]
        base = [{"点位ID": "L1", "门店名称": "上海测试店", "合同开业日期": "2026-07-01"}]
        benchmark = [{"点位ID": "L1", "月租金": "500"}]
        rows = build(daily, mapping, base, benchmark, [], [])
        self.assertEqual(rows[0]["观察阶段"], "28日滚动观察")
        self.assertEqual(rows[0]["近7日日均营收"], "100")
        self.assertIn("不直接形成完整好店结论", rows[0]["输出限制"])

    def test_peer_benchmark_uses_same_tier_median(self):
        rows = [
            {"SABC": "B", "近28日结算日数": 28, "近28日日均营收": "100"},
            {"SABC": "B", "近28日结算日数": 28, "近28日日均营收": "200"},
            {"SABC": "A", "近28日结算日数": 28, "近28日日均营收": "500"},
        ]
        attach_peer_benchmarks(rows)
        self.assertEqual(rows[0]["同类近28日日均中位数"], "150")
        self.assertEqual(rows[0]["同类有效样本数"], 2)


if __name__ == "__main__":
    unittest.main()
