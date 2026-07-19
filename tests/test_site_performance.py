import unittest

from scripts.build_site_performance import is_opening_partial_month


class SitePerformanceTests(unittest.TestCase):
    def test_opening_partial_month_is_excluded(self):
        self.assertTrue(is_opening_partial_month("2025-12-29", "2025-12"))

    def test_full_opening_month_is_kept(self):
        self.assertFalse(is_opening_partial_month("2025-12-01", "2025-12"))

    def test_later_month_is_kept(self):
        self.assertFalse(is_opening_partial_month("2025-12-29", "2026-01"))


if __name__ == "__main__":
    unittest.main()
