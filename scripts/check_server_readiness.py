"""Fail fast when the unattended server batch is missing required read-only configuration."""

from pathlib import Path

from config import settings


REQUIRED_ENV = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "LEASE_TABLE_APP_TOKEN",
    "LEASE_TABLE_ID",
    "BI_API_BASE_URL",
    "BI_API_KEY",
)

REQUIRED_FILES = (
    "config/store_site_mapping.json",
    "config/site_identity_episodes.json",
    "config/ops_source_policy.json",
)


def readiness_issues(getter, root: Path) -> list[str]:
    issues = [f"缺少环境配置:{name}" for name in REQUIRED_ENV if not getter(name)]
    issues.extend(f"缺少项目文件:{name}" for name in REQUIRED_FILES if not (root / name).exists())
    return issues


def main() -> None:
    issues = readiness_issues(settings.get, settings.ROOT_DIR)
    if issues:
        for issue in issues:
            print(issue)
        raise SystemExit(1)
    print("server readiness ok: read-only Feishu/BI config and tracked mapping files are present")


if __name__ == "__main__":
    main()
