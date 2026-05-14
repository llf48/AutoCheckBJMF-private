from datetime import datetime, timedelta


def _time_on_date(now, hhmm):
    hour, minute = hhmm.split(":")
    return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def get_next_poll_delay(now, start_time, end_time, interval_minutes):
    start = _time_on_date(now, start_time)
    end = _time_on_date(now, end_time)

    if now < start:
        return int((start - now).total_seconds())
    if now > end:
        return None

    return int(timedelta(minutes=interval_minutes).total_seconds())
