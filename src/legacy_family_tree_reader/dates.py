"""Conservative display helpers for Legacy's packed date values."""

from __future__ import annotations

import re
from datetime import date

_PACKED_DISPLAY = re.compile(
    r"^(?P<qualifier>\d{2})(?P<day>\d{2})(?P<month>\d{2})"
    r"(?P<year>\d{4})(?P<tail>\d{8})$"
)
_SORT_DATE = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})$")


def decode_legacy_date(value: object) -> str | None:
    """Return a readable date only when a Legacy value can be decoded safely.

    Legacy ``*D`` fields commonly contain 18 digits: a two-digit qualifier,
    day, month, year, and eight flag/reserved digits.  Only qualifier zero and
    a zero tail are interpreted here; qualified/ranged dates are returned
    unchanged rather than guessed.  Positive ``YYYYMMDD`` sort dates are also
    accepted.  Missing/sentinel values return ``None``.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"0", "-99999999", "99999999"}:
        return None

    match = _PACKED_DISPLAY.fullmatch(text)
    if match:
        if match["qualifier"] != "00" or match["tail"] != "00000000":
            return text
        return _format_parts(int(match["year"]), int(match["month"]), int(match["day"]), text)

    match = _SORT_DATE.fullmatch(text)
    if match:
        return _format_parts(int(match["year"]), int(match["month"]), int(match["day"]), text)
    return text


def _format_parts(year: int, month: int, day: int, original: str) -> str:
    if not 1 <= year <= 9999:
        return original
    if month == 0 and day == 0:
        return f"{year:04d}"
    if 1 <= month <= 12 and day == 0:
        return f"{year:04d}-{month:02d}"
    try:
        parsed = date(year, month, day)
    except ValueError:
        return original
    return parsed.isoformat()


# Explicit alias for callers that want to emphasize that this is display-only.
legacy_date_display = decode_legacy_date

__all__ = ["decode_legacy_date", "legacy_date_display"]
