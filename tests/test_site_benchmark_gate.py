import unittest

from scripts.build_site_benchmark import economic_gate


class SiteBenchmarkGateTests(unittest.TestCase):
    def test_economic_gate_passes_only_both_business_thresholds(self):
        status, gap = economic_gate(0.15, 280000, 12)
        self.assertEqual(status, "经济性达标-待完整验证")
        self.assertIn("老客复购", gap)

    def test_research_positive_can_still_fail_economic_gate(self):
        status, gap = economic_gate(0.18, 300000, 12)
        self.assertEqual(status, "经济性未达标")
        self.assertIn("租售比高于15%", gap)

    def test_new_store_is_observation(self):
        status, _ = economic_gate(0.10, 350000, 3)
        self.assertEqual(status, "观察-经营期不足")


if __name__ == "__main__":
    unittest.main()
