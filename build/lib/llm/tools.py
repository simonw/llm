from datetime import datetime, timezone
from importlib.metadata import version
import time


def llm_version() -> str:
    "Return the installed version of llm"
    return version("llm")


def llm_time() -> dict:
    "Returns the current time, as local time and UTC"
    # Get current times
    utc_time = datetime.now(timezone.utc)
    local_time = datetime.now()

    # Get timezone information
    local_tz_name = time.tzname[time.localtime().tm_isdst]
    is_dst = bool(time.localtime().tm_isdst)

    # Calculate offset
    offset_seconds = -time.timezone if not is_dst else -time.altzone
    offset_hours = offset_seconds // 3600
    offset_minutes = (offset_seconds % 3600) // 60

    timezone_offset = (
        f"UTC{'+' if offset_hours >= 0 else ''}{offset_hours:02d}:{offset_minutes:02d}"
    )

    return {
        "utc_time": utc_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "utc_time_iso": utc_time.isoformat(),
        "local_timezone": local_tz_name,
        "local_time": local_time.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone_offset": timezone_offset,
        "is_dst": is_dst,
    }
