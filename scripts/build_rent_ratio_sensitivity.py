"""Compare economic-candidate results under several rent-ratio thresholds."""

import argparse
import csv
from pathlib import Path


THRESHOLDS = (0.14, 0.15, 0.16, 0.18)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def qualifies(row: dict, threshold: float, minimum_months: int) -> bool:
    return (
        number(row.get("有效营收月份数")) >= minimum_months
        and number(row.get("近12月平均月营收")) >= 280000
        and 0 < number(row.get("租售比")) <= threshold
    )


def build(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    details = []
    qualified_by_threshold = {threshold: set() for threshold in THRESHOLDS}
    mature_by_threshold = {threshold: set() for threshold in THRESHOLDS}
    for row in rows:
        site_id = row.get("点位ID", "")
        detail = {
            "点位ID": site_id,
            "门店名称": row.get("门店名称", ""),
            "有效营收月份数": row.get("有效营收月份数", ""),
            "近12月平均月营收": row.get("近12月平均月营收", ""),
            "月租金": row.get("月租金", ""),
            "租售比": row.get("租售比", ""),
        }
        for threshold in THRESHOLDS:
            label = f"{int(threshold * 100)}%"
            candidate = qualifies(row, threshold, 6)
            mature = qualifies(row, threshold, 12)
            detail[f"经济性候选_{label}"] = "是" if candidate else "否"
            detail[f"完整期候选_{label}"] = "是" if mature else "否"
            if candidate:
                qualified_by_threshold[threshold].add(site_id)
            if mature:
                mature_by_threshold[threshold].add(site_id)
        details.append(detail)

    summaries = []
    previous_candidates = set()
    previous_mature = set()
    for threshold in THRESHOLDS:
        candidates = qualified_by_threshold[threshold]
        mature = mature_by_threshold[threshold]
        summaries.append(
            {
                "租售比阈值": f"{int(threshold * 100)}%",
                "经济性候选数_至少6月": len(candidates),
                "较上一档新增候选": len(candidates - previous_candidates),
                "新增候选点位ID": "；".join(sorted(candidates - previous_candidates)),
                "完整期候选数_至少12月": len(mature),
                "较上一档新增完整期候选": len(mature - previous_mature),
                "新增完整期候选点位ID": "；".join(sorted(mature - previous_mature)),
                "口径说明": "同时要求平均月营收不低于28万元；本表只做阈值敏感性，不自动修改正式标准",
            }
        )
        previous_candidates = candidates
        previous_mature = mature
    return details, summaries


def write_csv(path: Path, rows: list[dict], fallback_fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else fallback_fields
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rent-ratio threshold sensitivity outputs.")
    parser.add_argument("--benchmark", default="data/staging/site_benchmark.csv")
    parser.add_argument("--out", default="data/staging/rent_ratio_sensitivity.csv")
    parser.add_argument("--summary-out", default="data/staging/rent_ratio_sensitivity_summary.csv")
    args = parser.parse_args()
    details, summaries = build(read_csv(Path(args.benchmark)))
    write_csv(Path(args.out), details, ["点位ID", "门店名称"])
    write_csv(Path(args.summary_out), summaries, ["租售比阈值"])
    print(f"wrote {args.out} rows={len(details)}")
    print(f"wrote {args.summary_out} rows={len(summaries)}")


if __name__ == "__main__":
    main()
