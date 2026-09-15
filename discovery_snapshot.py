"""Non-executable, value-redacted schemas of already-fetched failure pages.

No HTTP, JavaScript evaluation, raw HTML, input values, or string literals.
These samples are diagnostic data, never input to attendance submission.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from bs4 import BeautifulSoup
from audit_log import CHINA_TZ, sanitize, write_audit_event

MAX_HTML = 262144
MAX_NODES = 160
MAX_SCRIPTS = 8
MAX_BYTES = 262144
ROUTE_WORDS = set("student course punchs punchw punchcard punchscan attendance start api assets js css login scan qr gps".split())
TAGS = set("html head body div span a button form input select option textarea label script template noscript p ul li i b strong img canvas meta link table tr td section main nav".split())
CLASSES = set("wrapper page page-content vue-loading card card-body row btn btn-primary punch-demo punch-tabs punch-tab is-active punch-card punch-card--primary punch-card--success punch-card--muted punch-status punch-meta punch-action punch-info-badge punch-success-info".split())


def identifier(value, config):
    """Retain schema names only, with dynamic numbers and known secrets removed."""
    value = str(value)
    if not re.fullmatch(r"[@:]?[A-Za-z_$][A-Za-z0-9_$.:@-]{0,63}", value):
        return "<field>"
    if sanitize(value, config) != value:
        return "<field>"
    return re.sub(r"\d+", "<number>", value)


def url_shape(value, config):
    try:
        parsed = urlsplit(value)
        parts = []
        for part in parsed.path.split("/")[:16]:
            if not part:
                continue
            part = unquote(part)
            parts.append(part if part in ROUTE_WORDS else "<number>" if part.isdigit()
                         else "<asset>.js" if part.endswith(".js") else "<segment>")
        return {"origin": "same_origin" if not parsed.netloc or parsed.hostname == "k8n.cn" else "external",
                "path_shape": "/".join(parts),
                "query_keys": sorted({identifier(k, config) for k, _ in parse_qsl(parsed.query, keep_blank_values=True)})[:24],
                "fragment_present": bool(parsed.fragment)}
    except ValueError:
        return {"origin": "unrecognized"}


def data_shape(value, config, depth=0):
    if depth >= 3:
        return {"type": "nested", "truncated": True}
    if isinstance(value, dict):
        return {"type": "object", "fields": {identifier(k, config): data_shape(v, config, depth + 1)
                for k, v in list(value.items())[:12]}, "truncated": len(value) > 12}
    if isinstance(value, list):
        return {"type": "array", "item": data_shape(value[0], config, depth + 1) if value else None}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    # Never retain scalar values, even short tokens or human-readable names.
    return {"type": "string"}


def script_shape(source, config):
    """Lex strings/comments away; report call/property names, not source code."""
    truncated = len(source) > 32768
    source = source[:32768]
    code = []
    keys = set()
    urls = []
    embedded = []
    i = 0
    while i < len(source):
        if source.startswith("//", i):
            end = source.find("\n", i + 2)
            i = len(source) if end < 0 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = len(source) if end < 0 else end + 2
        elif source[i] in "\"'`":
            quote, start = source[i], i + 1
            i += 1
            while i < len(source) and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            literal = source[start:i]
            i = min(len(source), i + 1)
            if quote == '"':
                try:
                    literal = json.loads(source[start - 1:i])
                except ValueError:
                    pass
            if quote != "`" and len(embedded) < 8 and len(literal) <= 8192:
                try:
                    data = json.loads(literal)
                    if isinstance(data, (dict, list)):
                        embedded.append(data_shape(data, config))
                except (ValueError, RecursionError):
                    pass
            if quote != "`" and source[i:].lstrip().startswith(":"):
                keys.add(identifier(literal, config))
            elif quote != "`" and literal.startswith(("/", "https://", "http://")) and len(urls) < 8:
                urls.append(url_shape(literal, config))
            code.append(" ")
        else:
            code.append(source[i])
            i += 1
    code = "".join(code)
    keys.update(identifier(k, config) for k in re.findall(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*:", code))
    calls = {identifier(k, config) for k in re.findall(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(", code)}
    calls.difference_update({"if", "for", "while", "switch", "catch", "function"})
    return {"calls": sorted(calls)[:32], "property_names": sorted(keys)[:32], "url_shapes": urls, "embedded_data": embedded,
            "truncated": truncated or len(calls) > 32 or len(keys) > 32}


def attribute_shape(name, value, config):
    text = " ".join(str(v) for v in value) if isinstance(value, list) else str(value)
    if name == "class":
        return {"classes": sorted({v if v in CLASSES else "<class>" for v in text.split()})[:16]}
    if name == "name":
        return {"field_name": identifier(text, config)}
    if name in ("type", "method"):
        allowed = {"hidden", "text", "password", "submit", "button", "post", "get", "application/json", "text/javascript", "module"}
        return {"kind": text.lower() if text.lower() in allowed else "<value>"}
    if name in ("href", "src", "action", "data-url", "data-href", "data-action"):
        if text.lower().startswith("javascript:"):
            return {"javascript": script_shape(text, config)}
        return {"url": url_shape(text, config)}
    if name.startswith(("on", "@", ":", "v-")):
        return {"javascript": script_shape(text, config)}
    if len(text) <= 8192:
        try:
            return {"data": data_shape(json.loads(text), config)}
        except (ValueError, RecursionError):
            pass
    return {"type": "string"}  # Includes hidden input values and opaque IDs.


def build_snapshot(html, config, page, status):
    soup = BeautifulSoup(html[:MAX_HTML], "html.parser")
    tags = soup.find_all(True)
    indices = {id(tag): index for index, tag in enumerate(tags)}
    ordered = sorted(tags, key=lambda t: 0 if t.name in ("a", "button", "form", "input") else 1)
    nodes = []
    for tag in ordered[:MAX_NODES]:
        node = {"index": indices[id(tag)], "parent": indices.get(id(tag.parent)),
                "tag": tag.name if tag.name in TAGS else "other",
                "attributes": {identifier(k, config): attribute_shape(k, v, config) for k, v in list(tag.attrs.items())[:16]}}
        nodes.append(node)
    scripts = soup.find_all("script")
    scripts = sorted(scripts, key=lambda t: 0 if re.search(r"punch|scan|attendance|qrcode", str(t), re.I) else 1)
    script_records = []
    for tag in scripts[:MAX_SCRIPTS]:
        record = {"node_index": indices[id(tag)]}
        if tag.get("src"):
            record["external_src"] = url_shape(tag["src"], config)
        else:
            text = tag.string or tag.get_text()
            try:
                record["data"] = data_shape(json.loads(text[:32768]), config)
            except (ValueError, RecursionError):
                record["javascript"] = script_shape(text, config)
        script_records.append(record)
    return {"schema_version": 1, "reason": "missing_punch_id", "page": page, "account": config.get("_audit_account_number", 0),
            "time_china": datetime.now(CHINA_TZ).isoformat(timespec="seconds"), "http_status": status,
            "html_sha256": hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest(),
            "redaction": "No raw HTML, visible text, literal values, credentials or executable scripts. Schema names only.",
            "node_count": len(tags), "script_count": len(scripts), "nodes": nodes, "scripts": script_records,
            "truncated": (len(html) > MAX_HTML or len(tags) > MAX_NODES or len(scripts) > MAX_SCRIPTS
                          or any(len(t.attrs) > 16 for t in ordered[:MAX_NODES]))}


def capture_discovery_snapshot(config, response, label):
    directory = config.get("discovery_snapshot_dir", "")
    if not directory:
        return
    page = {"/punchs?op=ing": "active_list", "/punchs": "fallback_list"}.get(label, "other")
    # All filenames use trusted local enums/counters, never URLs or student IDs.
    account = int(config.get("_audit_account_number", 0))
    path = Path(directory) / ("account-%d-%s.json" % (account, page))
    try:
        if path.exists():
            return  # At most one sample per account/page in this job's workspace.
        record = build_snapshot(response.text, config, page, response.status_code)
        encoded = json.dumps(record, ensure_ascii=True, indent=2)
        while len(encoded.encode("utf-8")) > MAX_BYTES:
            record["truncated"] = True
            record["nodes"] = record["nodes"][:len(record["nodes"]) // 2]
            record["scripts"] = record["scripts"][:len(record["scripts"]) // 2]
            encoded = json.dumps(record, ensure_ascii=True, indent=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        write_audit_event(config, "discovery_snapshot_saved", file=path.name, page=page,
                          node_count=len(record["nodes"]), script_count=len(record["scripts"]), truncated=record["truncated"])
    except Exception as exc:
        # Diagnostics must not change account outcomes or prevent later accounts.
        # Exception messages/paths may contain secrets, so log only the type.
        write_audit_event(config, "discovery_snapshot_error", page=page, error_type=type(exc).__name__)
