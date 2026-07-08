import json
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings


def _build_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    retry = Retry(
        total=2,
        backoff_factor=1,
        connect=2,
        read=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = _build_session()


def _join_url(path: str) -> str:
    base_url = settings.require("BI_API_BASE_URL")
    if not path:
        path = "/"
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def auth_headers() -> dict:
    api_key = settings.BI_API_KEY
    if not api_key:
        return {}

    header = settings.BI_API_KEY_HEADER or "Authorization"
    scheme = (settings.BI_API_AUTH_SCHEME or "Bearer").strip()
    if scheme.lower() == "raw":
        value = api_key
    else:
        value = f"{scheme} {api_key}"
    return {header: value}


def get(path: str, params: dict | None = None) -> requests.Response:
    return SESSION.get(_join_url(path), headers=auth_headers(), params=params, timeout=30)


def post(path: str, payload: dict | None = None) -> requests.Response:
    return SESSION.post(_join_url(path), headers=auth_headers(), json=payload or {}, timeout=30)


def describe_response(resp: requests.Response, sample_chars: int = 500) -> dict:
    content_type = resp.headers.get("content-type", "")
    info = {
        "url": resp.url,
        "status_code": resp.status_code,
        "content_type": content_type,
    }

    text = resp.text or ""
    if "json" not in content_type.lower():
        info["text_sample"] = text[:sample_chars]
        return info

    try:
        data = resp.json()
    except json.JSONDecodeError:
        info["text_sample"] = text[:sample_chars]
        return info

    if isinstance(data, dict):
        info["json_type"] = "object"
        info["top_level_keys"] = list(data.keys())[:30]
        for key in ("data", "rows", "items", "records", "result"):
            value = data.get(key)
            if isinstance(value, list):
                info["list_key"] = key
                info["list_length"] = len(value)
                if value and isinstance(value[0], dict):
                    info["first_row_keys"] = list(value[0].keys())[:50]
                break
            if isinstance(value, dict):
                info[f"{key}_keys"] = list(value.keys())[:50]
    elif isinstance(data, list):
        info["json_type"] = "list"
        info["list_length"] = len(data)
        if data and isinstance(data[0], dict):
            info["first_row_keys"] = list(data[0].keys())[:50]
    else:
        info["json_type"] = type(data).__name__
    return info
