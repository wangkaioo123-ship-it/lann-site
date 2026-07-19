import unittest

from scripts.build_rent_ratio_sensitivity import build, qualifies


class RentRatioSensitivityTests(unittest.TestCase):
    def test_threshold_change_only_affects_boundary_store(self):
        row = {"有效营收月份数": "12", "近12月平均月营收": "300000", "租售比": "0.159"}
        self.assertFalse(qualifies(row, 0.15, 12))
        self.assertTrue(qualifies(row, 0.16, 12))

    def test_low_revenue_never_passes(self):
        row = {"有效营收月份数": "12", "近12月平均月营收": "279999", "租售比": "0.10"}
        self.assertFalse(qualifies(row, 0.18, 12))

    def test_summary_reports_newly_added_sites(self):
        rows = [
            {"点位ID": "L1", "有效营收月份数": "12", "近12月平均月营收": "300000", "租售比": "0.13"},
            {"点位ID": "L2", "有效营收月份数": "12", "近12月平均月营收": "300000", "租售比": "0.155"},
        ]
        _, summary = build(rows)
        self.assertEqual(summary[0]["经济性候选数_至少6月"], 1)
        self.assertEqual(summary[2]["新增候选点位ID"], "L2")


if __name__ == "__main__":
    unittest.main()
