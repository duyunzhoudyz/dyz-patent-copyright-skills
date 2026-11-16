"""港湾记录整理器 v1.3 WSGI；仅提供函数，不启动服务器。"""

import json
from urllib.parse import parse_qsl

from core import InputError, convert

MAX_BODY_BYTES = 65536


def respond(start_response, status, body, content_type, extra=()):
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body)))]
    start_response(status, headers + list(extra))
    return [body]


def error_response(start_response, status, code, extra=()):
    body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    return respond(start_response, status, body, "application/json", extra)


def application(environ, start_response):
    """POST /convert：WSGI environ由调用者构造；无鉴权或网络入口。"""
    if environ.get("PATH_INFO") != "/convert":
        return error_response(start_response, "404 Not Found", "not_found")
    if environ.get("REQUEST_METHOD") != "POST":
        return error_response(start_response, "405 Method Not Allowed", "method_not_allowed",
                              [("Allow", "POST")])
    query = environ.get("QUERY_STRING", "")
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
    except ValueError:
        return error_response(start_response, "400 Bad Request", "invalid_query")
    options = dict(pairs)
    if len(options) != len(pairs) or any(key not in {"strict", "sort_by_id"}
                                      or value not in {"0", "1"} for key, value in pairs):
        return error_response(start_response, "400 Bad Request", "invalid_query")
    strict = options.get("strict", "0") == "1"
    sort_by_id = options.get("sort_by_id", "0") == "1"
    content_type = environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return error_response(start_response, "415 Unsupported Media Type", "invalid_content_type")
    try:
        length = int(environ.get("CONTENT_LENGTH", ""))
    except (TypeError, ValueError):
        return error_response(start_response, "400 Bad Request", "invalid_length")
    if length <= 0:
        return error_response(start_response, "400 Bad Request", "invalid_length")
    if length > MAX_BODY_BYTES:
        return error_response(start_response, "413 Payload Too Large", "payload_too_large")
    stream = environ.get("wsgi.input")
    if stream is None:
        return error_response(start_response, "400 Bad Request", "missing_body")
    try:
        raw = stream.read(length)
    except (OSError, ValueError):
        return error_response(start_response, "400 Bad Request", "body_read_error")
    if not isinstance(raw, bytes) or len(raw) != length:
        return error_response(start_response, "400 Bad Request", "body_length_mismatch")
    try:
        text, _ = convert(raw, strict=strict, sort_by_id=sort_by_id)
    except InputError as error:
        status = "400 Bad Request" if str(error) == "invalid_json" else "422 Unprocessable Entity"
        return error_response(start_response, status, str(error))
    return respond(start_response, "200 OK", text.encode("utf-8"), "text/csv; charset=utf-8")
