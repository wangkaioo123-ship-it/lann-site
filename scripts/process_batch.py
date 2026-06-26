"""
自主流水线：对"运营中"且未完成的店，逐份租赁合同 下载→OCR→删PDF，只留 OCR 文字。
本地始终只占一份 PDF 的量（用完即删）；token 过期则优雅停止。
产出 data/contracts/ocr/{L}__{file}.txt，供后续读数提取。
运行：python -m scripts.process_batch
"""

import csv
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import fitz

from services import feishu_oauth
from services.feishu_client import FEISHU_BASE_URL, SESSION, _proxies
from scripts.contract_plan import is_rent_file

TESS = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
TESSDATA = "C:/Users/王凯/lann-site/data/tessdata"
DONE = {"L0002", "L0003", "L0005", "L0006"}


def ocr_png(png):
    r = subprocess.run([TESS, str(png), "stdout", "-l", "chi_sim+eng", "--tessdata-dir", TESSDATA],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.stdout or ""


def main():
    with open("data/staging/base_table.csv", encoding="utf-8-sig") as f:
        operating = {x["点位ID"] for x in csv.DictReader(f) if x["门店状态"] == "运营中"}
    inv = json.loads(Path("data/contracts/inventory.json").read_text(encoding="utf-8"))
    by_l = defaultdict(list)
    for proj, info in inv.items():
        m = re.search(r"(L\d{4})", proj) or re.search(r"(L\d{4})", info.get("path", ""))
        if not m:
            continue
        for fi in info["files"]:
            by_l[m.group(1)].append((fi["name"], fi["token"]))

    token = feishu_oauth.get_valid_user_token()
    headers = {"Authorization": f"Bearer {token}"}
    ocr_dir = Path("data/contracts/ocr"); ocr_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path("data/contracts/_pdftmp"); tmp.mkdir(parents=True, exist_ok=True)

    targets = sorted(L for L in by_l if L in operating and L not in DONE)
    print(f"待处理运营中店：{len(targets)}")
    done_files = 0
    for L in targets:
        for name, tok in by_l[L]:
            if not is_rent_file(name) or name.lower().endswith(".jpg"):
                continue
            safe = re.sub(r"[^\w一-鿿.\-]", "_", name)[:60]
            ocrfile = ocr_dir / f"{L}__{safe}.txt"
            if ocrfile.exists():
                continue
            try:
                r = SESSION.get(f"{FEISHU_BASE_URL}/drive/v1/files/{tok}/download",
                                headers=headers, proxies=_proxies(), timeout=180)
                if "application/json" in r.headers.get("Content-Type", ""):
                    print(f"token 过期/非文件，停止（已处理 {done_files} 份）")
                    return
            except Exception as e:
                print(f"下载异常停止：{str(e)[:50]}（已处理 {done_files} 份）")
                return
            pdf = tmp / "cur.pdf"; pdf.write_bytes(r.content)
            try:
                doc = fitz.open(pdf)
                full = []
                for i in range(len(doc)):
                    pix = doc[i].get_pixmap(dpi=150)
                    p = tmp / "pg.png"; pix.save(p)
                    full.append(f"=== 第{i+1}页 ===\n{ocr_png(p)}")
                doc.close()
                ocrfile.write_text("\n".join(full), encoding="utf-8")
                done_files += 1
                print(f"  [{done_files}] OK {L} {name[:32]} ({len(full)}页)")
            except Exception as e:
                print(f"  OCR失败 {L} {name[:30]} {str(e)[:40]}")
            finally:
                pdf.unlink(missing_ok=True)
    print(f"全部完成，共处理 {done_files} 份")


if __name__ == "__main__":
    main()
