"""Settings read from the environment (and a local .env file, if present)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/Mxsrii/eece503p-c5-game-deals"
USER_AGENT = f"eece503p-c5-game-deals/0.1 (+{REPO_URL})"


@dataclass(frozen=True)
class Settings:
    ntfy_topic: str | None
    ntfy_server: str
    cheapshark_url: str
    db_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        db_path = Path(os.getenv("DB_PATH") or "data/sent.db")
        return cls(
            ntfy_topic=os.getenv("NTFY_TOPIC") or None,
            ntfy_server=(os.getenv("NTFY_SERVER") or "https://ntfy.sh").rstrip("/"),
            cheapshark_url=(
                os.getenv("CHEAPSHARK_URL") or "https://www.cheapshark.com/api/1.0"
            ).rstrip("/"),
            db_path=db_path if db_path.is_absolute() else PROJECT_ROOT / db_path,
        )
