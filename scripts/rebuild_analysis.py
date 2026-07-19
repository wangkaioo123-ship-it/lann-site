"""Validated local rebuild entry point for the core lann-site analysis chain."""

import subprocess
import sys

from config import settings


COMMANDS = [
    [sys.executable, "-m", "scripts.build_ops_source_bridge"],
    [sys.executable, "-m", "scripts.validate_data_contract", "--ops", "data/staging/site_ops_monthly_combined.csv"],
    [sys.executable, "-m", "scripts.build_site_identity_episodes", "--ops", "data/staging/site_ops_monthly_combined.csv"],
    [
        sys.executable,
        "-m",
        "scripts.build_site_performance",
        "--rent-file",
        "data/staging/rent_extract_analysis.csv",
        "--ops-file",
        "data/staging/site_ops_monthly_analysis.csv",
        "--base-file",
        "data/staging/base_table_analysis.csv",
        "--monthly-out",
        "data/staging/site_performance_monthly_bi_feishu_rent.csv",
        "--summary-out",
        "data/staging/site_performance_summary_bi_feishu_rent.csv",
    ],
    [
        sys.executable,
        "-m",
        "scripts.build_site_benchmark",
        "--base",
        "data/staging/base_table_analysis.csv",
    ],
    [sys.executable, "-m", "scripts.build_good_store_validation"],
    [sys.executable, "-m", "scripts.build_rent_ratio_sensitivity"],
    [sys.executable, "-m", "scripts.build_daily_ramp_analysis"],
    [sys.executable, "-m", "scripts.build_site_performance_attribution"],
    [sys.executable, "-m", "scripts.build_attribution_review_plan"],
    [sys.executable, "-m", "scripts.build_candidate_screen_v2"],
    [sys.executable, "-m", "scripts.build_data_manifest"],
]


def main() -> None:
    for command in COMMANDS:
        print("running", " ".join(command[2:]))
        result = subprocess.run(command, cwd=settings.ROOT_DIR, check=False)
        if result.returncode:
            print(f"analysis rebuild blocked at {' '.join(command[2:])} exit={result.returncode}")
            raise SystemExit(result.returncode)
    print("analysis rebuild complete")


if __name__ == "__main__":
    main()
