"""
飞书 OAuth：获取并维护"用户身份"的 access_token（以王凯本人身份读云文档）。
用户对所有测算表都有阅读权限，故借其身份即可读全部，无需逐张分享给 app。

token 存在 secrets/feishu_user_token.json（已 gitignore），含 refresh 机制，
日常再跑不必重新授权。
"""

import json
import time
from pathlib import Path

import requests

from config import settings

# 回调地址：必须与 app 后台"重定向 URL"里填的完全一致
REDIRECT_URI = "http://localhost:8765/callback"

AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"

# 需要向用户索取的权限：读云文档/电子表格/知识库/文档正文（只读）
# 注：offline_access(长期 refresh_token) 需管理员审批，暂不使用；token 有效期 2 小时。
# docx:document:readonly 用于读会议纪要等飞书文档正文。
SCOPES = "drive:drive:readonly sheets:spreadsheet:readonly wiki:wiki:readonly docx:document:readonly"

TOKEN_FILE = settings.ROOT_DIR / "secrets" / "feishu_user_token.json"


def _proxies():
    proxy = settings.FEISHU_HTTP_PROXY
    return {"http": proxy, "https": proxy} if proxy else None


def build_authorize_url(state: str = "lannsite") -> str:
    """拼出让用户在浏览器打开的授权链接。"""
    from urllib.parse import urlencode

    params = {
        "client_id": settings.require("FEISHU_APP_ID"),
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _save_token(data: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 记录到期时间戳，便于判断是否需要刷新
    data["_obtained_at"] = int(time.time())
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def exchange_code(code: str) -> dict:
    """用授权码换取 user_access_token + refresh_token。"""
    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.require("FEISHU_APP_ID"),
        "client_secret": settings.require("FEISHU_APP_SECRET"),
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(TOKEN_URL, json=payload, proxies=_proxies(), timeout=30)
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"换取用户 token 失败：{data}")
    _save_token(data)
    return data


def _refresh(refresh_token: str) -> dict:
    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.require("FEISHU_APP_ID"),
        "client_secret": settings.require("FEISHU_APP_SECRET"),
        "refresh_token": refresh_token,
    }
    resp = requests.post(TOKEN_URL, json=payload, proxies=_proxies(), timeout=30)
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"刷新用户 token 失败：{data}")
    _save_token(data)
    return data


def get_valid_user_token() -> str:
    """
    返回一个可用的 user_access_token：
    - 没有 token 文件 → 提示先登录
    - 快过期 → 用 refresh_token 自动刷新
    """
    if not TOKEN_FILE.exists():
        raise RuntimeError("尚未授权。请先运行：python -m scripts.feishu_login")
    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    obtained = data.get("_obtained_at", 0)
    expires_in = data.get("expires_in", 7200)
    # 留 5 分钟余量
    if time.time() > obtained + expires_in - 300:
        if not data.get("refresh_token"):
            raise RuntimeError("token 已过期且无 refresh_token，请重新运行：python -m scripts.feishu_login")
        data = _refresh(data["refresh_token"])
    return data["access_token"]
