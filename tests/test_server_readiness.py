import tempfile
import unittest
from pathlib import Path

from scripts.check_server_readiness import REQUIRED_ENV, REQUIRED_FILES, readiness_issues


class ServerReadinessTests(unittest.TestCase):
    def test_missing_config_is_reported_without_secret_values(self):
        with tempfile.TemporaryDirectory() as directory:
            issues = readiness_issues(lambda name: "", Path(directory))
        self.assertIn(f"缺少环境配置:{REQUIRED_ENV[0]}", issues)
        self.assertNotIn("secret-value", " ".join(issues))

    def test_complete_config_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in REQUIRED_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            self.assertEqual(readiness_issues(lambda name: "configured", root), [])


if __name__ == "__main__":
    unittest.main()
