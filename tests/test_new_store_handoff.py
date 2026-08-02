from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_new_store_handoff import read_input_package


REPO_ROOT = Path(__file__).resolve().parents[1]


class NewStoreHandoffTests(unittest.TestCase):
    def test_unconfirmed_bot_package_is_rejected(self) -> None:
        package = {
            "schema_version": "lann-site-neutral-input/v0.1",
            "project": {"id": "site_test", "name": "测试场地"},
            "confirmation": {"input_summary_confirmed": False},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input-package.json"
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "资料摘要尚未由负责人确认"):
                read_input_package(path, allow_unconfirmed=False)

    def test_reviewed_shadow_builds_valid_candidate(self) -> None:
        fixture = REPO_ROOT / "ai" / "evals" / "site_shadow_analysis" / "sijing_input.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            shadow = Path(temp_dir) / "shadow-analysis.json"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.build_site_shadow_analysis",
                    "--input",
                    str(fixture),
                    "--output",
                    str(shadow),
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.run_new_store_handoff",
                    "--shadow-input",
                    str(shadow),
                    "--output-dir",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            candidate = Path(temp_dir) / "site-record-candidate.json"
            self.assertTrue(candidate.exists())
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "site_record/v0.1")
            self.assertIn("新店增长候选交接完成", result.stdout)


if __name__ == "__main__":
    unittest.main()
