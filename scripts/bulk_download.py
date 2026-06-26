"""
趁 token 有效，批量下载"运营中"店的租赁类合同到本地（data/contracts/auto/）。
跳过已下载、跳过已终止、跳过已完成的店、跳过 jpg 照片。token 过期则优雅停止。
运行：python -m scripts.bulk_download
"""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from services import feishu_oauth
from services.feishu_client import FEISHU_BASE_URL, SESSION, _proxies
from scripts.contract_plan import is_rent_file

DONE = {"L0002", "L0003", "L0005", "L0006"}


def safe(s):
    return re.sub(r"[^\w一-鿿.\-（）()]", "_", s)[:70]


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

    out_dir = Path("data/contracts/auto")
    out_dir.mkdir(parents=True, exist_ok=True)
    token = feishu_oauth.get_valid_user_token()
    headers = {"Authorization": f"Bearer {token}"}

    targets = sorted(L for L in by_l if L in operating and L not in DONE)
    print(f"运营中待下载店：{len(targets)} 个")
    ok = fail = 0
    for L in targets:
        for name, tok in by_l[L]:
            if not is_rent_file(name) or name.lower().endswith(".jpg"):
                continue
            dest = out_dir / f"{L}__{safe(name)}"
            if dest.exists():
                continue
            try:
                url = f"{FEISHU_BASE_URL}/drive/v1/files/{tok}/download"
                r = SESSION.get(url, headers=headers, proxies=_proxies(), timeout=180)
                if "application/json" in r.headers.get("Content-Type", ""):
                    code = r.json().get("code")
                    print(f"  非文件/错误 {L} {name[:30]} code={code}")
                    if code and code != 0:
                        print("  token 可能过期，停止下载")
                        print(f"\n完成：{ok} 下载，{fail} 失败")
                        return
                    continue
                dest.write_bytes(r.content)
                ok += 1
                print(f"  [{ok}] {L} {name[:34]} {len(r.content)//1024}KB")
            except Exception as e:
                fail += 1
                print(f"  FAIL {L} {name[:30]} {str(e)[:50]}")
    print(f"\n完成：{ok} 下载，{fail} 失败")


if __name__ == "__main__":
    main()
