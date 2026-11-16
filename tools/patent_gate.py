"""专利最终正文的保守验收门禁；只解析明确句式，不调用模型。

类型化成员、采样/用途、能力、禁止/恢复、单条件句及单一父项从属为支持子集。复杂句式、
未给出的依据或未覆盖文字阻断交付，不将有限检查称为自然语言或法律认证。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .core import ContractError, canonical_bytes, digest, require, safe_path, sha256_bytes, strict_json_loads, write_new_json
from .fidelity import MAX_ATOMS, MAX_LOGIC_WORK, _compare

VERSION = "2.0"
MAX_BYTES = 500_000
MAX_CLAUSES = 256
HEADINGS = {"权利要求书", "权利要求", "独立权利要求", "从属权利要求", "说明书", "技术领域", "背景技术",
            "发明内容", "具体实施方式", "摘要", "附图说明", "发明名称"}
NOTICE = "合成示例；内部工作稿，待专业审阅，不得据此提交或外发。"
UNCERTAIN = re.compile(r"未知|未给(?:出|定)?|未(?:记载|说明|提供|确认|核实)|尚不明确|待(?:确认|核实|补证)|可能|假设|推测|建议|拟议|是否|不作限定|[？?]")
COMPLEX = re.compile(r"除非|否则|当且仅当|至少|至多|仅当|或者|以及|(?<!所)有时")
NEGATION = re.compile(r"并非|并不|不是|不|未|无|非|禁止|不得")
CONDITIONAL = re.compile(r"只有|仅在|一旦|如果|若|当|才|则|即可|必然|时|之后|以后|须|必须")
CLAIM = re.compile(r"^(\d{1,3})\s*[.．、]\s*(.+)$")
PARENT = re.compile(r"^根据权利要求\s*(\d+)\s*所述(?:的)?(?P<label>[^，,：:]{1,40})[，,：:]\s*(?:其特征在于[，,：:]\s*)?")
FRAGMENTS = re.compile(r"[^。；;\n！？!?：:]+[。；;！？!?：:]*")
COMBINATION = re.compile(r"^(?:同一方案|同一实施方式|原创合成(?P<device>\S{1,12})仅有这一种结构)[：:]")
QUALIFIER = re.compile(r"所述|上述|该(?=装置|系统|设备|方案)")
UNCERTAIN_SCOPE = re.compile(r"上述|前述|该规则|本规则")
MEMBERSHIP = re.compile(r"^(?P<owner>.+?)(?:包括|具有)(?P<members>.+)$")


def _plain(text):
    return re.sub(r"\s+", " ", text).strip().strip("。；;.!！?？，,：:")


def _atom(text, aliases=()):
    """仅处理指示词和在原文中唯一的对象名称，不删除否定、数量或模态。"""
    text = QUALIFIER.sub("", _plain(text).replace("**", ""))
    if aliases:
        replacements = {name: full for short, full in aliases for name in (short, full)}
        pattern = "|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True))
        text = re.sub(pattern, lambda match: replacements[match[0]], text)
    return text.strip()


def _context(text):
    """指代只来自显式声明；不同修饰或数量的对象不能靠简称混成一个。"""
    aliases, references, devices = [], {}, set()
    for short in ("传感器", "止挡"):
        names = set(re.findall(rf"(?:温度|压力|湿度|位置|固定|活动|另一|第二)?{short}", text))
        full = names - {short}
        if len(full) == 1 and not re.search(rf"另(?:一|一个)|多个{short}", text):
            aliases.append((short, next(iter(full))))
    for match in re.finditer(r"一种([^，,。；;：:]{1,24})(?:[，,])?包括", text):
        devices.add(match[1])
    for match in re.finditer(r"原创合成([^：:。；;]{1,12})仅有这一种结构", text):
        devices.add(match[1])
    if len(devices) == 1 and next(iter(devices)).endswith("装置"):
        aliases.append(("装置", next(iter(devices))))
    for match in re.finditer(r"(?:包括|具有)([^，,。；;：:]+)", text):
        for member in re.split(r"、|和|及", match[1]):
            name = re.sub(r"^(?:一个|两个|一条|两条|三条)(?:平行)?", "", member)
            references.setdefault(name, set()).add(member)
    holes = sorted(set(_atom(match[1], aliases) + "上孔" for match in
                       re.finditer(r"([^，,。；;：:\s]+?)上有一个孔", text)))
    measurements = set(re.findall(r"(温度|压力|湿度|位置)传感器", text))
    return {"aliases": aliases, "devices": sorted(devices),
            "references": {key: next(iter(values)) for key, values in references.items() if len(values) == 1},
            "holes": holes if len(holes) == 2 else [],
            "measure": next(iter(measurements)) if len(measurements) == 1 else None}


def _members(text, aliases):
    return sorted(_atom(part, aliases) for part in re.split(r"、|和|及", text) if part.strip())


def _thresholds(text):
    return sorted(re.split(r"、|和|及", text))


def _relation(kind, **values):
    return {"kind": kind, **values}


def _expression(text, aliases=(), context=None):
    """保留关系类型及角色；只有条件关系才编码为有限逻辑公式。"""
    context = context or {}
    text = _atom(text, aliases)
    text = re.sub(r"[，,]?并且$", "", text)
    text = re.sub(r"^(?:本实施方式的|一种)", "", text)
    text = re.sub(r"[，,]\s*其特征在于$", "", text)
    if not text or UNCERTAIN.search(text) or COMPLEX.search(text) or "并且" in text:
        return None
    if text.startswith("并非"):
        proposition = _expression(text[2:], aliases, context)
        return _relation("negation", proposition=proposition) if proposition is not None else None
    topic = re.fullmatch(r"本(?:工作稿|发明)涉及([^，,]+)", text)
    if topic:
        return _relation("topic", topic=topic[1])
    narrative = re.fullmatch(r"本(?:工作稿|发明)以([^，,]+?)之间的关系为说明对象", text)
    if narrative:
        return _relation("topics", topics=_members(narrative[1], aliases))
    fault = re.fullmatch(r"(?:并)?说明([^，,]+?)及([^，,]+?)后的控制约束", text)
    path = re.fullmatch(r"故障路径按([^，,]+?)及([^，,]+?)两个时段说明", text)
    if fault or path:
        first, second = (fault or path).groups()
        return _relation("fault_overview", fault=first, recovery=second)
    control = re.fullmatch(r"([^，,]+?)以([^，,]+?)与(两个|三个)阈值的比较结果控制([^，,]+)", text)
    if control:
        return _relation("control_overview", device=control[1], value=control[2],
                         threshold_count={"两个": 2, "三个": 3}[control[3]], output=control[4])
    normal = re.fullmatch(r"(?:在正常判断中|对于正常判断的两个条件)[，,](.+)", text)
    if normal:
        parts = _segments(normal[1], aliases, context)
        expressions = [_expression(value, aliases, context) for _, value in parts]
        if all(isinstance(value, dict) and "implies" in value for value in expressions):
            return {"all": expressions} if len(expressions) > 1 else expressions[0]
        return None
    # 逗号只在明确的关系内部有意义，不让宽泛的成员/小于正则吞进后一句。
    recovery = re.fullmatch(r"([^，,]+?)后[，,]?须收到([^，,]+?)才能([^，,]+)", text)
    if recovery:
        return _relation("recovery", event=recovery[1], confirmation=recovery[2], result=recovery[3])
    prohibition = re.fullmatch(r"(?:当)?([^，,]+?)时[，,]?禁止([^，,]+)", text)
    if prohibition:
        return _relation("prohibition", condition=prohibition[1], action=prohibition[2])
    capability = re.fullmatch(r"(?:在([^，,]+?)的状态下[，,])?([^，,]+?)可同时穿过([^，,]+?)[，,]?以阻止([^，,]+)", text)
    if capability:
        guard, subject, objects, purpose = capability.groups()
        if objects == "两孔" and context.get("holes"):
            objects = context["holes"]
        else:
            objects = _members(objects.replace("上的孔", "上孔"), aliases)
        return _relation("capability", subject=subject, action="穿过", objects=objects,
                         simultaneous=True, purpose=purpose, guard=guard or "")
    necessity = re.fullmatch(r"(.+?)是(.+?)的必要条件", text)
    if necessity:
        condition, result = necessity.groups()
        temporal = re.fullmatch(r"(.+?)后(.+)", result)
        if temporal:
            return _relation("recovery", event=temporal[1], confirmation=condition, result=temporal[2])
        if condition != result:
            return {"implies": [result, condition]}
        return None
    state_necessity = re.fullmatch(r"(.+?)与(.+?)的抵靠状态[，,]是(.+?)所必需的状态", text)
    if state_necessity:
        return {"implies": [state_necessity[3], state_necessity[1] + "抵靠" + state_necessity[2]]}
    patterns = (
        (r"只有(?:当)?(.+?)时[，,]?(.+?)才(.+)", True),
        (r"只有(.+?)[，,]?才(.+)", True),
        (r"仅在(.+?)[，,]?才(.+)", True),
        (r"仅在(.+?)[，,](.+)", True),
        (r"(?:如果|若)(.+?)[，,](?:则)?(.+)", False),
        (r"一旦(.+?)[，,](?:就|即)(.+)", False),
        (r"(?:当)?(.+?)时[，,]?(.+)", False),
    )
    for pattern, reverse in patterns:
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        parts = match.groups()
        left, right = (parts[0], parts[1] + parts[2]) if len(parts) == 3 else parts
        if reverse and left.endswith("时"):
            left = left[:-1]
        if (not left or not right or left == right or CONDITIONAL.search(left) or CONDITIONAL.search(right)
                or re.search(r"[，,]", left + right)):
            return None
        if context.get("measure") and re.match(r"^(?:低于|高于)[A-Za-z]", left):
            left = context["measure"] + left
        return {"implies": [right, left] if reverse else [left, right]}
    correspond = re.fullmatch(r"(.+?)对应(.+)", text)
    if correspond and not re.search(r"[，,]", text):
        return {"implies": list(correspond.groups())}
    membership = re.fullmatch(r"(.+?)[，,]?包括([^，,]+)", text)
    if membership:
        owner, members = membership.groups()
        return _relation("membership", owner=owner, members=_members(members, aliases))
    if re.search(r"[，,]|并且", text):
        return None
    order = re.fullmatch(r"(?:低阈值([A-Za-z]+)与高阈值([A-Za-z]+)满足)?([A-Za-z]+)小于([A-Za-z]+)(?:的关系)?", text)
    if order:
        low, high, left, right = order.groups()
        if low and (low, high) != (left, right):
            return None
        return _relation("order", left=left, operator="<", right=right)
    match = MEMBERSHIP.fullmatch(text)
    if match:
        owner, members = match.groups()
        return _relation("membership", owner=owner, members=_members(members, aliases))
    shared_holes = re.fullmatch(r"(.+?)上和(.+?)上各有一个孔", text)
    if shared_holes:
        return {"all": [_relation("membership", owner=owner + "上", members=["一个孔"])
                        for owner in shared_holes.groups()]}
    hole = re.fullmatch(r"(.+?)上有(.+孔)", text)
    if hole:
        return _relation("membership", owner=hole[1] + "上", members=[hole[2]])
    purpose = re.fullmatch(r"(.+?)用于(.+)", text)
    if purpose:
        return _relation("purpose", subject=purpose[1], action=purpose[2])
    sampling = re.fullmatch(r"(.+?)(?:进行)?(每[^，,。；;]{1,12})?采样(温度|压力|湿度|位置)?", text)
    if sampling and not CONDITIONAL.search(sampling[1]):
        subject = sampling[1].removesuffix("进行")
        return _relation("sampling", subject=subject, period=sampling[2] or "",
                         measure=sampling[3] or context.get("measure") or "")
    comparison = re.fullmatch(r"(.+?)将(.+?)与(.+?)比较", text)
    supplied = re.fullmatch(r"(.+?)供(.+?)与(.+?)比较", text)
    if comparison or supplied:
        subject, value, thresholds = comparison.groups() if comparison else (supplied[2], supplied[1], supplied[3])
        if value == (context.get("measure") or "") + "采样值":
            value = "采样值"
        return _relation("comparison", subject=subject, value=value, thresholds=_thresholds(thresholds))
    motion = re.fullmatch(r"(.+?)沿(.+?)移动", text)
    if motion:
        target = context.get("references", {}).get(motion[2], motion[2])
        return _relation("motion", subject=motion[1], path=target)
    if CONDITIONAL.search(text):
        return None
    return text


def _atoms(expr):
    if isinstance(expr, str):
        return {expr}
    if isinstance(expr, dict) and "kind" in expr:
        # 角色封装为一个不可拆的原子；能力的目的不是已经发生的事实。
        return {canonical_bytes(expr).decode("utf-8")}
    return set().union(*(_atoms(item) for values in expr.values() for item in values))


def _views(expr):
    """只允许有方向的保义投影，不把关系中的实体或动作导出为孤立事实。"""
    if isinstance(expr, dict) and "all" in expr:
        return [view for item in expr["all"] for view in _views(item)]
    result = [expr]
    if isinstance(expr, dict) and expr.get("kind") == "membership":
        result += [_relation("membership", owner=expr["owner"], members=[member]) for member in expr["members"]]
    if isinstance(expr, dict) and expr.get("kind") == "sampling":
        result += [{**expr, "period": ""}, _relation("purpose", subject=expr["subject"],
                                                     action="采样" + expr["measure"])]
    return result


def _segments(fragment, aliases, context):
    """整句条件优先；只在完整识别失败时重新解析同级并列项。"""
    if (_expression(fragment, aliases, context) is not None or not re.search(r"[，,]|并且", fragment)
            or "并且" in fragment and CONDITIONAL.search(fragment)):
        return [(0, fragment)]
    parts = list(re.finditer(r".+?(?:[，,](?:并且)?|并且|$)", fragment))
    result, index = [], 0
    while index < len(parts):
        part = parts[index]
        value = part[0]
        # 保留“只有A时，B才C”和能力目的中的逗号，不合并独立的前后条件。
        if index + 1 < len(parts) and (re.match(r"\s*(?:只有|仅在|若|如果|一旦|当)", value)
                                      or re.search(r"时[，,]$|可同时", value)):
            combined = fragment[part.start():parts[index + 1].end()]
            if _expression(combined, aliases, context) is not None:
                result.append((part.start(), combined))
                index += 2
                continue
        result.append((part.start(), value))
        index += 1
    return result


def _clauses(text, artifact_id, issues, *, original=False, aliases=(), context=None, coverage=None):
    result, claims, current, offset = [], [], None, 0
    context = context or _context(text)
    coverage = coverage if coverage is not None else []
    scope, scope_counter = None, 0
    paragraph = 0
    for mark in re.finditer(r"[？?]+", text):
        issues.append({"code": "original_uncertainty_marker" if original else "final_clause_unparsed_or_uncertain",
                       "artifact_id": artifact_id, "start": mark.start(), "end": mark.end(), "quote": mark[0]})
    for line in text.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        clean = raw.strip().replace("**", "")
        title = re.sub(r"^#{1,6}\s+", "", clean).strip()
        structural = title in HEADINGS or (clean.startswith("#") and title in context.get("devices", []))
        if structural or raw.strip() == NOTICE:
            coverage.append({"artifact_id": artifact_id, "start": offset, "end": offset + len(raw),
                             "quote": raw, "state": "structure" if structural else "notice"})
            current = None
            offset += len(line)
            continue
        if not clean:
            paragraph += 1
            scope = None
            offset += len(line)
            continue
        content_start = len(raw) - len(raw.lstrip())
        if clean.startswith("#"):
            content_start += len(re.match(r"#{1,6}\s*", raw[content_start:])[0])
        content = raw[content_start:]
        number = CLAIM.match(content.replace("**", ""))
        if number:
            identity, claim_text = int(number[1]), number[2]
            content_start = raw.find(claim_text) if claim_text in raw else content_start
            content = raw[content_start:]
            independent = re.match(r"^一种(?:method|system|device|方法|系统|装置|设备)方案[，,]", content)
            if independent:
                content_start += len(independent[0])
                content = raw[content_start:]
            parent = PARENT.match(content)
            parents = []
            if parent and parent["label"] not in {"另一", "其他", "任一", "任意", "多个"}:
                parents = [int(parent[1])]
                content_start += len(parent[0])
                content = raw[content_start:]
            elif "根据权利要求" in content:
                issues.append({"code": "claim_reference_unsupported", "artifact_id": artifact_id,
                               "claim_id": identity, "start": offset, "end": offset + len(raw)})
            current = {"id": identity, "artifact_id": artifact_id, "parent_ids": parents, "clause_indexes": []}
            claims.append(current)
            coverage.append({"artifact_id": artifact_id, "start": offset, "end": offset + content_start,
                             "quote": raw[:content_start], "state": "claim_prefix", "claim_id": identity})
        elif "根据权利要求" in clean and not original:
            issues.append({"code": "claim_number_or_reference_unsupported", "artifact_id": artifact_id,
                           "start": offset, "end": offset + len(raw)})
        for match in FRAGMENTS.finditer(content):
            combination = COMBINATION.fullmatch(match[0].strip()) if original else None
            prefix = _plain(match[0])
            if combination:
                scope_counter += 1
                scope = f"scope-{scope_counter}"
                coverage.append({"artifact_id": artifact_id, "start": offset + content_start + match.start(),
                                 "end": offset + content_start + match.end(), "quote": match[0],
                                 "state": "structure", "scope_id": scope})
                continue
            if original and re.match(r"^(?:实施(?:方式|例)[一二三四\d]+|(?:另一|其他|其它)(?:个)?(?:方案|实施方式|结构))", prefix):
                scope_counter += 1
                scope = f"alternative-{scope_counter}"
            if original and re.match(r"一种[^，,。；;：:]+(?:[，,])?包括", prefix):
                scope_counter += 1
                scope = f"device-{scope_counter}"
            for local, fragment in _segments(match[0], aliases, context):
                if not _plain(fragment):
                    continue
                start = offset + content_start + match.start() + local
                value = _plain(fragment)
                # 原文的材料声明不是技术事实，也不能为最终技术标题提供豁免。
                contextual = original and (UNCERTAIN.search(value) or value in {"也没有其他方案", "不是真实申请"}
                                           or value.startswith("以下全部为原创合成练习材料")
                                           or value.startswith("没有尺寸"))
                if contextual:
                    coverage.append({"artifact_id": artifact_id, "start": start, "end": start + len(fragment),
                                     "quote": fragment, "state": "unknown" if UNCERTAIN.search(value) else "source_constraint",
                                     "scope_id": scope})
                expr = None if contextual else _expression(fragment, aliases, context)
                row = {"artifact_id": artifact_id, "start": start, "end": start + len(fragment),
                       "quote": fragment, "expression": expr, "paragraph": paragraph,
                       "combined": scope is not None, "scope_id": scope,
                       "contextual": bool(contextual), "claim_id": current["id"] if current else None}
                result.append(row)
                if current is not None:
                    current["clause_indexes"].append(len(result) - 1)
                require(len(result) <= MAX_CLAUSES, "final_text_clause_budget")
        offset += len(line)
    # 编号和从属引语也是已解释的正文结构；未进入任何行的字符不能静默消失。
    intervals = [(row["start"], row["end"]) for row in result]
    intervals += [(row["start"], row["end"]) for row in coverage if row["artifact_id"] == artifact_id]
    occupied = bytearray(len(text))
    for start, end in intervals:
        occupied[start:end] = b"\x01" * (end - start)
    for match in re.finditer(r"[^\s]+", text):
        for position in range(match.start(), match.end()):
            if not occupied[position]:
                # 单字符排版标点不带技术语义；问号已单独记为阻断。
                state = "punctuation" if text[position] in "。；;，,：:.！!？?*#" else "uncovered"
                coverage.append({"artifact_id": artifact_id, "start": position, "end": position + 1,
                                 "quote": text[position], "state": state})
                if state == "uncovered":
                    issues.append({"code": "original_text_uncovered" if original else "final_text_uncovered",
                                   "artifact_id": artifact_id, "start": position, "end": position + 1})
    return result, claims


def _overview_supported(query, expressions):
    """概括句必须由同一范围的具名关系支撑，不能仅因是叙述语而豁免。"""
    typed = [item for item in expressions if isinstance(item, dict) and "kind" in item]
    kind = query["kind"]
    if kind == "topic":
        return any(item["kind"] == "membership" and item["owner"].endswith("装置")
                   and query["topic"] == item["owner"][:-2] for item in typed)
    if kind == "fault_overview":
        return (any(item["kind"] == "prohibition" and item["condition"] == query["fault"] for item in typed)
                and any(item["kind"] == "recovery" and item["event"] == query["recovery"] for item in typed))
    samples = [item for item in typed if item["kind"] == "sampling"]
    comparisons = [item for item in typed if item["kind"] == "comparison"]
    controls = [item["implies"] for item in expressions if isinstance(item, dict) and "implies" in item]
    if kind == "topics":
        topics = {item["measure"] + "采样" for item in samples if item["measure"]}
        if any(all(re.fullmatch(r"(?:低|高)?阈值[A-Za-z]+", value) for value in item["thresholds"])
               for item in comparisons):
            topics.add("阈值比较")
        for _, action in controls:
            match = re.fullmatch(r"(?:打开|关闭)(.+)", action)
            if match:
                topics.add(match[1] + "控制")
        return bool(query["topics"]) and set(query["topics"]) <= topics
    if kind == "control_overview":
        for comparison in comparisons:
            if len(comparison["thresholds"]) != query["threshold_count"]:
                continue
            if not any(sample["measure"] + "采样值" == query["value"] and comparison["value"] == "采样值"
                       for sample in samples):
                continue
            membership = any(item["kind"] == "membership" and item["owner"] == query["device"]
                             and {comparison["subject"], query["output"]} <= set(item["members"]) for item in typed)
            low = [re.fullmatch(r"低阈值([A-Za-z]+)", item) for item in comparison["thresholds"]]
            high = [re.fullmatch(r"高阈值([A-Za-z]+)", item) for item in comparison["thresholds"]]
            low = [match[1] for match in low if match]
            high = [match[1] for match in high if match]
            if len(low) != 1 or len(high) != 1:
                continue
            for sample in samples:
                measure = sample["measure"]
                if measure + "采样值" != query["value"]:
                    continue
                member_sampling = any(item["kind"] == "membership" and item["owner"] == query["device"]
                                      and sample["subject"] in item["members"] for item in typed)
                rules = ([measure + "低于" + low[0], "关闭" + query["output"]],
                         [measure + "高于" + high[0], "打开" + query["output"]])
                if membership and member_sampling and measure and all(rule in controls for rule in rules):
                    return True
    return False


def _proof(query, expressions, remaining):
    eligible = [view for expr in expressions if expr is not None for view in _views(expr)]
    if isinstance(query, dict) and "all" in query:
        proofs = [_proof(item, eligible, remaining) for item in query["all"]]
        return {"relation": "entailed" if all(p["relation"] == "entailed" and not p.get("vacuous") for p in proofs)
                else "undetermined", "vacuous": False}
    if isinstance(query, dict) and query.get("kind") == "membership" and len(query["members"]) != len(set(query["members"])):
        return {"relation": "undetermined", "vacuous": False}
    if query in eligible:
        return {"relation": "entailed", "vacuous": False}
    if isinstance(query, dict) and query.get("kind") == "capability" and query.get("guard"):
        if any(isinstance(item, dict) and item.get("kind") == "capability" and not item["guard"]
               and {**query, "guard": ""} == item for item in eligible):
            guards = query["guard"].split("且")
            conditions = [item["implies"] for item in eligible if isinstance(item, dict) and "implies" in item]
            if len(guards) == 2 and any(set(pair) == set(guards) for pair in conditions):
                return {"relation": "entailed", "vacuous": False}
    if isinstance(query, dict) and query.get("kind") in {"topic", "topics", "fault_overview", "control_overview"}:
        return {"relation": "entailed" if _overview_supported(query, eligible) else "undetermined", "vacuous": False}
    if isinstance(query, dict) and query.get("kind") == "membership":
        if len(query["members"]) != len(set(query["members"])):
            return {"relation": "undetermined", "vacuous": False}
        members = {member for item in eligible if isinstance(item, dict) and item.get("kind") == "membership"
                   and item["owner"] == query["owner"] for member in item["members"]}
        return {"relation": "entailed" if set(query["members"]) <= members else "undetermined"}
    if not (isinstance(query, dict) and "implies" in query):
        return {"relation": "undetermined", "vacuous": False}
    # 事实共现不能证明新的条件。只把实际条件关系交给既有有限比较器。
    relations = [expr for expr in eligible if isinstance(expr, dict) and "implies" in expr]
    connected, selected = set(_atoms(query)), []
    while True:
        found = [expr for expr in relations if expr not in selected and _atoms(expr) & connected]
        if not found:
            break
        for expr in found:
            selected.append(expr)
            connected.update(_atoms(expr))
        require(len(connected) <= MAX_ATOMS, "final_text_logic_atom_budget")
    if not selected:
        return {"relation": "undetermined", "vacuous": False}
    return _compare(selected, query, {atom: {} for atom in connected}, remaining)


def _unsupported_reason(expr, originals):
    if isinstance(expr, dict) and "implies" in expr:
        if any(isinstance(item, dict) and item.get("implies") == list(reversed(expr["implies"]))
               for original in originals for item in original["expressions"]):
            return "condition_direction_changed"
    if isinstance(expr, dict) and "kind" in expr:
        similar = [item for original in originals for item in original["expressions"]
                   if isinstance(item, dict) and item.get("kind") == expr["kind"]]
        if expr["kind"] == "order" and similar:
            return "comparison_direction_or_operand_changed"
        if expr["kind"] == "purpose":
            return "purpose_not_supported"
        if expr["kind"] == "capability":
            return "capability_scope_or_modality_changed"
        if expr["kind"] == "membership":
            if any(item["owner"] == expr["owner"] for item in similar):
                return "member_quantity_or_property_not_supported"
            return "member_ownership_not_supported"
        if expr["kind"] in {"topic", "topics", "fault_overview", "control_overview"}:
            return "overview_relations_not_supported_together"
        if expr["kind"] in {"comparison", "recovery", "prohibition", "sampling", "motion"}:
            return expr["kind"] + "_roles_or_constraints_not_supported"
    return "final_clause_not_supported"


def _audit(texts, sources):
    require(isinstance(texts, dict) and bool(texts), "final_texts_required")
    require(isinstance(sources, list) and 0 < len(sources) <= 64, "final_original_sources_required")
    require(len(canonical_bytes(texts)) <= MAX_BYTES, "final_text_byte_budget")
    require(len(canonical_bytes(sources)) <= MAX_BYTES, "final_source_byte_budget")
    issues, originals, identities, source_coverage = [], [], set(), []
    for source in sources:
        require(isinstance(source, dict), "final_source_object_required")
        for key in ("id", "version", "text", "sha256"):
            require(isinstance(source.get(key), str) and bool(source[key].strip()), "final_source_fields_required")
        require(source.get("role") == "original", "final_source_original_required")
        require(source["id"] not in identities, "final_source_duplicate")
        identities.add(source["id"])
        require(source["sha256"] == sha256_bytes(source["text"].encode("utf-8")), "final_source_hash_mismatch")
        source_issues = []
        context = _context(source["text"])
        clauses, source_claims = _clauses(source["text"], source["id"], source_issues, original=True,
                                          aliases=context["aliases"], context=context, coverage=source_coverage)
        if any(row["parent_ids"] for row in source_claims) or "根据权利要求" in source["text"]:
            # 原文从属范围不能拆成独立事实；该上下文尚未支持时整份拒绝。
            source_issues.append({"code": "original_claim_dependency_unsupported"})
            issues.append({"code": "original_claim_dependency_unsupported", "document_id": source["id"]})
        # 未解析原句可能含否定、例外或冲突，不能挑出邻近肯定句作为独立证明。
        expressions = [row["expression"] for row in clauses]
        if any(isinstance(item, dict) and item.get("kind") == "negation"
               and _proof(item["proposition"], [other for other in expressions if other is not item],
                          [MAX_LOGIC_WORK])["relation"] == "entailed" for item in expressions):
            issues.append({"code": "original_statements_conflict", "document_id": source["id"]})
        if source_issues or any(row["expression"] is None and not row["contextual"] for row in clauses):
            issues.append({"code": "original_text_not_fully_parsed", "document_id": source["id"]})
        # 回指的不确定性可能跨段撤销前文；范围无法唯一确定时不择取肯定句。
        unresolved_scope = any(row["contextual"] and UNCERTAIN_SCOPE.search(row["quote"]) for row in clauses)
        groups = {}
        for row in clauses:
            key = row["scope_id"] or f"clause-{row['start']}"
            groups.setdefault(key, []).append(row)
        for key, group in groups.items():
            supported = [row["expression"] for row in group if row["expression"] is not None]
            derivations = []
            if key.startswith("scope-") and len(context["devices"]) == 1:
                # 单一结构中明确的部件主体可回述为整机成员；不把成员的属性当作新部件。
                owners = sorted({expr.get("owner", expr.get("subject")) for expr in supported
                                 if isinstance(expr, dict) and expr.get("kind") in {"membership", "motion", "capability"}
                                 and not expr.get("owner", "").endswith("上")
                                 and not re.search(r"外部|外置|配套|外接|另一|其他|其它", expr.get("owner", expr.get("subject", "")))})
                if owners:
                    member_relation = _relation("membership", owner=context["devices"][0], members=owners)
                    supported.append(member_relation)
                    derivations.append({"rule": "single_structure_component_subjects", "expression": member_relation,
                                        "citations": [_location(row) for row in group if row["expression"] is not None]})
            if any(isinstance(expr, dict) and expr.get("kind") == "negation"
                   and _proof(expr["proposition"], [other for other in supported if other is not expr],
                              [MAX_LOGIC_WORK])["relation"] == "entailed" for expr in supported):
                issues.append({"code": "original_statements_conflict", "document_id": source["id"], "scope_id": key})
                supported = []
            originals.append({"document": source, "paragraph": group[0]["paragraph"], "scope_id": key,
                              "clauses": group, "combined": bool(group[0]["scope_id"]),
                              "expressions": [] if unresolved_scope else supported,
                              "derivations": derivations, "context": context})
    all_clauses, all_claims, remaining, by_id, coverage = [], [], [MAX_LOGIC_WORK], {}, []
    claim_groups, current_claim_group = [], []
    for artifact_id, text in texts.items():
        require(isinstance(artifact_id, str) and artifact_id.strip() and isinstance(text, str) and text.strip(),
                "final_artifact_text_required")
        # 仅合并各原文共同认可的唯一名称；不会从另一份原文借用歧义别名。
        contexts = [item["context"] for item in originals]
        context = {"devices": sorted({name for item in contexts for name in item["devices"]})}
        for key in ("measure", "holes"):
            values = [item[key] for item in contexts]
            context[key] = values[0] if values and all(value == values[0] for value in values) else None
        aliases = sorted(set.intersection(*(set(item["aliases"]) for item in contexts))) if contexts else []
        context["references"] = {key: value for item in contexts for key, value in item["references"].items()
                                 if all(other["references"].get(key) == value for other in contexts)}
        clauses, claims = _clauses(text, artifact_id, issues, aliases=aliases, context=context, coverage=coverage)
        if not clauses and text.strip() != NOTICE:
            issues.append({"code": "artifact_technical_text_missing", "artifact_id": artifact_id})
        require(len(all_clauses) + len(clauses) <= MAX_CLAUSES, "final_text_clause_budget")
        for row in clauses:
            row["support"] = []
            expr = row["expression"]
            if expr is None:
                issues.append({"code": "final_clause_unparsed_or_uncertain", **_location(row)})
                continue
            for original in originals:
                proof = _proof(expr, original["expressions"], remaining)
                if proof["relation"] == "entailed" and not proof.get("vacuous", False):
                    relevant = [item for item in original["clauses"] if item["expression"] is not None
                                and (_proof(expr, [item["expression"]], remaining)["relation"] == "entailed"
                                     or isinstance(expr, dict) and "implies" in expr
                                     and _atoms(expr) & _atoms(item["expression"]))]
                    if not relevant:
                        relevant = [item for item in original["clauses"] if item["expression"] is not None]
                    row["support"].append({"document_id": original["document"]["id"],
                                           "paragraph": original["paragraph"], "scope_id": original["scope_id"],
                                           "combined": original["combined"],
                                           "citations": [_location(item) for item in relevant],
                                           "derivations": original["derivations"]})
            if not row["support"]:
                issues.append({"code": _unsupported_reason(expr, originals), **_location(row)})
        # 不同完整工件（例如答复与替换稿）可各自从1编号；拆成块的连续权项仍共享父项。
        if claims and claims[0]["id"] == 1 and by_id:
            claim_groups.append(current_claim_group)
            current_claim_group, by_id = [], {}
        for claim in claims:
            current_claim_group.append(claim["id"])
            if claim["id"] in by_id:
                issues.append({"code": "claim_number_duplicate", "artifact_id": artifact_id, "claim_id": claim["id"]})
            parent = claim["parent_ids"][0] if claim["parent_ids"] else None
            own = [clauses[i] for i in claim["clause_indexes"]]
            inherited = by_id.get(parent, {}).get("all_clauses", []) if parent is not None else []
            if parent is not None and (parent not in by_id or parent >= claim["id"]):
                issues.append({"code": "claim_parent_missing_or_forward", "artifact_id": artifact_id,
                               "claim_id": claim["id"], "parent_id": parent})
            if not own:
                issues.append({"code": "claim_no_limitations", "artifact_id": artifact_id, "claim_id": claim["id"]})
            if len(own) > 1 and parent is None:
                scopes = [{(s["document_id"], s["scope_id"]) for s in row["support"] if s["combined"]}
                          for row in own]
                if not set.intersection(*scopes):
                    issues.append({"code": "claim_combination_not_supported_together", "artifact_id": artifact_id,
                                   "claim_id": claim["id"]})
            if parent is not None and inherited:
                prior = [row["expression"] for row in inherited if row["expression"] is not None]
                additional = False
                for row in own:
                    expr = row["expression"]
                    if expr is None:
                        continue
                    implied = _proof(expr, prior, remaining)["relation"] == "entailed"
                    additional |= not implied
                if not additional:
                    issues.append({"code": "dependent_claim_no_additional_limitation", "artifact_id": artifact_id,
                                   "claim_id": claim["id"], "parent_id": parent})
                scopes = [{(s["document_id"], s["scope_id"]) for s in row["support"] if s["combined"]}
                          for row in inherited + own]
                if scopes and not set.intersection(*scopes):
                    issues.append({"code": "dependent_combination_not_supported_together", "artifact_id": artifact_id,
                                   "claim_id": claim["id"], "parent_id": parent})
            claim["all_clauses"] = inherited + own
            by_id[claim["id"]] = claim
            all_claims.append({key: claim[key] for key in ("artifact_id", "id", "parent_ids")})
        all_clauses.extend(clauses)
    claim_groups.append(current_claim_group)
    if any(group != list(range(1, len(group) + 1)) for group in claim_groups):
        issues.append({"code": "claim_numbering_gap_or_order"})
    if not all_clauses:
        issues.append({"code": "final_technical_text_missing"})
    input_binding = {"input_hash": digest({"texts": texts, "sources": sources}),
                     "text_bindings": {key: sha256_bytes(value.encode("utf-8")) for key, value in texts.items()},
                     "source_bindings": [{key: row[key] for key in ("id", "version", "sha256")} for row in sources]}
    return {"contract_version": VERSION, "status": "blocked" if issues else "checked",
            "input_binding": input_binding, "input_hash": input_binding["input_hash"],
            "text_bindings": {key: sha256_bytes(value.encode("utf-8")) for key, value in texts.items()},
            "source_bindings": [{key: row[key] for key in ("id", "version", "sha256")} for row in sources],
            "clauses": all_clauses, "claims": all_claims, "issues": issues,
            "context_coverage": coverage, "source_coverage": source_coverage,
            "coverage_ledger": coverage + [{**_location(row), "state": "supported" if row["support"] else
                                           "unparsed" if row["expression"] is None else "unsupported"}
                                          for row in all_clauses],
            "logic_work_units": MAX_LOGIC_WORK - remaining[0],
            "scope": "bounded_typed_chinese_relations_and_single_parent_claims",
            "coverage": "complete_supplied_text_in_supported_subset" if not issues else "incomplete_or_rejected",
            "dependent_addition_check": "typed_relations_and_finite_implication_only",
            "source_authenticity": "not_verified", "natural_language_verified": False,
            "professional_review": "not_performed", "external_action": "not_performed"}


def _location(row):
    return {key: row[key] for key in ("artifact_id", "start", "end", "quote")}


def audit_final_text(texts: dict[str, str], sources: list[dict]) -> dict:
    """重读实际字符生成验收报告；不采信调用者公式、分类或历史passed。"""
    try:
        return _audit(texts, sources)
    except (ContractError, UnicodeError, RecursionError, TypeError, KeyError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ContractError) else "final_gate_input_invalid"
        return {"contract_version": VERSION, "status": "blocked", "issues": [{"code": code}],
                "claims": [], "clauses": [], "input_binding": {},
                "coverage": "not_checked", "natural_language_verified": False,
                "professional_review": "not_performed", "external_action": "not_performed"}


def require_final_text(texts: dict[str, str], sources: list[dict]) -> dict:
    """失败直接抛错，调用者必须在写出最终正文／候选清单前调用。"""
    report = audit_final_text(texts, sources)
    if report["status"] != "checked":
        error = ContractError("final_text_gate_blocked")
        error.report = report
        raise error
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地合成专利正文门禁；失败只写报告，不写交付稿")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--root", default=".")
    parser.add_argument("--manuscript", required=True, help="实际待交付UTF-8正文文件")
    parser.add_argument("--sources", required=True, help="含sensitivity和documents的原文JSON")
    parser.add_argument("--report", required=True, help="新的门禁报告JSON")
    parser.add_argument("--deliver", help="仅验收通过时创建的正文副本")
    args = parser.parse_args(argv)
    try:
        require(args.synthetic, "synthetic_declaration_required")
        manuscript = safe_path(args.root, args.manuscript)
        sources_path = safe_path(args.root, args.sources)
        require(manuscript.stat().st_size <= MAX_BYTES and sources_path.stat().st_size <= MAX_BYTES,
                "final_gate_file_budget")
        raw = manuscript.read_bytes()
        report_path = safe_path(args.root, args.report, must_exist=False)
        require(report_path not in {manuscript, sources_path}, "final_gate_output_collision")
        payload = strict_json_loads(sources_path.read_text(encoding="utf-8"))
        require(payload.get("sensitivity") == "synthetic", "synthetic_only")
        target = safe_path(args.root, args.deliver, must_exist=False) if args.deliver else None
        if target is not None:
            require(target not in {manuscript, sources_path, report_path}, "final_gate_output_collision")
            require(not target.exists() and target.parent.is_dir(), "final_delivery_target_invalid")
        report = audit_final_text({"manuscript": raw.decode("utf-8")}, payload.get("documents"))
        write_new_json(args.root, args.report, report)
        if report["status"] != "checked":
            print("final_text_gate_blocked", file=sys.stderr)
            return 2
        if target is not None:
            with target.open("xb") as stream:
                stream.write(raw)
        print("final_text_checked_not_professional_approval")
        return 0
    except (ContractError, OSError, UnicodeError, TypeError, ValueError):
        print("final_text_gate_rejected", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
