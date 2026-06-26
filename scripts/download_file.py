"""
下载一个飞书云盘文件到本地（用于读合同扫描件）。
用法：python -m scripts.download_file <file_token> <输出文件名>
"""

import sys
from pathlib import Path

from services import feishu_oauth
from services.feishu_client import FEISHU_BASE_URL, SESSION, _proxies


def download(file_token, out_path, token):
    url = f"{FEISHU_BASE_URL}/drive/v1/files/{file_token}/download"
    headers = {"Authorization": f"Bearer {token}"}
    resp = SESSION.get(url, headers=headers, proxies=_proxies(), timeout=120)
    if "application/json" in resp.headers.get("Content-Type", ""):
        print("下载失败：", resp.json())
        return None
    out_path.write_bytes(resp.content)
    print(f"已下载 {len(resp.content)} 字节 → {out_path}")
    return out_path


def main():
    file_token = sys.argv[1]
    out_name = sys.argv[2]
    token = feishu_oauth.get_valid_user_token()
    out_dir = Path("data/contracts")
    out_dir.mkdir(parents=True, exist_ok=True)
    download(file_token, out_dir / out_name, token)


if __name__ == "__main__":
    main()
