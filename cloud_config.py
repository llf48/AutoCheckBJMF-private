import os
from datetime import datetime, timezone, timedelta


REQUIRED_ENV = ("BJMF_CLASS_ID", "BJMF_LAT", "BJMF_LNG", "BJMF_ACC", "BJMF_COOKIE")
CHINA_TZ = timezone(timedelta(hours=8))


def _required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("Missing required environment variable: %s" % name)
    return value


def load_cloud_config():
    cookie_value = _required("BJMF_COOKIE")
    cookies = [line.strip() for line in cookie_value.splitlines() if line.strip()]

    return {
        "class": _required("BJMF_CLASS_ID"),
        "lat": _required("BJMF_LAT"),
        "lng": _required("BJMF_LNG"),
        "acc": _required("BJMF_ACC"),
        "cookie": cookies,
        "pushplus": os.environ.get("PUSHPLUS_TOKEN", "").strip(),
        "debug": os.environ.get("BJMF_DEBUG", "").lower() == "true",
    }


def is_inside_china_time_window(now_utc=None, start="07:50", end="18:00"):
    now_utc = now_utc or datetime.now(timezone.utc)
    now_china = now_utc.astimezone(CHINA_TZ)
    start_hour, start_minute = [int(part) for part in start.split(":")]
    end_hour, end_minute = [int(part) for part in end.split(":")]
    start_dt = now_china.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_dt = now_china.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    return start_dt <= now_china <= end_dt
