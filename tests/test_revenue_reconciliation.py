import unittest

from scripts.reconcile_bi_revenue_sources import compare, dedupe_monthly, normalize_name


class RevenueReconciliationTests(unittest.TestCase):
    def test_city_prefix_is_part_of_store_identity(self):
        self.assertNotEqual(normalize_name("上海万象城店"), normalize_name("成都万象城店"))

    def test_latest_monthly_batch_wins(self):
        rows = [
            {"store_id": "1", "store_name": "花木店", "data_month": "2026-01", "real_income_with_marketing": 10, "created_at": "2026-02-01"},
            {"store_id": "1", "store_name": "花木店", "data_month": "2026-01", "real_income_with_marketing": 20, "created_at": "2026-02-02"},
        ]
        latest = dedupe_monthly(rows)
        self.assertEqual(latest[("1", "2026-01")]["real_income_with_marketing"], 20)

    def test_sources_match_by_normalized_store_name(self):
        monthly = {
            ("100", "2026-01"): {
                "store_id": "100",
                "store_name": "花木店",
                "data_month": "2026-01",
                "real_income_with_marketing": 100,
            }
        }
        daily = [{"store_id": "1", "store_name": "花木店", "data_month": "2026-01", "daily_prod_amt": 101, "day_count": 31}]
        rows = compare(monthly, daily)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["对账状态"], "差异<=1%")
        self.assertEqual(rows[0]["月度门店ID"], "100")
        self.assertEqual(rows[0]["日结门店ID"], "1")

    def test_duplicate_daily_store_names_are_summed(self):
        monthly = {
            ("100", "2026-01"): {
                "store_id": "100",
                "store_name": "测试店",
                "data_month": "2026-01",
                "real_income_with_marketing": 100,
            }
        }
        daily = [
            {"store_id": "1", "store_name": "测试店", "data_month": "2026-01", "daily_prod_amt": 40},
            {"store_id": "2", "store_name": "测试店", "data_month": "2026-01", "daily_prod_amt": 60},
        ]
        row = compare(monthly, daily)[0]
        self.assertEqual(row["日结月合计"], "100.00")
        self.assertEqual(row["日结ID数"], 2)

    def test_zero_monthly_value_is_not_reported_as_match(self):
        monthly = {
            ("100", "2026-01"): {
                "store_id": "100",
                "store_name": "测试店",
                "data_month": "2026-01",
                "real_income_with_marketing": 0,
            }
        }
        daily = [{"store_id": "1", "store_name": "测试店", "data_month": "2026-01", "daily_prod_amt": 50, "day_count": 1}]
        self.assertEqual(compare(monthly, daily)[0]["对账状态"], "月度值为0")


if __name__ == "__main__":
    unittest.main()
