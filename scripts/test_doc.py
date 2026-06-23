"""
测试"读飞书会议文档"的路径是否打通。
用法：python -m scripts.test_doc <飞书文档链接>
支持 /docx/xxx 和 /wiki/xxx（wiki 包裹的文档）两种链接。
"""

import re
import sys

from services import feishu_client, feishu_oauth


def resolve_doc_id(link: str, token: str):
    """把文档链接解析成 docx 的 document_id。"""
    m = re.search(r"/docx/([A-Za-z0-9]+)", link)
    if m:
        return m.group(1)
    m = re.search(r"/wiki/([A-Za-z0-9]+)", link)
    if m:
        node = feishu_client.get_wiki_node(m.group(1), token)
        if node.get("obj_type") in ("docx", "doc"):
            return node.get("obj_token")
        return None
    return None


def main():
    if len(sys.argv) < 2:
        print("用法：python -m scripts.test_doc <飞书文档链接>")
        return
    link = sys.argv[1]
    token = feishu_oauth.get_valid_user_token()
    doc_id = resolve_doc_id(link, token)
    if not doc_id:
        print(f"无法从链接解析出文档ID（可能不是 docx）：{link}")
        return
    print(f"读取文档 {doc_id} ...\n")
    content = feishu_client.get_doc_raw_content(doc_id, token)
    print(f"✅ 读到正文，共 {len(content)} 字。预览前 600 字：\n")
    print(content[:600])


if __name__ == "__main__":
    main()
