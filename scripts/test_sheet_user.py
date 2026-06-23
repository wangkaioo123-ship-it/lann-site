"""
用"王凯身份"(user token) 读测试表，验证云文档读权限是否真的通了。
运行：python -m scripts.test_sheet_user
"""

from services import feishu_client, feishu_oauth

TEST_SHEET_TOKEN = "shtcnMvf6CFUcw9SafMa3sg7BJh"


def main():
    token = feishu_oauth.get_valid_user_token()
    print(f"用用户身份尝试读取 {TEST_SHEET_TOKEN} ...\n")
    try:
        meta = feishu_client.get_spreadsheet_meta(TEST_SHEET_TOKEN, token)
    except RuntimeError as e:
        print(f"❌ 仍然失败：{e}")
        return
    sheets = meta.get("sheets", [])
    print(f"✅ 读到了！共 {len(sheets)} 个 sheet：")
    for s in sheets:
        print(f"  - {s.get('title')}  (sheet_id={s.get('sheet_id')})")
    if sheets:
        first_id = sheets[0].get("sheet_id")
        print(f"\n=== 第一个 sheet「{sheets[0].get('title')}」前若干行 ===")
        rows = feishu_client.read_sheet_range(TEST_SHEET_TOKEN, f"{first_id}!A1:F40", token)
        for i, row in enumerate(rows, 1):
            cells = [str(c) for c in row if c not in (None, "")]
            if cells:
                print(f"  行{i}: {' | '.join(cells)}")


if __name__ == "__main__":
    main()
