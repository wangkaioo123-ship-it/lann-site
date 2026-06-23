"""
飞书 API 访问层（数据层）。
所有对飞书的 HTTP 调用都封装在这里，业务/脚本代码不得直接发 HTTP。
当前仅实现"只读"能力：获取 token、读多维表格字段与记录。
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"


def _build_session():
    """
    构建带重试的会话。
    trust_env=False：忽略系统代理(Clash)——飞书是国内服务应直连，
    走 Clash 转发会偶发握手超时。仅当 .env 显式配了 FEISHU_HTTP_PROXY 才用代理。
    """
    s = requests.Session()
    s.trust_env = False
    retry = Retry(total=3, backoff_factor=1, connect=3, read=3,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = _build_session()


def _proxies():
    """仅当显式配置了代理才用，否则 None（直连）。"""
    proxy = settings.FEISHU_HTTP_PROXY
    if proxy:
        return {"http": proxy, "https": proxy}
    return None


def get_tenant_access_token() -> str:
    """
    获取 tenant_access_token（应用级身份）。
    用于后续所有飞书 API 调用的鉴权。
    """
    url = f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": settings.require("FEISHU_APP_ID"),
        "app_secret": settings.require("FEISHU_APP_SECRET"),
    }
    resp = SESSION.post(url, json=payload, proxies=_proxies(), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        # 不打印 secret，只暴露飞书返回的错误码与提示
        raise RuntimeError(f"获取 token 失败：code={data.get('code')} msg={data.get('msg')}")
    return data["tenant_access_token"]


def list_table_fields(app_token: str, table_id: str, token: str) -> list:
    """
    读取一张多维表格的全部字段定义（字段名 + 类型）。
    这是判断"立项/合同数据是什么形态"的关键依据。
    """
    url = f"{FEISHU_BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}"}
    fields = []
    page_token = None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        resp = SESSION.get(url, headers=headers, params=params, proxies=_proxies(), timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取字段失败：code={data.get('code')} msg={data.get('msg')}")
        fields.extend(data["data"].get("items", []))
        if data["data"].get("has_more"):
            page_token = data["data"].get("page_token")
        else:
            break
    return fields


def list_table_records(app_token: str, table_id: str, token: str, max_records: int = 5) -> list:
    """
    抽样读取若干条记录，用于观察真实数据长什么样。
    默认只取前 5 条，避免一次拉全量。
    """
    url = f"{FEISHU_BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"page_size": min(max_records, 100)}
    resp = SESSION.get(url, headers=headers, params=params, proxies=_proxies(), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"读取记录失败：code={data.get('code')} msg={data.get('msg')}")
    return data["data"].get("items", [])


def get_spreadsheet_meta(spreadsheet_token: str, token: str) -> dict:
    """
    读取一个飞书电子表格的元信息（标题 + 各 sheet 列表）。
    返回飞书原始 data。若权限不足会抛出带错误码的异常。
    """
    url = f"{FEISHU_BASE_URL}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query"
    headers = {"Authorization": f"Bearer {token}"}
    resp = SESSION.get(url, headers=headers, proxies=_proxies(), timeout=60)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"读取电子表格元信息失败：code={data.get('code')} msg={data.get('msg')}")
    return data["data"]


def read_sheet_range(spreadsheet_token: str, range_str: str, token: str,
                     value_render_option: str = "ToString") -> list:
    """
    读取电子表格某个区间的单元格值（二维数组）。
    range_str 形如 'sheetId!A1:J50'。
    value_render_option=ToString 让公式返回"算好的值"而非公式文本。
    """
    url = (f"{FEISHU_BASE_URL}/sheets/v2/spreadsheets/{spreadsheet_token}"
           f"/values/{range_str}?valueRenderOption={value_render_option}")
    headers = {"Authorization": f"Bearer {token}"}
    resp = SESSION.get(url, headers=headers, proxies=_proxies(), timeout=60)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"读取电子表格内容失败：code={data.get('code')} msg={data.get('msg')}")
    return data["data"].get("valueRange", {}).get("values", [])


def get_wiki_node(node_token: str, token: str) -> dict:
    """
    解析 wiki 节点 → 拿到它背后真正的文档 token（obj_token）和类型。
    用于把 /wiki/xxx 链接转成可读的电子表格 token。
    """
    url = f"{FEISHU_BASE_URL}/wiki/v2/spaces/get_node"
    headers = {"Authorization": f"Bearer {token}"}
    resp = SESSION.get(url, headers=headers, params={"token": node_token},
                        proxies=_proxies(), timeout=60)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"解析 wiki 节点失败：code={data.get('code')} msg={data.get('msg')}")
    return data["data"].get("node", {})


def get_doc_raw_content(document_id: str, token: str) -> str:
    """
    读取一篇飞书文档(docx)的纯文本内容（会议纪要等）。
    用 raw_content 接口，直接拿正文文本，最省事。
    """
    url = f"{FEISHU_BASE_URL}/docx/v1/documents/{document_id}/raw_content"
    headers = {"Authorization": f"Bearer {token}"}
    resp = SESSION.get(url, headers=headers, proxies=_proxies(), timeout=60)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"读取文档内容失败：code={data.get('code')} msg={data.get('msg')}")
    return data["data"].get("content", "")


def list_folder_children(folder_token: str, token: str) -> list:
    """
    列出一个云空间文件夹下的文件（含类型 docx/sheet 等），用于发现会议文档清单。
    """
    url = f"{FEISHU_BASE_URL}/drive/v1/files"
    headers = {"Authorization": f"Bearer {token}"}
    items = []
    page_token = None
    while True:
        params = {"folder_token": folder_token, "page_size": 200}
        if page_token:
            params["page_token"] = page_token
        resp = SESSION.get(url, headers=headers, params=params, proxies=_proxies(), timeout=60)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"列文件夹失败：code={data.get('code')} msg={data.get('msg')}")
        items.extend(data["data"].get("files", []))
        if data["data"].get("has_more"):
            page_token = data["data"].get("next_page_token")
        else:
            break
    return items


def list_all_records(app_token: str, table_id: str, token: str,
                     max_total: int = 1000, text_as_array: bool = False) -> list:
    """
    分页读取全部记录（带安全上限）。
    text_as_array=True 时，多行文本字段会以"分段数组"返回，
    其中链接段会带 link 字段——用于判断某个文本字段里是否藏着 URL（如文档/合同链接）。
    """
    url = f"{FEISHU_BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None
    while len(records) < max_total:
        params = {"page_size": 100}
        if text_as_array:
            params["text_field_as_array"] = "true"
        if page_token:
            params["page_token"] = page_token
        resp = SESSION.get(url, headers=headers, params=params, proxies=_proxies(), timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取记录失败：code={data.get('code')} msg={data.get('msg')}")
        records.extend(data["data"].get("items", []))
        if data["data"].get("has_more"):
            page_token = data["data"].get("page_token")
        else:
            break
    return records[:max_total]
