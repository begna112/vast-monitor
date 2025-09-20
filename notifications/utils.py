from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone


HR = "~~                                                 ~~"


def humanize_duration(seconds: float) -> str:
    secs = int(round(seconds))
    if secs < 60:
        return f"{secs}s"
    minutes, s = divmod(secs, 60)
    if minutes < 60:
        return f"{minutes}m {s}s"
    hours, m = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {m}m {s}s"
    days, h = divmod(hours, 24)
    return f"{days}d {h}h {m}m"


def _to_epoch(dt_iso: str) -> Optional[int]:
    try:
        dt = datetime.fromisoformat(dt_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def discord_ts(dt_iso: Optional[str], style: str = "f") -> str:
    if not dt_iso:
        return ""
    epoch = _to_epoch(dt_iso)
    if epoch is None:
        return dt_iso
    return f"<t:{epoch}:{style}>"

