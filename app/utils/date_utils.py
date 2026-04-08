"""Date utility functions."""

import math
from datetime import UTC, datetime, timedelta


def format_expiry_date(expiry_date: datetime | None, include_time: bool = False) -> str:
    """Format expiry date with remaining days calculation.

    Args:
        expiry_date: Expiry date to format
        include_time: Whether to include HH:MM in the output

    Returns:
        Formatted string like "08.05.2026 (осталось 30 дн.)"
    """
    if not expiry_date:
        return "Бессрочно"

    # Ensure UTC timezone
    if expiry_date.tzinfo is None:
        expiry_date = expiry_date.replace(tzinfo=UTC)

    now = datetime.now(UTC)

    # Visual display (+3 hours for MSK context)
    display_date = expiry_date + timedelta(hours=3)
    date_format = "%d.%m.%Y %H:%M" if include_time else "%d.%m.%Y"
    date_str = display_date.strftime(date_format)

    # Proper remaining days calculation
    delta_seconds = (expiry_date - now).total_seconds()
    remaining_days = math.ceil(delta_seconds / 86400)

    if remaining_days > 0:
        return f"{date_str} (осталось {remaining_days} дн.)"
    elif remaining_days == 0:
        return f"{date_str} (истекает сегодня)"
    else:
        return f"{date_str} (истек {abs(remaining_days)} дн. назад)"
