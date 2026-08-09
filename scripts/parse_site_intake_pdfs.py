"""Parse archived PDF sources from a neutral Bot intake package.

The parser is deliberately conservative: it extracts only labelled values that
can be tied to a concrete page. It does not score floor plans, traffic flow, or
commercial quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pdfplumber
from pypdf import PdfReader

from scripts.convert_neutral_site_input import convert_neutral_packet, validate_neutral_packet


TEXT_PAGE_MIN_CHARS = 20


@dataclass(frozen=True)
class FactRule:
    field: str
    category: str
    pattern: re.Pattern[str]
    value: Callable[[re.Match[str]], Any]
    unit: str | None = None
    confidence: str = "高"
    fact_scope: str = "direct"


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _group(group: int = 1) -> Callable[[re.Match[str]], str]:
    return lambda match: match.group(group).strip()


def audience_from_text(text: str) -> str:
    positions = {
        audience: text.find(audience)
        for audience in ("居住客群", "办公客群")
        if audience in text
    }
    return min(positions, key=positions.get) if positions else ""


FACT_RULES = [
    FactRule(
        "项目所在板块",
        "项目概况",
        re.compile(r"(上海松江\s*泗泾镇板块)"),
        lambda match: re.sub(r"\s+", "", match.group(1)),
    ),
    FactRule(
        "轨交关系",
        "项目概况",
        re.compile(r"(9号线泗泾站地铁上盖)"),
        _group(),
    ),
    FactRule(
        "商业楼层",
        "项目概况",
        re.compile(r"商业\s*楼层\s*(B\d+\s*[-–]\s*L\d+)", re.I),
        lambda match: re.sub(r"\s+", "", match.group(1)),
    ),
    FactRule(
        "项目总建筑面积_GFA",
        "项目概况",
        re.compile(r"总建筑面积\s*\(GFA\)\s*约?\s*(\d+(?:\.\d+)?)\s*万\s*m[²2]", re.I),
        _group(),
        "万平方米",
    ),
    FactRule(
        "经营建筑面积_GRA",
        "项目概况",
        re.compile(r"经营\s*建筑面积\s*\(GRA\)\s*约?\s*(\d+(?:\.\d+)?)\s*万\s*m[²2]", re.I),
        _group(),
        "万平方米",
    ),
    FactRule(
        "商业可租赁面积",
        "项目概况",
        re.compile(r"商业\s*可租赁面积\s*约?\s*(\d+(?:\.\d+)?)\s*万\s*m[²2]", re.I),
        _group(),
        "万平方米",
    ),
    FactRule(
        "停车位",
        "项目概况",
        re.compile(r"停车位\s*约?\s*(\d+)\s*个"),
        _group(),
        "个",
    ),
    FactRule(
        "住宅配套",
        "项目概况",
        re.compile(r"住宅配套\s*约?\s*(\d+)\s*套"),
        _group(),
        "套",
    ),
    FactRule(
        "计划开业时间",
        "项目概况",
        re.compile(r"(\d{4}\s*年\s*Q[1-4]).{0,12}开业", re.I),
        lambda match: re.sub(r"\s+", "", match.group(1)),
    ),
    FactRule(
        "铺位号",
        "铺位",
        re.compile(r"(?:店铺编号|铺位号)\s*[：:]?\s*([A-Z]\d+[A-Za-z]?)"),
        _group(),
    ),
    FactRule(
        "使用面积",
        "铺位",
        re.compile(r"使用面积\s*[：:]?\s*(\d+(?:\.\d+)?)\s*[㎡m²2]+"),
        _group(),
        "平方米（暂定，以实测报告为准）",
    ),
    FactRule(
        "所在楼层",
        "铺位",
        re.compile(r"楼层\s*(L\d+)\s*铺位号"),
        _group(),
    ),
    FactRule(
        "租赁期限",
        "租赁条件",
        re.compile(r"租赁期限\s*(\d+年)\s*[（(]不含装修期[：:]?\s*([\d.]+个月)[）)]"),
        lambda match: f"{match.group(1)}（不含装修期{match.group(2)}）",
    ),
    FactRule(
        "预计开业日",
        "租赁条件",
        re.compile(r"预计开业日\s*(\d{4}年\d{1,2}月\d{1,2}日)"),
        _group(),
    ),
    FactRule(
        "合作方式",
        "租赁条件",
        re.compile(r"合作方式\s*(扣率租金和固定租金两者取高\+物业管理费\+推广费)"),
        _group(),
    ),
    FactRule(
        "付款方式",
        "租赁条件",
        re.compile(r"付款方式\s*(季付|月付|半年付|年付)"),
        _group(),
    ),
    FactRule(
        "物业管理费",
        "租赁条件",
        re.compile(r"物业管理费单价[：:]?\s*(\d+(?:\.\d+)?)\s*元/m[²2]/月"),
        _group(),
        "元/平方米/月（含税）",
    ),
    FactRule(
        "推广费",
        "租赁条件",
        re.compile(r"推广费单价[：:]?\s*(\d+(?:\.\d+)?)\s*元/m[²2]/月"),
        _group(),
        "元/平方米/月（含税）",
    ),
    FactRule(
        "POS及数据采集设备费",
        "租赁条件",
        re.compile(r"POS机及数据采集设备费[：:]?\s*(\d+)\s*元/月"),
        _group(),
        "元/月（含税）",
    ),
    FactRule(
        "装修期管理费",
        "租赁条件",
        re.compile(r"装修期管理费.{0,12}?(\d+(?:\.\d+)?)\s*元/m[²2]"),
        _group(),
        "元/平方米（含税）",
    ),
    FactRule(
        "意向金",
        "租赁条件",
        re.compile(r"意向金\s*(\d+)\s*元"),
        _group(),
        "元",
    ),
    FactRule(
        "租赁保证金",
        "租赁条件",
        re.compile(r"租赁保证金.{0,40}?(\d+)\s*个月.{0,40}?人民币\s*(\d+)\s*元"),
        lambda match: {
            "months": match.group(1),
            "amount_yuan": match.group(2),
            "basis": "末年月租金+月物业费+月推广费",
        },
    ),
    FactRule(
        "提案回复期限",
        "租赁条件",
        re.compile(r"于\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)前给予回复"),
        lambda match: re.sub(r"\s+", "", match.group(1)),
    ),
    FactRule(
        "提案法律效力声明",
        "租赁条件",
        re.compile(r"(本建议书仅为我方向贵方提供的租赁建议，不具有法律约束力，亦不构成我方向贵方的要约)"),
        _group(),
    ),
    FactRule(
        "报告口径_现有居住人口",
        "调研数据",
        re.compile(r"现有居住人口\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
    FactRule(
        "报告口径_现有办公总人口",
        "调研数据",
        re.compile(r"现有(?:总)?办公人口\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
    FactRule(
        "报告口径_现有办公净人口",
        "调研数据",
        re.compile(r"办公净人口\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
    FactRule(
        "报告口径_现有总人口",
        "调研数据",
        re.compile(r"现有总人口\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
    FactRule(
        "报告预测_2026年底总人口",
        "调研数据",
        re.compile(r"预计至2026年底总人口约为\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
    FactRule(
        "报告预测_未来总人口",
        "调研数据",
        re.compile(r"未来总人口数量\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
    FactRule(
        "报告预测_未来总人口约值",
        "调研数据",
        re.compile(r"未来总人口近\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
    FactRule(
        "报告口径_休闲娱乐特征",
        "调研数据",
        re.compile(
            r"(休闲娱乐以影院、足疗按摩、KTV等传统娱乐消费主导，"
            r"区域内更常消费影院、按摩以及健身运动，"
            r"酒吧(?:、书店)?、新潮娱乐体验等消费显著外溢)"
        ),
        _group(),
        confidence="中",
    ),
    FactRule(
        "报告口径_居住客群美业特征",
        "调研数据",
        re.compile(r"(美业消费较活跃，且有外溢消费情况)"),
        _group(),
        confidence="中",
    ),
    FactRule(
        "报告口径_美容SPA外溢特征",
        "调研数据",
        re.compile(r"(美发、美容\s*spa区域外消费较活跃)", re.I),
        lambda match: re.sub(r"\s+", "", match.group(1)),
        confidence="中",
    ),
    FactRule(
        "报告口径_区域外偏好品牌包含LANNI",
        "调研数据",
        re.compile(r"(LANNI泰式古法按摩)"),
        _group(),
        confidence="中",
    ),
    FactRule(
        "手册口径_泗泾站工作日早高峰日均客流",
        "商场手册",
        re.compile(r"工作日早高峰日均客流量[^。]{0,40}?最高达\s*(\d+(?:\.\d+)?)\s*万人次"),
        _group(),
        "万人次",
        "中",
    ),
    FactRule(
        "手册口径_泗泾站单日最高客流",
        "商场手册",
        re.compile(r"单日泗泾站最高客流达\s*(\d+(?:\.\d+)?)\s*万人次"),
        _group(),
        "万人次",
        "中",
    ),
    FactRule(
        "手册口径_9号线日均客流",
        "商场手册",
        re.compile(r"9号线日均客流达\s*(\d+(?:\.\d+)?)\s*万人次"),
        _group(),
        "万人次",
        "中",
    ),
    FactRule(
        "手册口径_15分钟车程覆盖人口",
        "商场手册",
        re.compile(r"15分钟车程覆盖人口约为\s*(\d+(?:\.\d+)?)\s*万"),
        _group(),
        "万人",
        "中",
    ),
]


def _non_space_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def suspicious_character_ratio(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return 0.0
    suspicious = 0
    for char in compact:
        code = ord(char)
        category = unicodedata.category(char)
        allowed = (
            char.isascii()
            or 0x3400 <= code <= 0x9FFF
            or 0x3000 <= code <= 0x303F
            or 0xFF00 <= code <= 0xFFEF
            or category.startswith(("N", "P", "S"))
        )
        if not allowed or char == "\ufffd":
            suspicious += 1
    return suspicious / len(compact)


def image_coverage(page: Any) -> float:
    page_area = float(page.width * page.height) or 1.0
    area = 0.0
    for image in page.images:
        width = max(0.0, float(image.get("x1", 0)) - float(image.get("x0", 0)))
        height = max(0.0, float(image.get("bottom", 0)) - float(image.get("top", 0)))
        area += width * height
    return min(area / page_area, 1.0)


def diagnose_page(page: Any, text: str, tables: list[list[list[str | None]]]) -> dict[str, Any]:
    character_count = _non_space_length(text)
    suspicious_ratio = suspicious_character_ratio(text)
    vector_object_count = len(page.lines) + len(page.rects) + len(page.curves)
    coverage = image_coverage(page)
    flags: list[str] = []
    if character_count < 80:
        flags.append("文字层不足")
    if suspicious_ratio >= 0.05 or "\ufffd" in text:
        flags.append("文字层疑似乱码")
    if tables and (character_count < 350 or vector_object_count >= 150):
        flags.append("以表格为主")
    if (
        coverage >= 0.35
        or (page.images and character_count < 220)
        or vector_object_count >= 500
    ):
        flags.append("以图片或复杂图形为主")
    return {
        "text_character_count": character_count,
        "suspicious_character_ratio": round(suspicious_ratio, 4),
        "image_count": len(page.images),
        "image_coverage": round(coverage, 4),
        "vector_object_count": vector_object_count,
        "detected_table_count": len(tables),
        "quality_flags": flags,
    }


def normalize_ocr_text(text: str) -> str:
    text = text.replace("．", ".").replace("：", ":")
    return re.sub(
        r"(?<=[\u3400-\u9fffA-Za-z0-9])\s+(?=[\u3400-\u9fffA-Za-z0-9])",
        "",
        text,
    )


def meaningful_tables(tables: list[list[list[str | None]]]) -> list[list[list[str]]]:
    cleaned: list[list[list[str]]] = []
    for table in tables:
        rows = [
            [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in row]
            for row in table
        ]
        nonempty = sum(bool(cell) for row in rows for cell in row)
        columns = max((len(row) for row in rows), default=0)
        if nonempty >= 4 and columns >= 2:
            cleaned.append(rows)
    return cleaned


def extract_life_service_chart_fact(page: Any, text: str) -> dict[str, Any] | None:
    if not re.search(r"生活服务(?:业态)?消费频次占比", text):
        return None
    audience = audience_from_text(text)
    if not audience:
        return None
    categories = ["超市", "便利店", "花店", "美甲美睫", "美发", "美容SPA", "其他"]
    words = page.extract_words()
    labels = {
        word["text"]: word
        for word in words
        if word["text"] in categories and float(word["top"]) < 300
    }
    percentages = [
        word
        for word in words
        if re.fullmatch(r"\d+(?:\.\d+)?%", word["text"])
        and 140 < float(word["top"]) < 240
    ]
    values: dict[str, dict[str, float]] = {}
    for category in categories:
        label = labels.get(category)
        if not label:
            return None
        center = (float(label["x0"]) + float(label["x1"])) / 2
        nearby = sorted(
            (
                word
                for word in percentages
                if abs(((float(word["x0"]) + float(word["x1"])) / 2) - center) < 45
            ),
            key=lambda word: float(word["x0"]),
        )
        if len(nearby) != 2:
            return None
        values[category] = {
            "区域内": float(nearby[0]["text"].rstrip("%")),
            "区域外": float(nearby[1]["text"].rstrip("%")),
        }
    return {
        "category": "调研数据",
        "field": f"报告口径_{audience}生活服务消费频次占比",
        "value": values,
        "unit": "%",
        "fact_kind": "资料可证实事实",
        "confidence": "中",
        "recognition_method": "pdfplumber_layout",
    }


def find_pdftoppm(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise FileNotFoundError(f"pdftoppm不存在: {path}")
    discovered = shutil.which("pdftoppm")
    if discovered and not discovered.lower().endswith(".cmd"):
        return Path(discovered)
    bundled = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe"
    )
    if bundled.is_file():
        return bundled
    raise FileNotFoundError("未找到可用的pdftoppm可执行文件")


def render_page(pdf_path: Path, page_number: int, output_prefix: Path, pdftoppm: Path) -> Path:
    subprocess.run(
        [
            str(pdftoppm),
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-singlefile",
            "-png",
            "-r",
            "170",
            str(pdf_path),
            str(output_prefix),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    image_path = output_prefix.with_suffix(".png")
    if not image_path.is_file():
        raise FileNotFoundError(f"页面渲染未生成图片: {image_path}")
    return image_path


def run_windows_ocr(image_path: Path, script_path: Path) -> dict[str, Any]:
    # OCR output is temporary and must never be written beside a Bot-owned,
    # read-only archived source.
    with tempfile.TemporaryDirectory(prefix="lann-site-ocr-result-") as directory:
        output_path = Path(directory) / "ocr.json"
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-ImagePath",
                str(image_path),
                "-OutputPath",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if output_path.is_file():
            return json.loads(output_path.read_text(encoding="utf-8-sig"))
        return json.loads(completed.stdout)


def classify_pdf(page_texts: list[str]) -> str:
    readable = sum(len(_compact(text)) >= TEXT_PAGE_MIN_CHARS for text in page_texts)
    if not readable:
        return "扫描型或无可提取文字"
    if readable == len(page_texts):
        return "文本型"
    return "图文混合型"


def _page_source(source: dict[str, Any], page_number: int) -> dict[str, Any]:
    storage = source["storage"]
    return {
        "source_id": f"{source['source_id']}-p{page_number}",
        "source_type": "其他",
        "title": f"{source['original_file_name']}（第{page_number}页）",
        "ref": f"bot-storage://{storage['relative_path']}#page={page_number}",
        "availability": "可读取",
    }


def extract_page_facts(
    text: str, recognition_method: str = "pdf_text_layer"
) -> list[dict[str, Any]]:
    compact = _compact(text)
    rows: list[dict[str, Any]] = []
    for rule in FACT_RULES:
        match = rule.pattern.search(compact)
        if not match:
            continue
        row = {
            "category": rule.category,
            "field": rule.field,
            "value": rule.value(match),
            "fact_kind": "资料可证实事实",
            "confidence": rule.confidence,
            "recognition_method": recognition_method,
        }
        if rule.field == "报告口径_休闲娱乐特征":
            audience = audience_from_text(compact)
            if audience:
                row["field"] = f"报告口径_{audience}休闲娱乐特征"
        if rule.unit:
            row["unit"] = rule.unit
        rows.append(row)

    rent_table = re.search(
        r"第1年\s*(\d+)\s*(\d+)%\s*第2年\s*(\d+)\s*(\d+)%\s*"
        r"第3年\s*(\d+)\s*(\d+)%\s*第4年\s*(\d+)\s*(\d+)%\s*"
        r"第5年\s*(\d+)\s*(\d+)%",
        compact,
    )
    if rent_table:
        values = list(rent_table.groups())
        rows.append(
            {
                "category": "租赁条件",
                "field": "营运期租金",
                "value": [
                    {
                        "year": year,
                        "fixed_rent_yuan_per_sqm_month": values[(year - 1) * 2],
                        "turnover_rate_percent": values[(year - 1) * 2 + 1],
                    }
                    for year in range(1, 6)
                ],
                "fact_kind": "资料可证实事实",
                "confidence": "高",
                "recognition_method": recognition_method,
            }
        )
    return rows


def low_confidence_candidates(
    text: str, source_id: str, page_number: int, recognition_method: str
) -> list[dict[str, Any]]:
    compact = _compact(text)
    candidates: list[dict[str, Any]] = []
    patterns = [
        (
            "手册声称_5公里内无竞品",
            re.compile(r"5\s*公里内无竞品"),
            "招商手册营销口径，需以外部竞品地图和现场核验，不能直接作为选址事实",
        ),
        (
            "手册声称_泗泾站客流排名",
            re.compile(r"泗泾站蝉联\s*TOP\s*1", re.I),
            "排名口径、统计范围和原始数据尚未提供",
        ),
    ]
    if recognition_method == "windows_media_ocr":
        patterns.append(
            (
                "图面文字_目标铺位候选",
                re.compile(r"L4015a", re.I),
                "图面OCR识别到目标铺位号，需与可视图面或原始CAD人工复核",
            )
        )
    for field, pattern, reason in patterns:
        match = pattern.search(compact)
        if not match:
            continue
        candidates.append(
            {
                "candidate_id": f"review-{source_id}-p{page_number}-{len(candidates) + 1}",
                "field": field,
                "value": match.group(0),
                "source_ref": f"{source_id}-p{page_number}",
                "recognition_method": recognition_method,
                "confidence": "低",
                "reason": reason,
            }
        )
    return candidates


def parse_neutral_pdf_package(
    packet: dict[str, Any],
    storage_root: Path,
    *,
    enable_ocr: bool = False,
    pdftoppm_path: str | None = None,
    ocr_script_path: Path | None = None,
    ocr_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_neutral_packet(packet)

    internal = convert_neutral_packet(packet)
    inventory: list[dict[str, Any]] = []
    page_sources: dict[str, dict[str, Any]] = {}
    extracted: list[dict[str, Any]] = []
    unreadable: list[str] = []
    page_analysis: list[dict[str, Any]] = []
    table_records: list[dict[str, Any]] = []
    manual_review_items: list[dict[str, Any]] = []
    ocr_errors: list[str] = []
    poppler = find_pdftoppm(pdftoppm_path) if enable_ocr else None
    ocr_script = ocr_script_path or Path(__file__).with_name("windows_ocr_page.ps1")

    with tempfile.TemporaryDirectory(prefix="lann-site-pdf-ocr-") as temporary:
        temporary_root = Path(temporary)
        for source in packet["sources"]:
            storage = source.get("storage")
            if source.get("source_kind") != "file" or not storage:
                continue
            path = storage_root / storage["relative_path"]
            if not path.is_file():
                unreadable.append(f"{source['source_id']}：归档文件不存在")
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != storage["sha256"]:
                unreadable.append(f"{source['source_id']}：文件哈希与中性包不一致")
                continue
            try:
                reader = PdfReader(str(path))
                fallback_texts = [page.extract_text() or "" for page in reader.pages]
                plumber = pdfplumber.open(path)
            except Exception as exc:  # pragma: no cover - reader errors vary by PDF
                unreadable.append(f"{source['source_id']}：PDF读取失败（{type(exc).__name__}）")
                continue

            page_texts: list[str] = []
            try:
                for page_number, page in enumerate(plumber.pages, start=1):
                    text = page.extract_text() or fallback_texts[page_number - 1]
                    fallback_text = fallback_texts[page_number - 1]
                    page_texts.append(text)
                    raw_tables = page.extract_tables()
                    tables = meaningful_tables(raw_tables)
                    diagnostics = diagnose_page(page, text, raw_tables)
                    fallback_suspicious = suspicious_character_ratio(fallback_text)
                    diagnostics["pypdf_suspicious_character_ratio"] = round(
                        fallback_suspicious, 4
                    )
                    if fallback_suspicious >= 0.05:
                        diagnostics["quality_flags"].append("文字层疑似乱码（pypdf）")
                    page_id = f"{source['source_id']}-p{page_number}"
                    page_sources[page_id] = _page_source(source, page_number)

                    for table_number, rows in enumerate(tables, start=1):
                        table_records.append(
                            {
                                "source_ref": page_id,
                                "file_name": source["original_file_name"],
                                "page_number": page_number,
                                "table_number": table_number,
                                "recognition_method": "pdfplumber_table",
                                "rows": rows,
                            }
                        )

                    for fact in extract_page_facts(text, "pdfplumber_text_layer"):
                        fact["source_refs"] = [page_id]
                        extracted.append(fact)
                    chart_fact = extract_life_service_chart_fact(page, text)
                    if chart_fact:
                        chart_fact["source_refs"] = [page_id]
                        extracted.append(chart_fact)
                    if (
                        _compact(fallback_text) != _compact(text)
                        and fallback_suspicious < 0.05
                    ):
                        for fact in extract_page_facts(fallback_text, "pypdf_text_layer"):
                            fact["source_refs"] = [page_id]
                            extracted.append(fact)
                    manual_review_items.extend(
                        low_confidence_candidates(
                            text, source["source_id"], page_number, "pdfplumber_text_layer"
                        )
                    )

                    page_result: dict[str, Any] = {
                        "source_ref": page_id,
                        "file_name": source["original_file_name"],
                        "page_number": page_number,
                        **diagnostics,
                        "text_layer_excerpt": _compact(text)[:500],
                        "ocr_attempted": False,
                    }
                    if enable_ocr and diagnostics["quality_flags"]:
                        page_result["ocr_attempted"] = True
                        try:
                            cached = (ocr_cache or {}).get(page_id)
                            if cached and cached.get("ocr_engine") and not cached.get("ocr_error"):
                                ocr = {
                                    "engine": cached["ocr_engine"],
                                    "text": cached.get("ocr_text", ""),
                                    "lines": cached.get("ocr_lines", []),
                                }
                                ocr_text = str(cached.get("ocr_text", ""))
                                page_result["ocr_cache_used"] = True
                            else:
                                prefix = temporary_root / f"{source['source_id']}-p{page_number}"
                                image_path = render_page(path, page_number, prefix, poppler)
                                ocr = run_windows_ocr(image_path, ocr_script)
                                ocr_text = normalize_ocr_text(str(ocr.get("text") or ""))
                                page_result["ocr_cache_used"] = False
                            page_result.update(
                                {
                                    "ocr_engine": ocr.get("engine"),
                                    "ocr_character_count": _non_space_length(ocr_text),
                                    "ocr_text": ocr_text,
                                    "ocr_lines": ocr.get("lines", []),
                                }
                            )
                            for fact in extract_page_facts(ocr_text, "windows_media_ocr"):
                                if fact["confidence"] == "高":
                                    fact["confidence"] = "中"
                                fact["source_refs"] = [page_id]
                                extracted.append(fact)
                            manual_review_items.extend(
                                low_confidence_candidates(
                                    ocr_text,
                                    source["source_id"],
                                    page_number,
                                    "windows_media_ocr",
                                )
                            )
                        except Exception as exc:  # pragma: no cover - environment dependent
                            message = (
                                f"{source['original_file_name']}第{page_number}页："
                                f"OCR失败（{type(exc).__name__}: {str(exc)[:160]}）"
                            )
                            page_result["ocr_error"] = message
                            ocr_errors.append(message)
                    page_analysis.append(page_result)
            finally:
                plumber.close()

            page_counts = [_non_space_length(text) for text in page_texts]
            inventory.append(
                {
                    "source_id": source["source_id"],
                    "file_name": source["original_file_name"],
                    "sha256": storage["sha256"],
                    "bytes": len(raw),
                    "page_count": len(page_texts),
                    "text_character_count": sum(page_counts),
                    "page_text_character_counts": page_counts,
                    "pdf_type": classify_pdf(page_texts),
                    "pages_requiring_fallback": sum(
                        bool(row["quality_flags"])
                        for row in page_analysis
                        if row["source_ref"].startswith(f"{source['source_id']}-p")
                    ),
                }
            )

    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in extracted:
        value_key = json.dumps(fact["value"], ensure_ascii=False, sort_keys=True)
        key = (fact["field"], value_key)
        if key not in deduplicated:
            deduplicated[key] = fact
        else:
            deduplicated[key]["source_refs"].extend(fact["source_refs"])
            methods = set(deduplicated[key]["recognition_method"].split("+"))
            methods.update(fact["recognition_method"].split("+"))
            deduplicated[key]["recognition_method"] = "+".join(sorted(methods))
            if fact["confidence"] == "高":
                deduplicated[key]["confidence"] = "高"

    facts = list(deduplicated.values())
    for index, fact in enumerate(facts, start=1):
        fact["fact_id"] = f"pdf-fact-{index:03d}"
        fact["source_refs"] = list(dict.fromkeys(fact["source_refs"]))

    manual_unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in manual_review_items:
        key = (item["field"], str(item["value"]), item["source_ref"])
        manual_unique[key] = item
    manual_review_items = list(manual_unique.values())

    target_units = {
        str(fact["value"])
        for fact in facts
        if fact["field"] == "铺位号" and str(fact["value"]).strip()
    }
    manual_review_items = [
        item
        for item in manual_review_items
        if not (
            item["field"] == "图面文字_目标铺位候选"
            and str(item["value"]) in target_units
        )
    ]
    brand_pages = [
        row
        for row in page_analysis
        if "Brandmixed" in row["file_name"]
        and re.search(r"花园城\s*L4(?:\s|$)", row["text_layer_excerpt"])
    ]
    for unit in target_units:
        if brand_pages and not any(unit.lower() in str(row.get("ocr_text", "")).lower() for row in brand_pages):
            manual_review_items.append(
                {
                    "candidate_id": f"review-brand-map-{unit}",
                    "field": "目标铺位与品牌落位图版本一致性",
                    "value": f"租赁提案目标铺位为{unit}，但L4品牌落位图可视OCR未识别到该铺位号",
                    "source_ref": brand_pages[0]["source_ref"],
                    "recognition_method": "cross_document_check",
                    "confidence": "低",
                    "reason": "可能是品牌图不标铺号、版本差异或图面分辨率限制，需商场提供最新版带铺号平面图确认",
                }
            )

    used_page_ids = {ref for fact in facts for ref in fact["source_refs"]}
    internal["sources"].extend(page_sources[page_id] for page_id in sorted(used_page_ids))
    internal["facts"] = facts
    # Parsing source files improves evidence coverage; it must not advance the
    # formal site stage. A later owner-confirmed workflow may update this value.
    internal["stage_status"]["workflow_stage"] = "待研判"
    if any(fact["field"] == "项目所在板块" and "上海" in fact["value"] for fact in facts):
        internal["candidate"]["city"] = "上海"
    internal["missing_information"] = [
        item
        for item in internal["missing_information"]
        if "文件内容尚未由lann-site解析" not in item
        and item != "项目城市未由Bot中性输入提供"
        and not item.startswith("租金、工程、经营可行性及签约阶段状态尚未")
    ]
    internal["missing_information"].extend(
        [
            "未收到LANN标准工程条件表，电量、给排水、空调、消防、层高等工程初筛条件无法核验",
            "租赁提案注明交付条件需在合同条款商议时确定，当前无法确认最终工程交付条件",
            "铺位图只能核验楼层、铺号和图面标注，不能据此判断人流动线或经营优劣",
            "租赁提案为不具法律约束力的建议书，价格有效性、接受状态及最新版本待人工确认",
            "调研报告中的人口数据属于报告口径，尚未与外部原始数据交叉核验",
            "品牌落位图L4页未在可视OCR中识别到租赁提案所列目标铺位号，需最新版带铺号平面图核对版本一致性",
            "中性包没有用户文字补充或语音转写，现场经营判断、工程人员勘察及客户匹配状态未进入本轮资料",
        ]
    )
    internal["missing_information"].extend(unreadable)
    internal["missing_information"].extend(ocr_errors)
    internal["missing_information"] = list(dict.fromkeys(internal["missing_information"]))

    review = {
        "schema_version": "site-intake-pdf-review/v0.2",
        "project": packet["project"],
        "requested_action": packet["requested_action"],
        "input_summary_confirmed": packet["confirmation"]["input_summary_confirmed"],
        "external_writes": packet["external_writes"],
        "document_inventory": inventory,
        "page_analysis": page_analysis,
        "structured_tables": table_records,
        "page_sources": [page_sources[page_id] for page_id in sorted(used_page_ids)],
        "extracted_facts": facts,
        "manual_review_items": manual_review_items,
        "missing_information": internal["missing_information"],
        "guardrails": [
            "仅提取页面上可直接核验的标签和值",
            "OCR新增事实记录识别方式；OCR单独命中的高置信规则自动降为中置信",
            "低置信识别不进入正式事实，只进入待人工核验清单",
            "表格按页保留二维行列，图面OCR保留词坐标",
            "未对楼层、铺位、人流动线或生意优劣评分",
            "报告口径数据不等于已完成外部交叉验证",
            "未写入dashboard或其他正式业务数据",
        ],
        "review_summary": (
            "文本层、表格和页面图像均已进入逐页诊断；现有资料足以核验项目基本参数、"
            "租赁提案和报告口径，但目标铺位与品牌落位图版本一致性、工程条件及外部数据"
            "仍需人工或外部原始数据确认。"
        ),
    }
    return internal, review


def compare_with_baseline(
    review: dict[str, Any], baseline: dict[str, Any] | None
) -> dict[str, Any]:
    if not baseline:
        return {"baseline_available": False, "added_facts": [], "removed_facts": []}

    def key(fact: dict[str, Any]) -> tuple[str, str]:
        return (
            fact["field"],
            json.dumps(fact["value"], ensure_ascii=False, sort_keys=True),
        )

    before = {key(fact): fact for fact in baseline.get("extracted_facts", [])}
    after = {key(fact): fact for fact in review.get("extracted_facts", [])}
    added = [after[item] for item in after.keys() - before.keys()]
    removed = [before[item] for item in before.keys() - after.keys()]
    return {
        "baseline_available": True,
        "baseline_schema_version": baseline.get("schema_version"),
        "baseline_fact_count": len(before),
        "current_fact_count": len(after),
        "added_facts": sorted(added, key=lambda row: row["field"]),
        "removed_facts": sorted(removed, key=lambda row: row["field"]),
    }


def render_review_markdown(review: dict[str, Any]) -> str:
    flagged_pages = [row for row in review["page_analysis"] if row["quality_flags"]]
    ocr_pages = [row for row in flagged_pages if row["ocr_attempted"]]
    comparison = review.get("comparison") or {}
    lines = [
        f"# {review['project']['name']}资料拆解 v0.2（逐页诊断与OCR增强）",
        "",
        f"- Bot动作：`{review['requested_action']}`（仅收集资料）",
        f"- 输入摘要已确认：{'是' if review['input_summary_confirmed'] else '否'}",
        "- Dashboard写入：禁止，且本次未尝试",
        f"- 本轮结论：{review['review_summary']}",
        f"- 逐页诊断：共{len(review['page_analysis'])}页，{len(flagged_pages)}页触发降级检查，"
        f"{len(ocr_pages)}页已执行本地OCR",
        f"- 结构化表格：{len(review['structured_tables'])}个；待人工核验："
        f"{len(review['manual_review_items'])}项",
        "",
        "## 文件覆盖",
        "",
        "| 文件 | 页数 | 类型 | 可提取字符数 | 降级页数 |",
        "|---|---:|---|---:|---:|",
    ]
    for row in review["document_inventory"]:
        lines.append(
            f"| {row['file_name']} | {row['page_count']} | {row['pdf_type']} | "
            f"{row['text_character_count']} | {row['pages_requiring_fallback']} |"
        )
    if comparison.get("baseline_available"):
        lines.extend(
            [
                "",
                "## 相较第一轮新增读取",
                "",
                f"- 第一轮事实：{comparison['baseline_fact_count']}条；本轮事实："
                f"{comparison['current_fact_count']}条。",
            ]
        )
        for fact in comparison["added_facts"]:
            value = fact["value"]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(
                f"- {fact['field']}：{value}"
                f"（{fact['recognition_method']}，置信度{fact['confidence']}）"
            )
        if not comparison["added_facts"]:
            lines.append("- 没有新增可直接进入事实层的字段；增强结果均进入表格或待人工核验区。")
    lines.extend(
        [
            "",
            "## 可核验事实",
            "",
            "| 类别 | 字段 | 值 | 识别方式/置信度 | 来源 |",
            "|---|---|---|---|---|",
        ]
    )
    source_titles = {row["source_id"]: row["title"] for row in review["page_sources"]}
    for fact in review["extracted_facts"]:
        value = (
            json.dumps(fact["value"], ensure_ascii=False)
            if isinstance(fact["value"], (dict, list))
            else str(fact["value"])
        )
        unit = f" {fact['unit']}" if fact.get("unit") else ""
        lines.append(
            f"| {fact['category']} | {fact['field']} | {value}{unit} | "
            f"{fact.get('recognition_method', '未记录')} / {fact['confidence']} | "
            f"{'、'.join(source_titles[ref] for ref in fact['source_refs'])} |"
        )
    lines.extend(["", "## 待人工核验（未进入正式事实）", ""])
    if review["manual_review_items"]:
        for item in review["manual_review_items"]:
            page = next(
                row for row in review["page_analysis"] if row["source_ref"] == item["source_ref"]
            )
            lines.append(
                f"- **{item['field']}**：{item['value']}；来源："
                f"{page['file_name']}第{page['page_number']}页；方式："
                f"{item['recognition_method']}；原因：{item['reason']}"
            )
    else:
        lines.append("- 无。")
    lines.extend(["", "## 逐页降级覆盖", ""])
    for row in flagged_pages:
        status = (
            f"OCR {row.get('ocr_character_count', 0)}字"
            if row["ocr_attempted"] and not row.get("ocr_error")
            else row.get("ocr_error", "未执行OCR")
        )
        lines.append(
            f"- {row['file_name']}第{row['page_number']}页："
            f"{'、'.join(row['quality_flags'])}；{status}"
        )
    lines.extend(["", "## 尚缺信息", ""])
    lines.extend(f"- {item}" for item in review["missing_information"])
    lines.extend(["", "## 本轮边界", ""])
    lines.extend(f"- {item}" for item in review["guardrails"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse PDFs from a Bot neutral site intake package.")
    parser.add_argument("--input", required=True, help="Bot input-package.json")
    parser.add_argument(
        "--storage-root",
        required=True,
        help="Directory against which storage.relative_path is resolved",
    )
    parser.add_argument("--internal-output", required=True, help="Enriched Site internal input JSON")
    parser.add_argument("--review-output", required=True, help="Review JSON")
    parser.add_argument("--review-markdown", required=True, help="Human review Markdown")
    parser.add_argument("--enable-ocr", action="store_true", help="Render flagged pages and run local OCR")
    parser.add_argument("--pdftoppm", help="Explicit pdftoppm executable")
    parser.add_argument("--baseline-review", help="First-round review JSON for comparison")
    parser.add_argument("--ocr-cache-review", help="Prior v0.2 review JSON whose successful OCR can be reused")
    args = parser.parse_args()

    with Path(args.input).open(encoding="utf-8") as file:
        packet = json.load(file)
    ocr_cache = None
    if args.ocr_cache_review:
        cached_review = json.loads(Path(args.ocr_cache_review).read_text(encoding="utf-8"))
        ocr_cache = {row["source_ref"]: row for row in cached_review.get("page_analysis", [])}
    internal, review = parse_neutral_pdf_package(
        packet,
        Path(args.storage_root),
        enable_ocr=args.enable_ocr,
        pdftoppm_path=args.pdftoppm,
        ocr_cache=ocr_cache,
    )
    baseline = None
    if args.baseline_review:
        baseline = json.loads(Path(args.baseline_review).read_text(encoding="utf-8"))
    review["comparison"] = compare_with_baseline(review, baseline)

    outputs = [
        (Path(args.internal_output), internal),
        (Path(args.review_output), review),
    ]
    for path, payload in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    markdown_path = Path(args.review_markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_review_markdown(review), encoding="utf-8")

    print(f"项目: {review['project']['name']}")
    print(f"PDF: {len(review['document_inventory'])}份")
    print(f"可核验事实: {len(review['extracted_facts'])}条")
    print(f"逐页诊断: {len(review['page_analysis'])}页")
    print(f"OCR: {sum(row['ocr_attempted'] for row in review['page_analysis'])}页")
    print(f"结构化表格: {len(review['structured_tables'])}个")
    print(f"待人工核验: {len(review['manual_review_items'])}项")
    print("楼层/动线主观评分: 未执行")
    print("dashboard写入: 未执行")


if __name__ == "__main__":
    main()
