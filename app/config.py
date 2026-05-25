from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    smsverify_token: str
    smsverify_base_url: str
    country: str
    project: str
    get_wait: int
    poll_interval: int
    poll_timeout: int
    database_path: str
    admin_username: str
    admin_password: str
    session_secret: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            smsverify_token=os.environ.get("SMSVERIFY_TOKEN", ""),
            smsverify_base_url=os.environ.get("SMSVERIFY_BASE_URL", ""),
            country=os.environ.get("SMSVERIFY_COUNTRY", "kh"),
            project=os.environ.get("SMSVERIFY_PROJECT", "chatgpt"),
            get_wait=int(os.environ.get("SMSVERIFY_GET_WAIT", "30")),
            poll_interval=int(os.environ.get("SMSVERIFY_POLL_INTERVAL", "5")),
            poll_timeout=int(os.environ.get("SMSVERIFY_POLL_TIMEOUT", "300")),
            database_path=os.environ.get("SMSVERIFY_DATABASE", str(Path("data") / "smsverify.db")),
            admin_username=os.environ.get("ADMIN_USERNAME", "admin"),
            admin_password=os.environ.get("ADMIN_PASSWORD", ""),
            session_secret=os.environ.get("SESSION_SECRET", "change-me"),
        )
