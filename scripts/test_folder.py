"""
测试列出一个飞书云空间文件夹下的文件。
用法：python -m scripts.test_folder <文件夹链接>
"""

import re
import sys

from services import feishu_client, feishu_oauth


def main():
    if len(sys.argv) < 2:
        print("用法：python -m scripts.test_folder <文件夹链接>")
        return
    m = re.search(r"/drive/folder/([A-Za-z0-9]+)", sys.argv[1])
    if not m:
        print("链接里没找到 /drive/folder/ 的文件夹 token")
        return
    folder_token = m.group(1)
    token = feishu_oauth.get_valid_user_token()
    print(f"列出文件夹 {folder_token} ...\n")
    files = feishu_client.list_folder_children(folder_token, token)
    print(f"✅ 共 {len(files)} 个条目：\n")
    for f in files:
        print(f"  [{f.get('type')}] {f.get('name')}  (token={f.get('token')})")


if __name__ == "__main__":
    main()
