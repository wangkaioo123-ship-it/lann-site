import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from config import settings
from scripts.build_candidate_screen import parse_number


BENCHMARK_FILE = "data/staging/site_benchmark.csv"
SURVEY_FILE = "data/staging/site_survey_facts.csv"
OUT_FILE = "data/staging/site_performance_attribution.csv"
SUMMARY_FILE = "data/staging/site_performance_attribution_summary.csv"


OUTPUT_FIELDS = [
    "点位ID",
    "门店名称",
    "城市",
    "门店属性",
    "门店状态",
    "经营结果标签",
    "可能归因",
    "归因置信度",
    "应优先补的调研字段",
    "是否已有调研报告",
    "调研报告名称",
    "近12月平均月营收",
    "月租金",
    "租售比",
    "平均月新客数",
    "平均客单价_折扣后",
    "平均理疗师日均产值",
    "租售比分层",
    "营收分位",
    "租金分位",
    "新客分位",
    "理疗师产值分位",
    "样本角色",
    "下一步动作",
]


SURVEY_FIELDS = {
    "新客强": ["客质和人流", "常驻人口摘要", "周边小区摘要", "写字楼摘要", "商场客流评级"],
    "新客弱": ["客质和人流", "常驻人口摘要", "周边小区摘要", "写字楼摘要", "商场客流评级"],
    "租金压力": ["租金物业月成本", "面积", "商场年销售额评级", "商场竞争力", "远景机会"],
    "营收强": ["商场定位评级", "商圈等级评级", "零售品牌评级", "餐饮品牌评级", "配套品牌评级", "点评摘要"],
    "营收弱": ["商场定位评级", "商圈等级评级", "点评摘要", "同类竞品摘要", "竞争性", "风险性"],
    "产值强": ["客质和人流", "点评摘要", "同类竞品摘要", "商场定位评级"],
    "产值弱": ["客质和人流", "点评摘要", "同类竞品摘要", "商场定位评级"],
    "成长观察": ["客质和人流", "常驻人口摘要", "周边小区摘要", "写字楼摘要", "商场客流评级", "商场定位评级", "点评摘要"],
    "经营期不足": ["客质和人流", "商场定位评级", "商圈等级评级", "点评摘要", "同类竞品摘要", "竞争性", "风险性"],
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def value(row: dict, field: str) -> float:
    return parse_number(row.get(field, "")) or 0.0


def flag(row: dict, field: str, target: str) -> bool:
    return row.get(field, "") == target


def survey_by_site(rows: list[dict]) -> dict[str, dict]:
    return {row.get("点位ID", ""): row for row in rows if row.get("点位ID")}


def result_label(row: dict) -> str:
    role = row.get("样本角色", "")
    revenue_high = flag(row, "营收分位", "样本前25%") or flag(row, "营收分位", "样本中上")
    revenue_low = flag(row, "营收分位", "样本后25%") or flag(row, "营收分位", "样本中下")
    rent_high = flag(row, "租金分位", "样本后25%")
    ratio_high = row.get("租售比分层", "") in ("高压", "异常高压")
    ratio_healthy = row.get("租售比分层", "") in ("健康", "正常偏高")
    new_high = flag(row, "新客分位", "样本前25%") or flag(row, "新客分位", "样本中上")
    new_low = flag(row, "新客分位", "样本后25%")
    therapist_high = flag(row, "理疗师产值分位", "样本前25%") or flag(row, "理疗师产值分位", "样本中上")
    therapist_low = flag(row, "理疗师产值分位", "样本后25%")

    if role.startswith("正向") and new_high:
        return "正向样本-新客驱动"
    if role.startswith("正向") and therapist_high:
        return "正向样本-高产值承接"
    if role.startswith("正向"):
        return "正向样本-结构健康"
    if role.startswith("观察"):
        return "观察样本-经营期不足"
    if ratio_healthy and revenue_low and new_high:
        return "成长样本-新客强租售比健康"
    if ratio_high and revenue_low:
        return "反向样本-租金高且营收弱"
    if ratio_high and revenue_high:
        return "异常样本-高租金高营收承压"
    if ratio_healthy and revenue_low:
        return "反向样本-租金不高但营收弱"
    if new_low and therapist_high:
        return "异常样本-新客弱但承接强"
    if new_high and therapist_low:
        return "异常样本-新客强但承接弱"
    if rent_high:
        return "压力样本-租金偏高"
    return "中性样本-待结合调研"


def attribution(row: dict, label: str) -> tuple[str, str]:
    reasons = []
    confidence = "中"
    revenue_bucket = row.get("营收分位", "")
    rent_bucket = row.get("租金分位", "")
    new_bucket = row.get("新客分位", "")
    therapist_bucket = row.get("理疗师产值分位", "")
    ratio_band = row.get("租售比分层", "")

    if "新客驱动" in label:
        reasons.append("新客分位靠前，选址可能带来较强自然客流或商圈触达")
        confidence = "中高"
    if "高产值承接" in label:
        reasons.append("理疗师产值分位靠前，需剥离运营承接能力对营收的贡献")
    if "结构健康" in label:
        reasons.append("营收和租售比结构健康，可作为正向选址样本")
    if "租金高且营收弱" in label:
        reasons.append("租售比高压且营收分位偏低，疑似选址客流或商圈质量不足以覆盖租金")
        confidence = "高"
    if "高租金高营收承压" in label:
        reasons.append("营收强但租金压力仍高，需要识别是否为战略点位或商场稀缺性支撑")
    if "租金不高但营收弱" in label:
        reasons.append("租金不是主因，更应检查客流、商圈、竞品和门店承接")
        confidence = "中高"
    if "新客弱但承接强" in label:
        reasons.append("新客偏弱但产值较好，问题可能在获客半径，不一定在服务承接")
    if "新客强但承接弱" in label:
        reasons.append("新客强但产值偏弱，需剥离运营承接和客质结构")
    if "租金偏高" in label:
        reasons.append("租金分位偏高，需重点验证商场客流和消费力是否足以支撑")
    if "成长样本" in label:
        reasons.append("新客分位靠前且租售比健康，营收分位偏低更可能是爬坡或承接问题，暂不应作为反向选址样本")
        confidence = "中"
    if "经营期不足" in label:
        reasons.append("有效营收月份不足，当前只能观察爬坡质量，不能定性为正向或反向样本")
        confidence = "低"

    if not reasons:
        if ratio_band in ("高压", "异常高压"):
            reasons.append("租售比处于高压区，优先复核租金与营收结构")
        elif revenue_bucket in ("样本前25%", "样本中上"):
            reasons.append("营收表现尚可，需结合新客和商圈结构确认选址贡献")
        else:
            reasons.append("经营结果未出现强信号，先作为中位参照样本")
            confidence = "低"

    if new_bucket == "样本后25%":
        reasons.append("新客偏弱")
    if therapist_bucket == "样本后25%":
        reasons.append("理疗师产值偏弱")
    if rent_bucket == "样本后25%":
        reasons.append("租金处于高位")

    return "；".join(dict.fromkeys(reasons)), confidence


def fields_to_enrich(row: dict, label: str) -> str:
    tags = []
    if "新客" in label:
        tags.extend(["新客强" if "强" in label or "驱动" in label else "新客弱"])
    if "租金" in label or row.get("租售比分层", "") in ("高压", "异常高压"):
        tags.append("租金压力")
    if "营收弱" in label:
        tags.append("营收弱")
    elif "正向" in label or "高营收" in label:
        tags.append("营收强")
    if "产值" in label:
        tags.append("产值强" if "强" in label or "承接强" in label or "高产值" in label else "产值弱")
    if "成长样本" in label:
        tags.append("成长观察")
    if "经营期不足" in label:
        tags.append("经营期不足")

    fields = []
    for tag in tags:
        fields.extend(SURVEY_FIELDS.get(tag, []))
    if not fields:
        fields.extend(["商圈等级评级", "商场定位评级", "商场客流评级", "同类竞品摘要", "点评摘要"])
    return "；".join(dict.fromkeys(fields))


def next_action(has_survey: bool, label: str) -> str:
    if has_survey:
        return "读取对应调研报告结构字段，验证经营归因信号"
    if "正向" in label or "反向" in label or "异常" in label or "成长样本" in label:
        return "优先补齐该店历史选址调研报告或按现有模板回填关键字段"
    if "经营期不足" in label:
        return "先观察有效经营月份，暂不作为正反样本定性"
    return "暂作为经营样本，不优先补调研"


def build_rows(benchmark_rows: list[dict], survey_rows: list[dict]) -> list[dict]:
    surveys = survey_by_site(survey_rows)
    out = []
    for row in benchmark_rows:
        label = result_label(row)
        reasons, confidence = attribution(row, label)
        survey = surveys.get(row.get("点位ID", ""), {})
        has_survey = bool(survey)
        out.append(
            {
                "点位ID": row.get("点位ID", ""),
                "门店名称": row.get("门店名称", ""),
                "城市": row.get("城市", ""),
                "门店属性": row.get("门店属性", ""),
                "门店状态": row.get("门店状态", ""),
                "经营结果标签": label,
                "可能归因": reasons,
                "归因置信度": confidence,
                "应优先补的调研字段": fields_to_enrich(row, label),
                "是否已有调研报告": "是" if has_survey else "否",
                "调研报告名称": survey.get("报告名称", ""),
                "近12月平均月营收": row.get("近12月平均月营收", ""),
                "月租金": row.get("月租金", ""),
                "租售比": row.get("租售比", ""),
                "平均月新客数": row.get("平均月新客数", ""),
                "平均客单价_折扣后": row.get("平均客单价_折扣后", ""),
                "平均理疗师日均产值": row.get("平均理疗师日均产值", ""),
                "租售比分层": row.get("租售比分层", ""),
                "营收分位": row.get("营收分位", ""),
                "租金分位": row.get("租金分位", ""),
                "新客分位": row.get("新客分位", ""),
                "理疗师产值分位": row.get("理疗师产值分位", ""),
                "样本角色": row.get("样本角色", ""),
                "下一步动作": next_action(has_survey, label),
            }
        )
    priority = {
        "正向样本-新客驱动": 0,
        "正向样本-高产值承接": 1,
        "正向样本-结构健康": 2,
        "成长样本-新客强租售比健康": 3,
        "反向样本-租金高且营收弱": 4,
        "反向样本-租金不高但营收弱": 5,
        "异常样本-高租金高营收承压": 6,
        "异常样本-新客弱但承接强": 7,
        "异常样本-新客强但承接弱": 8,
        "压力样本-租金偏高": 9,
        "观察样本-经营期不足": 10,
    }
    out.sort(key=lambda item: (priority.get(item["经营结果标签"], 99), item["城市"], item["门店名称"]))
    return out


def build_summary(rows: list[dict]) -> list[dict]:
    counts = Counter(row["经营结果标签"] for row in rows)
    by_city = defaultdict(Counter)
    survey_counts = Counter()
    for row in rows:
        by_city[row["城市"]][row["经营结果标签"]] += 1
        survey_counts[row["是否已有调研报告"]] += 1

    summary = [{"维度": "经营结果标签", "项目": key, "数量": value} for key, value in counts.most_common()]
    summary.extend({"维度": "调研报告覆盖", "项目": key, "数量": value} for key, value in survey_counts.items())
    for city, counter in sorted(by_city.items()):
        for key, value in counter.most_common():
            summary.append({"维度": f"城市-{city}", "项目": key, "数量": value})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default=BENCHMARK_FILE)
    parser.add_argument("--survey", default=SURVEY_FILE)
    parser.add_argument("--out", default=OUT_FILE)
    parser.add_argument("--summary-out", default=SUMMARY_FILE)
    args = parser.parse_args()

    benchmark_rows = read_csv(settings.ROOT_DIR / args.benchmark)
    survey_rows = read_csv(settings.ROOT_DIR / args.survey)
    rows = build_rows(benchmark_rows, survey_rows)
    summary = build_summary(rows)
    write_csv(settings.ROOT_DIR / args.out, rows, OUTPUT_FIELDS)
    write_csv(settings.ROOT_DIR / args.summary_out, summary, ["维度", "项目", "数量"])

    print(f"wrote {settings.ROOT_DIR / args.out} rows={len(rows)}")
    print(Counter(row["经营结果标签"] for row in rows))
    print(Counter(row["是否已有调研报告"] for row in rows))


if __name__ == "__main__":
    main()
