"""
整本合同 OCR → 自动挑出"费用相关行"（房租/物业/推广+数字），并存全文。
绕开逐页看图，定位费用条款页 + 抓候选数字，再人工/看图核对。
用法：python -m scripts.ocr_contract <pdf路径>
"""

import re
import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF

TESS = r"C:/Program Files/Tesseract-OCR/tesseract.exe"
TESSDATA = "C:/Users/王凯/lann-site/data/tessdata"
KW = ["房租", "租金", "物业", "管理费", "推广", "广告", "递增", "保证金", "押金", "免租", "提成"]


def ocr_png(png):
    r = subprocess.run(
        [TESS, str(png), "stdout", "-l", "chi_sim+eng", "--tessdata-dir", TESSDATA],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    return r.stdout or ""


def main():
    pdf = Path(sys.argv[1])
    doc = fitz.open(pdf)
    out_dir = Path("data/contracts/ocr"); out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path("data/contracts/_tmp"); tmp.mkdir(parents=True, exist_ok=True)
    full = []
    print(f"{pdf.name}  {len(doc)} 页，OCR 中 ...")
    for i in range(len(doc)):
        pix = doc[i].get_pixmap(dpi=150)
        p = tmp / "ocrpage.png"
        pix.save(p)
        text = ocr_png(p)
        full.append(f"=== 第 {i + 1} 页 ===\n{text}")
        hits = [ln.strip() for ln in text.splitlines()
                if any(k in ln for k in KW) and re.search(r"\d", ln)]
        if hits:
            print(f"\n--- 第 {i + 1} 页 ---")
            for h in hits[:18]:
                print("  ", h)
    (out_dir / f"{pdf.stem}.txt").write_text("\n".join(full), encoding="utf-8")
    print(f"\n全文 OCR 已存：data/contracts/ocr/{pdf.stem}.txt")


if __name__ == "__main__":
    main()
