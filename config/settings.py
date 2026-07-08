"""
配置加载层：集中读取环境变量与本地 .env 文件。
所有密钥只从这里读，业务代码不直接碰环境变量。
"""

import os
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"


def _load_env_file(path: Path) -> None:
    """
    极简 .env 解析：把本地 .env 的键值读进 os.environ。
    不引入额外依赖（python-dotenv），减少安装风险。
    已存在的环境变量优先，不覆盖。
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(ENV_FILE)


def get(name: str, default: str = "") -> str:
    """读取一个配置项。"""
    return os.environ.get(name, default)


def require(name: str) -> str:
    """读取一个必填配置项，缺失则报错（错误信息不含密钥本身）。"""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少必填配置 {name}，请在 {ENV_FILE} 中填写")
    return value


# 飞书相关配置（统一出口）
FEISHU_APP_ID = get("FEISHU_APP_ID")
FEISHU_APP_SECRET = get("FEISHU_APP_SECRET")
LEASE_TABLE_APP_TOKEN = get("LEASE_TABLE_APP_TOKEN")
LEASE_TABLE_ID = get("LEASE_TABLE_ID")
EXPANSION_TABLE_APP_TOKEN = get("EXPANSION_TABLE_APP_TOKEN")
EXPANSION_TABLE_ID = get("EXPANSION_TABLE_ID")
EXPANSION_TABLE_VIEW_ID = get("EXPANSION_TABLE_VIEW_ID")
FEISHU_HTTP_PROXY = get("FEISHU_HTTP_PROXY")

# BI API config. Keep real values in local .env only.
BI_API_BASE_URL = get("BI_API_BASE_URL").rstrip("/")
BI_API_KEY = get("BI_API_KEY")
BI_API_KEY_HEADER = get("BI_API_KEY_HEADER", "Authorization")
BI_API_AUTH_SCHEME = get("BI_API_AUTH_SCHEME", "Bearer")
BI_API_TEST_PATH = get("BI_API_TEST_PATH", "/")
BI_API_REVENUE_PATH = get("BI_API_REVENUE_PATH")
BI_API_USERNAME = get("BI_API_USERNAME")
BI_API_PASSWORD = get("BI_API_PASSWORD")
