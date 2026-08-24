import unittest

from scripts.run_server_batch import COMMANDS


class ServerBatchTests(unittest.TestCase):
    def test_franchise_review_runs_after_analysis_rebuild(self):
        modules = [command[2] for command in COMMANDS]
        self.assertEqual(modules[-2:], [
            "scripts.rebuild_analysis",
            "scripts.build_franchise_operating_review",
        ])
        self.assertEqual(COMMANDS[-1][-2:], [
            "--workforce-contract",
            "config/store_workforce_monthly.v1.contract.json",
        ])


if __name__ == "__main__":
    unittest.main()
