"""
把 PDF（扫描件）渲染成 PNG 图片，供视觉读取（绕过缺失的 pdftoppm）。
用法：python -m scripts.pdf_to_images <pdf路径> [页范围，如 1-8]
"""

import re
import sys
from pathlib import Path

import fitz  # PyMuPDF


def parse_pages(s, n):
    m = re.match(r"(\d+)-(\d+)", s)
    if m:
        return range(int(m.group(1)) - 1, min(int(m.group(2)), n))
    return range(0, min(int(s), n))


def main():
    pdf = Path(sys.argv[1])
    rng = sys.argv[2] if len(sys.argv) > 2 else "1-8"
    doc = fitz.open(pdf)
    out = Path("data/contracts/pages")
    out.mkdir(parents=True, exist_ok=True)
    print(f"{pdf.name} 共 {len(doc)} 页，渲染 {rng}")
    for i in parse_pages(rng, len(doc)):
        pix = doc[i].get_pixmap(dpi=150)
        p = out / f"{pdf.stem}_p{i + 1}.png"
        pix.save(p)
        print("渲染", p)


if __name__ == "__main__":
    main()
