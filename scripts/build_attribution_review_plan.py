import argparse
import csv
from collections import defaultdict
from pathlib import Path

from config import settings
from scripts.build_candidate_screen import parse_number


ATTRIBUTION_FILE = "data/staging/site_performance_attribution.csv"
OUT_FILE = "data/staging/site_attribution_review_plan.csv"


OUTPUT_FIELDS = [
    "优先级",
    "经营结果标签",
    "点位ID",
    "门店名称",
    "城市",
    "是否已有调研报告",
    "调研报告名称",
    "复盘目的",
    "重点验证假设",
    "应优先补的调研字段",
    "近12月平均月营收",
    "月租金",
    "租售比",
    "平均月新客数",
    "平均理疗师日均产值",
    "可能归因",
    "下一步动作",
]


LABEL_PRIORITY = {
    "正向样本-新客驱动": 1,
    "反向样本-租金高且营收弱": 2,
    "成长样本-新客强租售比健康": 3,
    "反向样本-租金不高但营收弱": 4,
    "异常样本-高租金高营收承压": 5,
    "异常样本-新客强但承接弱": 6,
    "异常样本-新客弱但承接强": 7,
    "正向样本-高产值承接": 8,
    "正向样本-结构健康": 9,
    "压力样本-租金偏高": 10,
    "观察样本-经营期不足": 11,
}


PURPOSE = {
    "正向样本-新客驱动": "找出未来选址应复制的新客/客流信号",
    "正向样本-高产值承接": "区分选址贡献与运营承接贡献",
    "正向样本-结构健康": "提炼稳健型好店的基础条件",
    "反向样本-租金高且营收弱": "识别租金红线和商场/商圈误判信号",
    "反向样本-租金不高但营收弱": "识别便宜但不产生生意的位置风险",
    "成长样本-新客强租售比健康": "识别有新客动能但营收仍在爬坡的成长样本",
    "异常样本-高租金高营收承压": "判断高租金点位是否有战略或稀缺性支撑",
    "异常样本-新客强但承接弱": "判断问题在运营承接还是客质结构",
    "异常样本-新客弱但承接强": "判断问题在获客半径还是商圈触达",
    "压力样本-租金偏高": "验证租金压力是否被商场质量抵消",
    "观察样本-经营期不足": "观察新店爬坡质量，不做正反样本定性",
}


HYPOTHESIS = {
    "正向样本-新客驱动": "调研中的客流、人口、小区、写字楼、商场客流评级是否能解释新客强",
    "正向样本-高产值承接": "客质、竞品、点评与商场定位是否解释高产值，而非只由运营造成",
    "正向样本-结构健康": "商圈等级、品牌组合和点评口碑是否共同支撑稳定经营",
    "反向样本-租金高且营收弱": "调研阶段是否已出现租金高、客流不足、竞品或商场风险信号",
    "反向样本-租金不高但营收弱": "低租金是否掩盖了商圈、客流、客质或竞品问题",
    "成长样本-新客强租售比健康": "新客和租售比已经可接受，营收分位偏低是否来自经营爬坡或承接效率",
    "异常样本-高租金高营收承压": "高营收是否足以长期覆盖租金，是否属于战略点位或稀缺点位",
    "异常样本-新客强但承接弱": "新客来源足够但客质、项目结构或运营承接导致产值偏弱",
    "异常样本-新客弱但承接强": "服务承接没问题，但商圈触达或自然客流不足",
    "压力样本-租金偏高": "商场综合质量是否足以解释接受高租金",
    "观察样本-经营期不足": "有效经营月份是否不足以判断，早期新客和产值是否显示好店潜力",
}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(row: dict, field: str) -> float:
    return parse_number(row.get(field, "")) or 0.0


def score(row: dict) -> tuple[int, float, float, float]:
    has_survey_bonus = 0 if row.get("是否已有调研报告") == "是" else 1
    label = row.get("经营结果标签", "")
    if "反向" in label:
        return (has_survey_bonus, -number(row, "租售比"), number(row, "近12月平均月营收"), 0)
    if "新客" in label:
        return (has_survey_bonus, -number(row, "平均月新客数"), -number(row, "近12月平均月营收"), 0)
    if "产值" in label:
        return (has_survey_bonus, -number(row, "平均理疗师日均产值"), -number(row, "近12月平均月营收"), 0)
    return (has_survey_bonus, -number(row, "近12月平均月营收"), -number(row, "租售比"), 0)


def build_plan(rows: list[dict], per_label: int) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        label = row.get("经营结果标签", "")
        if label in LABEL_PRIORITY:
            grouped[label].append(row)

    out = []
    for label, priority in sorted(LABEL_PRIORITY.items(), key=lambda item: item[1]):
        selected = sorted(grouped.get(label, []), key=score)[:per_label]
        for row in selected:
            out.append(
                {
                    "优先级": f"P{priority}",
                    "经营结果标签": label,
                    "点位ID": row.get("点位ID", ""),
                    "门店名称": row.get("门店名称", ""),
                    "城市": row.get("城市", ""),
                    "是否已有调研报告": row.get("是否已有调研报告", ""),
                    "调研报告名称": row.get("调研报告名称", ""),
                    "复盘目的": PURPOSE.get(label, ""),
                    "重点验证假设": HYPOTHESIS.get(label, ""),
                    "应优先补的调研字段": row.get("应优先补的调研字段", ""),
                    "近12月平均月营收": row.get("近12月平均月营收", ""),
                    "月租金": row.get("月租金", ""),
                    "租售比": row.get("租售比", ""),
                    "平均月新客数": row.get("平均月新客数", ""),
                    "平均理疗师日均产值": row.get("平均理疗师日均产值", ""),
                    "可能归因": row.get("可能归因", ""),
                    "下一步动作": row.get("下一步动作", ""),
                }
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=ATTRIBUTION_FILE)
    parser.add_argument("--out", default=OUT_FILE)
    parser.add_argument("--per-label", type=int, default=3)
    args = parser.parse_args()

    rows = read_csv(settings.ROOT_DIR / args.source)
    plan = build_plan(rows, args.per_label)
    write_csv(settings.ROOT_DIR / args.out, plan)
    print(f"wrote {settings.ROOT_DIR / args.out} rows={len(plan)}")
    for row in plan[:12]:
        print(row["优先级"], row["经营结果标签"], row["门店名称"], row["是否已有调研报告"])


if __name__ == "__main__":
    main()
