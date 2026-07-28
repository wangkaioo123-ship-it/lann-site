"""Parse archived image and engineering-workbook sources from a neutral Site intake.

The supplement parser is intentionally conservative. Image OCR produces
human-review candidates rather than formal facts. Engineering workbooks keep
LANN requirements, merchant replies, and machine interpretations separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PIL import Image

from scripts.convert_neutral_site_input import convert_source, validate_neutral_packet
from scripts.parse_site_intake_pdfs import normalize_ocr_text, run_windows_ocr


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
ENGINEERING_SUFFIXES = {".xlsx"}
CRITICAL_TERMS = ("层高", "新风", "排风", "空调", "电力", "给水", "排水", "排污", "消防")


def is_image_source(source: dict[str, Any]) -> bool:
    storage = source.get("storage") or {}
    mime = str(storage.get("mime_type") or "").lower()
    suffix = Path(str(storage.get("relative_path") or "")).suffix.lower()
    return mime.startswith("image/") or suffix in IMAGE_SUFFIXES


def is_engineering_workbook(source: dict[str, Any]) -> bool:
    storage = source.get("storage") or {}
    suffix = Path(str(storage.get("relative_path") or "")).suffix.lower()
    name = str(source.get("original_file_name") or "")
    return suffix in ENGINEERING_SUFFIXES and ("工程" in name or "开店条件" in name)


def verified_archived_path(source: dict[str, Any], storage_root: Path) -> tuple[Path, bytes]:
    storage = source.get("storage") or {}
    relative_path = storage.get("relative_path")
    if not relative_path:
        raise ValueError("中性包未提供归档相对路径")
    resolved_root = storage_root.resolve()
    path = (resolved_root / relative_path).resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError("归档相对路径越出storage root")
    if not path.is_file():
        raise FileNotFoundError("归档文件不存在")
    raw = path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != storage.get("sha256"):
        raise ValueError("文件哈希与中性包不一致")
    if storage.get("bytes") is not None and len(raw) != storage["bytes"]:
        raise ValueError("文件字节数与中性包不一致")
    return path, raw


def image_fact_candidates(
    text: str, source: dict[str, Any], recognition_method: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    compact = re.sub(r"\s+", " ", normalize_ocr_text(text)).strip()
    message_id = source.get("message_id")
    source_ref = source["source_id"]
    labelled_patterns = [
        ("推荐铺位", re.compile(r"(?:推荐铺位|推荐店铺|建议铺位)\s*[：:]?\s*([A-Z]\d+[A-Za-z]?)", re.I)),
        ("铺位号", re.compile(r"(?:店铺编号|铺位号)\s*[：:]?\s*([A-Z]\d+[A-Za-z]?)", re.I)),
        ("面积", re.compile(r"(?:使用面积|建筑面积|面积)\s*[：:]?\s*(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", re.I)),
        ("楼层", re.compile(r"(?:所在楼层|楼层)\s*[：:]?\s*(L\d+)", re.I)),
    ]
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for field, pattern in labelled_patterns:
        for match in pattern.finditer(compact):
            value = match.group(1)
            key = (field, value.lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "candidate_id": f"image-candidate-{source_ref}-{len(candidates) + 1}",
                    "category": "截图明确标注",
                    "field": field,
                    "value": value,
                    "verification_status": "待人工核验",
                    "source_ref": source_ref,
                    "message_id": message_id,
                    "recognition_method": recognition_method,
                    "confidence": "中",
                    "reason": "截图OCR识别到明确标签和值；需回看原图后再决定是否进入正式事实。",
                }
            )

    manual: list[dict[str, Any]] = []
    low_patterns = [
        ("图面文字_铺位号候选", re.compile(r"(L-?\d{3,}[A-Za-z]?)", re.I)),
        ("图面文字_面积候选", re.compile(r"(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", re.I)),
    ]
    labelled_values = {str(item["value"]).lower() for item in candidates}
    for field, pattern in low_patterns:
        for match in pattern.finditer(compact):
            if match.group(1).lower() in labelled_values:
                continue
            manual.append(
                {
                    "candidate_id": f"image-review-{source_ref}-{len(manual) + 1}",
                    "field": field,
                    "value": match.group(1),
                    "source_ref": source_ref,
                    "message_id": message_id,
                    "recognition_method": recognition_method,
                    "confidence": "低",
                    "reason": "截图中缺少稳定标签关系，不进入正式事实或待核验事实，需人工查看原图。",
                }
            )
    return candidates, manual


def parse_image_source(
    source: dict[str, Any],
    storage_root: Path,
    *,
    enable_ocr: bool,
    ocr_script_path: Path,
    ocr_cache: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    path, raw = verified_archived_path(source, storage_root)
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        image_format = image.format

    cached = (ocr_cache or {}).get(source["source_id"])
    ocr: dict[str, Any] | None = None
    ocr_error: str | None = None
    if cached:
        ocr = cached
    elif enable_ocr:
        try:
            ocr = run_windows_ocr(path, ocr_script_path)
        except Exception as exc:  # pragma: no cover - environment dependent
            ocr_error = f"{type(exc).__name__}: {str(exc)[:160]}"

    ocr_text = normalize_ocr_text(str((ocr or {}).get("text") or ""))
    recognition_method = str((ocr or {}).get("engine") or "windows-media-ocr/zh-Hans-CN")
    candidates, manual = image_fact_candidates(ocr_text, source, recognition_method)
    return {
        "source_id": source["source_id"],
        "original_file_name": source.get("original_file_name"),
        "original_ref": f"bot-storage://{source['storage']['relative_path']}",
        "message_id": source.get("message_id"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "mime_type": source["storage"].get("mime_type"),
        "image_format": image_format,
        "width": width,
        "height": height,
        "hash_verified": True,
        "recognition_method": recognition_method if ocr else None,
        "ocr_text": ocr_text,
        "ocr_lines": (ocr or {}).get("lines", []),
        "ocr_error": ocr_error,
        "fact_candidates": candidates,
        "manual_review_items": manual,
        "guardrail": "仅提取截图上可见的客观文字和明确标注；不判断动线、楼层优劣或盈利。",
    }


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(f".//{{{MAIN_NS}}}t"))
        for item in root.findall(f"{{{MAIN_NS}}}si")
    ]


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship")
    }
    rows = []
    for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
        target = targets[sheet.attrib[f"{{{REL_NS}}}id"]].lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        rows.append((sheet.attrib["name"], target))
    return rows


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{{{MAIN_NS}}}t"))
    value = cell.findtext(f"{{{MAIN_NS}}}v")
    if value is None:
        return ""
    if cell_type == "s":
        return shared[int(value)]
    return value


def read_xlsx_sheets(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        sheets: list[dict[str, Any]] = []
        for name, target in _sheet_targets(archive):
            root = ET.fromstring(archive.read(target))
            cells: dict[str, str] = {}
            for cell in root.findall(f".//{{{MAIN_NS}}}c"):
                cells[cell.attrib["r"]] = _cell_value(cell, shared).strip()
            merged: dict[str, str] = {}
            for node in root.findall(f".//{{{MAIN_NS}}}mergeCell"):
                start, end = node.attrib["ref"].split(":")
                start_match = re.fullmatch(r"([A-Z]+)(\d+)", start)
                end_match = re.fullmatch(r"([A-Z]+)(\d+)", end)
                if not start_match or not end_match or start_match.group(1) != end_match.group(1):
                    continue
                column = start_match.group(1)
                for row_number in range(int(start_match.group(2)), int(end_match.group(2)) + 1):
                    merged[f"{column}{row_number}"] = start
            sheets.append({"sheet_name": name, "cells": cells, "merged_anchors": merged})
        return sheets


def _resolved_cell(sheet: dict[str, Any], ref: str) -> tuple[str, str]:
    source_ref = sheet["merged_anchors"].get(ref, ref)
    return str(sheet["cells"].get(source_ref, "")), source_ref


def normalize_reply_candidate(reply: str) -> tuple[str, str, str]:
    compact = re.sub(r"\s+", "", reply)
    if not compact:
        return "信息不足", "低", "商场回复为空，不能视为满足。"
    if re.search(r"不满足|无法|不能|不可以|不具备|没有|无此", compact):
        return "不满足", "中", "机器按明确否定词解释，仍需人工确认语境。"
    if re.search(r"待|需|协调|确认|可改造|条件|原则上|应该|尽量|预计", compact):
        return "有条件满足", "低", "回复包含条件、计划或不确定措辞，不得自动判定通过。"
    if re.search(r"满足|可以|已提供|已接入|没问题|无问题|符合", compact):
        return "满足", "中", "机器按明确肯定词解释，仍需人工确认并核对证据。"
    return "信息不足", "低", "自由文本未形成明确满足结论。"


def parse_engineering_workbook(source: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    path, raw = verified_archived_path(source, storage_root)
    sheets = read_xlsx_sheets(path)
    sheet_reviews: list[dict[str, Any]] = []
    all_requirements: list[dict[str, Any]] = []
    for sheet in sheets:
        cells = sheet["cells"]
        header_row = next(
            (
                int(re.search(r"\d+", ref).group())
                for ref, value in cells.items()
                if "Lann开店条件要求" in value
            ),
            None,
        )
        reply_column = next(
            (
                re.match(r"[A-Z]+", ref).group()
                for ref, value in cells.items()
                if header_row and int(re.search(r"\d+", ref).group()) == header_row and "回复" in value
            ),
            None,
        )
        requirement_column = next(
            (
                re.match(r"[A-Z]+", ref).group()
                for ref, value in cells.items()
                if header_row and int(re.search(r"\d+", ref).group()) == header_row and "Lann开店条件要求" in value
            ),
            None,
        )
        requirements: list[dict[str, Any]] = []
        if header_row and reply_column and requirement_column:
            max_row = max(int(re.search(r"\d+", ref).group()) for ref in cells)
            for row_number in range(header_row + 1, max_row + 1):
                requirement_ref = f"{requirement_column}{row_number}"
                requirement, actual_requirement_ref = _resolved_cell(sheet, requirement_ref)
                if not requirement:
                    continue
                reply_ref = f"{reply_column}{row_number}"
                reply, actual_reply_ref = _resolved_cell(sheet, reply_ref)
                category, category_ref = _resolved_cell(sheet, f"B{row_number}")
                item, item_ref = _resolved_cell(sheet, f"C{row_number}")
                note, note_ref = _resolved_cell(sheet, f"E{row_number}")
                status, confidence, reason = normalize_reply_candidate(reply)
                requirements.append(
                    {
                        "row_number": row_number,
                        "category": category,
                        "category_source": f"{sheet['sheet_name']}!{category_ref}",
                        "item": item,
                        "item_source": f"{sheet['sheet_name']}!{item_ref}",
                        "lann_requirement": requirement,
                        "lann_requirement_source": f"{sheet['sheet_name']}!{actual_requirement_ref}",
                        "note": note,
                        "note_source": f"{sheet['sheet_name']}!{note_ref}",
                        "merchant_reply": reply,
                        "merchant_reply_source": f"{sheet['sheet_name']}!{actual_reply_ref}",
                        "normalized_status_candidate": status,
                        "machine_interpretation": True,
                        "interpretation_confidence": confidence,
                        "interpretation_reason": reason,
                        "human_confirmation_required": True,
                        "critical_item": any(
                            term in f"{category}{item}{requirement}" for term in CRITICAL_TERMS
                        ),
                    }
                )
        all_requirements.extend(requirements)
        sheet_reviews.append(
            {
                "sheet_name": sheet["sheet_name"],
                "header_row": header_row,
                "requirement_count": len(requirements),
                "reply_count": sum(bool(row["merchant_reply"]) for row in requirements),
                "requirements": requirements,
            }
        )

    reply_count = sum(bool(row["merchant_reply"]) for row in all_requirements)
    vague = [
        row
        for row in all_requirements
        if row["merchant_reply"] and row["interpretation_confidence"] == "低"
    ]
    blockers = [
        row
        for row in all_requirements
        if row["merchant_reply"] and row["normalized_status_candidate"] == "不满足"
    ]
    classification = (
        "LANN标准工程要求清单"
        if all_requirements and reply_count == 0
        else "LANN标准要求与项目填写核对表兼有"
        if all_requirements
        else "无法识别工程要求结构"
    )
    return {
        "source_id": source["source_id"],
        "original_file_name": source.get("original_file_name"),
        "original_ref": f"bot-storage://{source['storage']['relative_path']}",
        "message_id": source.get("message_id"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "hash_verified": True,
        "classification": classification,
        "sheet_count": len(sheets),
        "sheets": sheet_reviews,
        "requirement_count": len(all_requirements),
        "merchant_reply_count": reply_count,
        "merchant_reply_coverage": (
            round(reply_count / len(all_requirements), 4) if all_requirements else 0
        ),
        "vague_reply_count": len(vague),
        "vague_replies": vague,
        "key_blocker_count": len(blockers),
        "key_blockers": blockers,
        "critical_items_without_written_reply": [
            row for row in all_requirements if row["critical_item"] and not row["merchant_reply"]
        ],
        "interpretation_boundary": (
            "LANN要求、商场自由文本回复和机器归一化候选分层保存；空白回复不等于满足，"
            "含糊回复不得自动判定通过，机器状态必须人工确认。"
        ),
    }


def apply_supplements(
    packet: dict[str, Any],
    storage_root: Path,
    internal: dict[str, Any],
    review: dict[str, Any],
    *,
    enable_image_ocr: bool = True,
    ocr_script_path: Path | None = None,
    ocr_cache: dict[str, dict[str, Any]] | None = None,
    only_source_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_neutral_packet(packet)
    if packet["external_writes"] != {
        "dashboard_allowed": False,
        "dashboard_attempted": False,
    }:
        raise ValueError("补充资料解析只允许在禁止dashboard外写的中性包上运行")

    source_ids = {row["source_id"] for row in internal["sources"]}
    image_reviews_by_id = {
        row["source_id"]: row for row in review.get("image_sources", [])
    }
    workbook_reviews_by_id = {
        row["source_id"]: row for row in review.get("engineering_workbooks", [])
    }
    supplement_errors = [
        item
        for item in review.get("supplement_errors", [])
        if not only_source_ids or not any(source_id in item for source_id in only_source_ids)
    ]
    ocr_script = ocr_script_path or Path(__file__).with_name("windows_ocr_page.ps1")
    for source in packet["sources"]:
        if only_source_ids and source["source_id"] not in only_source_ids:
            continue
        if source["source_id"] not in source_ids:
            converted, _ = convert_source(source)
            internal["sources"].append(converted)
            source_ids.add(source["source_id"])
        try:
            if is_image_source(source):
                image_reviews_by_id[source["source_id"]] = parse_image_source(
                    source,
                    storage_root,
                    enable_ocr=enable_image_ocr,
                    ocr_script_path=ocr_script,
                    ocr_cache=ocr_cache,
                )
            elif is_engineering_workbook(source):
                workbook_reviews_by_id[source["source_id"]] = parse_engineering_workbook(
                    source, storage_root
                )
        except Exception as exc:
            supplement_errors.append(
                f"{source['source_id']}：补充资料读取失败（{type(exc).__name__}: {str(exc)[:160]}）"
            )

    image_reviews = list(image_reviews_by_id.values())
    workbook_reviews = list(workbook_reviews_by_id.values())
    review["schema_version"] = "site-intake-review/v0.3"
    review["image_sources"] = image_reviews
    review["image_fact_candidates"] = [
        item for row in image_reviews for item in row["fact_candidates"]
    ]
    pdf_values: dict[str, set[str]] = {}
    for fact in internal["facts"]:
        if fact.get("field") in {"铺位号", "使用面积", "所在楼层"}:
            pdf_values.setdefault(fact["field"], set()).add(str(fact.get("value", "")).strip())
    comparison_field = {"推荐铺位": "铺位号", "铺位号": "铺位号", "面积": "使用面积", "楼层": "所在楼层"}
    review["image_evidence_comparison"] = []
    for candidate in review["image_fact_candidates"]:
        pdf_field = comparison_field.get(candidate["field"])
        known_values = pdf_values.get(pdf_field, set()) if pdf_field else set()
        value = str(candidate["value"]).strip()
        status = (
            "重复印证"
            if value in known_values
            else "不一致"
            if known_values
            else "新增证据"
        )
        review["image_evidence_comparison"].append(
            {
                "image_candidate_id": candidate["candidate_id"],
                "field": candidate["field"],
                "image_value": value,
                "pdf_field": pdf_field,
                "pdf_values": sorted(known_values),
                "comparison_status": status,
                "human_confirmation_required": True,
                "source_ref": candidate["source_ref"],
                "message_id": candidate.get("message_id"),
            }
        )
    review.setdefault("manual_review_items", []).extend(
        item for row in image_reviews for item in row["manual_review_items"]
    )
    manual_unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in review["manual_review_items"]:
        key = (
            str(item.get("field", "")),
            str(item.get("value", "")),
            str(item.get("source_ref", "")),
        )
        manual_unique[key] = item
    review["manual_review_items"] = list(manual_unique.values())
    review["engineering_workbooks"] = workbook_reviews
    review["supplement_errors"] = supplement_errors
    guardrails = review.setdefault("guardrails", [])
    for guardrail in (
        "截图仅作为补充证据；明确标注先进入待人工核验，不据截图判断动线、楼层优劣或盈利",
        "工程表中的LANN要求、商场回复和机器解释分层保存；空白或含糊回复不得自动判定通过",
        "负责人确认前期工程初筛通过，不代表每项均已有商场书面证据",
        "未写入dashboard或其他正式业务数据",
    ):
        if guardrail not in guardrails:
            guardrails.append(guardrail)

    internal["facts"] = [
        fact
        for fact in internal["facts"]
        if not str(fact.get("fact_id", "")).startswith("engineering-supplement-")
    ]
    existing_source_ids = {row["source_id"] for row in internal["sources"]}
    for workbook_index, workbook in enumerate(workbook_reviews, start=1):
        base_source = next(
            row for row in packet["sources"] if row["source_id"] == workbook["source_id"]
        )
        for sheet_index, sheet in enumerate(workbook["sheets"], start=1):
            for requirement in sheet["requirements"]:
                row_number = requirement["row_number"]
                requirement_source_id = (
                    f"engineering-cell-{workbook_index}-{sheet_index}-r{row_number}-requirement"
                )
                if requirement_source_id not in existing_source_ids:
                    internal["sources"].append(
                        {
                            "source_id": requirement_source_id,
                            "source_type": "LANN标准工程条件",
                            "title": (
                                f"{workbook['original_file_name']}｜{sheet['sheet_name']}｜"
                                f"{requirement['lann_requirement_source'].split('!')[-1]}"
                            ),
                            "ref": (
                                f"{workbook['original_ref']}#sheet={sheet['sheet_name']}"
                                f"&cell={requirement['lann_requirement_source'].split('!')[-1]}"
                            ),
                            "availability": "可读取",
                            "message_id": workbook.get("message_id"),
                            "sha256": workbook["sha256"],
                            "mime_type": base_source["storage"].get("mime_type"),
                        }
                    )
                    existing_source_ids.add(requirement_source_id)
                label = " / ".join(
                    value
                    for value in (requirement["category"], requirement["item"])
                    if value
                )
                internal["facts"].append(
                    {
                        "fact_id": (
                            f"engineering-supplement-{workbook_index}-{sheet_index}-"
                            f"r{row_number}-requirement"
                        ),
                        "category": "LANN标准工程要求",
                        "field": label or f"第{row_number}行工程要求",
                        "value": requirement["lann_requirement"],
                        "fact_kind": "资料可证实事实",
                        "confidence": "高",
                        "recognition_method": "xlsx_ooxml_cell",
                        "source_refs": [requirement_source_id],
                    }
                )
                if requirement["merchant_reply"]:
                    reply_source_id = (
                        f"engineering-cell-{workbook_index}-{sheet_index}-r{row_number}-reply"
                    )
                    if reply_source_id not in existing_source_ids:
                        internal["sources"].append(
                            {
                                "source_id": reply_source_id,
                                "source_type": "LANN标准工程条件",
                                "title": (
                                    f"{workbook['original_file_name']}｜{sheet['sheet_name']}｜"
                                    f"{requirement['merchant_reply_source'].split('!')[-1]}"
                                ),
                                "ref": (
                                    f"{workbook['original_ref']}#sheet={sheet['sheet_name']}"
                                    f"&cell={requirement['merchant_reply_source'].split('!')[-1]}"
                                ),
                                "availability": "可读取",
                                "message_id": workbook.get("message_id"),
                                "sha256": workbook["sha256"],
                                "mime_type": base_source["storage"].get("mime_type"),
                            }
                        )
                        existing_source_ids.add(reply_source_id)
                    internal["facts"].append(
                        {
                            "fact_id": (
                                f"engineering-supplement-{workbook_index}-{sheet_index}-"
                                f"r{row_number}-merchant-reply"
                            ),
                            "category": "商场/铺位实际条件回复原文",
                            "field": label or f"第{row_number}行商场回复",
                            "value": requirement["merchant_reply"],
                            "fact_kind": "资料可证实事实",
                            "confidence": "中",
                            "recognition_method": "xlsx_ooxml_cell_verbatim",
                            "source_refs": [reply_source_id],
                        }
                    )

    internal["missing_information"] = [
        item
        for item in internal["missing_information"]
        if "电子工程条件表原文件未归档" not in item
        and "未收到LANN标准工程条件表" not in item
    ]
    if workbook_reviews:
        if all(row["merchant_reply_count"] == 0 for row in workbook_reviews):
            internal["missing_information"].append(
                "LANN标准工程要求已归档，但缺少逐项现场/商场反馈证据"
            )
        else:
            internal["missing_information"].append(
                "LANN标准工程要求及部分商场回复已归档，机器归一化状态仍待人工逐项确认"
            )
    internal["missing_information"].extend(supplement_errors)
    internal["missing_information"] = list(dict.fromkeys(internal["missing_information"]))
    review["missing_information"] = internal["missing_information"]
    review["external_writes"] = packet["external_writes"]
    return internal, review


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse image and engineering workbook supplements.")
    parser.add_argument("--input-package", required=True)
    parser.add_argument("--storage-root", required=True)
    parser.add_argument("--internal-input", required=True)
    parser.add_argument("--review-json", required=True)
    parser.add_argument("--disable-image-ocr", action="store_true")
    parser.add_argument(
        "--source-id",
        action="append",
        dest="source_ids",
        help="Only process the specified source_id; repeat to process more than one.",
    )
    args = parser.parse_args()

    packet = json.loads(Path(args.input_package).read_text(encoding="utf-8"))
    internal_path = Path(args.internal_input)
    review_path = Path(args.review_json)
    internal = json.loads(internal_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    internal, review = apply_supplements(
        packet,
        Path(args.storage_root),
        internal,
        review,
        enable_image_ocr=not args.disable_image_ocr,
        only_source_ids=set(args.source_ids) if args.source_ids else None,
    )
    internal_path.write_text(
        json.dumps(internal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"图片来源: {len(review['image_sources'])}")
    print(f"工程工作簿: {len(review['engineering_workbooks'])}")
    print(f"补充资料错误: {len(review['supplement_errors'])}")
    print("dashboard写入: 禁止")


if __name__ == "__main__":
    main()
