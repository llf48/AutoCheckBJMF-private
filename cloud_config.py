import os
from datetime import datetime, timezone, timedelta


REQUIRED_ENV = ("BJMF_CLASS_ID", "BJMF_LAT", "BJMF_LNG", "BJMF_ACC", "BJMF_COOKIE")
CHINA_TZ = timezone(timedelta(hours=8))
MIN_AUTOSUBMIT_WATCH_MINUTES = 5
MAX_AUTOSUBMIT_WATCH_INTERVAL_SECONDS = 30


def _required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("Missing required environment variable: %s" % name)
    return value


def load_cloud_config():
    cookie_value = _required("BJMF_COOKIE")
    cookies = [line.strip() for line in cookie_value.splitlines() if line.strip()]
    autosubmit = os.environ.get("BJMF_AUTOSUBMIT", "").lower() == "true"
    watch_minutes = int(os.environ.get("BJMF_WATCH_MINUTES", "0") or "0")
    watch_interval_seconds = int(os.environ.get("BJMF_WATCH_INTERVAL_SECONDS", "300") or "300")

    if autosubmit and watch_minutes > 0:
        watch_minutes = max(watch_minutes, MIN_AUTOSUBMIT_WATCH_MINUTES)
        if watch_interval_seconds <= 0 or watch_interval_seconds > MAX_AUTOSUBMIT_WATCH_INTERVAL_SECONDS:
            watch_interval_seconds = MAX_AUTOSUBMIT_WATCH_INTERVAL_SECONDS

    return {
        "class": _required("BJMF_CLASS_ID"),
        "lat": _required("BJMF_LAT"),
        "lng": _required("BJMF_LNG"),
        "acc": _required("BJMF_ACC"),
        "cookie": cookies,
        "pushplus": os.environ.get("PUSHPLUS_TOKEN", "").strip(),
        "debug": os.environ.get("BJMF_DEBUG", "").lower() == "true",
        "autosubmit": autosubmit,
        "watch_minutes": watch_minutes,
        "watch_interval_seconds": watch_interval_seconds,
        "watch_until_window_end": os.environ.get("BJMF_WATCH_UNTIL_WINDOW_END", "").lower() == "true",
    }


def is_inside_china_time_window(now_utc=None, start="07:50", end="18:00"):
    now_utc = now_utc or datetime.now(timezone.utc)
    now_china = now_utc.astimezone(CHINA_TZ)
    start_hour, start_minute = [int(part) for part in start.split(":")]
    end_hour, end_minute = [int(part) for part in end.split(":")]
    start_dt = now_china.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_dt = now_china.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return start_dt <= now_china <= end_dt


def seconds_until_china_time_window_end(now_utc=None, end="18:00"):
    now_utc = now_utc or datetime.now(timezone.utc)
    now_china = now_utc.astimezone(CHINA_TZ)
    end_hour, end_minute = [int(part) for part in end.split(":")]
    end_dt = now_china.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return max(0, int((end_dt - now_china).total_seconds()))


def seconds_until_china_time_window_start(now_utc=None, start="07:50"):
    now_utc = now_utc or datetime.now(timezone.utc)
    now_china = now_utc.astimezone(CHINA_TZ)
    start_hour, start_minute = [int(part) for part in start.split(":")]
    start_dt = now_china.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    return max(0, int((start_dt - now_china).total_seconds()))
