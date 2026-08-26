import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.build_franchise_operating_review import plan_auto_backfill, run_auto_backfill
from services.franchise_review_display import BUSINESS_REVIEW_SCHEMA_VERSION


def write_manifest(root: Path, month: str, status="ready_for_business_review", dashboard_write_allowed=False):
    run_dir = root / month / f"run-{month}"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "franchise-operating-run/v0.1",
        "run_id": f"run-{month}",
        "run_month": month,
        "status": status,
        "dashboard_write_allowed": dashboard_write_allowed,
        "business_review_schema_version": BUSINESS_REVIEW_SCHEMA_VERSION,
        "outputs": {"business_review_json": "business_review.json"},
    }
    (run_dir / "business_review.json").write_text("{}", encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload, run_dir


class FranchiseOperatingBackfillTests(unittest.TestCase):
    def test_june_is_first_and_successes_advance_one_month_at_a_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = plan_auto_backfill(root, today=date(2026, 8, 25))
            self.assertEqual(first["complete_months"], ["2026-06", "2026-07"])
            self.assertEqual(first["selected_month"], "2026-06")

            write_manifest(root, "2026-06")
            second = plan_auto_backfill(root, today=date(2026, 8, 25))
            self.assertEqual(second["successful_months"], ["2026-06"])
            self.assertEqual(second["selected_month"], "2026-07")

            write_manifest(root, "2026-07")
            caught_up = plan_auto_backfill(root, today=date(2026, 8, 25))
            self.assertEqual(caught_up["pending_months"], [])
            self.assertIsNone(caught_up["selected_month"])
            self.assertEqual(caught_up["mode"], "regular_latest")

    def test_failed_month_stays_at_front_for_automatic_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(root, "2026-06", status="blocked_by_data_gate")
            write_manifest(root, "2026-07")
            plan = plan_auto_backfill(root, today=date(2026, 8, 25))
        self.assertEqual(plan["selected_month"], "2026-06")
        self.assertEqual(plan["pending_months"], ["2026-06"])

    def test_success_requires_read_only_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(root, "2026-06", dashboard_write_allowed=True)
            plan = plan_auto_backfill(root, today=date(2026, 8, 25))
        self.assertEqual(plan["selected_month"], "2026-06")
        self.assertFalse(plan["dashboard_write_allowed"])

    def test_old_success_without_business_display_is_backfilled_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload, run_dir = write_manifest(root, "2026-06")
            payload.pop("business_review_schema_version")
            payload["outputs"] = {}
            (run_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
            plan = plan_auto_backfill(root, today=date(2026, 8, 25))
        self.assertEqual(plan["selected_month"], "2026-06")

    def test_caught_up_run_uses_regular_latest_and_records_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_manifest(root, "2026-06")
            manifest, run_dir = write_manifest(root, "2026-07")
            manifest["generated_at"] = "2026-08-25T00:00:00+00:00"
            with patch(
                "scripts.build_franchise_operating_review.build",
                return_value=(manifest, run_dir, True),
            ) as mocked:
                _, _, duplicate, status = run_auto_backfill(
                    output_root=root,
                    today=date(2026, 8, 25),
                    now=datetime(2026, 8, 25, tzinfo=timezone.utc),
                )
            self.assertIsNone(mocked.call_args.kwargs["target_month"])
            self.assertTrue(duplicate)
            self.assertEqual(status["mode"], "regular_latest")
            self.assertEqual(status["attempted_month"], "2026-07")
            self.assertFalse(status["dashboard_write_allowed"])
            saved = json.loads((root / "auto_backfill_status.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["run_status"], "ready_for_business_review")
        self.assertTrue(saved["duplicate_input"])


if __name__ == "__main__":
    unittest.main()
