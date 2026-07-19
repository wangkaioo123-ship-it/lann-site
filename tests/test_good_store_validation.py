import unittest

from scripts.build_good_store_validation import build, build_metrics, coefficient_variation


class GoodStoreValidationTests(unittest.TestCase):
    def test_stable_revenue_has_zero_variation(self):
        self.assertEqual(coefficient_variation([100, 100, 100]), 0)

    def test_metrics_keep_old_share_distinct_from_repeat_rate(self):
        rows = [
            {"月份": "2026-01", "实际营收": "100", "新客数": "10", "老客数": "30"},
            {"月份": "2026-02", "实际营收": "200", "新客数": "20", "老客数": "40"},
            {"月份": "2026-03", "实际营收": "300", "新客数": "30", "老客数": "50"},
        ]
        metrics = build_metrics(rows)
        self.assertEqual(metrics["平均月新客数"], "20")
        self.assertEqual(metrics["平均月老客数"], "40")
        self.assertEqual(metrics["老客人数占比"], "0.6667")

    def test_opening_partial_month_is_not_used_in_metrics(self):
        rows = [
            {"月份": "2025-12", "实际营收": "10", "月度Gate纳入": "否"},
            {"月份": "2026-01", "实际营收": "100", "月度Gate纳入": "是"},
        ]
        metrics = build_metrics(rows)
        self.assertEqual(metrics["有效营收月份数"], 1)
        self.assertEqual(metrics["平均月营收"], "100")

    def test_validation_uses_benchmark_window(self):
        benchmark = [{"点位ID": "L1", "门店名称": "测试店", "好店经济性Gate": "经济性达标-待完整验证", "统计月份起": "2026-02", "统计月份止": "2026-03"}]
        monthly = [
            {"点位ID": "L1", "月份": "2026-01", "实际营收": "1"},
            {"点位ID": "L1", "月份": "2026-02", "实际营收": "100"},
            {"点位ID": "L1", "月份": "2026-03", "实际营收": "100"},
        ]
        self.assertEqual(build(benchmark, monthly)[0]["有效营收月份数"], 2)

    def test_relocation_is_not_generic_new_site_evidence(self):
        benchmark = [{"点位ID": "L1-02", "门店名称": "测试新铺", "好店经济性Gate": "经济性达标-待完整验证"}]
        monthly = [{"点位ID": "L1-02", "月份": "2026-01", "实际营收": "100"}]
        episodes = [{"analysis_point_id": "L1-02", "resolution_status": "confirmed", "relation_type": "同商场换铺"}]
        row = build(benchmark, monthly, episodes)[0]
        self.assertEqual(row["样本类型"], "迁址/换铺承接样本")


if __name__ == "__main__":
    unittest.main()
