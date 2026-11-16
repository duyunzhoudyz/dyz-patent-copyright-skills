"""港湾记录整理器 v1.3：原创合成核心；沿用项目NC许可。"""

import csv
import io
import json

VERSION = "1.3"
FIELDS = ("id", "label", "value")
MAX_RECORDS = 1000


class InputError(ValueError):
    """只携带固定错误类别，不回显用户记录。"""


def decode_payload(raw):
    """UTF-8 JSON只解码，不在此决定字段是否合法。"""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InputError("invalid_json") from error


def validate_records(records, strict=False):
    """v1.3始终拒绝重复ID；strict还拒绝额外字段。"""
    if not isinstance(records, list):
        raise InputError("records_must_be_array")
    if len(records) > MAX_RECORDS:
        raise InputError("too_many_records")
    cleaned = []
    seen_ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise InputError("record_must_be_object")
        if not all(field in record for field in FIELDS):
            raise InputError("missing_field")
        if strict and set(record) != set(FIELDS):
            raise InputError("unknown_field")
        record_id, label, value = (record[field] for field in FIELDS)
        if not isinstance(record_id, str) or not record_id.strip():
            raise InputError("invalid_id")
        if not isinstance(label, str) or not label.strip():
            raise InputError("invalid_label")
        try:
            (record_id + label).encode("utf-8")
        except UnicodeEncodeError as error:
            raise InputError("invalid_text_encoding") from error
        if type(value) is not int or value < 0:
            raise InputError("invalid_value")
        if record_id in seen_ids:
            raise InputError("duplicate_id")
        seen_ids.add(record_id)
        cleaned.append({"id": record_id, "label": label, "value": value})
    return cleaned


def render_csv(records):
    """输出固定列和LF换行；引号、逗号等由csv模块转义。"""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def convert(raw, strict=False, sort_by_id=False):
    """返回CSV正文与记录数；可选按id的Unicode字符序排序。"""
    records = validate_records(decode_payload(raw), strict=strict)
    if sort_by_id:
        records = sorted(records, key=lambda record: record["id"])
    return render_csv(records), len(records)
