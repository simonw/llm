import time
from datetime import datetime, timezone
from importlib.metadata import version


def llm_version() -> str:
    "Return the installed version of llm"
    return version("llm")


def llm_time() -> dict:
    "Returns the current time, as local time and UTC"
    # Get current times
    utc_time = datetime.now(timezone.utc)
    local_time = datetime.now(timezone.utc).astimezone()

    # Get timezone information
    local_tz_name = time.tzname[time.localtime().tm_isdst]
    is_dst = bool(time.localtime().tm_isdst)

    # Calculate offset. Compute the magnitude with divmod() rather than
    # floor-dividing a negative value, which rounds -3:30 down to -4:00,
    # and apply the sign separately so the hours are always zero-padded
    # to two digits (":02d" does not pad the sign of a negative number).
    offset_seconds = -time.timezone if not is_dst else -time.altzone
    offset_sign = "+" if offset_seconds >= 0 else "-"
    offset_hours, offset_remainder = divmod(abs(offset_seconds), 3600)
    offset_minutes = offset_remainder // 60

    timezone_offset = f"UTC{offset_sign}{offset_hours:02d}:{offset_minutes:02d}"

    return {
        "utc_time": utc_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "utc_time_iso": utc_time.isoformat(),
        "local_timezone": local_tz_name,
        "local_time": local_time.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone_offset": timezone_offset,
        "is_dst": is_dst,
    }
