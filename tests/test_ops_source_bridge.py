import unittest

from scripts.build_ops_source_bridge import combine
from scripts.refresh_hanson_daily_ops import build_monthly, build_trends


class OpsSourceBridgeTests(unittest.TestCase):
    def test_only_complete_closed_month_is_included(self):
        daily = [
            {"data_date": f"2026-04-{day:02d}", "store_id": 1, "store_name": "测试店", "prod_amt": 100}
            for day in range(1, 31)
        ] + [{"data_date": "2026-05-01", "store_id": 1, "store_name": "测试店", "prod_amt": 100}]
        mapping = [{"Hanson门店名称": "测试店", "确认点位ID": "L0001"}]
        monthly, _ = build_monthly(daily, mapping)
        self.assertEqual(monthly[0]["分析纳入"], "是")
        self.assertEqual(monthly[0]["实际营收"], "3000.00")
        self.assertEqual(monthly[1]["分析纳入"], "否")

    def test_unmapped_store_is_rejected(self):
        daily = [
            {"data_date": f"2026-04-{day:02d}", "store_id": 1, "store_name": "未知店", "prod_amt": 100}
            for day in range(1, 31)
        ] + [{"data_date": "2026-05-01", "store_id": 1, "store_name": "未知店", "prod_amt": 100}]
        monthly, issues = build_monthly(daily, [])
        self.assertEqual(monthly[0]["分析纳入"], "否")
        self.assertIn("门店未映射", issues[0]["问题"])

    def test_bridge_switches_after_confirmed_cutoff(self):
        official = [
            {"点位ID": "L1", "Hanson门店名称": "测试店", "月份": "2026-03", "实际营收": "100", "数据来源": "official"},
            {"点位ID": "L1", "Hanson门店名称": "测试店", "月份": "2026-04", "实际营收": "999", "数据来源": "official"},
        ]
        daily = [
            {"点位ID": "L1", "Hanson门店名称": "测试店", "月份": "2026-04", "实际营收": "101", "分析纳入": "是", "数据来源": "daily"}
        ]
        customers = [
            {"store_name": "测试店", "data_month": "2026-04", "new_customer_count": 10, "old_customer_count": 20, "order_customer_times": 40, "retention_base_count": 25, "retained_customer_count": 10, "customer_order_count": 45, "customer_segments": 2}
        ]
        rows = combine(official, daily, "2026-03", customers)
        self.assertEqual([(row["月份"], row["实际营收"]) for row in rows], [("2026-03", "100"), ("2026-04", "101")])
        self.assertEqual(rows[1]["新客数"], "10")
        self.assertEqual(rows[1]["老客数"], "20")
        self.assertEqual(rows[1]["客单价_折扣后"], "2.52")
        self.assertEqual(rows[1]["留存率"], "40.00")
        self.assertEqual(rows[1]["返店频次"], "1.50")

    def test_trend_ignores_partially_closed_latest_day(self):
        daily = []
        for day in range(1, 4):
            for store_id, name in ((1, "甲店"), (2, "乙店")):
                daily.append({"data_date": f"2026-05-{day:02d}", "store_id": store_id, "store_name": name, "prod_amt": 100})
        daily.append({"data_date": "2026-05-04", "store_id": 1, "store_name": "甲店", "prod_amt": 999})
        mapping = [
            {"Hanson门店名称": "甲店", "确认点位ID": "L1"},
            {"Hanson门店名称": "乙店", "确认点位ID": "L2"},
        ]
        rows = build_trends(daily, mapping)
        self.assertEqual(rows[0]["数据截止日"], "2026-05-03")
        self.assertEqual(rows[0]["近30日营收"], "300.00")

    def test_trend_uses_current_physical_point_episode(self):
        daily = [{"data_date": "2026-05-01", "store_id": 1, "store_name": "换铺店", "prod_amt": 100}]
        mapping = [{"hanson_store_name": "换铺店", "site_id": "L1", "status": "confirmed"}]
        episodes = [{"hanson_store_name": "换铺店", "analysis_point_id": "L1-02", "effective_start": "2026-04-01", "effective_end": "", "resolution_status": "confirmed"}]
        self.assertEqual(build_trends(daily, mapping, episodes)[0]["点位ID"], "L1-02")


if __name__ == "__main__":
    unittest.main()
