# -*- coding: utf-8 -*-
"""Append-only audit log for dashboard write operations."""
import datetime
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

AUDIT_PATH = Path("dashboard/audit.jsonl")


def write_audit(
    *,
    user_id: int,
    username: str,
    guild_id: Optional[int],
    route: str,
    action: str,
    before: Any = None,
    after: Any = None,
) -> None:
    AUDIT_PATH.parent.mkdir(exist_ok=True)
    line = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "user_id": str(user_id),
        "username": username,
        "guild_id": str(guild_id) if guild_id is not None else None,
        "route": route,
        "action": action,
        "before": before,
        "after": after,
    }
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error("Audit write failed: %s", e)
