import os
from datetime import datetime, timezone, timedelta


REQUIRED_ENV = ("BJMF_CLASS_ID", "BJMF_LAT", "BJMF_LNG", "BJMF_ACC", "BJMF_COOKIE")
CHINA_TZ = timezone(timedelta(hours=8))
MIN_AUTOSUBMIT_WATCH_MINUTES = 5
MAX_AUTOSUBMIT_WATCH_INTERVAL_SECONDS = 30
CLASS_WINDOWS = (("08:00", "12:00"), ("14:30", "17:40"))
CLASS_CYCLE_MINUTES = 45
CLASS_DURATION_MINUTES = 40
CLASS_CHECK_MINUTES = (0, 10, 20, 30)
CLASS_CHECK_TOLERANCE_SECONDS = 150


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
        "paused": os.environ.get("BJMF_PAUSED", "").lower() == "true",
        "safe_single_check": os.environ.get("BJMF_SAFE_SINGLE_CHECK", "true").lower() == "true",
        "force_check": os.environ.get("BJMF_FORCE_CHECK", "").lower() == "true",
        "class_window_gate": os.environ.get("BJMF_CLASS_WINDOW_GATE", "").lower() == "true",
        "notice_text": os.environ.get("BJMF_NOTICE_TEXT", "").strip(),
        "direct_punch_url": os.environ.get("BJMF_DIRECT_PUNCH_URL", "").strip(),
    }


def _china_time_on_current_date(now_china, value):
    hour, minute = [int(part) for part in value.split(":")]
    return now_china.replace(hour=hour, minute=minute, second=0, microsecond=0)


def is_class_cycle_check_time(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    now_china = now_utc.astimezone(CHINA_TZ)
    for start, end in CLASS_WINDOWS:
        start_dt = _china_time_on_current_date(now_china, start)
        end_dt = _china_time_on_current_date(now_china, end)
        if not start_dt <= now_china <= end_dt:
            continue

        elapsed_seconds = int((now_china - start_dt).total_seconds())
        cycle_seconds = elapsed_seconds % (CLASS_CYCLE_MINUTES * 60)
        if cycle_seconds >= CLASS_DURATION_MINUTES * 60:
            return False

        for minute in CLASS_CHECK_MINUTES:
            slot_seconds = minute * 60
            delay_seconds = cycle_seconds - slot_seconds
            if 0 <= delay_seconds <= CLASS_CHECK_TOLERANCE_SECONDS:
                return True
        return False
    return False


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
