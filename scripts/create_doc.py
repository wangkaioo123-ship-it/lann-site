"""
用 app(tenant) token 把"部门工作解构"markdown 灌进已创建的飞书 docx。
把 markdown 解析成飞书文档块（标题/段落/项目符号；表格行转成项目符号）。
运行：python -m scripts.create_doc
"""

import re
from pathlib import Path

from services import feishu_client
from services.feishu_client import FEISHU_BASE_URL, SESSION, _proxies

DOC_ID = "BBsodrDBQonAkXxrtlUcoWllnad"  # 已创建的文档
MD_PATH = Path("C:/Users/王凯/工作OS/部门AI赋能-达成画面与改造路线.md")

# markdown 级别 → 飞书 block_type 和字段名
HEADING = {1: (3, "heading1"), 2: (4, "heading2"), 3: (5, "heading3"), 4: (6, "heading4")}


def clean(s):
    return s.replace("**", "").replace("`", "").strip()


def make_block(btype, key, content):
    return {"block_type": btype, key: {"elements": [{"text_run": {"content": content}}]}}


def md_to_blocks(md):
    blocks = []
    for raw in md.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s or s == "---" or s.startswith("```"):
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", s)
        if m:
            lvl = len(m.group(1))
            bt, key = HEADING[lvl]
            blocks.append(make_block(bt, key, clean(m.group(2))))
            continue
        if s.startswith("|"):  # 表格行
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):  # 分隔行
                continue
            blocks.append(make_block(12, "bullet", clean(" ｜ ".join(cells))))
            continue
        if s.startswith("- ") or s.startswith("* "):
            blocks.append(make_block(12, "bullet", clean(s[2:])))
            continue
        if s.startswith("> "):
            blocks.append(make_block(2, "text", clean(s[2:])))
            continue
        blocks.append(make_block(2, "text", clean(s)))
    return blocks


def insert(doc_id, blocks, token):
    url = f"{FEISHU_BASE_URL}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
    headers = {"Authorization": f"Bearer {token}"}
    # 分批，每批 40 块，追加到末尾
    for i in range(0, len(blocks), 40):
        batch = blocks[i:i + 40]
        resp = SESSION.post(url, headers=headers,
                            json={"children": batch, "index": i},
                            proxies=_proxies(), timeout=60)
        data = resp.json()
        if data.get("code") != 0:
            print(f"❌ 第 {i} 批失败：code={data.get('code')} msg={data.get('msg')}")
            print(data)
            return False
        print(f"  已插入 {i + len(batch)}/{len(blocks)} 块")
    return True


def clear_doc(doc_id, token):
    """删除文档根下所有子块（清空旧内容）。"""
    url = f"{FEISHU_BASE_URL}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
    headers = {"Authorization": f"Bearer {token}"}
    resp = SESSION.get(url, headers=headers, params={"page_size": 500},
                       proxies=_proxies(), timeout=60)
    items = resp.json().get("data", {}).get("items", [])
    n = len(items)
    if n == 0:
        return
    del_url = f"{FEISHU_BASE_URL}/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete"
    resp = SESSION.delete(del_url, headers=headers,
                          json={"start_index": 0, "end_index": n},
                          proxies=_proxies(), timeout=60)
    print(f"清空旧内容：{n} 块，code={resp.json().get('code')}")


def main():
    token = feishu_client.get_tenant_access_token()
    clear_doc(DOC_ID, token)
    blocks = md_to_blocks(MD_PATH.read_text(encoding="utf-8"))
    print(f"解析出 {len(blocks)} 个文档块，开始插入 ...")
    if insert(DOC_ID, blocks, token):
        print("\n✅ 内容已写入")
        print(f"文档链接：https://lann.feishu.cn/docx/{DOC_ID}")


if __name__ == "__main__":
    main()
