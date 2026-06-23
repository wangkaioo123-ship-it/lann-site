"""
权限+模板测试：尝试读取一张"单店测算"电子表格。
两个目的：
  1) 确认现有 app 有没有"云文档读"权限（能读=不用额外申请）
  2) 看测算表的真实模板长什么样（决定能否批量解析）

运行：python -m scripts.test_sheet
"""

from services import feishu_client

# 取自探查样本：上海打浦桥日月光店的单店测算表
TEST_SHEET_TOKEN = "shtcnMvf6CFUcw9SafMa3sg7BJh"


def main():
    token = feishu_client.get_tenant_access_token()
    print(f"尝试读取电子表格 {TEST_SHEET_TOKEN} ...\n")

    try:
        meta = feishu_client.get_spreadsheet_meta(TEST_SHEET_TOKEN, token)
    except RuntimeError as e:
        print(f"❌ 读取失败：{e}")
        print("\n如果错误提示是权限/permission 相关，说明需要先给 app 开通'云文档/云空间读'权限。")
        return

    sheets = meta.get("sheets", [])
    print(f"✅ 能读！这个电子表格有 {len(sheets)} 个 sheet：")
    for s in sheets:
        print(f"  - {s.get('title')}  (sheet_id={s.get('sheet_id')})")

    if not sheets:
        return

    first_id = sheets[0].get("sheet_id")
    print(f"\n=== 第一个 sheet「{sheets[0].get('title')}」前若干行（看测算模板）===")
    rows = feishu_client.read_sheet_range(TEST_SHEET_TOKEN, f"{first_id}!A1:F40", token)
    for i, row in enumerate(rows, 1):
        # 把每行非空单元格拼出来，便于看结构
        cells = [str(c) for c in row if c not in (None, "")]
        if cells:
            print(f"  行{i}: {' | '.join(cells)}")


if __name__ == "__main__":
    main()
