from cloud_config import CHINA_TZ, is_class_cycle_check_time, is_inside_china_time_window, load_cloud_config
from cloud_config import seconds_until_china_time_window_end
from cloud_config import seconds_until_china_time_window_start
from audit_log import sanitize, write_account_summary, write_audit_event
import random
import re
import time
import hashlib
from datetime import datetime
from html import unescape
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


REMEMBER_COOKIE_PATTERN = r"remember_student_[A-Za-z0-9_]+=[^;\s]+"
PUNCH_PAGE_SUFFIXES = ("/punchs?op=ing",)
ACTIVE_MARKERS = (
    "\u70b9\u51fb\u53bb\u5b8c\u6210\u7b7e\u5230",
    "\u70b9\u6b64\u53bb\u5b8c\u6210\u7b7e\u5230",
    "\u5b8c\u6210\u7b7e\u5230",
    "\u7acb\u5373\u7b7e\u5230",
)
SIGNED_MARKERS = ("\u5df2\u7b7e\u5230", "\u5df2\u7b7e", "宸茬")
COOLDOWN_MARKERS = ("\u51b7\u5374", "\u7b49\u5f85\u65f6\u95f4", "\u5206\u949f\u5b8c\u5168\u540e\u518d\u8bbf\u95ee")
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


def extract_student_id(cookie):
    try:
        remember_cookie = find_remember_cookie(cookie)
    except RuntimeError:
        return "unknown"
    decoded_value = unquote(remember_cookie.split("=", 1)[1])
    match = re.match(r"(\d+)(?:\||$)", decoded_value)
    return match.group(1) if match else "unknown"


def _sanitize_audit_value(value):
    return sanitize(value)


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


def normalize_markup(html):
    # Decode transport/HTML escaping, never execute JavaScript or guess QR values.
    return unescape(html).replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/").replace(r"\u0026", "&")


def submission_url_candidates(html, class_id=None):
    pattern = r"""(?<![\w:/.-])((?:https?://[^\s/"'<>]+)?/student/punch(?:w|s|card|scan)/course/\d+/\d+[^"'<>\\\s]*)"""
    urls = {}
    for value in re.findall(pattern, normalize_markup(html)):
        url = urljoin("https://k8n.cn", value)
        parsed = urlsplit(url)
        route = re.fullmatch(r"/student/punch(?:w|s|card|scan)/course/(\d+)/(\d+)/?", parsed.path)
        if parsed.hostname != "k8n.cn" or parsed.username or parsed.password or not route:
            continue
        if class_id is not None and route.group(1) != str(class_id):
            continue
        urls[route.group(2)] = url
    return urls


def extract_punch_ids(html, class_id=None):
    html = normalize_markup(html)
    gps_ids = re.findall(r"punch_gps\((\d+)\)", html)
    gps_ids.extend(re.findall(r"""pages/punchs/gps\?[^"']*punch_id=(\d+)""", html))
    scan_ids = []
    for punch_id, url in submission_url_candidates(html, class_id).items():
        (scan_ids if re.search(r"/punch(?:card|scan)/", urlsplit(url).path) else gps_ids).append(punch_id)
    gps_ids.extend(re.findall(r"""id=["']gps_btn_(\d+)["']""", html))
    scan_patterns = (
        r"punchcard[_-](\d+)",
        r"punchcard\s*\(\s*(\d+)\s*\)",
        r"(?:scan|scancard|qrcode|qr)[_-](\d+)",
        r"""data-(?:scan|punchcard)-id\s*=\s*["']?(\d+)""",
        r"""["'](?:scan|punchcard)_id["']\s*:\s*["']?(\d+)""",
    )
    for pattern in scan_patterns:
        scan_ids.extend(re.findall(pattern, html, flags=re.IGNORECASE))
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("[data-punch-id], input[name='punch_id']"):
        value = tag.get("data-punch-id") or tag.get("value", "")
        if re.fullmatch(r"[1-9]\d*", str(value)) and value not in gps_ids:
            scan_ids.append(str(value))
    return _unique(gps_ids), _unique(scan_ids)


def extract_submit_urls(html, class_id):
    return submission_url_candidates(html, class_id)


def extract_gps_submit_urls(html, class_id):
    return extract_submit_urls(html, class_id)


def extract_form_submit_url(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", method=lambda value: value and value.lower() == "post")
    if not form:
        return None
    return urljoin(page_url, form.get("action") or page_url)


def extract_punch_id_from_url(url):
    patterns = (
        r"/student/punch(?:w|s|card|scan)/course/\d+/(\d+)",
        r"[?&]punch_id=(\d+)",
        r"[?&]id=(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def parse_notice_end_time(notice_text, now_china=None):
    if not notice_text:
        return None
    now_china = now_china or datetime.now(CHINA_TZ)
    patterns = (
        r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*结束",
        r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*结束",
    )
    match = re.search(patterns[0], notice_text)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=CHINA_TZ,
        )
    match = re.search(patterns[1], notice_text)
    if match:
        month, day, hour, minute, second = match.groups()
        return datetime(
            now_china.year,
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=CHINA_TZ,
        )
    return None


def should_run_for_notice(config, now_china=None):
    notice_text = config.get("notice_text", "")
    if not notice_text:
        return True
    now_china = now_china or datetime.now(CHINA_TZ)
    end_time = parse_notice_end_time(notice_text, now_china)
    if not end_time:
        print("BJMF_NOTICE_TEXT did not contain a recognizable end time. Running one check.")
        return True
    print("Notice punch window ends at:", end_time.isoformat(timespec="seconds"))
    if now_china > end_time:
        print("Notice punch window has already ended. Skipping network check.")
        return False
    return True


def get_visible_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip())


def contains_any(text, markers):
    return any(marker in text for marker in markers)


def get_page_title(html):
    title_tag = BeautifulSoup(html, "html.parser").find("title")
    return title_tag.text.strip() if title_tag and title_tag.text else ""


def has_signed_status(html):
    text = get_visible_text(html)
    text = re.sub(r"\bnot(?:\s+yet)?\s+signed\b", "", text, flags=re.I)
    return contains_any(text, SIGNED_MARKERS) or bool(re.search(r"(?<![\w-])signed(?![\w-])", text, re.I))


def pending_task_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select(".punch-card"):
        if "punch-card--success" in card.get("class", []) or has_signed_status(str(card)) or contains_any(card.get_text(" ", strip=True), ("已结束", "已过期")):
            card.decompose()
    return str(soup)


def has_active_task_marker(html):
    return contains_any(get_visible_text(html), ACTIVE_MARKERS)


def has_cooldown_marker(html):
    return contains_any(get_visible_text(html), COOLDOWN_MARKERS)


class AccountCooldownError(RuntimeError):
    pass


class LoginRequiredError(RuntimeError):
    pass


class UnrecognizedPageError(RuntimeError):
    pass


def raise_if_cooldown_page(html):
    if has_cooldown_marker(html):
        raise AccountCooldownError(
            "BJMF returned a cooldown page; do not retry this account until the cooldown expires, "
            "because another visit can extend the waiting period."
        )


def raise_if_login_abnormal(response):
    title = get_page_title(response.text)
    if contains_any(title, ERROR_TITLE_MARKERS):
        raise UnrecognizedPageError("Login status or page access is abnormal; this alone does not prove the cookie expired.")
    decoded_url = unquote(response.url).lower()
    if "/login" in decoded_url or "open.weixin.qq.com/connect/oauth2/authorize" in decoded_url:
        raise LoginRequiredError("Request was redirected to login/OAuth. BJMF_COOKIE may have expired.")


def _redact_structure_value(value):
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value)
    value = str(value)
    value = re.sub(r"([?&][^=&#\s]+)=([^&#\s]*)", r"\1=<value>", value)
    value = re.sub(r"\d+", "<n>", value)
    value = re.sub(r"[A-Za-z0-9_-]{24,}", "<token>", value)
    return value[:180]


def get_active_structure_hints(html, limit=12):
    soup = BeautifulSoup(html, "html.parser")
    keywords = ("punch", "scan", "card", "qrcode", "qr", "sign")
    hints = []
    tags = sorted(soup.find_all(True), key=lambda tag: 0 if tag.name in ("a", "button", "form", "input") else 1)
    for tag in tags:
        attribute_text = " ".join([str(tag.name)] + list(tag.attrs) + [str(value) for value in tag.attrs.values()]).lower()
        visible_text = " ".join(tag.stripped_strings)
        has_relevant_attribute = any(keyword in attribute_text for keyword in keywords)
        has_active_text = tag.name not in ("html", "body") and contains_any(visible_text, ACTIVE_MARKERS)
        if not has_relevant_attribute and not has_active_text:
            continue
        attributes = {}
        for name, value in tag.attrs.items():
            if name in ("class", "id", "name", "type", "method", "data-punch-id", "data-scan-id", "data-punchcard-id"):
                attributes[name] = _redact_structure_value(value)
            elif name in ("href", "action", "data-url", "data-href", "data-action", "path"):
                attributes[name] = "<javascript>" if str(value).lower().startswith("javascript:") else _redact_structure_value(value)
            else:
                attributes[str(name)[:60]] = "<present>"
        hints.append({"tag": tag.name, "attrs": attributes})
        if len(hints) >= limit:
            break
    return hints


def has_unparsed_static_qr_task(html, gps_ids, scan_ids, class_id=None):
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select(".punch-card--primary"):
        card_html = str(card)
        card_gps, card_scan = extract_punch_ids(card_html, class_id)
        if card_gps or card_scan or has_signed_status(card_html):
            continue
        card_text = "\n".join(card.stripped_strings)
        if contains_any(card_text, ACTIVE_MARKERS) and "二维码" in card_text:
            return True
    return False


class MissingPunchIdError(RuntimeError):
    pass


def raise_if_unparsed_active_task(html, gps_ids, scan_ids, class_id=None):
    cards = BeautifulSoup(html, "html.parser").select(".punch-card--primary")
    if cards and len(BeautifulSoup(html, "html.parser").select(".punch-card")) > 1:
        # A signed sibling or an ID for a different card cannot satisfy this card.
        for card in cards:
            card_html = str(card)
            card_gps, card_scan = extract_punch_ids(card_html, class_id)
            raise_if_unparsed_active_task(card_html, card_gps, card_scan, class_id)
        return
    if gps_ids or scan_ids or has_signed_status(html):
        return
    if has_active_task_marker(html):
        if has_unparsed_static_qr_task(html, gps_ids, scan_ids, class_id):
            raise MissingPunchIdError(
                "Active static QR punch does not expose its punch id on the student task list or fallback page. "
                "Scan the QR code and trigger the workflow with direct_punch_url; "
                "the same URL will be submitted separately for every configured cookie account."
            )
        hints = get_active_structure_hints(html)
        raise MissingPunchIdError(
            "Active punch task is visible, but cloud_check could not parse its punch id. "
            "Sanitized structure hints: %r" % hints
        )


def describe_tasks(html, class_id):
    tasks = []
    for card in BeautifulSoup(html, "html.parser").select(".punch-card")[:30]:
        markup = str(card)
        text = get_visible_text(markup)
        gps, scan = extract_punch_ids(markup, class_id)
        times = _unique(re.findall(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?", text))
        kind = "qr" if "二维码" in text else "gps" if "GPS" in text.upper() else "unknown"
        state = "signed" if has_signed_status(markup) else "ended" if "已结束" in text else "active" if has_active_task_marker(markup) else "unknown"
        tasks.append({"kind": kind, "state": state, "times": times, "punch_ids": _unique(gps + scan)})
    return tasks


def print_page_diagnostics(label, response, class_id, config=None):
    gps_ids, scan_ids = extract_punch_ids(response.text)
    submit_urls = extract_submit_urls(response.text, class_id)
    course_ids = _unique(re.findall(r"(?:course/|course_id=)(\d+)", response.text))
    evidence = {
            "page": label,
            "status": response.status_code,
            "final_url": sanitize(response.url),
            "title": sanitize(get_page_title(response.text)),
            "html_bytes": len(response.text.encode("utf-8", errors="ignore")),
            "html_sha256": hashlib.sha256(response.text.encode("utf-8", errors="ignore")).hexdigest(),
            "active_marker": has_active_task_marker(response.text),
            "signed_marker": has_signed_status(response.text),
            "cooldown_marker": has_cooldown_marker(response.text),
            "gps_ids": gps_ids,
            "scan_ids": scan_ids,
            "submit_url_count": len(submit_urls),
            "course_ids_seen": course_ids[:10],
            "structure_hints": get_active_structure_hints(response.text),
            "tasks": describe_tasks(response.text, class_id),
        }
    print("Page diagnostics:", evidence)
    if config is not None:
        write_audit_event(config, "page_observed", **evidence)


def get_attendance_page(url, headers, config=None, phase="list"):
    """Bounded GETs only; never forward credentials through an unchecked redirect."""
    original = urlsplit(url)
    for _ in range(3):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "k8n.cn" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise RuntimeError("Attendance request must remain on the HTTPS k8n.cn origin.")
        if config is not None:
            write_audit_event(config, "get_attempt", phase=phase, url=url)
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=False)
        if config is not None:
            write_audit_event(config, "get_response", phase=phase, http_status=response.status_code, url=response.url)
        if response.status_code in (301, 302, 303, 307, 308):
            target = urljoin(url, response.headers.get("Location", ""))
            if "/login" in target.lower() or "open.weixin.qq.com/" in target.lower():
                raise LoginRequiredError("Request was redirected to login/OAuth. BJMF_COOKIE may have expired.")
            if urlsplit(target).path.rstrip("/") != original.path.rstrip("/"):
                raise RuntimeError("Attendance redirect changed the endpoint; stopped before following it.")
            if "/student/punch" in original.path:
                validate_punch_url(target, headers, (config or {}).get("class"))
            url = target
            continue
        response.raise_for_status()
        raise_if_cooldown_page(response.text)
        raise_if_login_abnormal(response)
        return response
    raise RuntimeError("Too many attendance redirects; stopped without submitting.")


def validate_punch_url(url, headers, class_id=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "k8n.cn" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise RuntimeError("Punch URL must use the HTTPS k8n.cn origin.")
    route = re.fullmatch(r"/student/punch(?:w|s|card|scan)/course/(\d+)/(\d+)/?", parsed.path)
    if not route or (class_id is not None and route.group(1) != str(class_id)):
        raise RuntimeError("Punch URL does not match the configured course submission route.")
    student_id = extract_student_id(headers.get("Cookie", ""))
    for sid in parse_qs(parsed.query).get("sid", []):
        if sid.isdigit() and student_id != "unknown" and sid != student_id:
            raise RuntimeError("Punch URL belongs to a different account; provide an account-neutral punch URL.")


def resolve_submit_url(candidate_url, headers, config=None):
    if not candidate_url:
        return None
    validate_punch_url(candidate_url, headers)
    response = get_attendance_page(candidate_url, headers, config, phase="submission_preflight")
    target = extract_form_submit_url(response.text, response.url) or candidate_url
    validate_punch_url(target, headers)
    return target


def verify_signed(class_id, headers, punch_id=None, config=None):
    for suffix in ("/punchs?op=ing", "/punchs?op=ed"):
        response = get_attendance_page("https://k8n.cn/student/course/" + class_id + suffix, headers, config, phase="verification")
        if config is not None:
            print_page_diagnostics("verification" + suffix, response, class_id, config)
        if punch_id is None:
            continue  # A course-wide signed marker is insufficient proof.
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".punch-card") or [soup]
        for card in cards:
            markup = str(card)
            gps_ids, scan_ids = extract_punch_ids(markup)
            ids = set(gps_ids + scan_ids)
            ids.update(re.findall(r'data-punch-id=["\'](\d+)["\']', markup))
            if ids == {str(punch_id)} and has_signed_status(markup):
                return True
    return False


def classify_server_result(text):
    if contains_any(text, ("失败", "未成功", "错误", "已结束", "已过期", "未开始")):
        return "rejected"
    if contains_any(text, ("已经签到", "已签到", "重复签到")):
        return "already_signed"
    if "签到成功" in text or text.strip().lower() == "success":
        return "confirmed"
    return "unknown"


def post_punch(config, headers, punch_id, punch_url):
    if not config.get("autosubmit", False):
        raise RuntimeError("Read-only mode prohibits attendance POST requests.")
    validate_punch_url(punch_url, headers, config["class"])
    punch_url = resolve_submit_url(punch_url, headers, config) or punch_url
    validate_punch_url(punch_url, headers, config["class"])
    if extract_punch_id_from_url(punch_url) != str(punch_id):
        raise RuntimeError("Submission form changed the task ID; stopped without submitting.")
    payload = {
        "id": punch_id,
        "lat": modify_decimal_part(config["lat"]),
        "lng": modify_decimal_part(config["lng"]),
        "acc": config["acc"],
        "res": "",
        "gps_addr": "",
    }
    write_audit_event(config, "post_attempt", punch_id=str(punch_id), url=punch_url)
    config["_post_attempts"] = config.get("_post_attempts", 0) + 1
    config["_outcome"] = "submission_unknown"
    try:
        punch_response = requests.post(punch_url, headers=headers, data=payload, timeout=30, allow_redirects=False)
    except requests.RequestException as exc:
        config["_outcome"] = "submission_unknown"
        write_audit_event(config, "post_error", punch_id=str(punch_id), error_type=type(exc).__name__, outcome="submission_unknown")
        raise
    result_soup = BeautifulSoup(punch_response.text, "html.parser")
    result_title = result_soup.find("div", id="title")
    result_text = result_title.text.strip() if result_title else "Punch request sent."
    submission_status = classify_server_result(result_text)
    write_audit_event(
        config,
        "post_response",
        punch_id=str(punch_id),
        http_status=punch_response.status_code,
        server_result=result_text,
        submission_status=submission_status,
    )
    punch_response.raise_for_status()
    if 300 <= punch_response.status_code < 400:
        raise RuntimeError("Submission returned a redirect; result is unknown and was not resubmitted.")
    raise_if_cooldown_page(punch_response.text)
    raise_if_login_abnormal(punch_response)
    print(sanitize(result_text, config))
    if submission_status == "rejected":
        config["_outcome"] = "submission_rejected"
        raise RuntimeError("Server rejected punch: " + sanitize(result_text, config))
    return submission_status


def submit_and_verify(config, headers, punch_id, punch_url):
    status = post_punch(config, headers, punch_id, punch_url)
    confirmed = status in ("confirmed", "already_signed")
    if confirmed:
        config["_confirmed"] = config.get("_confirmed", 0) + 1
        config["_outcome"] = "submitted_confirmed" if status == "confirmed" else "server_already_signed"
    try:
        signed = verify_signed(config["class"], headers, punch_id=punch_id, config=config)
    except (requests.RequestException, RuntimeError) as exc:
        signed = None
        write_audit_event(config, "verification_unavailable", punch_id=str(punch_id), error_type=type(exc).__name__)
    write_audit_event(config, "signed_verification", punch_id=str(punch_id), signed=signed, verification_scope="exact_task")
    if signed and not confirmed:
        config["_confirmed"] = config.get("_confirmed", 0) + 1
        config["_outcome"] = "submitted_confirmed"
    if not confirmed and not signed:
        config["_outcome"] = "submission_unknown"
        raise RuntimeError("Punch request sent, but neither its response nor exact-task verification confirmed success.")


def check_direct_punch_url(config, cookie):
    class_id = config["class"]
    headers = get_headers(class_id, cookie)
    direct_url = urljoin("https://k8n.cn", config["direct_punch_url"])
    validate_punch_url(direct_url, headers, class_id)
    response = get_attendance_page(direct_url, headers, config, phase="direct_link")
    print_page_diagnostics("direct_punch_url", response, class_id, config)
    raise_if_cooldown_page(response.text)

    if has_signed_status(response.text) and not has_active_task_marker(response.text):
        config["_outcome"] = "already_signed"
        write_audit_event(config, "already_signed", post_attempted=False)
        return 0

    punch_id = extract_punch_id_from_url(response.url) or extract_punch_id_from_url(direct_url)
    if not punch_id:
        gps_ids, scan_ids = extract_punch_ids(response.text)
        punch_ids = _unique(gps_ids + scan_ids)
        punch_id = punch_ids[0] if len(punch_ids) == 1 else None
    if not punch_id:
        raise RuntimeError("Direct punch URL did not expose a unique punch id.")

    submit_url = extract_form_submit_url(response.text, response.url) or direct_url
    print("Using direct punch url:", sanitize(response.url, config))
    print("Direct punch id:", punch_id)
    if not config.get("autosubmit", False):
        config["_outcome"] = "dry_run"
        print("BJMF_AUTOSUBMIT is not true. Dry run only; no punch request was submitted.")
        return 1
    submit_and_verify(config, headers, punch_id, submit_url)
    return 1


def check_one_cookie(config, cookie):
    class_id = config["class"]
    headers = get_headers(class_id, cookie)

    if config.get("direct_punch_url"):
        return check_direct_punch_url(config, cookie)

    responses = []
    for suffix in PUNCH_PAGE_SUFFIXES:
        url = "https://k8n.cn/student/course/" + class_id + suffix
        response = get_attendance_page(url, headers, config)
        responses.append((suffix, response))
        print_page_diagnostics(suffix, response, class_id, config)
        raise_if_cooldown_page(response.text)

    combined_html = "\n".join(response.text for _, response in responses)
    gps_ids, scan_ids = extract_punch_ids(pending_task_html(combined_html), class_id)
    if any(
        has_unparsed_static_qr_task(response.text, gps_ids, scan_ids, class_id)
        for _, response in responses
    ):
        suffix = "/punchs"
        url = "https://k8n.cn/student/course/" + class_id + suffix
        response = get_attendance_page(url, headers, config, phase="fallback_list")
        responses.append((suffix, response))
        print_page_diagnostics(suffix, response, class_id, config)
        raise_if_cooldown_page(response.text)
        combined_html = "\n".join(item.text for _, item in responses)
        gps_ids, scan_ids = extract_punch_ids(pending_task_html(combined_html), class_id)
    submit_urls = extract_submit_urls(pending_task_html(combined_html), class_id)
    missing_error = None
    for _, response in responses:
        try:
            raise_if_unparsed_active_task(response.text, gps_ids, scan_ids, class_id)
        except MissingPunchIdError as exc:
            missing_error = exc
    punch_ids = _unique(gps_ids + scan_ids)
    print("Checked at China time:", datetime.now(CHINA_TZ).isoformat(timespec="seconds"))
    print("Found GPS punch ids:", gps_ids)
    print("Found scan punch ids:", scan_ids)
    print("Found submit urls:", sanitize(submit_urls, config))

    if not punch_ids:
        if missing_error:
            raise missing_error
        if not get_visible_text(combined_html):
            raise UnrecognizedPageError("Task list was empty/unreadable, not evidence of no task.")
        config["_outcome"] = "already_signed" if has_signed_status(combined_html) else "no_task"
        write_audit_event(config, config["_outcome"], post_attempted=False)

    if punch_ids and not config.get("autosubmit", False):
        config["_outcome"] = "dry_run"
        print("BJMF_AUTOSUBMIT is not true. Dry run only; no punch request was submitted.")
        if missing_error:
            raise missing_error
        return len(punch_ids)

    for punch_id in punch_ids:
        punch_url = submit_urls.get(
            punch_id,
            "https://k8n.cn/student/punchs/course/" + class_id + "/" + punch_id,
        )
        submit_and_verify(config, headers, punch_id, punch_url)

    if missing_error:
        raise missing_error
    return len(punch_ids)


def check_all_cookies(config, checker=None):
    checker = checker or check_one_cookie
    total_found = 0
    failures = []
    rows = []
    cookies = config["cookie"]
    for account_number, cookie in enumerate(cookies, start=1):
        account_config = dict(config)
        account_config["_audit_account_number"] = account_number
        account_config["_audit_student_id"] = extract_student_id(cookie)
        account_config["_post_attempts"] = 0
        account_config["_confirmed"] = 0
        account_config["_outcome"] = "checked"
        detail = ""
        write_audit_event(account_config, "account_check_started")
        try:
            found = checker(account_config, cookie)
            total_found += found
            write_audit_event(account_config, "account_check_finished", tasks_found=found,
                              outcome=account_config["_outcome"], post_attempts=account_config["_post_attempts"], confirmed=account_config["_confirmed"])
        except Exception as exc:
            failures.append(exc)
            if account_config["_confirmed"]:
                account_config["_outcome"] = "partial_failure"
            elif isinstance(exc, MissingPunchIdError):
                account_config["_outcome"] = "needs_punch_url"
            elif account_config["_post_attempts"] == 0 and isinstance(exc, AccountCooldownError):
                account_config["_outcome"] = "cooldown"
            elif account_config["_post_attempts"] == 0 and isinstance(exc, LoginRequiredError):
                account_config["_outcome"] = "login_required"
            elif account_config["_post_attempts"] == 0 and isinstance(exc, UnrecognizedPageError):
                account_config["_outcome"] = "unrecognized_page"
            elif account_config["_outcome"] == "checked":
                account_config["_outcome"] = "check_failed"
            elif account_config["_outcome"] in ("submitted_confirmed", "already_signed"):
                account_config["_outcome"] = "partial_failure"
            safe_error = sanitize(str(exc), account_config)
            detail = safe_error
            write_audit_event(
                account_config,
                "account_check_failed",
                error_type=type(exc).__name__,
                error_message=safe_error,
                outcome=account_config["_outcome"],
                post_attempts=account_config["_post_attempts"],
                confirmed=account_config["_confirmed"],
            )
            print("Cookie account %d check failed: %s" % (account_number, safe_error))
        rows.append({"account": account_number, "student_id": account_config["_audit_student_id"],
                     "outcome": account_config["_outcome"], "post_attempts": account_config["_post_attempts"],
                     "confirmed": account_config["_confirmed"], "detail": detail})

    write_account_summary(rows)
    if failures:
        raise RuntimeError(
            "%d of %d cookie account checks failed." % (len(failures), len(cookies))
        )
    return total_found


def run_once():
    config = load_cloud_config()
    has_manual_trigger = config.get("force_check") or config.get("notice_text") or config.get("direct_punch_url")
    if not is_inside_china_time_window() and not has_manual_trigger:
        write_audit_event(config, "run_skipped", reason="outside_daily_window")
        print("Outside 07:50-18:00 China time window. Skipping.")
        return
    if not should_run_for_notice(config):
        write_audit_event(config, "run_skipped", reason="notice_expired")
        return 0

    return check_all_cookies(config)


def run_watch():
    config = load_cloud_config()
    write_audit_event(config, "run_started")
    has_manual_trigger = config.get("force_check") or config.get("notice_text") or config.get("direct_punch_url")
    if config.get("paused") and not has_manual_trigger and not config.get("class_window_gate"):
        write_audit_event(config, "run_skipped", reason="paused")
        print("BJMF_PAUSED is true. Skipping network check.")
        return
    if config.get("class_window_gate") and not has_manual_trigger:
        if not is_class_cycle_check_time():
            write_audit_event(config, "run_skipped", reason="outside_class_cycle_minute")
            print("BJMF_CLASS_WINDOW_GATE is true, but this is not a class-cycle check minute. Skipping network check.")
            return
        print("BJMF_CLASS_WINDOW_GATE allowed this class-cycle check.")

    if config.get("safe_single_check"):
        print("BJMF_SAFE_SINGLE_CHECK is true. Running one low-frequency check only.")
        return run_once()

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

        total_found = check_all_cookies(config)
        if total_found:
            print("Detected %d punch task(s). See per-account submission results above. Ending watch." % total_found)
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
