from cloud_config import is_inside_china_time_window, load_cloud_config
import random
import re

import requests
from bs4 import BeautifulSoup


REMEMBER_COOKIE_PATTERN = r"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d=[^;]+"


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

    gps_ids = re.findall(r"punch_gps\((\d+)\)", response.text)
    scan_ids = re.findall(r"punchcard_(\d+)", response.text)
    punch_ids = gps_ids + scan_ids
    print("Found GPS punch ids:", gps_ids)
    print("Found scan punch ids:", scan_ids)

    for punch_id in punch_ids:
        punch_url = "https://k8n.cn/student/punchs/course/" + class_id + "/" + punch_id
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


def run_once():
    if not is_inside_china_time_window():
        print("Outside 07:50-18:00 China time window. Skipping.")
        return

    config = load_cloud_config()
    for cookie in config["cookie"]:
        check_one_cookie(config, cookie)


if __name__ == "__main__":
    run_once()
