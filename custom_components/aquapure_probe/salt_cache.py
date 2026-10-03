"""Preserve a real salt observation without treating it as a fresh reading."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any


def numeric_salt(value: Any) -> float | None:
    """Reject missing, non-finite, negative, and boolean values."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def valid_cache(value: Any) -> dict[str, Any] | None:
    """Only restore an identified, timestamped numeric observation."""
    if not isinstance(value, dict) or not value.get("serial"):
        return None
    salt = numeric_salt(value.get("salt_ppm"))
    try:
        timestamp = datetime.fromisoformat(value["salt_last_success"])
    except (KeyError, TypeError, ValueError):
        return None
    if salt is None or timestamp.tzinfo is None:
        return None
    return {
        "serial": str(value["serial"]),
        "system_name": str(value.get("system_name") or "Pool"),
        "salt_ppm": salt,
        "salt_last_success": timestamp.isoformat(),
    }


def retain_salt(
    data: dict[str, Any], previous: dict[str, Any] | None, now: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Keep last-known salt on an omitted reading; never advance its timestamp."""
    result = dict(data)
    cached = valid_cache(previous)
    if cached and cached["serial"] != str(data.get("serial")):
        cached = None
    fresh = numeric_salt(data.get("salt_ppm"))
    if fresh is not None:
        cached = valid_cache({**data, "salt_ppm": fresh, "salt_last_success": now})
    result.update(
        salt_ppm=cached["salt_ppm"] if cached else None,
        salt_last_success=cached["salt_last_success"] if cached else None,
        salt_stale=fresh is None,
    )
    return result, cached
