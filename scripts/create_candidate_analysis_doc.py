import csv
from datetime import datetime
from pathlib import Path

from services import feishu_client
from services.feishu_client import FEISHU_BASE_URL, SESSION, _proxies


SOURCE = Path("data/staging/candidate_screen.csv")
TITLE = "新点位初筛归因分析"

HEADING = {1: (3, "heading1"), 2: (4, "heading2"), 3: (5, "heading3")}


def read_rows() -> list[dict]:
    with SOURCE.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def count_by(rows: list[dict], field: str) -> dict[str, int]:
    counts = {}
    for row in rows:
        key = row.get(field) or "空"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True))


def top_rows(rows: list[dict], limit: int = 20) -> list[dict]:
    matched = [row for row in rows if row.get("匹配状态") != "未匹配"]
    not_waiting = [row for row in rows if row.get("初筛结论") != "待补资料"]
    seen = set()
    result = []
    for row in not_waiting + matched:
        key = row.get("record_id") or row.get("项目名称")
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= limit:
            break
    return result


def bullet_table(rows: list[dict]) -> list[str]:
    lines = []
    for row in rows:
        parts = [
            row.get("项目名称", ""),
            row.get("城市", ""),
            f"匹配：{row.get('匹配调研门店') or row.get('匹配状态')}",
            f"营收：{row.get('采用预期月营业额') or '缺'}",
            f"月租：{row.get('租金物业月成本') or '缺'}",
            f"租售比：{row.get('估算租售比') or '无法算'}",
            f"结论：{row.get('初筛结论')}",
            f"问题：{row.get('资料风险')}",
        ]
        lines.append("；".join(parts))
    return lines


def build_markdown(rows: list[dict]) -> str:
    total = len(rows)
    conclusion_counts = count_by(rows, "初筛结论")
    match_counts = count_by(rows, "匹配状态")
    risk_counts = count_by(rows, "资料风险")
    matched_count = total - match_counts.get("未匹配", 0)

    lines = [
        f"# {TITLE}",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 一、结论摘要",
        f"- 本轮覆盖候选项目 {total} 个。",
        f"- 能与选址调研报告形成匹配的项目 {matched_count} 个；未匹配 {match_counts.get('未匹配', 0)} 个。",
        f"- 当前可算出租售比的核心样本很少，初筛结果应作为“资料治理优先级”，不能直接作为最终选址结论。",
        f"- 本轮只有西岸梦中心同时具备调研稳定营收与月租金物业成本，可形成租售比估算：约 0.156，低于现有门店租售比中位数，结论为可跟进但需补资料。",
        "",
        "## 二、初筛结论分布",
    ]
    for key, value in conclusion_counts.items():
        lines.append(f"- {key}：{value} 个")

    lines.extend(["", "## 三、调研报告匹配情况"])
    for key, value in match_counts.items():
        lines.append(f"- {key}：{value} 个")

    lines.extend(
        [
            "",
            "## 四、主要归因",
            "- 第一归因：租金口径缺失。多数候选项目即使有预期营收，也缺少月租金、物业费或可换算的面积/日租金组合，导致无法计算租售比。",
            "- 第二归因：调研报告链路未沉淀到候选表。236 个候选里，只有少数能通过城市约束后的名称匹配连到调研事实；报告链接字段大量为空，导致匹配稳定性不足。",
            "- 第三归因：预期营收口径混用。候选表中存在 80、6 等小数字，脚本已对小于 1000 的候选营收按万元暂估并标记；调研报告中“6个月”这类周期不再被当作金额采用。",
            "- 第四归因：候选资料完整度不足。大量项目处于“资料部分可用”或“缺基础字段”，缺口集中在预期营收、租金口径、调研报告链接和基础字段。",
            "- 第五归因：当前初筛是数据治理视角，不是最终业务判断。没有租金和营收的项目不能被判定为差，只能判定为暂时无法进入严肃对标。",
            "",
            "## 五、资料风险 Top 分布",
        ]
    )
    for key, value in list(risk_counts.items())[:12]:
        lines.append(f"- {key}：{value} 个")

    lines.extend(["", "## 六、重点样本"])
    lines.extend([f"- {line}" for line in bullet_table(top_rows(rows))])

    lines.extend(
        [
            "",
            "## 七、下一步建议",
            "- P0：先补齐候选项目的租金/月成本口径，优先字段为月租金、物业费、面积、日租金、免租期和合同年限。",
            "- P0：把已有 14 份选址调研报告链接回填到扩展管理候选表，避免依赖名称模糊匹配。",
            "- P1：统一预期月营业额单位，明确所有金额字段使用“元/月”，历史万元口径字段单独标记。",
            "- P1：对“可初步对标”的候选项目优先补调研报告和租金口径，形成第一批可复核样本。",
            "- P2：在数据补齐后，再把现有门店基准表中的正向/反向样本用于相似商场、城市、面积和租售比对标。",
            "",
            "## 八、数据来源",
            "- 扩展管理候选项目：data/staging/expansion_candidates.csv",
            "- 选址调研报告结构化事实：data/staging/site_survey_facts.csv",
            "- 现有门店经营基准分位：data/staging/site_benchmark_stats.csv",
            "- 初筛输出：data/staging/candidate_screen.csv",
        ]
    )
    return "\n".join(lines)


def clean_text(value: str) -> str:
    return value.replace("**", "").replace("`", "").strip()


def block(block_type: int, key: str, content: str) -> dict:
    return {"block_type": block_type, key: {"elements": [{"text_run": {"content": content}}]}}


def md_to_blocks(md: str) -> list[dict]:
    blocks = []
    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            bt, key = HEADING[3]
            blocks.append(block(bt, key, clean_text(line[4:])))
        elif line.startswith("## "):
            bt, key = HEADING[2]
            blocks.append(block(bt, key, clean_text(line[3:])))
        elif line.startswith("# "):
            bt, key = HEADING[1]
            blocks.append(block(bt, key, clean_text(line[2:])))
        elif line.startswith("- "):
            blocks.append(block(12, "bullet", clean_text(line[2:])))
        else:
            blocks.append(block(2, "text", clean_text(line)))
    return blocks


def create_doc(token: str, title: str) -> str:
    url = f"{FEISHU_BASE_URL}/docx/v1/documents"
    headers = {"Authorization": f"Bearer {token}"}
    resp = SESSION.post(url, headers=headers, json={"title": title}, proxies=_proxies(), timeout=60)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"创建飞书文档失败：code={data.get('code')} msg={data.get('msg')} data={data}")
    doc = data.get("data", {}).get("document", {})
    document_id = doc.get("document_id") or data.get("data", {}).get("document_id")
    if not document_id:
        raise RuntimeError(f"创建飞书文档成功但未返回 document_id：{data}")
    return document_id


def insert_blocks(document_id: str, blocks: list[dict], token: str) -> None:
    url = f"{FEISHU_BASE_URL}/docx/v1/documents/{document_id}/blocks/{document_id}/children"
    headers = {"Authorization": f"Bearer {token}"}
    for start in range(0, len(blocks), 40):
        batch = blocks[start : start + 40]
        resp = SESSION.post(
            url,
            headers=headers,
            json={"children": batch, "index": start},
            proxies=_proxies(),
            timeout=60,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"写入飞书文档失败：code={data.get('code')} msg={data.get('msg')} data={data}")


def main() -> None:
    rows = read_rows()
    md = build_markdown(rows)
    token = feishu_client.get_tenant_access_token()
    title = f"{TITLE} - {datetime.now().strftime('%Y%m%d')}"
    document_id = create_doc(token, title)
    insert_blocks(document_id, md_to_blocks(md), token)
    print(f"https://lann.feishu.cn/docx/{document_id}")


if __name__ == "__main__":
    main()
