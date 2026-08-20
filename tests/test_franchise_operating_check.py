import unittest
from datetime import date

from services.franchise_operating_check import build_operating_check_candidates


AS_OF = date(2026, 8, 17)


def monthly_rows(
    site_id="L0001",
    revenues=(300000, 300000, 300000, 270000, 250000, 240000),
    customers=(500, 500, 500, 470, 450, 430),
    new_customers=(120, 120, 120, 110, 100, 95),
    old_customers=(380, 380, 380, 360, 350, 335),
    workdays=(200, 200, 200, 190, 180, 175),
    therapist_output=(1500, 1500, 1500, 1500, 1520, 1510),
    rent_ratios=(0.2, 0.2, 0.2, 0.22, 0.24, 0.25),
):
    months = ("2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07")
    rows = []
    for index, month in enumerate(months):
        rows.append(
            {
                "点位ID": site_id,
                "门店名称": f"测试门店{site_id}",
                "门店属性": "加盟",
                "门店状态": "运营中",
                "月份": month,
                "实际营收": str(revenues[index]),
                "新客数": str(new_customers[index]),
                "老客数": str(old_customers[index]),
                "总客数": str(customers[index]),
                "理疗师工作人天": str(workdays[index]),
                "理疗师日均产值": str(therapist_output[index]),
                "留存率": "35",
                "返店频次": "1.8",
                "租售比": str(rent_ratios[index]),
                "月度Gate纳入": "是",
            }
        )
    return rows


class FranchiseOperatingCheckTests(unittest.TestCase):
    def build(self, rows, target_month=None):
        return build_operating_check_candidates(rows, today=AS_OF, target_month=target_month)

    def test_combined_decline_creates_candidate_without_causal_claim(self):
        result = self.build(monthly_rows())
        candidate = result["stores"]["L0001"]["candidate"]
        self.assertTrue(result["global"]["ready"])
        self.assertIsNotNone(candidate)
        self.assertIn("operating-combination-decline", candidate["trigger_codes"])
        self.assertNotIn("导致", candidate["hypotheses"])

    def test_single_metric_decline_does_not_create_candidate(self):
        result = self.build(
            monthly_rows(
                customers=(500,) * 6,
                new_customers=(120,) * 6,
                old_customers=(380,) * 6,
                workdays=(200,) * 6,
                therapist_output=(1500, 1500, 1500, 1320, 1280, 1250),
            )
        )
        self.assertIsNone(result["stores"]["L0001"]["candidate"])

    def test_rent_pressure_requires_revenue_decline(self):
        result = self.build(
            monthly_rows(
                revenues=(300000, 300000, 300000, 290000, 285000, 280000),
                customers=(500,) * 6,
                new_customers=(120,) * 6,
                old_customers=(380,) * 6,
                workdays=(200,) * 6,
                rent_ratios=(0.26, 0.26, 0.26, 0.27, 0.28, 0.29),
            )
        )
        self.assertIn("rent-pressure-with-revenue-decline", result["stores"]["L0001"]["candidate"]["trigger_codes"])

    def test_global_data_gate_stops_all_candidates(self):
        complete = monthly_rows("L0001")
        incomplete = monthly_rows("L0002")
        incomplete[-1]["理疗师工作人天"] = ""
        incomplete[-1]["点位ID"] = ""
        result = self.build(complete + incomplete)
        self.assertFalse(result["global"]["ready"])
        self.assertIn("未映射", result["global"]["message"])
        self.assertIsNone(result["stores"]["L0001"]["candidate"])

    def test_current_incomplete_month_is_trend_only(self):
        rows = monthly_rows()
        rows.append({**rows[-1], "月份": "2026-08", "实际营收": "1000", "月度Gate纳入": "否"})
        result = self.build(rows)
        self.assertTrue(result["global"]["ready"])
        self.assertEqual(result["global"]["latest_month"], "2026-07")

    def test_explicit_historical_month_can_be_replayed(self):
        result = build_operating_check_candidates(monthly_rows(), today=date(2026, 12, 1), target_month="2026-07")
        self.assertTrue(result["global"]["ready"])
        self.assertEqual(result["global"]["latest_month"], "2026-07")

    def test_future_month_is_rejected_even_when_explicit(self):
        rows = monthly_rows()
        rows.append({**rows[-1], "月份": "2026-08", "月度Gate纳入": "是"})
        result = build_operating_check_candidates(rows, today=date(2026, 8, 17), target_month="2026-08")
        self.assertFalse(result["global"]["ready"])
        self.assertIn("尚未闭月", result["global"]["message"])


if __name__ == "__main__":
    unittest.main()
