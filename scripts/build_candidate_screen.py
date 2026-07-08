import argparse
import csv
import re
from difflib import SequenceMatcher
from pathlib import Path

from config import settings


EXPANSION_FILE = "data/staging/expansion_candidates.csv"
SURVEY_FILE = "data/staging/site_survey_facts.csv"
BENCHMARK_STATS_FILE = "data/staging/site_benchmark_stats.csv"
OUT_FILE = "data/staging/candidate_screen.csv"


OUTPUT_FIELDS = [
    "record_id",
    "项目名称",
    "城市",
    "当前阶段",
    "开店性质",
    "资料完整度",
    "候选资料缺口",
    "匹配状态",
    "匹配调研门店",
    "匹配调研报告",
    "商圈等级",
    "商场评级",
    "物业形态",
    "预期房量规模",
    "预计门店类型",
    "候选预期月营业额",
    "调研稳定营业额预期",
    "采用预期月营业额",
    "营收口径提示",
    "租金物业月成本",
    "候选租金元每平每天",
    "调研面积",
    "估算月租金",
    "估算租售比",
    "租售比参考",
    "租售比风险",
    "营收参考",
    "资料风险",
    "调研风险摘要",
    "初筛结论",
    "初筛理由",
    "下一步动作",
]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_link(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value.split("?")[0].rstrip("/")


def norm_name(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"\d{4}[./-]?\d{0,2}[./-]?\d{0,2}", "", value)
    for token in [
        "上海",
        "深圳",
        "成都",
        "武汉",
        "苏州",
        "宁波",
        "北京",
        "广州",
        "门店",
        "店铺",
        "店",
        "项目",
        "选址",
        "调研",
        "报告",
        "立项",
        "信息表",
        "单店模型",
        "测算",
        "---",
        "-",
        "_",
        " ",
    ]:
        value = value.replace(token, "")
    return re.sub(r"[^\w\u4e00-\u9fff]", "", value)


def infer_city(value: str) -> str:
    value = value or ""
    for city in [
        "上海",
        "深圳",
        "成都",
        "武汉",
        "苏州",
        "宁波",
        "北京",
        "广州",
        "南京",
        "杭州",
        "无锡",
        "嘉兴",
    ]:
        if city in value:
            return city
    return ""


def city_of_candidate(candidate: dict) -> str:
    city = infer_city(candidate.get("城市", ""))
    if city:
        return city
    return infer_city(candidate.get("项目名称", ""))


def city_of_survey(survey: dict) -> str:
    return infer_city(survey.get("门店名称", "")) or infer_city(survey.get("报告名称", ""))


def comparable_city(candidate_city: str, survey_city: str) -> bool:
    return not candidate_city or not survey_city or candidate_city == survey_city


def parse_number(value: str) -> float | None:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    number = float(match.group())
    tail = value[match.end() : match.end() + 4]
    if "万" in value or "w" in value.lower():
        number *= 10000
    elif "千" in tail:
        number *= 1000
    return number


def parse_money(value: str, small_number_as_wan: bool = False) -> tuple[float | None, str]:
    raw = (value or "").strip()
    if not raw:
        return None, ""
    number = parse_number(raw)
    if number is None:
        return None, ""
    has_money_unit = any(unit in raw for unit in ["元", "万", "w", "W"])
    has_period_unit = any(unit in raw for unit in ["个月", "月", "年"])
    if has_period_unit and not has_money_unit:
        return None, "疑似周期，未按金额采用"
    if small_number_as_wan and 0 < number < 1000 and not has_money_unit:
        return number * 10000, "原值小于1000，按万元口径暂估"
    return number, ""


def fmt_money(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(round(value)))


def fmt_ratio(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4f}"


def load_benchmark_stats(rows: list[dict]) -> dict[str, dict[str, float]]:
    stats = {}
    for row in rows:
        metric = row.get("指标", "")
        if not metric:
            continue
        stats[metric] = {}
        for key in ("P25", "P50_中位数", "P75"):
            number = parse_number(row.get(key, ""))
            if number is not None:
                stats[metric][key] = number
    return stats


def index_surveys(rows: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    by_link = {}
    prepared = []
    for row in rows:
        link = clean_link(row.get("报告链接", ""))
        if link:
            by_link[link] = row
        names = [row.get("门店名称", ""), row.get("报告名称", "")]
        prepared.append({"row": row, "keys": [norm_name(name) for name in names if name]})
    return by_link, prepared


def match_survey(candidate: dict, by_link: dict[str, dict], surveys: list[dict]) -> tuple[str, dict | None]:
    link = clean_link(candidate.get("选址调研报告", ""))
    if link and link in by_link:
        return "报告链接匹配", by_link[link]

    candidate_keys = [
        norm_name(candidate.get("项目名称", "")),
        norm_name(candidate.get("立项信息表", "")),
        norm_name(candidate.get("选址调研报告", "")),
    ]
    candidate_keys = [key for key in candidate_keys if len(key) >= 2]
    if not candidate_keys:
        return "未匹配", None

    candidate_city = city_of_candidate(candidate)
    best_score = 0.0
    best_row = None
    for item in surveys:
        survey_city = city_of_survey(item["row"])
        if not comparable_city(candidate_city, survey_city):
            continue
        for left in candidate_keys:
            for right in item["keys"]:
                if not right:
                    continue
                if len(left) >= 4 and len(right) >= 4 and (left in right or right in left):
                    score = 1.0
                else:
                    score = SequenceMatcher(None, left, right).ratio()
                if score > best_score:
                    best_score = score
                    best_row = item["row"]

    if best_score >= 0.72:
        return f"名称匹配({best_score:.2f})", best_row
    return "未匹配", None


def rent_ratio_band(ratio: float | None, stats: dict[str, dict[str, float]]) -> tuple[str, str]:
    if ratio is None:
        return "", "无法判断"
    rent_sale = stats.get("租售比", {})
    p50 = rent_sale.get("P50_中位数", 0.2279)
    p75 = rent_sale.get("P75", 0.2788)
    if ratio <= p50:
        return "不高于现有样本中位数", "低"
    if ratio <= p75:
        return "介于现有样本中位数和P75之间", "中"
    return "高于现有样本P75", "高"


def revenue_ref(revenue: float | None, stats: dict[str, dict[str, float]]) -> str:
    if revenue is None:
        return "缺预期营收"
    stat = stats.get("近12月平均月营收", {})
    p25 = stat.get("P25", 186922.47)
    p50 = stat.get("P50_中位数", 256806.1)
    p75 = stat.get("P75", 322444.54)
    if revenue < p25:
        return "低于现有样本P25"
    if revenue < p50:
        return "低于现有样本中位数"
    if revenue <= p75:
        return "介于现有样本中位数和P75之间"
    return "高于现有样本P75"


def estimate_monthly_rent(candidate: dict, survey: dict | None) -> tuple[float | None, str]:
    survey_cost, _ = parse_money((survey or {}).get("租金物业月成本", ""))
    if survey_cost:
        return survey_cost, "调研报告月租金物业成本"

    daily_rent = parse_number(candidate.get("租金（元/㎡/天）", ""))
    area = parse_number((survey or {}).get("面积", ""))
    if daily_rent and area:
        return daily_rent * area * 365 / 12, "候选日租金*调研面积估算"
    return None, ""


def choose_revenue(candidate: dict, survey: dict | None) -> tuple[float | None, str, str, str]:
    candidate_revenue, candidate_note = parse_money(candidate.get("预期月营业额", ""), small_number_as_wan=True)
    survey_revenue, survey_note = parse_money((survey or {}).get("稳定营业额预期", ""))
    notes = []
    if candidate_note:
        notes.append(f"候选预期：{candidate_note}")
    if survey_note:
        notes.append(f"调研预期：{survey_note}")
    if survey_revenue:
        return survey_revenue, fmt_money(candidate_revenue), fmt_money(survey_revenue), "；".join(notes)
    return candidate_revenue, fmt_money(candidate_revenue), fmt_money(survey_revenue), "；".join(notes)


def risk_summary(
    candidate: dict,
    match_status: str,
    revenue: float | None,
    monthly_rent: float | None,
) -> tuple[str, str]:
    risks = []
    actions = []

    if candidate.get("资料完整度") != "可初步对标":
        risks.append(candidate.get("资料完整度") or "资料不足")
        actions.append("补齐候选项目基础字段")
    if match_status == "未匹配":
        risks.append("无调研报告匹配")
        actions.append("补充或校验选址调研报告链接")
    if revenue is None:
        risks.append("缺预期营收")
        actions.append("补充业绩预估及驱动假设")
    if monthly_rent is None:
        risks.append("缺租金口径")
        actions.append("补充租金/物业/月成本口径")
    return "；".join(risks) if risks else "资料可用于初筛", "；".join(dict.fromkeys(actions)) if actions else "进入人工复核"


def conclusion(rent_risk: str, material_risk: str, survey: dict | None) -> tuple[str, str]:
    reasons = []
    if rent_risk == "高":
        reasons.append("租售比高于现有样本P75")
    elif rent_risk == "中":
        reasons.append("租售比处于中高区间")
    elif rent_risk == "低":
        reasons.append("租售比未超过现有样本中位数")

    if material_risk != "资料可用于初筛":
        reasons.append(material_risk)

    survey_risk = (survey or {}).get("风险性", "")
    if survey_risk:
        reasons.append("调研报告存在风险描述")

    if rent_risk == "高":
        return "谨慎", "；".join(reasons)
    if "缺预期营收" in material_risk or "缺租金口径" in material_risk:
        return "待补资料", "；".join(reasons)
    if material_risk != "资料可用于初筛":
        return "可跟进但需补资料", "；".join(reasons)
    return "可进入复核", "；".join(reasons)


def build_rows(candidates: list[dict], surveys: list[dict], stats: dict[str, dict[str, float]]) -> list[dict]:
    by_link, prepared_surveys = index_surveys(surveys)
    rows = []
    for candidate in candidates:
        match_status, survey = match_survey(candidate, by_link, prepared_surveys)
        revenue, candidate_revenue_text, survey_revenue_text, revenue_note = choose_revenue(candidate, survey)
        monthly_rent, rent_source = estimate_monthly_rent(candidate, survey)
        ratio = monthly_rent / revenue if monthly_rent and revenue else None
        ratio_ref, ratio_risk = rent_ratio_band(ratio, stats)
        material_risk, next_action = risk_summary(candidate, match_status, revenue, monthly_rent)
        result, reasons = conclusion(ratio_risk, material_risk, survey)

        rows.append(
            {
                "record_id": candidate.get("record_id", ""),
                "项目名称": candidate.get("项目名称", ""),
                "城市": candidate.get("城市", ""),
                "当前阶段": candidate.get("当前阶段", ""),
                "开店性质": candidate.get("开店性质", ""),
                "资料完整度": candidate.get("资料完整度", ""),
                "候选资料缺口": candidate.get("缺口说明", ""),
                "匹配状态": match_status,
                "匹配调研门店": (survey or {}).get("门店名称", ""),
                "匹配调研报告": (survey or {}).get("报告名称", ""),
                "商圈等级": candidate.get("商圈等级", ""),
                "商场评级": candidate.get("商场评级", ""),
                "物业形态": candidate.get("物业形态", ""),
                "预期房量规模": candidate.get("预期房量规模", ""),
                "预计门店类型": candidate.get("预计门店类型", ""),
                "候选预期月营业额": candidate_revenue_text,
                "调研稳定营业额预期": survey_revenue_text,
                "采用预期月营业额": fmt_money(revenue),
                "营收口径提示": revenue_note,
                "租金物业月成本": fmt_money(monthly_rent),
                "候选租金元每平每天": candidate.get("租金（元/㎡/天）", ""),
                "调研面积": (survey or {}).get("面积", ""),
                "估算月租金": rent_source,
                "估算租售比": fmt_ratio(ratio),
                "租售比参考": ratio_ref,
                "租售比风险": ratio_risk,
                "营收参考": revenue_ref(revenue, stats),
                "资料风险": material_risk,
                "调研风险摘要": (survey or {}).get("风险性", ""),
                "初筛结论": result,
                "初筛理由": reasons,
                "下一步动作": next_action,
            }
        )
    rows.sort(key=lambda r: (r["初筛结论"], r["资料完整度"], r["城市"], r["项目名称"]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default=EXPANSION_FILE)
    parser.add_argument("--surveys", default=SURVEY_FILE)
    parser.add_argument("--stats", default=BENCHMARK_STATS_FILE)
    parser.add_argument("--out", default=OUT_FILE)
    args = parser.parse_args()

    candidates = read_csv(settings.ROOT_DIR / args.candidates)
    surveys = read_csv(settings.ROOT_DIR / args.surveys)
    stats = load_benchmark_stats(read_csv(settings.ROOT_DIR / args.stats))
    rows = build_rows(candidates, surveys, stats)
    out = settings.ROOT_DIR / args.out
    write_csv(out, rows)

    counts = {}
    for row in rows:
        counts[row["初筛结论"]] = counts.get(row["初筛结论"], 0) + 1
    print(f"wrote {out} rows={len(rows)}")
    print(counts)


if __name__ == "__main__":
    main()
