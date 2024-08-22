from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return timezone-aware UTC timestamp"""
    return datetime.now(timezone.utc)
