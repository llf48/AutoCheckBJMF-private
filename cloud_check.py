from cloud_config import CHINA_TZ, is_inside_china_time_window, load_cloud_config
from cloud_config import seconds_until_china_time_window_end
from cloud_config import seconds_until_china_time_window_start
import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


REMEMBER_COOKIE_PATTERN = r"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d=[^;]+"
PUNCH_PAGE_SUFFIXES = ("/punchs?op=ing", "/punchs")
ACTIVE_MARKERS = (
    "\u70b9\u51fb\u53bb\u5b8c\u6210\u7b7e\u5230",
    "\u5b8c\u6210\u7b7e\u5230",
    "\u7acb\u5373\u7b7e\u5230",
    "\u6b63\u5728\u8fdb\u884c",
    "\u786e\u5b9a",
    "鐐规",
    "绛惧埌",
    "姝ｅ湪",
    "瀹屾垚",
    "绔嬪嵆",
)
SIGNED_MARKERS = ("\u5df2\u7b7e\u5230", "\u5df2\u7b7e", "signed", "宸茬")
ERROR_TITLE_MARKERS = ("\u51fa\u9519", "\u9519\u8bef", "鍑洪敊")


def modify_decimal_part(num):
    num = float(num)
    num_str = f"{num:.8f}"
    decimal_index = num_str.find(".")
    decimal_part = num_str[decimal_index + 4:decimal_index + 9]
    decimal_value = int(decimal_part)
    random_offset = random.randint(-15000, 15000)
    new_decimal_value = abs(decimal_value + random_offset)
    new_decimal_str = f"{new_decimal_value:05d}"
    new_num_str = num_str[:decimal_index + 4] + new_decimal_str + num_str[decimal_index + 9:]
    return float(new_num_str)


def find_remember_cookie(cookie):
    result = re.search(REMEMBER_COOKIE_PATTERN, cookie)
    if not result:
        raise RuntimeError("BJMF_COOKIE does not contain the expected remember_student token.")
    return result.group(0)


def get_headers(class_id, cookie):
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 9; wv) AppleWebKit/537.36 Mobile Safari/537.36 MicroMessenger/8.0.47",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "X-Requested-With": "com.tencent.mm",
        "Referer": "https://k8n.cn/student/course/" + class_id,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": find_remember_cookie(cookie),
    }


def _unique(values):
    seen = set()
    unique_values = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


def extract_punch_ids(html):
    gps_ids = []
    gps_ids.extend(re.findall(r"punch_gps\((\d+)\)", html))
    gps_ids.extend(re.findall(r"pages/punchs/gps\?[^\"']*punch_id=(\d+)", html))
    gps_ids.extend(re.findall(r"/student/punchw/course/\d+/(\d+)", html))
    gps_ids.extend(re.findall(r"/student/punchs/course/\d+/(\d+)", html))
    gps_ids.extend(re.findall(r"id=[\"']gps_btn_(\d+)[\"']", html))

    scan_ids = re.findall(r"punchcard_(\d+)", html)
    return _unique(gps_ids), _unique(scan_ids)


def extract_submit_urls(html, class_id):
    urls = {}
    soup = BeautifulSoup(html, "html.parser")
    patterns = [
        r"(https?://k8n\.cn/student/punchw/course/%s/(\d+)[^\"'<>\s]*)" % re.escape(class_id),
        r"(https?://k8n\.cn/student/punchs/course/%s/(\d+)[^\"'<>\s]*)" % re.escape(class_id),
        r"(/student/punchw/course/%s/(\d+)[^\"'<>\s]*)" % re.escape(class_id),
        r"(/student/punchs/course/%s/(\d+)[^\"'<>\s]*)" % re.escape(class_id),
    ]

    def add_url(value):
        if not value:
            return
        for pattern in patterns:
            for matched_url, punch_id in re.findall(pattern, value):
                urls[punch_id] = urljoin("https://k8n.cn", matched_url)

    for tag in soup.find_all(True):
        for attr in ("href", "action", "path", "data-url", "data-href", "data-action"):
            add_url(tag.get(attr))
    add_url(html)
    return urls


def extract_gps_submit_urls(html, class_id):
    return extract_submit_urls(html, class_id)


def extract_form_submit_url(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", method=lambda value: value and value.lower() == "post")
    if not form:
        return None
    return urljoin(page_url, form.get("action") or page_url)


def get_visible_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip())


def has_signed_status(html):
    text = get_visible_text(html)
    return "已签到" in text or "已签" in text


def raise_if_unparsed_active_task(html, gps_ids, scan_ids):
    if gps_ids or scan_ids or has_signed_status(html):
        return
    text = get_visible_text(html)
    active_markers = ("点此去完成签到", "完成签到", "立即签到", "确定")
    if any(marker in text for marker in active_markers):
        raise RuntimeError("Active punch task is visible, but cloud_check could not parse its punch id.")


def contains_any(text, markers):
    return any(marker in text for marker in markers)


def get_page_title(html):
    title_tag = BeautifulSoup(html, "html.parser").find("title")
    return title_tag.text.strip() if title_tag and title_tag.text else ""


def has_signed_status(html):
    return contains_any(get_visible_text(html), SIGNED_MARKERS)


def has_active_task_marker(html):
    return contains_any(get_visible_text(html), ACTIVE_MARKERS)


def raise_if_login_abnormal(response):
    title = get_page_title(response.text)
    if contains_any(title, ERROR_TITLE_MARKERS):
        raise RuntimeError("Login status is abnormal. BJMF_COOKIE may have expired.")
    if "/login" in response.url.lower():
        raise RuntimeError("Request was redirected to login. BJMF_COOKIE may have expired.")


def raise_if_unparsed_active_task(html, gps_ids, scan_ids):
    if gps_ids or scan_ids or has_signed_status(html):
        return
    if has_active_task_marker(html):
        raise RuntimeError("Active punch task is visible, but cloud_check could not parse its punch id.")


def print_page_diagnostics(label, response, class_id):
    gps_ids, scan_ids = extract_punch_ids(response.text)
    submit_urls = extract_submit_urls(response.text, class_id)
    course_ids = _unique(re.findall(r"(?:course/|course_id=)(\d+)", response.text))
    print(
        "Page diagnostics:",
        {
            "page": label,
            "status": response.status_code,
            "final_url": response.url,
            "title": get_page_title(response.text),
            "html_bytes": len(response.text.encode("utf-8", errors="ignore")),
            "active_marker": has_active_task_marker(response.text),
            "signed_marker": has_signed_status(response.text),
            "gps_ids": gps_ids,
            "scan_ids": scan_ids,
            "submit_url_count": len(submit_urls),
            "course_ids_seen": course_ids[:10],
        },
    )


def resolve_submit_url(candidate_url, headers):
    if not candidate_url:
        return None
    response = requests.get(candidate_url, headers=headers, timeout=30)
    response.raise_for_status()
    return extract_form_submit_url(response.text, response.url) or candidate_url


def verify_signed(class_id, headers):
    for suffix in ("/punchs?op=ing", "/punchs?op=ed"):
        response = requests.get("https://k8n.cn/student/course/" + class_id + suffix, headers=headers, timeout=30)
        response.raise_for_status()
        if has_signed_status(response.text):
            return True
    return False


def check_one_cookie(config, cookie):
    class_id = config["class"]
    url = "https://k8n.cn/student/course/" + class_id + "/punchs"
    headers = get_headers(class_id, cookie)

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title_tag = soup.find("title")
    if title_tag and "出错" in title_tag.text:
        raise RuntimeError("Login status is abnormal. BJMF_COOKIE may have expired.")

    gps_ids, scan_ids = extract_punch_ids(response.text)
    submit_urls = extract_submit_urls(response.text, class_id)
    raise_if_unparsed_active_task(response.text, gps_ids, scan_ids)
    punch_ids = _unique(gps_ids + scan_ids)
    print("Checked at China time:", datetime.now(CHINA_TZ).isoformat(timespec="seconds"))
    print("Found GPS punch ids:", gps_ids)
    print("Found scan punch ids:", scan_ids)
    print("Found submit urls:", submit_urls)

    if punch_ids and not config.get("autosubmit", False):
        print("BJMF_AUTOSUBMIT is not true. Dry run only; no punch request was submitted.")
        return len(punch_ids)

    for punch_id in punch_ids:
        punch_url = submit_urls.get(
            punch_id,
            "https://k8n.cn/student/punchs/course/" + class_id + "/" + punch_id,
        )
        punch_url = resolve_submit_url(punch_url, headers) or punch_url
        payload = {
            "id": punch_id,
            "lat": modify_decimal_part(config["lat"]),
            "lng": modify_decimal_part(config["lng"]),
            "acc": config["acc"],
            "res": "",
            "gps_addr": "",
        }
        punch_response = requests.post(punch_url, headers=headers, data=payload, timeout=30)
        punch_response.raise_for_status()
        result_soup = BeautifulSoup(punch_response.text, "html.parser")
        result_title = result_soup.find("div", id="title")
        print(result_title.text.strip() if result_title else "Punch request sent.")

    if punch_ids and not verify_signed(class_id, headers):
        raise RuntimeError("Punch request finished, but follow-up check did not show a signed status.")

    return len(punch_ids)


def check_one_cookie(config, cookie):
    class_id = config["class"]
    headers = get_headers(class_id, cookie)

    responses = []
    for suffix in PUNCH_PAGE_SUFFIXES:
        url = "https://k8n.cn/student/course/" + class_id + suffix
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        raise_if_login_abnormal(response)
        responses.append((suffix, response))
        print_page_diagnostics(suffix, response, class_id)

    combined_html = "\n".join(response.text for _, response in responses)
    gps_ids, scan_ids = extract_punch_ids(combined_html)
    submit_urls = extract_submit_urls(combined_html, class_id)
    for _, response in responses:
        raise_if_unparsed_active_task(response.text, gps_ids, scan_ids)
    punch_ids = _unique(gps_ids + scan_ids)
    print("Checked at China time:", datetime.now(CHINA_TZ).isoformat(timespec="seconds"))
    print("Found GPS punch ids:", gps_ids)
    print("Found scan punch ids:", scan_ids)
    print("Found submit urls:", submit_urls)

    if punch_ids and not config.get("autosubmit", False):
        print("BJMF_AUTOSUBMIT is not true. Dry run only; no punch request was submitted.")
        return len(punch_ids)

    for punch_id in punch_ids:
        punch_url = submit_urls.get(
            punch_id,
            "https://k8n.cn/student/punchs/course/" + class_id + "/" + punch_id,
        )
        punch_url = resolve_submit_url(punch_url, headers) or punch_url
        payload = {
            "id": punch_id,
            "lat": modify_decimal_part(config["lat"]),
            "lng": modify_decimal_part(config["lng"]),
            "acc": config["acc"],
            "res": "",
            "gps_addr": "",
        }
        punch_response = requests.post(punch_url, headers=headers, data=payload, timeout=30)
        punch_response.raise_for_status()
        result_soup = BeautifulSoup(punch_response.text, "html.parser")
        result_title = result_soup.find("div", id="title")
        print(result_title.text.strip() if result_title else "Punch request sent.")

    if punch_ids and not verify_signed(class_id, headers):
        raise RuntimeError("Punch request finished, but follow-up check did not show a signed status.")

    return len(punch_ids)


def run_once():
    if not is_inside_china_time_window():
        print("Outside 07:50-18:00 China time window. Skipping.")
        return

    config = load_cloud_config()
    total_found = 0
    for cookie in config["cookie"]:
        total_found += check_one_cookie(config, cookie)
    return total_found


def run_watch():
    config = load_cloud_config()
    watch_minutes = config["watch_minutes"]
    if watch_minutes <= 0:
        return run_once()

    watch_seconds = watch_minutes * 60
    if config.get("watch_until_window_end"):
        seconds_until_end = seconds_until_china_time_window_end()
        watch_seconds = min(watch_seconds, seconds_until_end) if watch_seconds else seconds_until_end
        print("Watching until China time window end or %d seconds, whichever comes first." % watch_seconds)
    deadline = time.time() + watch_seconds
    interval = config["watch_interval_seconds"]
    while True:
        if not is_inside_china_time_window():
            seconds_until_start = seconds_until_china_time_window_start()
            if seconds_until_start > 0:
                if time.time() + seconds_until_start > deadline:
                    print("Watch window ended before China time window opened.")
                    return
                print("Before 07:50 China time window. Sleeping %d seconds." % seconds_until_start)
                time.sleep(seconds_until_start)
                continue
            print("Outside 07:50-18:00 China time window. Stopping watch.")
            return

        total_found = 0
        for cookie in config["cookie"]:
            total_found += check_one_cookie(config, cookie)
        if total_found:
            print("Found and submitted %d punch task(s). Ending watch." % total_found)
            return
        remaining_seconds = deadline - time.time()
        if remaining_seconds <= 0:
            print("Watch window ended without active punch tasks.")
            return
        sleep_seconds = min(interval, remaining_seconds)
        print("No active punch task. Sleeping %d seconds." % int(sleep_seconds))
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    run_watch()
