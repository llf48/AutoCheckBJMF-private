"""Shared, credential-redacted evidence for cloud and local executions."""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

CHINA_TZ = timezone(timedelta(hours=8))


def sanitize(value, config=None):
    if isinstance(value, dict):
        return {str(key): sanitize(item, config) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item, config) for item in value]
    if not isinstance(value, str):
        return value
    cookies = (config or {}).get("cookie", [])
    if isinstance(cookies, str):
        cookies = [cookies]
    for cookie in cookies:
        for secret in (cookie, unquote(cookie), *unquote(cookie).split("|")[1:]):
            if len(secret) >= 4:
                value = value.replace(secret, "<redacted>")
    value = re.sub(r"remember_student_[A-Za-z0-9_]+=[^;\s]+", "<redacted-cookie>", value)
    value = re.sub(r"([?&][^=&#\s]+)=([^&#\s]*)", r"\1=<redacted>", value)
    value = re.sub(r"[A-Za-z0-9_-]{24,}", "<redacted-token>", value)
    return value.replace("\r", " ").replace("\n", " ")[:240]


def write_audit_event(config, event, **fields):
    entrypoint = Path(config.get("_audit_entrypoint", Path(__file__).with_name("cloud_check.py")))
    record = {
        "time_china": datetime.now(CHINA_TZ).isoformat(timespec="milliseconds"),
        "event": event,
        "source": config.get("_audit_source") or ("github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local_cloud"),
        "entrypoint": entrypoint.name,
        "pid": os.getpid(),
    }
    if config.get("_audit_entrypoint"):
        record["script_path"] = str(entrypoint.resolve())
    for source, target in (("_audit_account_number", "account"), ("_audit_student_id", "student_id"),
                           ("github_run_id", "github_run_id"), ("github_run_attempt", "run_attempt"), ("github_sha", "revision")):
        if config.get(source) is not None and config.get(source) != "":
            record[target] = config[source]
    if "revision" not in record and entrypoint.is_file():
        record["entrypoint_sha256"] = hashlib.sha256(entrypoint.read_bytes()).hexdigest()
    controlled = {"reason", "error_type", "outcome", "submission_status", "verification_scope", "html_sha256"}
    record.update({key: value if key in controlled else sanitize(value, config) for key, value in fields.items()})
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    print("BJMF_AUDIT " + serialized, flush=True)
    if config.get("audit_log_path"):
        try:
            with open(config["audit_log_path"], "a", encoding="utf-8") as stream:
                stream.write(serialized + "\n")
        except OSError:
            print("Audit file unavailable; the event above is retained in console logs.", flush=True)


def write_account_summary(rows):
    labels = {"already_signed": "检查前已签到", "submitted_confirmed": "提交已确认", "no_task": "没有进行中的任务",
              "needs_punch_url": "缺少任务ID，需要有效签到链接", "submission_unknown": "已尝试提交，结果未确认",
              "submission_rejected": "服务器拒绝提交", "check_failed": "检查失败", "partial_failure": "部分任务成功，另有失败",
              "dry_run": "仅检测，未提交", "checked": "检查结束", "cooldown": "账号冷却，本轮不再访问",
              "cooldown_wait": "冷却保护中，未访问平台", "cooldown_state_error": "冷却状态读写异常，需检查",
              "login_required": "需要重新登录", "unrecognized_page": "页面异常，不能据此认定Cookie过期",
              "server_already_signed": "提交时服务器告知已签到，并非本次新增签到"}
    lines = ["", "### 各账号签到结果", "", "| 账号 | 用户ID | 结果 | POST尝试次数 | 已确认次数 | 详情 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        detail = str(row.get("detail", "")).replace("|", "/").replace("\n", " ")
        outcome = row["outcome"] + " — " + labels.get(row["outcome"], row["outcome"])
        lines.append("| {account} | {student_id} | {outcome} | {post_attempts} | {confirmed} | {detail} |".format(**dict(row, outcome=outcome, detail=detail)))
    lines.extend(["", "“检查前已签到”不能证明由本次运行完成；实际提交见 POST 及服务器响应记录。",
                  "复核只匹配本次任务。服务器已明确确认成功后，复核暂不可用不会改写为签到失败。",
                  "工作流失败可能只涉及其中一个账号，各账号的结果以表格为准。", ""])
    text = "\n".join(lines)
    print(text, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(text)
        except OSError:
            print("GitHub summary unavailable; per-account results are retained above.", flush=True)
