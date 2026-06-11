"""Small shared helpers for coercing KSP cfg string values to numbers."""

from __future__ import annotations

from typing import Optional


def to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def to_int(value: Optional[str]) -> Optional[int]:
    f = to_float(value)
    return int(f) if f is not None else None
