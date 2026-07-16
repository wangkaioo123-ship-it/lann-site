import argparse
import csv
from pathlib import Path

from config import settings
from scripts.build_candidate_screen import parse_number


SCREEN_FILE = "data/staging/candidate_screen.csv"
BENCHMARK_FILE = "data/staging/site_benchmark.csv"
STATS_FILE = "data/staging/site_benchmark_stats.csv"
OUT_FILE = "data/staging/candidate_screen_v2.csv"


OUTPUT_FIELDS = [
    "record_id",
    "项目名称",
    "城市",
    "当前阶段",
    "开店性质",
    "资料完整度",
    "判断层级",
    "推荐等级",
    "核心判断",
    "主要机会",
    "主要风险",
    "缺失资料",
    "下一步动作",
    "匹配调研门店",
    "采用预期月营业额",
    "租金物业月成本",
    "估算租售比",
    "租售比参考",
    "营收参考",
    "正向对标样本",
    "风险对标样本",
    "城市样本概况",
    "外部情报优先级",
    "外部情报要查什么",
]


POSITIVE_ROLES = ("正向样本-高营收低租售比", "正向样本-经营健康")
RISK_ROLES = ("反向样本-极端租金压力", "反向样本-租金高且营收弱", "压力样本-租金偏高")


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


def fmt_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 0.000001:
        return str(int(round(value)))
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def norm_city(value: str) -> str:
    value = (value or "").strip()
    for suffix in ("市", "省"):
        value = value.replace(suffix, "")
    return value


def num(row: dict, field: str) -> float | None:
    return parse_number(row.get(field, ""))


def load_stats(rows: list[dict]) -> dict[str, dict[str, float]]:
    result = {}
    for row in rows:
        metric = row.get("指标", "")
        if not metric:
            continue
        result[metric] = {}
        for key in ("P25", "P50_中位数", "P75"):
            value = parse_number(row.get(key, ""))
            if value is not None:
                result[metric][key] = value
    return result


def sample_sort_key(row: dict) -> tuple[int, float, float]:
    role = row.get("样本角色", "")
    revenue = num(row, "近12月平均月营收") or 0
    ratio = num(row, "租售比") or 99
    role_rank = 0 if role in POSITIVE_ROLES else 1
    return (role_rank, ratio, -revenue)


def risk_sort_key(row: dict) -> tuple[int, float, float]:
    role = row.get("样本角色", "")
    ratio = num(row, "租售比") or 0
    revenue = num(row, "近12月平均月营收") or 0
    role_rank = 0 if role in RISK_ROLES else 1
    return (role_rank, -ratio, revenue)


def sample_label(row: dict) -> str:
    return (
        f"{row.get('城市', '')}{row.get('门店名称', '')}"
        f"({row.get('样本角色', '')}，月营收{fmt_number(num(row, '近12月平均月营收'))}，"
        f"租售比{fmt_number(num(row, '租售比'), 4)})"
    )


def has_city_role_samples(benchmark_rows: list[dict], city: str, roles: tuple[str, ...]) -> bool:
    city = norm_city(city)
    return any(
        row.get("样本角色", "") in roles and norm_city(row.get("城市", "")) == city
        for row in benchmark_rows
    )


def pick_samples(benchmark_rows: list[dict], city: str, roles: tuple[str, ...], limit: int, risk: bool = False) -> list[dict]:
    city = norm_city(city)
    rows = [
        row
        for row in benchmark_rows
        if row.get("样本角色", "") in roles and (not city or norm_city(row.get("城市", "")) == city)
    ]
    if not rows:
        rows = [row for row in benchmark_rows if row.get("样本角色", "") in roles]
    rows.sort(key=risk_sort_key if risk else sample_sort_key)
    return rows[:limit]


def sample_text(benchmark_rows: list[dict], city: str, roles: tuple[str, ...], samples: list[dict], risk: bool = False) -> str:
    if not samples:
        return "暂无可用样本"
    if has_city_role_samples(benchmark_rows, city, roles):
        prefix = "同城风险样本" if risk else "同城正向样本"
    else:
        prefix = "同城无风险样本，跨城参考" if risk else "同城无正向样本，跨城参考"
    return f"{prefix}：" + "；".join(sample_label(item) for item in samples)


def city_summary(benchmark_rows: list[dict], city: str) -> str:
    city = norm_city(city)
    rows = [row for row in benchmark_rows if norm_city(row.get("城市", "")) == city]
    if not rows:
        return "无同城经营样本"
    positive = sum(1 for row in rows if row.get("样本角色", "") in POSITIVE_ROLES)
    risk = sum(1 for row in rows if row.get("样本角色", "") in RISK_ROLES)
    ratios = [num(row, "租售比") for row in rows if num(row, "租售比") is not None]
    revenues = [num(row, "近12月平均月营收") for row in rows if num(row, "近12月平均月营收") is not None]
    avg_ratio = sum(ratios) / len(ratios) if ratios else None
    avg_revenue = sum(revenues) / len(revenues) if revenues else None
    return f"同城样本{len(rows)}个，正向{positive}个，风险{risk}个，均值月营收{fmt_number(avg_revenue)}，均值租售比{fmt_number(avg_ratio, 4)}"


def judge_depth(row: dict) -> str:
    has_ratio = bool(row.get("估算租售比", "").strip())
    has_survey = bool(row.get("匹配调研门店", "").strip())
    has_revenue = bool(row.get("采用预期月营业额", "").strip())
    has_rent = bool(row.get("租金物业月成本", "").strip())
    if has_ratio and has_survey:
        return "A-可进入经营复核"
    if has_revenue and has_rent:
        return "B-可做租售比预判"
    if has_revenue or has_rent or has_survey:
        return "C-可做资料补齐判断"
    return "D-仅可排资料优先级"


def missing_materials(row: dict) -> list[str]:
    missing = []
    if not row.get("匹配调研门店", "").strip():
        missing.append("选址调研报告")
    if not row.get("采用预期月营业额", "").strip():
        missing.append("预期月营收/业绩驱动假设")
    if not row.get("租金物业月成本", "").strip():
        missing.append("月租金物业成本")
    if not row.get("商圈等级", "").strip():
        missing.append("商圈等级")
    if not row.get("商场评级", "").strip():
        missing.append("商场评级")
    return missing


def external_intel(row: dict, depth: str, missing: list[str], city_has_samples: bool) -> tuple[str, str]:
    needs = []
    if not city_has_samples:
        needs.append("城市/商圈基础热度")
    if "选址调研报告" in missing:
        needs.append("商场公开信息与客流")
    if row.get("商场评级", "") or row.get("商圈等级", ""):
        needs.append("竞品密度与点评口碑")
    if row.get("当前阶段", "") in ("洽谈中", "调研中", "报批中"):
        needs.append("商场招商稳定性和负面新闻")
    if not needs:
        needs.append("先补内部租金和营收口径")

    if depth.startswith("A") or depth.startswith("B"):
        priority = "P1-用于验证判断"
    elif row.get("当前阶段", "") in ("洽谈中", "调研中", "报批中"):
        priority = "P1-辅助是否继续推进"
    else:
        priority = "P2-内部资料补齐后再查"
    return priority, "；".join(dict.fromkeys(needs))


def recommendation(row: dict, stats: dict[str, dict[str, float]], missing: list[str]) -> tuple[str, str, str, str]:
    ratio = num(row, "估算租售比")
    revenue = num(row, "采用预期月营业额")
    stage = row.get("当前阶段", "")
    material_risk = row.get("资料风险", "")
    p50_ratio = stats.get("租售比", {}).get("P50_中位数", 0.2279)
    p75_ratio = stats.get("租售比", {}).get("P75", 0.2788)
    p50_revenue = stats.get("近12月平均月营收", {}).get("P50_中位数", 256806.1)

    opportunities = []
    risks = []
    actions = []

    if revenue and revenue >= p50_revenue:
        opportunities.append("预期营收不低于现有样本中位数")
    if ratio is not None and ratio <= p50_ratio:
        opportunities.append("租售比低于或接近现有样本中位数")
    if row.get("匹配调研门店", ""):
        opportunities.append("已有调研报告可追溯")
    if row.get("商圈等级", "") in ("S", "A") or row.get("商场评级", "") in ("S", "A"):
        opportunities.append("商圈/商场评级较高")

    if ratio is not None and ratio > p75_ratio:
        risks.append("租售比高于现有样本P75")
    if revenue and revenue < p50_revenue:
        risks.append("预期营收低于现有样本中位数")
    if material_risk and material_risk != "资料可用于初筛":
        risks.append(material_risk)
    if missing:
        risks.append("缺" + "、".join(missing[:3]))

    if ratio is not None:
        if ratio <= p50_ratio and revenue and revenue >= p50_revenue:
            grade = "优先复核"
            core = "租售比和营收预期同时过线，值得进入人工复核。"
            actions.append("复核租金口径、营收驱动和落位条件")
        elif ratio <= p75_ratio:
            grade = "可跟进"
            core = "租售比未触发高压红线，但还需要补足业务驱动和落位信息。"
            actions.append("补齐调研报告中的客流、竞品和工程条件")
        else:
            grade = "谨慎"
            core = "租售比已经高于现有样本P75，需要先压租金或抬高营收假设可信度。"
            actions.append("先做租金谈判红线和营收敏感性测算")
    elif stage == "已开业":
        grade = "已开业回填复盘"
        core = "项目已开业但候选侧资料未闭环，应回填真实租金、营收和开业后表现，反哺选址样本库。"
        actions.append("用真实经营数据和合同租金补做开业后复盘")
    elif stage in ("已签约", "报批中"):
        grade = "签约前后补经营模型"
        core = "项目已接近落地，优先补齐租金和营收模型，避免只留过程资料。"
        actions.append("补月租金物业成本、预期月营收和业绩驱动假设")
    elif "月租金物业成本" in missing and revenue:
        grade = "优先补租金"
        core = "已有营收预期但缺租金口径，补租金后即可形成租售比判断。"
        actions.append("优先补月租金、物业费、面积和日租金")
    elif "预期月营收/业绩驱动假设" in missing and row.get("匹配调研门店", ""):
        grade = "优先补营收假设"
        core = "已有调研材料但缺经营假设，需要把客流、新客、客单和房量假设补上。"
        actions.append("补预期月营收、新客数、客单价、房量和理疗师配置")
    elif stage in ("洽谈中", "调研中"):
        grade = "优先补调研"
        core = "项目处于推进阶段，先补调研和商务口径，再决定是否进入经营复核。"
        actions.append("补选址调研报告、月租金物业成本和营收假设")
    elif row.get("资料完整度", "") == "可初步对标":
        grade = "优先补关键资料"
        core = "候选基础信息较好，但缺少能支撑经营判断的租金、营收或调研链接。"
        actions.append("补齐缺失的经营判断字段")
    elif "预期月营收/业绩驱动假设" in missing or "月租金物业成本" in missing:
        grade = "资料池待筛"
        core = "缺营收或租金，当前不能形成严肃经营判断，先作为资料池排队。"
        actions.append("按推进阶段补月租金物业成本和预期月营收")
    else:
        grade = "暂缓判断"
        core = "当前资料只能用于排补资料优先级。"
        actions.append("低优先级补齐基础字段")

    return (
        grade,
        core,
        "；".join(dict.fromkeys(opportunities)) or "暂无明确机会信号",
        "；".join(dict.fromkeys(risks)) or "暂无明显风险信号",
        "；".join(dict.fromkeys(actions)),
    )


def build_rows(screen_rows: list[dict], benchmark_rows: list[dict], stats: dict[str, dict[str, float]]) -> list[dict]:
    out = []
    cities_with_samples = {norm_city(row.get("城市", "")) for row in benchmark_rows if row.get("城市")}
    for row in screen_rows:
        city = row.get("城市", "")
        missing = missing_materials(row)
        depth = judge_depth(row)
        grade, core, opportunity, risk, action = recommendation(row, stats, missing)
        city_has_samples = norm_city(city) in cities_with_samples
        if not city_has_samples and grade in ("资料池待筛", "优先补关键资料"):
            grade = "待建城市样本"
            core = "该城市缺现有经营样本，内部对标能力弱，需要外部情报和跨城类比一起判断。"
            action = "先补城市商圈情报，再找跨城正反样本类比"
        positive_samples = pick_samples(benchmark_rows, city, POSITIVE_ROLES, 3)
        risk_samples = pick_samples(benchmark_rows, city, RISK_ROLES, 3, risk=True)
        intel_priority, intel_need = external_intel(row, depth, missing, city_has_samples)

        out.append(
            {
                "record_id": row.get("record_id", ""),
                "项目名称": row.get("项目名称", ""),
                "城市": city,
                "当前阶段": row.get("当前阶段", ""),
                "开店性质": row.get("开店性质", ""),
                "资料完整度": row.get("资料完整度", ""),
                "判断层级": depth,
                "推荐等级": grade,
                "核心判断": core,
                "主要机会": opportunity,
                "主要风险": risk,
                "缺失资料": "；".join(missing) if missing else "无核心缺失",
                "下一步动作": action,
                "匹配调研门店": row.get("匹配调研门店", ""),
                "采用预期月营业额": row.get("采用预期月营业额", ""),
                "租金物业月成本": row.get("租金物业月成本", ""),
                "估算租售比": row.get("估算租售比", ""),
                "租售比参考": row.get("租售比参考", ""),
                "营收参考": row.get("营收参考", ""),
                "正向对标样本": sample_text(benchmark_rows, city, POSITIVE_ROLES, positive_samples),
                "风险对标样本": sample_text(benchmark_rows, city, RISK_ROLES, risk_samples, risk=True),
                "城市样本概况": city_summary(benchmark_rows, city),
                "外部情报优先级": intel_priority,
                "外部情报要查什么": intel_need,
            }
        )
    order = {
        "优先复核": 0,
        "可跟进": 1,
        "签约前后补经营模型": 2,
        "优先补租金": 3,
        "优先补营收假设": 4,
        "优先补调研": 5,
        "优先补关键资料": 6,
        "已开业回填复盘": 7,
        "待建城市样本": 8,
        "资料池待筛": 9,
        "谨慎": 10,
        "暂缓判断": 11,
    }
    out.sort(key=lambda item: (order.get(item["推荐等级"], 99), item["判断层级"], item["城市"], item["项目名称"]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", default=SCREEN_FILE)
    parser.add_argument("--benchmark", default=BENCHMARK_FILE)
    parser.add_argument("--stats", default=STATS_FILE)
    parser.add_argument("--out", default=OUT_FILE)
    args = parser.parse_args()

    screen_rows = read_csv(settings.ROOT_DIR / args.screen)
    benchmark_rows = read_csv(settings.ROOT_DIR / args.benchmark)
    stats = load_stats(read_csv(settings.ROOT_DIR / args.stats))
    rows = build_rows(screen_rows, benchmark_rows, stats)
    out_path = settings.ROOT_DIR / args.out
    write_csv(out_path, rows)

    counts = {}
    depths = {}
    for row in rows:
        counts[row["推荐等级"]] = counts.get(row["推荐等级"], 0) + 1
        depths[row["判断层级"]] = depths.get(row["判断层级"], 0) + 1
    print(f"wrote {out_path} rows={len(rows)}")
    print("推荐等级", counts)
    print("判断层级", depths)


if __name__ == "__main__":
    main()
