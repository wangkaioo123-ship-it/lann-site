"""
递归走"门店合约档案"文件夹树，列出每个项目及其合同文件，存成清单。
输出：data/contracts/inventory.json（项目 → 文件列表）+ 控制台树状打印。
运行：python -m scripts.list_contract_tree
"""

import json
from pathlib import Path

from services import feishu_client, feishu_oauth

ROOT = "TwwHfx1FqlvcJOdbfCXcThh9n0f"  # 1-门店合约档案

inventory = {}  # 项目名 → {folder_token, files:[{name,token}]}


def walk(folder_token, token, path):
    items = feishu_client.list_folder_children(folder_token, token)
    files = [it for it in items if it.get("type") == "file"]
    subfolders = [it for it in items if it.get("type") == "folder"]
    # 含文件的文件夹 = 一个项目
    if files:
        name = path[-1] if path else "(根)"
        inventory[name] = {
            "folder_token": folder_token,
            "path": " / ".join(path),
            "files": [{"name": f["name"], "token": f["token"]} for f in files],
        }
        print(f"{'  ' * len(path)}📁 {name}  ({len(files)} 文件)")
    for sf in subfolders:
        print(f"{'  ' * len(path)}├─ {sf['name']}")
        walk(sf["token"], token, path + [sf["name"]])


def main():
    token = feishu_oauth.get_valid_user_token()
    print("走合约档案树 ...\n")
    walk(ROOT, token, [])
    out = Path("data/contracts/inventory.json")
    out.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共 {len(inventory)} 个项目（含合同文件的文件夹）。清单已存：{out}")


if __name__ == "__main__":
    main()
