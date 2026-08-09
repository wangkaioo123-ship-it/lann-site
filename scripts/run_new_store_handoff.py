"""Run the minimal Bot -> Site -> Dashboard candidate handoff."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_command(command: Sequence[str], *, cwd: Path) -> None:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode:
        detail = (result.stderr or result.stdout or "没有返回详细原因").strip()
        raise RuntimeError(f"子步骤执行失败：{detail[-2000:]}")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def read_input_package(path: Path, *, allow_unconfirmed: bool) -> dict:
    package = json.loads(path.read_text(encoding="utf-8"))
    if package.get("schema_version") != "lann-site-neutral-input/v0.1":
        raise ValueError("输入文件不是 lann-site-neutral-input/v0.1")
    if not package.get("project", {}).get("id"):
        raise ValueError("输入包缺少项目 ID")
    if not package.get("project", {}).get("name"):
        raise ValueError("输入包缺少项目名称")
    if (
        not package.get("confirmation", {}).get("input_summary_confirmed")
        and not allow_unconfirmed
    ):
        raise ValueError("资料摘要尚未由负责人确认，不能进入 Site 分析")
    return package


def build_read_only_analysis_package(package: dict) -> dict:
    analysis_package = copy.deepcopy(package)
    external_writes = dict(analysis_package.get("external_writes") or {})
    external_writes["dashboard_allowed"] = False
    external_writes["dashboard_attempted"] = False
    analysis_package["external_writes"] = external_writes
    return analysis_package


def build_from_input_package(args: argparse.Namespace, output_dir: Path) -> Path:
    input_package = Path(args.input_package).resolve()
    storage_root = Path(args.storage_root).resolve()
    package = read_input_package(
        input_package,
        allow_unconfirmed=args.allow_unconfirmed,
    )
    project_id = package["project"]["id"]
    project_dir = output_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    analysis_package_path = project_dir / "analysis-input-package.json"
    analysis_package_path.write_text(
        json.dumps(build_read_only_analysis_package(package), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    internal_input = project_dir / "internal-input.json"
    review_json = project_dir / "evidence-review.json"
    review_markdown = project_dir / "evidence-review.md"
    shadow_analysis = project_dir / "shadow-analysis.json"

    parse_command = [
        sys.executable,
        "-m",
        "scripts.parse_site_intake_pdfs",
        "--input",
        str(analysis_package_path),
        "--storage-root",
        str(storage_root),
        "--internal-output",
        str(internal_input),
        "--review-output",
        str(review_json),
        "--review-markdown",
        str(review_markdown),
    ]
    if args.enable_ocr:
        parse_command.append("--enable-ocr")
    run_command(parse_command, cwd=REPO_ROOT)

    run_command(
        [
            sys.executable,
            "-m",
            "scripts.parse_site_intake_supplements",
            "--input-package",
            str(analysis_package_path),
            "--storage-root",
            str(storage_root),
            "--internal-input",
            str(internal_input),
            "--review-json",
            str(review_json),
        ],
        cwd=REPO_ROOT,
    )
    run_command(
        [
            sys.executable,
            "-m",
            "scripts.build_site_shadow_analysis",
            "--input",
            str(internal_input),
            "--output",
            str(shadow_analysis),
        ],
        cwd=REPO_ROOT,
    )
    return shadow_analysis


def build_candidate(shadow_input: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "site-record-candidate.json"
    run_command(
        [
            sys.executable,
            "-m",
            "scripts.build_site_record_candidate",
            "--input",
            str(shadow_input.resolve()),
            "--output",
            str(candidate_path),
        ],
        cwd=REPO_ROOT,
    )
    return candidate_path


def import_dashboard_candidate(
    candidate_path: Path,
    *,
    dashboard_repo: Path,
    operator: str,
) -> None:
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        raise RuntimeError("未找到 Node.js，无法导入 Dashboard 候选缓冲区")
    importer = dashboard_repo / "scripts" / "import_site_candidate.js"
    if not importer.exists():
        raise FileNotFoundError(f"未找到 Dashboard 候选导入脚本：{importer}")
    run_command(
        [node, str(importer), str(candidate_path), "--operator", operator],
        cwd=dashboard_repo,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the minimal Bot -> Site -> Dashboard candidate handoff."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-package", help="Bot input-package.json")
    source.add_argument("--shadow-input", help="Existing reviewed Site shadow analysis")
    parser.add_argument("--storage-root", help="Bot site-intake root; required with --input-package")
    parser.add_argument("--output-dir", required=True, help="Handoff output directory")
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--allow-unconfirmed", action="store_true")
    parser.add_argument("--import-dashboard", action="store_true")
    parser.add_argument("--dashboard-repo", help="lann-dashboard repository path")
    parser.add_argument("--operator", help="Dashboard import operator")
    args = parser.parse_args(argv)

    if args.input_package and not args.storage_root:
        parser.error("--input-package requires --storage-root")
    if args.import_dashboard and (not args.dashboard_repo or not args.operator):
        parser.error("--import-dashboard requires --dashboard-repo and --operator")
    return args


def main(argv: Sequence[str] | None = None) -> Path:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    if args.input_package:
        shadow_input = build_from_input_package(args, output_dir)
        candidate_dir = shadow_input.parent
    else:
        shadow_input = Path(args.shadow_input).resolve()
        candidate_dir = output_dir

    candidate_path = build_candidate(shadow_input, candidate_dir)
    if args.import_dashboard:
        import_dashboard_candidate(
            candidate_path,
            dashboard_repo=Path(args.dashboard_repo).resolve(),
            operator=args.operator,
        )

    print(f"新店增长候选交接完成: {candidate_path}")
    print("当前状态: 候选缓冲区；仍需负责人确认后才能进入正式场地跟进")
    return candidate_path


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"新店增长候选交接失败: {error}", file=sys.stderr)
        raise SystemExit(1) from error
