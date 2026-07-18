import unittest

from scripts.build_site_identity_episodes import build_analysis_ops, covers_full_month


class SiteIdentityEpisodeTests(unittest.TestCase):
    def test_transition_month_is_not_assigned(self):
        episode = {"effective_start": "2023-07-29", "effective_end": ""}
        self.assertFalse(covers_full_month(episode, "2023-07"))
        self.assertTrue(covers_full_month(episode, "2023-08"))

    def test_gap_and_partial_months_are_excluded(self):
        episodes = [
            {
                "hanson_store_name": "日月光店",
                "analysis_point_id": "L0008-01",
                "effective_start": "",
                "effective_end": "2023-05-15",
                "resolution_status": "confirmed",
            },
            {
                "hanson_store_name": "日月光店",
                "analysis_point_id": "L0008-02",
                "effective_start": "2023-07-29",
                "effective_end": "",
                "resolution_status": "confirmed",
            },
        ]
        ops = [
            {"Hanson门店名称": "日月光店", "月份": "2023-04", "点位ID": "L0008"},
            {"Hanson门店名称": "日月光店", "月份": "2023-05", "点位ID": "L0008"},
            {"Hanson门店名称": "日月光店", "月份": "2023-06", "点位ID": "L0008"},
            {"Hanson门店名称": "日月光店", "月份": "2023-07", "点位ID": "L0008"},
            {"Hanson门店名称": "日月光店", "月份": "2023-08", "点位ID": "L0008"},
        ]
        rows, issues = build_analysis_ops(ops, episodes)
        self.assertEqual([(row["月份"], row["点位ID"]) for row in rows], [("2023-04", "L0008-01"), ("2023-08", "L0008-02")])
        self.assertEqual(len(issues), 3)

    def test_pending_store_is_not_silently_assigned(self):
        rows, issues = build_analysis_ops(
            [{"Hanson门店名称": "宝乐汇店", "月份": "2026-01", "点位ID": "L0020"}],
            [{"hanson_store_name": "宝乐汇店", "resolution_status": "pending"}],
        )
        self.assertEqual(rows, [])
        self.assertEqual(issues[0]["问题"], "身份方案待确认")


if __name__ == "__main__":
    unittest.main()
