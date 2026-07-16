import csv
from collections import defaultdict
from pathlib import Path


RAW = Path("data/staging/ops_monthly_raw_bi.csv")
MAPPING = Path("data/staging/store_month_mapping_review.csv")
BASE = Path("data/staging/base_table.csv")
SUMMARY = Path("data/staging/site_performance_summary_bi_feishu_rent.csv")
BENCHMARK = Path("data/staging/site_benchmark.csv")
MONTHLY_OUT = Path("data/staging/huamu_yingfeng_monthly.csv")
SUMMARY_OUT = Path("data/staging/huamu_yingfeng_summary.csv")
DOC_OUT = Path("docs/HUAMU_YINGFENG_REVIEW_V0.1.md")


SITE_IDS = ["L0002", "L0032", "L0083"]
SITE_NOTES = {
    "L0002": "花木老店；用户补充为 2014 年开业，长期稳定在 30 万以上。",
    "L0032": "云汇天地/盈丰天地；用户补充为 2022 年开业，原计划承接或替代花木。",
    "L0083": "花木陆悦坊；2025 年底新开，可作为同区域新点观察样本。",
}


USER_FACTS = [
    "花木店可以理解为成熟老客资产型门店。",
    "盈丰天地没有呈现出有效承接花木老客加自身新客发现度。",
    "按过往经验，老店旁边开新店通常会分流老店客人，但盈丰天地没有形成持续分流。",
    "当初考虑搬迁，是因为盈丰天地是新商场，花木所在商业街较老且客单价持续走低，品牌形象需要升级。",
    "上海分公司总经理判断两店可以同时开，因此花木没有关闭；事后看避免了更大损失。",
    "花木店为街铺，入口一般，但不属于非常不显眼。",
    "盈丰天地在 B1，位于电梯和手扶梯旁边；停车到店路径不绕，B2 停车后上来即可，理论停车体验优于花木。",
    "当时有引导花木老客去盈丰；花木翻新约 20 多天期间，盈丰当月生意接近 30 万。",
    "花木恢复后，去过盈丰的客人又回到花木。",
    "盈丰天地商场本身客流不多，后期空铺率严重，更多沦为展会或写字楼公共餐饮配套。",
    "盈丰周边与花木周边体感上像是一批人。",
]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def num(value) -> float:
    try:
        return float(value) if value not in ("", None) else 0.0
    except ValueError:
        return 0.0


def fmt(value, digits=1) -> str:
    if value in ("", None):
        return ""
    value = float(value)
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def pct(value) -> str:
    if value in ("", None):
        return ""
    return f"{float(value) * 100:.1f}%"


def avg(rows: list[dict], field: str) -> float:
    values = [num(row.get(field)) for row in rows if row.get(field) not in ("", None)]
    return sum(values) / len(values) if values else 0.0


def weighted(rows: list[dict], field: str, weight_field: str) -> float:
    weight = sum(num(row.get(weight_field)) for row in rows)
    if weight <= 0:
        return avg(rows, field)
    return sum(num(row.get(field)) * num(row.get(weight_field)) for row in rows) / weight


def summarize(rows: list[dict]) -> dict:
    revenue_rows = [row for row in rows if num(row.get("real_income_with_marketing")) > 0]
    if not revenue_rows:
        return {}
    return {
        "months": len(revenue_rows),
        "start": revenue_rows[0]["data_month"],
        "end": revenue_rows[-1]["data_month"],
        "avg_revenue": avg(revenue_rows, "real_income_with_marketing"),
        "avg_new": avg(revenue_rows, "new_customer_count"),
        "avg_old": avg(revenue_rows, "old_customer_count"),
        "avg_total": avg(revenue_rows, "order_customer_times"),
        "before_ticket": weighted(revenue_rows, "per_customer_before_discount", "order_customer_times"),
        "after_ticket": weighted(revenue_rows, "per_customer_after_discount", "order_customer_times"),
        "retention": weighted(revenue_rows, "retention_rate", "old_customer_count"),
        "stored_conversion": weighted(revenue_rows, "stored_member_conversion_rate", "new_customer_count"),
        "therapist_output": weighted(revenue_rows, "therapist_daily_output", "therapist_workdays"),
    }


def period_rows(rows: list[dict], start: str, end: str) -> list[dict]:
    return [row for row in rows if start <= row.get("data_month", "") <= end and num(row.get("real_income_with_marketing")) > 0]


def build() -> tuple[list[dict], list[dict], str]:
    mapping_rows = read_csv(MAPPING)
    base_rows = read_csv(BASE)
    raw_rows = read_csv(RAW)
    summary_rows = read_csv(SUMMARY)
    benchmark_rows = read_csv(BENCHMARK)

    site_to_store = {
        row["确认点位ID"]: row["Hanson门店名称"]
        for row in mapping_rows
        if row.get("确认点位ID") in SITE_IDS
    }
    base_by_site = {row["点位ID"]: row for row in base_rows if row.get("点位ID") in SITE_IDS}
    summary_by_site = {row["点位ID"]: row for row in summary_rows if row.get("点位ID") in SITE_IDS}
    benchmark_by_site = {row["点位ID"]: row for row in benchmark_rows if row.get("点位ID") in SITE_IDS}

    raw_by_store = defaultdict(list)
    for row in raw_rows:
        raw_by_store[row.get("store_name", "")].append(row)
    for rows in raw_by_store.values():
        rows.sort(key=lambda row: row.get("data_month", ""))

    monthly = []
    summary = []
    for site_id in SITE_IDS:
        store = site_to_store.get(site_id, "")
        site = base_by_site.get(site_id, {})
        rows = [row for row in raw_by_store.get(store, []) if num(row.get("real_income_with_marketing")) > 0]
        for row in rows:
            monthly.append(
                {
                    "点位ID": site_id,
                    "门店名称": site.get("门店名称", ""),
                    "Hanson门店名称": store,
                    "月份": row.get("data_month", ""),
                    "实际营收": fmt(num(row.get("real_income_with_marketing"))),
                    "新客数": fmt(num(row.get("new_customer_count"))),
                    "老客数": fmt(num(row.get("old_customer_count"))),
                    "订单客次": fmt(num(row.get("order_customer_times"))),
                    "折扣前客单": fmt(num(row.get("per_customer_before_discount"))),
                    "折扣后客单": fmt(num(row.get("per_customer_after_discount"))),
                    "留存率": fmt(num(row.get("retention_rate"))),
                    "储值转化率": fmt(num(row.get("stored_member_conversion_rate"))),
                    "理疗师日均产值": fmt(num(row.get("therapist_daily_output"))),
                }
            )

        periods = {
            "全量有营收月份": rows,
            "2022-2024稳定观察期": period_rows(rows, "2022-01", "2024-12"),
            "近12月": period_rows(rows, "2025-04", "2026-03"),
            "2025年1-11月": period_rows(rows, "2025-01", "2025-11"),
        }
        for period_name, period_data in periods.items():
            metrics = summarize(period_data)
            if not metrics:
                continue
            summary.append(
                {
                    "点位ID": site_id,
                    "门店名称": site.get("门店名称", ""),
                    "Hanson门店名称": store,
                    "观察期": period_name,
                    "月份数": metrics["months"],
                    "起始月份": metrics["start"],
                    "结束月份": metrics["end"],
                    "月均营收": fmt(metrics["avg_revenue"]),
                    "月均新客": fmt(metrics["avg_new"]),
                    "月均老客": fmt(metrics["avg_old"]),
                    "月均订单客次": fmt(metrics["avg_total"]),
                    "折扣前客单": fmt(metrics["before_ticket"]),
                    "折扣后客单": fmt(metrics["after_ticket"]),
                    "留存率": fmt(metrics["retention"]),
                    "储值转化率": fmt(metrics["stored_conversion"]),
                    "理疗师日均产值": fmt(metrics["therapist_output"]),
                    "月租金": summary_by_site.get(site_id, {}).get("月租金", ""),
                    "近12月租售比": summary_by_site.get(site_id, {}).get("租售比_按平均月营收", ""),
                    "样本角色": benchmark_by_site.get(site_id, {}).get("样本角色", ""),
                    "风险提示": benchmark_by_site.get(site_id, {}).get("风险提示", ""),
                    "业务备注": SITE_NOTES.get(site_id, ""),
                }
            )

    doc = render_doc(summary, base_by_site, summary_by_site, benchmark_by_site)
    return monthly, summary, doc


def row(summary: list[dict], site_id: str, period: str) -> dict:
    return next((item for item in summary if item["点位ID"] == site_id and item["观察期"] == period), {})


def render_doc(summary: list[dict], base_by_site: dict, summary_by_site: dict, benchmark_by_site: dict) -> str:
    huamu = row(summary, "L0002", "近12月")
    yingfeng_recent = row(summary, "L0032", "近12月")
    yingfeng_stable = row(summary, "L0032", "2022-2024稳定观察期")
    luyue = row(summary, "L0083", "全量有营收月份")
    huamu_base = base_by_site.get("L0002", {})
    yingfeng_base = base_by_site.get("L0032", {})
    luyue_base = base_by_site.get("L0083", {})

    facts = "\n".join(f"- {fact}" for fact in USER_FACTS)

    return f"""# 花木店-盈丰天地 500 米迁移失败复盘 V0.2

生成日期：2026-07-13

## 一、复盘问题

花木店是 2014 年开业的成熟老店，长期稳定在 30 万以上。盈丰天地/云汇天地 2022 年开业，原本曾被设想为承接或替代花木店，但实际表现明显偏弱。两点直线距离约 500 米，因此这是一个非常适合作为选址归因样板的案例。

本复盘先回答一个问题：为什么 500 米内，一个点位长期稳定，一个点位明显失败？

## 二、内部经营数据对比

| 门店 | 观察期 | 月均营收 | 月均新客 | 月均老客 | 折扣前客单 | 储值转化率 | 留存率 | 理疗师日均产值 | 月租金/租售比 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 花木店 | 近12月 | {huamu.get("月均营收")} | {huamu.get("月均新客")} | {huamu.get("月均老客")} | {huamu.get("折扣前客单")} | {huamu.get("储值转化率")} | {huamu.get("留存率")} | {huamu.get("理疗师日均产值")} | {huamu.get("月租金")} / {pct(num(huamu.get("近12月租售比")))} |
| 盈丰天地/云汇天地 | 2022-2024稳定观察期 | {yingfeng_stable.get("月均营收")} | {yingfeng_stable.get("月均新客")} | {yingfeng_stable.get("月均老客")} | {yingfeng_stable.get("折扣前客单")} | {yingfeng_stable.get("储值转化率")} | {yingfeng_stable.get("留存率")} | {yingfeng_stable.get("理疗师日均产值")} | - |
| 盈丰天地/云汇天地 | 近12月 | {yingfeng_recent.get("月均营收")} | {yingfeng_recent.get("月均新客")} | {yingfeng_recent.get("月均老客")} | {yingfeng_recent.get("折扣前客单")} | {yingfeng_recent.get("储值转化率")} | {yingfeng_recent.get("留存率")} | {yingfeng_recent.get("理疗师日均产值")} | {yingfeng_recent.get("月租金")} / {pct(num(yingfeng_recent.get("近12月租售比")))} |
| 花木陆悦坊 | 全量有营收月份 | {luyue.get("月均营收")} | {luyue.get("月均新客")} | {luyue.get("月均老客")} | {luyue.get("折扣前客单")} | {luyue.get("储值转化率")} | {luyue.get("留存率")} | {luyue.get("理疗师日均产值")} | {luyue.get("月租金")} / {pct(num(luyue.get("近12月租售比")))} |

数据口径说明：
- 近12月为 2025-04 至 2026-03。
- 盈丰天地近12月包含关停前收缩期，因此同时列出 2022-2024 稳定观察期。
- 花木陆悦坊有效营收月份不足，只作为同区域新点观察，不作为正反样本定性。

## 三、业务事实校准

{facts}

## 四、修正后的初步结论

1. 花木店不是单纯靠“这个商圈”好，而是已经形成成熟顾客资产。近12月月均营收约 {huamu.get("月均营收")}，月均老客约 {huamu.get("月均老客")}，说明它的核心不是一次性新客冲高，而是稳定老客和服务关系。

2. 盈丰天地的问题首先不是客单价，而是有效顾客规模不足。2022-2024 稳定观察期月均营收约 {yingfeng_stable.get("月均营收")}，月均新客约 {yingfeng_stable.get("月均新客")}，月均老客约 {yingfeng_stable.get("月均老客")}；近12月继续走弱，租售比恶化到 {pct(num(yingfeng_recent.get("近12月租售比")))}。

3. “500 米”可以带来短期迁移，但没有形成持续迁移。花木翻新约 20 多天期间，盈丰月营收曾接近 30 万，说明花木老客并非完全不能到盈丰；但花木恢复后客人又回流花木，说明盈丰没有把临时承接转化为长期留存。

4. 盈丰的问题更像是“商场自身目的性和长期吸引力不足”，而不是停车、入口或物理可达性明显失败。盈丰在 B1、电梯和手扶梯旁，停车路径不绕，理论上停车体验优于花木；但商场客流少、空铺率高、消费目的性弱，使其无法持续承接花木的成熟客群。

5. 搬迁决策的原始逻辑是成立的：花木商业街较老、客单价走低、品牌形象需要升级。但这个案例说明，品牌形象升级不能替代稳定客源资产；新商场如果没有足够目的性客流，迁店风险会被显著放大。

## 五、关键假设

### 假设 A：花木店的优势来自成熟社区/街区动线和老客习惯

花木地址：{huamu_base.get("地址", "")}

需要验证：
- 距离最近地铁口的真实步行路径。
- 周边高频老客来源是社区、办公还是长期目的性消费。
- 花木是否具备街铺可见性和低决策成本。

### 假设 B：盈丰天地可以短期承接花木客人，但留不住

盈丰/云汇地址：{yingfeng_base.get("地址", "")}

需要验证：
- 花木翻新期间盈丰接近 30 万的具体月份和数据构成。
- 该月增长来自花木老客、自然新客，还是一次性运营引流。
- 花木恢复后，去过盈丰的会员回流比例。
- 盈丰无法持续留住客人的主要原因是商场吸引力、门店体验、团队承接，还是顾客路径习惯。

### 假设 C：盈丰天地自身的新客发现效率不足

需要验证：
- 大众点评/小红书/地图搜索中的门店曝光、评价数量、关键词。
- 1km/1.5km/3km 内竞品密度和价格带。
- 商场内同楼层业态是否支持按摩/疗愈类目的自然发现。
- 商场后期空铺率、招商质量、公共餐饮/展会属性，对 LANN 自然新客发现是否有负向影响。

## 六、下一步我来拉取/整理的数据

内部数据：
- 花木与盈丰的会员重叠和迁移：花木老客是否去盈丰消费过。
- 花木翻新期间盈丰接近 30 万的月份拆解：新客、老客、储值转化、点钟、开卡、消费会员来源。
- 花木恢复后 3-6 个月，盈丰承接会员的复购和回流去向。
- 两店开业后 6-12 个月爬坡曲线。
- 两店点钟、开卡、储值转化、老客复购频次差异。

外部数据：
- 地图坐标、步行距离、步行时间、地铁口与停车路径。
- 商场楼层、主入口、扶梯/电梯路径、是否 B1、是否主力客流动线。
- 周边住宅、办公、商业 POI 和竞品密度。
- 点评/小红书/地图声量和评价结构。
- 盈丰天地招商、空铺、主力业态和写字楼配套属性。

## 七、对选址模型的启发

这个案例暂时提炼出 5 个必须进入后续选址模型的因子：

1. 直线距离不能替代真实到店路径。
2. 老客迁移要区分“能否短期迁移”和“能否长期留存”。
3. 商场内铺不能只看停车、入口和楼层，还要看商场自身目的性、招商质量和空铺风险。
4. 品牌形象升级型迁店必须单独评估“原老店顾客资产损失”。
5. 选址调研必须补“新客发现效率”“老客承接成本”“商场持续经营活力”三个字段。

## 八、当前判断等级

当前结论为 V0.2 校准版，依据内部 BI、租金、门店基础表和用户业务补充形成。下一版最关键的验证数据是会员跨店迁移和花木翻新期间盈丰接近 30 万月份的构成拆解。
"""


def main() -> None:
    monthly, summary, doc = build()
    write_csv(
        MONTHLY_OUT,
        monthly,
        [
            "点位ID",
            "门店名称",
            "Hanson门店名称",
            "月份",
            "实际营收",
            "新客数",
            "老客数",
            "订单客次",
            "折扣前客单",
            "折扣后客单",
            "留存率",
            "储值转化率",
            "理疗师日均产值",
        ],
    )
    write_csv(
        SUMMARY_OUT,
        summary,
        [
            "点位ID",
            "门店名称",
            "Hanson门店名称",
            "观察期",
            "月份数",
            "起始月份",
            "结束月份",
            "月均营收",
            "月均新客",
            "月均老客",
            "月均订单客次",
            "折扣前客单",
            "折扣后客单",
            "留存率",
            "储值转化率",
            "理疗师日均产值",
            "月租金",
            "近12月租售比",
            "样本角色",
            "风险提示",
            "业务备注",
        ],
    )
    DOC_OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {MONTHLY_OUT} rows={len(monthly)}")
    print(f"wrote {SUMMARY_OUT} rows={len(summary)}")
    print(f"wrote {DOC_OUT}")


if __name__ == "__main__":
    main()
