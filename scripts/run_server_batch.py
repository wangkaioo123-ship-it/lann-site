"""Run the complete read-only-source lann-site server batch and record its status locally."""

import json
import subprocess
import sys
from datetime import datetime, timezone

from config import settings


COMMANDS = [
    [sys.executable, "-m", "scripts.check_server_readiness"],
    [sys.executable, "-m", "scripts.extract_base"],
    [sys.executable, "-m", "scripts.extract_rent_from_feishu"],
    [sys.executable, "-m", "scripts.export_store_classification_from_feishu"],
    [sys.executable, "-m", "scripts.export_ops_from_bi"],
    [sys.executable, "-m", "scripts.refresh_hanson_daily_ops"],
    [sys.executable, "-m", "scripts.rebuild_analysis"],
]


def write_status(status: dict) -> None:
    path = settings.ROOT_DIR / "data/staging/server_batch_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    status = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "status": "running",
        "last_step": "",
    }
    write_status(status)
    for command in COMMANDS:
        step = " ".join(command[2:])
        status["last_step"] = step
        write_status(status)
        result = subprocess.run(command, cwd=settings.ROOT_DIR, check=False)
        if result.returncode:
            status.update(
                {
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "status": "failed",
                    "exit_code": result.returncode,
                }
            )
            write_status(status)
            raise SystemExit(result.returncode)
    status.update(
        {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "exit_code": 0,
        }
    )
    write_status(status)
    print("server batch complete")


if __name__ == "__main__":
    main()
