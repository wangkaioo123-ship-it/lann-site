"""
从 inventory.json 整理成按 L 编号排序的处理计划：每个店列出"租赁类"文件，
过滤掉证照/测算/投资/借款/收益权等无关件。
运行：python -m scripts.contract_plan
"""

import json
import re
from collections import defaultdict
from pathlib import Path

INV = Path("data/contracts/inventory.json")

# 租赁类文件关键词（保留）；无关件关键词（剔除）
KEEP = ["合同", "续租", "续签", "补充协议", "租赁", "备忘"]
DROP = ["证照", "营业执照", "测算", "投资", "立项", "借款", "收益权", "收条", "预算"]


def is_rent_file(name):
    if any(d in name for d in DROP):
        return False
    return any(k in name for k in KEEP)


def main():
    inv = json.loads(INV.read_text(encoding="utf-8"))
    by_l = defaultdict(list)  # L编号 → [(path, name, token)]
    other = []
    for proj, info in inv.items():
        m = re.search(r"(L\d{4})", proj) or re.search(r"(L\d{4})", info.get("path", ""))
        key = m.group(1) if m else None
        for f in info["files"]:
            rec = (info.get("path", proj), f["name"], f["token"])
            if key:
                by_l[key].append(rec)
            else:
                other.append(rec)

    print(f"=== 按 L 编号（{len(by_l)} 个店）===\n")
    for L in sorted(by_l):
        rent = [r for r in by_l[L] if is_rent_file(r[1])]
        print(f"{L}  （{len(rent)} 份租赁类 / 共 {len(by_l[L])} 文件）")
        for path, name, tok in rent:
            tag = ""
            if "新址" in path or "新址" in name:
                tag = " [新址]"
            elif "旧址" in path or "旧址" in name:
                tag = " [旧址]"
            print(f"    - {name}{tag}  ({tok})")
    print(f"\n非 L 编号项目（意向书等）：{len(other)} 文件，跳过")


if __name__ == "__main__":
    main()
