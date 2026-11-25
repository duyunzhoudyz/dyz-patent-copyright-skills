"""专利最终正文的保守验收门禁；只解析明确句式，不调用模型。

类型化成员、采样/用途、能力、禁止/恢复、单条件句及单一父项从属为支持子集。复杂句式、
未给出的依据或未覆盖文字阻断交付，不将有限检查称为自然语言或法律认证。
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from .core import ContractError, canonical_bytes, digest, require, safe_path, sha256_bytes, strict_json_loads, write_new_json
from .fidelity import MAX_ATOMS, MAX_LOGIC_WORK, _check_nesting, _compare

VERSION = "2.1"
MAX_BYTES = 500_000
MAX_CLAUSES = 256
MAX_ANCHOR_DEPTH = 16
MAX_ANCHOR_PAYLOAD = 512
ANCHOR_START = re.compile(r"\[(FORMULA|TABLE|FIG):")
ANCHOR_ID = re.compile(r"[A-Za-z0-9_.-]{1,40}(?=[:\]])")
MATH_SCRIPT = re.compile(r"[_^]\{[^{}]*\}")
HEADINGS = {"权利要求书", "权利要求", "独立权利要求", "从属权利要求", "说明书", "技术领域", "背景技术",
            "发明内容", "具体实施方式", "摘要", "附图说明", "发明名称", "description", "detailed description",
            "summary", "summary of the invention", "background", "background of the invention", "technical field",
            "abstract", "brief description of the drawings", "title", "field of the invention"}
CLAIM_HEADINGS = {"权利要求书", "权利要求", "独立权利要求", "从属权利要求", "claims", "independent claims",
                  "dependent claims", "what is claimed is", "what is claimed is:"}
HEADINGS.update(CLAIM_HEADINGS)
NOTICE = "合成示例；内部工作稿，待专业审阅，不得据此提交或外发。"
UNCERTAIN = re.compile(r"未知|未给(?:出|定)?|未(?:记载|说明|提供|确认|核实)|尚不明确|待(?:确认|核实|补证)|可能|假设|推测|建议|拟议|是否|不作限定|[？?]")
COMPLEX = re.compile(r"除非|否则|当且仅当|至少|至多|仅当|或者|以及|(?<!所)有时")
NEGATION = re.compile(r"并非|并不|不是|不|未|无|非|禁止|不得|排除|避免|弃用|禁用")
CONDITIONAL = re.compile(r"只有|仅在|一旦|如果|若|当|才|则|即可|必然|时|之后|以后|须|必须")
EN_UNCERTAIN = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:unknown|tbd|todo|fixme|to\s+confirm|unconfirmed|unspecified|pending|may|might|perhaps|probably|optional|optionally|assumed|proposed|unclear|unverified)(?![A-Za-z0-9_])")
EN_COMPLEX = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:if\s+and\s+only\s+if|not\s+only\s+if|unless|otherwise|except|at\s+least|at\s+most|whereas|wherein|provided\s+that|or)(?![A-Za-z0-9_])")
EN_NEGATION = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:not|never|without|no|cannot|(?:can|won|don|doesn|didn|isn|aren|wasn|weren|shouldn|wouldn|couldn|haven|hasn|hadn|mustn)['’]t"
    r"|prohibited|forbidden|neither|nor|exclud(?:e|es|ed|ing)|deprecat(?:e|es|ed|ing)|rather\s+than|instead\s+of|avoid(?:s|ed|ing)?)(?![A-Za-z0-9_])")
EN_CONDITIONAL = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:if|once|when|whenever|unless|only\s+if|until|after|before|must)(?![A-Za-z0-9_])")
CLAIM = re.compile(r"^(\d{1,3})\s*[.．、]\s*(.+)$")
PARENT = re.compile(r"^(?:根据|如|依据)?权利要求\s*(\d+)\s*所述(?:的)?(?P<label>[^，,：:]{1,40})[，,：:]\s*(?:其特征在于[，,：:]\s*)?")
CN_PARENT_REF = re.compile(
    r"(?:根据|如|依据)权利要求|权利要求\s*\d+|权利要求\s*[一二三四五六七八九十]+"
    r"|(?:上一|前一项|以上|任一|任意|前述|上述|多项)[^。；;\n]{0,8}权利要求"
)
EN_PARENT = re.compile(
    r"(?i)^(?:the\s+)?(?:method|system|apparatus|device|controller|assembly|structure)\s+"
    r"(?:of|according\s+to|as\s+claimed\s+in|as\s+recited\s+in|as\s+defined\s+in)\s+claim\s+(\d+)"
    r"(?!\s*(?:(?:and|or|to|through|thru|plus)\b|[-–—/&+;~]|,\s*(?:\d+|claims?\b|and\b|or\b)))\s*,?\s*(?:wherein\s+|further\s+)?"
)
EN_PARENT_REF = re.compile(
    r"(?i)\b(?:claims?\s+\d+|(?:any|either|each|the|one)\s+(?:(?:one|more)\s+)?(?:of\s+)?(?:the\s+)?(?:preceding|previous|prior|earlier|above|foregoing)\s+claims?"
    r"|(?:preceding|previous|prior|earlier|above|foregoing)\s+claims?|any\s+(?:one\s+)?of\s+(?:the\s+)?claims?)\b"
)
# 在锚点遮罩上切句以保留偏移；编号 Eq. 标签中的点不作为句末。
FRAGMENTS = re.compile(
    r"(?:[^。；;\n！？!?：:.]|\.(?!\s|$)|(?<=(?i:\bEq))\.(?=[ \t]+[(（]?[ \t]*\d))+"
    r"(?:[。；;！？!?：:]|\.(?=\s|$))*")
COMBINATION = re.compile(r"^(?:同一方案|同一实施方式|原创合成(?P<device>\S{1,12})仅有这一种结构)[：:]")
_NONFIRST_NUMBER = r"0*(?:[2-9]\d*|1\d+)(?!\d)"
_NONFIRST_ORDINAL = rf"(?:[二三四五六七八九十百零][一二三四五六七八九十百零]*|一[百千][一二三四五六七八九十百零]*|{_NONFIRST_NUMBER})"
ALTERNATIVE_SCOPE = re.compile(
    rf"(?i)(?:实施(?:方式|例)\s*[（(]?\s*{_NONFIRST_ORDINAL}|第{_NONFIRST_ORDINAL}(?:个)?实施(?:方式|例)"
    r"|(?:另一|其他|其它|替代|备选)(?:个)?(?:实施(?:方式|例)|方案|结构)"
    r"|\b(?:alternative|other|another|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+(?:embodiment|example|design)s?\b"
    rf"|(?<!\bfirst\s)\b(?:embodiment|example)\b\s*[（(]?\s*(?:{_NONFIRST_NUMBER}|[ivx]{{2,}}|(?-i:[A-HJ-Z])"
    r"|[a-hj-z](?=\s*(?:[）)：:。.,，；;！？!?]|$)))\b)")
BACKGROUND_SCOPE = re.compile(
    r"(?i)(?:(?:技术)?背景|现有技术|已有技术|对比(?:实施)?例|比较(?:实施)?例|对照(?:实施)?例"
    r"|(?:technical\s+)?background\b|(?:the\s+)?prior[ -]art\b|comparative\s+(?:example|embodiment)\b)")
SECTION_NUMBER = re.compile(r"^(?:(?:\d+(?:[.．]\d+)*|[一二三四五六七八九十]+)(?:[.．、]\s*|\s+)|[（(][一二三四五六七八九十\d]+[）)]\s*)")
_CN_FORMULA_OBJECT = r"公式|算式|方程|表达式|计算式|关系式"
FORMULA_SCOPE_CUE = re.compile(rf"(?i){_CN_FORMULA_OBJECT}|(?:上述|前述|[该此本])\s*式|\b(?:formulas?|equations?|expressions?)\b")
FORMULA_FORWARD_CUE = re.compile(r"(?i)以下|下列|如下|\b(?:following|below)\b")
FORMULA_BACKREF = re.compile(rf"(?i)上述|该|此|前述|本(?=\s*(?:{_CN_FORMULA_OBJECT}|式))|\b(?:the\s+above|said|this|that|these|those)\b")
FORMULA_COLLECTIVE = re.compile(
    rf"(?i)(?:全部|所有|两(?:个|条|项|式)|各(?:个|条|项|式))[^，,。；;：:]{{0,8}}(?:{_CN_FORMULA_OBJECT}|式)"
    rf"|(?:{_CN_FORMULA_OBJECT}|式)(?:\s*均|\s*都|\s*全部)"
    r"|\b(?:formulas|equations|expressions)\b|\b(?:all|both)\s+(?:of\s+)?(?:the\s+)?(?:above|said|these|those)\b"
)
FORMULA_REPLACEMENT = re.compile(r"(?i)[，,]\s*(?:改用|而改用|(?:and\s+)?(?:instead\s+use|use\s+instead))$")
FORMULA_LABEL = re.compile(
    r"(?i)(?:计算关系|数学关系|关系式|公式|算式|方程|表达式)(?:为|是)?"
    r"|(?:the\s+)?(?:formula|equation|expression|calculation)\s+is"
    r"|公式\s*[一二三四五六七八九十]+"
    r"|(?:公式|式|formula|equation|eq\.?)\s*(?:\d+|\(\s*\d+\s*\)|（\s*\d+\s*）)")
QUALIFIER = re.compile(r"所述|上述|该(?=装置|系统|设备|方案)")
UNCERTAIN_SCOPE = re.compile(r"上述|前述|该规则|本规则")
MEMBERSHIP = re.compile(r"^(?P<owner>.+?)(?:包括|具有)(?P<members>.+)$")


def _anchors(line):
    """每个保留前缀必须有合法 ID、深度和闭合；不回退为普通说明文字。"""
    pos = 0
    while token := ANCHOR_START.search(line, pos):
        identity = ANCHOR_ID.match(line, token.end())
        require(identity is not None, "formula_anchor_malformed")
        pos = identity.end()
        payload = None
        if line[pos] == ":":
            begin = pos + 1
            depth = 1
            for pos in range(begin, min(len(line), begin + MAX_ANCHOR_PAYLOAD + 1)):
                if line[pos] == "[":
                    depth += 1
                    require(depth <= MAX_ANCHOR_DEPTH, "formula_anchor_nesting_exceeded")
                    require(not ANCHOR_START.match(line, pos), "formula_anchor_malformed")
                elif line[pos] == "]":
                    depth -= 1
                    if not depth:
                        break
            require(not depth and pos > begin, "formula_anchor_malformed")
            payload = line[begin:pos]
        pos += 1
        yield token.start(), pos, token[1], identity[0], payload


def _anchor_mask(line, anchors):
    parts, pos = [], 0
    for start, end, *_ in anchors:
        parts.extend((line[pos:start], " " * (end - start)))
        pos = end
    parts.append(line[pos:])
    return "".join(parts)


def _anchor_relation(anchor):
    _, _, kind, identity, payload = anchor
    if kind == "FORMULA" and payload is not None:
        return _formula_content(identity, payload)
    return _relation("anchor", anchor_kind=kind, anchor_id=identity, anchor_payload=(payload or "").strip())


def _record_negated_formula(coverage, row, expression):
    if expression is not None:
        coverage.append({**_location(row), "state": "original_formula_negated", "expression": expression})


def _formula_key(expression):
    if isinstance(expression, dict) and (expression.get("kind") == "formula_content"
                                         or expression.get("anchor_kind") == "FORMULA"):
        return expression["anchor_id"], expression.get("structure_sha256")
    return None


def _format_free(text):
    return text if text.isascii() else "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


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


def _norm_en(text: str) -> str:
    """句首首字母大小写归一，同时保留技术代号（如 T1 / CPU / D1）的大小写。"""
    s = re.sub(r"\s+", " ", text).strip()
    if len(s) >= 2 and s[0].isupper() and (s[1].islower() or s[1] == " "):
        return s[0].lower() + s[1:]
    return s


def _formula_content(anchor_id, latex):
    from . import omml
    try:
        formula = omml.inspect_omml(omml.latex_to_omml_element(latex))
    except ContractError:
        return None
    if formula["valid"]:
        return _relation("formula_content", anchor_id=anchor_id, structure_sha256=formula["structure_sha256"])
    return None


def _is_bare_formula(value):
    # Math identifiers inside commands or grouped scripts are not English prose.
    value = value.strip().rstrip("。.;；").rstrip()
    if not re.search(r"[=<>_^\\]", value):
        return False
    prose = re.sub(r"\\[A-Za-z]+|(?<=\[)[A-Za-z]+(?=\])", "_", value)
    for _ in range(MAX_ANCHOR_DEPTH):
        prose, count = re.subn(r"\{[^{}]*\}", "_", prose)
        if not count:
            break
    return (not re.search(r"\b[A-Za-z]{2,}\b\s+[A-Za-z]|\b[A-Za-z]\b\s+[A-Za-z]{2,}\b", prose)
            and _formula_content(None, value) is not None)


def _expression(text, aliases=(), context=None):
    """保留关系类型及角色；只有条件关系才编码为有限逻辑公式。"""
    context = context or {}
    text = _atom(text, aliases)
    text = re.sub(r"[，,]?并且$", "", text)
    text = re.sub(r"^(?:本实施方式的|一种)", "", text)
    text = re.sub(r"[，,]\s*其特征在于$", "", text)
    prose = MATH_SCRIPT.sub(" ", text)
    # 有限英文技术句式子集：先于关系抽取拦截不确定/复杂/否定/嵌套条件，防误放行。
    if re.search(r"[A-Za-z]", text) and not re.search(r"[\u4e00-\u9fff]", text):
        en_low = text.strip()
        if not en_low or EN_UNCERTAIN.search(prose) or EN_COMPLEX.search(prose) or EN_NEGATION.search(prose):
            return None
        if EN_PARENT_REF.search(en_low):
            return None
        en_only_if_prefix = re.fullmatch(r"(?i)only if ([^,]+?),\s*(?:then\s+)?(.+)", en_low)
        if en_only_if_prefix:
            left, right = _norm_en(en_only_if_prefix[1]), _norm_en(en_only_if_prefix[2])
            if (left and right and left != right
                    and not EN_CONDITIONAL.search(MATH_SCRIPT.sub(" ", left))
                    and not EN_CONDITIONAL.search(MATH_SCRIPT.sub(" ", right))):
                return {"implies": [right, left]}
            return None
        en_only_if_infix = re.fullmatch(r"(?i)(.+?)\s+only if\s+(.+)", en_low)
        if en_only_if_infix:
            right, left = _norm_en(en_only_if_infix[1].rstrip(" ,")), _norm_en(en_only_if_infix[2].lstrip(" ,"))
            if (left and right and left != right
                    and not EN_CONDITIONAL.search(MATH_SCRIPT.sub(" ", left))
                    and not EN_CONDITIONAL.search(MATH_SCRIPT.sub(" ", right))):
                return {"implies": [right, left]}
            return None
        en_if = re.fullmatch(r"(?i)(?:if|once)\s+([^,]+?),\s*(?:then\s+)?(.+)", en_low)
        if en_if:
            left, right = _norm_en(en_if[1]), _norm_en(en_if[2])
            if (left and right and left != right
                    and not EN_CONDITIONAL.search(MATH_SCRIPT.sub(" ", left))
                    and not EN_CONDITIONAL.search(MATH_SCRIPT.sub(" ", right))):
                return {"implies": [left, right]}
            return None
        if EN_CONDITIONAL.search(prose):
            return None
        en_order = re.fullmatch(r"(?i)([A-Za-z][A-Za-z0-9_]*)\s+is\s+less\s+than\s+([A-Za-z][A-Za-z0-9_]*)", en_low)
        if en_order:
            return _relation("order", left=en_order[1], operator="<", right=en_order[2])
        en_purpose = re.fullmatch(r"(?i)(.+?)\s+is\s+configured\s+to\s+(.+)", en_low)
        if en_purpose:
            return _relation("purpose", subject=_norm_en(en_purpose[1]), action=_norm_en(en_purpose[2]))
        en_member = re.fullmatch(r"(?i)(.+?)\s+(?:comprises|includes)\s+(.+)", en_low)
        if en_member:
            # 仅当每项均以不定/计数限定词开头且不含介词短语或动词/分词限定时才拆分，防剥离后置修饰语或介词宾语！
            obj = en_member[2]
            raw_parts = [
                p.strip() for p in re.split(
                    r",\s*and\s+|,\s*|\s+and\s+(?=(?:a|an|one|two|three|first|second|plurality)\b)",
                    obj,
                ) if p.strip()
            ]
            det_re = re.compile(r"(?i)^(?:a|an|one|two|three|first|second|plurality)\b")
            prep_or_verb_re = re.compile(
                r"(?i)\b(?:of|in|on|at|to|for|with|by|from|between|into|through|under|over|near|around|against|upon|within|without"
                r"|above|below|across|along|inside|outside|beside|behind|beyond|via|per|than|that|which|where|whose"
                r"|made|held|set|built|cut|driven|bound|is|are|was|were|has|have|had|\w+(?:ing|ed))\b"
            )
            has_comma = "," in obj
            has_and = bool(re.search(r"(?i)(?:,\s*|\s+)and\s+", obj))
            if (len(raw_parts) > 1
                    and (not has_comma or has_and)
                    and all(det_re.match(p) and not prep_or_verb_re.search(p) for p in raw_parts)):
                items = [_norm_en(p) for p in raw_parts]
            else:
                items = [_norm_en(obj)]
            return _relation("membership", owner=_norm_en(en_member[1]), members=sorted(items))
        return _norm_en(en_low)
    if (not text or UNCERTAIN.search(text) or COMPLEX.search(text) or "并且" in text
            or (re.search(r"[A-Za-z]", prose)
                and (EN_UNCERTAIN.search(prose) or EN_NEGATION.search(prose)
                     or EN_COMPLEX.search(prose) or EN_CONDITIONAL.search(prose)))):
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
    """整句条件优先；只在完整识别失败且整句不含不确定/例外/否定/英文条件复杂词时重新解析同级并列项。"""
    prose = MATH_SCRIPT.sub(" ", fragment)
    has_ascii = bool(re.search(r"[A-Za-z]", prose))
    if (_expression(fragment, aliases, context) is not None
            or not re.search(r"[，,]|并且", fragment)
            or ("并且" in fragment and CONDITIONAL.search(fragment))
            or UNCERTAIN.search(fragment)
            or COMPLEX.search(fragment)
            or re.search(r"但|但是|然而|不过|仅限|除了|除外|并非|并不|不得|无|未|非|不(?!是真实申请)", fragment)
            or re.search(r"(?:[，,]|并且)[^。；;\n]*?禁止", fragment)
            or re.match(r"^\s*在[^，,。；;\n]{1,40}(?:状态|情况|条件|模式)下[，,]", fragment)
            or (has_ascii and (EN_UNCERTAIN.search(prose) or EN_COMPLEX.search(prose)
                               or EN_CONDITIONAL.search(prose) or EN_NEGATION.search(prose)))):
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
    raw_text, text = text, _format_free(text)
    result, claims, current, offset = [], [], None, 0
    context = context or _context(text)
    coverage = coverage if coverage is not None else []
    issue_start, coverage_start = len(issues), len(coverage)
    scope, scope_counter = None, 0
    excluded_level = None
    paragraph_excluded = dependent_formula = False
    restricted_formula = pending_formula = listed_formula = None
    recent_formulas = []
    after_claim_break = claims_section = description_section = False
    standalone_independent = False
    standalone_row = None
    paragraph = 0
    for mark in re.finditer(r"[？?]+", text):
        issues.append({"code": "original_uncertainty_marker" if original else "final_clause_unparsed_or_uncertain",
                       "artifact_id": artifact_id, "start": mark.start(), "end": mark.end(), "quote": mark[0]})
    for line in text.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        raw_anchors = list(_anchors(raw))
        clean = raw.strip().replace("**", "")
        heading = re.match(r"^(#{1,6})\s+", clean)
        title = clean[heading.end():].strip() if heading else clean
        section_title = SECTION_NUMBER.sub("", title)
        title_key = section_title.casefold()
        structural = title_key in HEADINGS or (heading and title in context.get("devices", []))
        if original and (heading or structural):
            level = len(heading[1]) if heading else 1
            if ALTERNATIVE_SCOPE.search(section_title) or BACKGROUND_SCOPE.search(section_title):
                excluded_level = level if excluded_level is None else min(level, excluded_level)
            elif excluded_level is not None and level <= excluded_level and title_key in HEADINGS:
                excluded_level = None
        if heading or structural:
            standalone_independent = title_key == "独立权利要求" and not claims_section
            current = scope = pending_formula = restricted_formula = listed_formula = None
            recent_formulas.clear()
            paragraph_excluded = dependent_formula = after_claim_break = False
        if structural or raw.strip() == NOTICE:
            coverage.append({"artifact_id": artifact_id, "start": offset, "end": offset + len(raw),
                             "quote": raw, "state": "structure" if structural else "notice"})
            if structural and (not claims_section or title_key in HEADINGS):
                claims_section = title_key in CLAIM_HEADINGS
                description_section = not claims_section
                after_claim_break = False
            offset += len(line)
            continue
        if not clean:
            paragraph += 1
            scope = None
            paragraph_excluded = dependent_formula = False
            restricted_formula = listed_formula = None
            after_claim_break |= current is not None
            current = None
            offset += len(line)
            continue
        content_start = len(raw) - len(raw.lstrip())
        if clean.startswith("#"):
            content_start += len(re.match(r"#{1,6}\s*", raw[content_start:])[0])
        content = raw[content_start:]
        visible = content.replace("**", "")
        number = CLAIM.match(visible) if not heading else None
        if number:
            after_claim_break = False
            if (scope or "").startswith("orig-claim-"):
                scope = None
                if not (pending_formula or listed_formula):
                    restricted_formula = None
            if claims_section:
                recent_formulas.clear()
            identity, claim_text = int(number[1]), number[2]
            prefix_end = number.start(2)
            independent = re.match(r"^一种(?:method|system|device|方法|系统|装置|设备)方案[，,]", claim_text)
            if independent:
                prefix_end += independent.end()
                claim_text = visible[prefix_end:]
            parent = PARENT.match(claim_text)
            en_parent = EN_PARENT.match(claim_text) if parent is None else None
            parents = []
            dependent_formula = bool(CN_PARENT_REF.search(claim_text) or EN_PARENT_REF.search(claim_text))
            if (parent
                    and "权利要求" not in parent["label"]
                    and not re.search(r"另一|其他|其它|任一|任意|多个|多项|或|至|到", parent["label"])
                    and not CN_PARENT_REF.search(claim_text[parent.end():])):
                parents = [int(parent[1])]
                prefix_end += parent.end()
            elif en_parent and not EN_PARENT_REF.search(claim_text[en_parent.end():]):
                parents = [int(en_parent[1])]
                prefix_end += en_parent.end()
            elif dependent_formula:
                issues.append({"code": "claim_reference_unsupported", "artifact_id": artifact_id,
                               "claim_id": identity, "start": offset, "end": offset + len(raw)})
            if visible != content and prefix_end < len(visible):
                positions = [item.start() for item in re.finditer(r"\*\*|.", content) if item[0] != "**"]
                content_start += positions[prefix_end]
            else:
                content_start += len(content) if prefix_end == len(visible) else prefix_end
            content = raw[content_start:]
            current = {"id": identity, "artifact_id": artifact_id, "parent_ids": parents, "clause_indexes": []}
            claims.append(current)
            if original and not parents:
                scope = f"orig-claim-{identity}"
            coverage.append({"artifact_id": artifact_id, "start": offset, "end": offset + content_start,
                             "quote": raw[:content_start], "state": "claim_prefix", "claim_id": identity})
        elif (CN_PARENT_REF.search(clean) or EN_PARENT_REF.search(clean)) and not original:
            issues.append({"code": "claim_number_or_reference_unsupported", "artifact_id": artifact_id,
                           "start": offset, "end": offset + len(raw)})
        anchor_matches = []
        for start, end, *anchor in raw_anchors:
            require(start >= content_start, "formula_anchor_in_structural_prefix")
            anchor_matches.append((start - content_start, end - content_start, *anchor))
        bare_formula = not anchor_matches and _is_bare_formula(content.strip())
        anchor_index = 0
        formula_intro = False
        for match in FRAGMENTS.finditer(_anchor_mask(content, anchor_matches)):
            literal = content[match.start():match.end()]
            anchors = []
            while anchor_index < len(anchor_matches) and anchor_matches[anchor_index][0] < match.end():
                anchors.append(anchor_matches[anchor_index])
                anchor_index += 1
            formulas = [anchor for anchor in anchors if anchor[2] == "FORMULA"]
            prose = MATH_SCRIPT.sub(" ", match[0]).replace("**", "")
            prefix = _plain(prose).strip()
            combination = COMBINATION.fullmatch(literal.strip()) if original else None
            if combination:
                scope_counter += 1
                scope = f"scope-{scope_counter}"
                recent_formulas.clear()
                pending_formula = listed_formula = None
                coverage.append({"artifact_id": artifact_id, "start": offset + content_start + match.start(),
                                 "end": offset + content_start + match.end(), "quote": literal,
                                 "state": "structure", "scope_id": scope})
                continue
            colon = prose.rstrip().endswith(("：", ":"))
            label = not prefix or FORMULA_LABEL.fullmatch(prefix)
            formula_item = bare_formula or (label and formulas and len(formulas) == len(anchors))
            label_only = label and prefix and not anchors
            carried = pending_formula or listed_formula
            # A colon can carry an exclusion across blank lines until its item arrives.
            if formula_item:
                listed_formula, pending_formula = carried, None
                formula_intro = False
            elif label_only and colon and carried:
                pending_formula = carried
            elif not label_only:
                carried = listed_formula = None
                if not formula_intro:
                    pending_formula = None
                if number:
                    recent_formulas.clear()
            source_constraint = bool(carried and label_only)
            formula_backref = replacement = False
            negative = cue = False
            if original and not bare_formula:
                if ALTERNATIVE_SCOPE.search(prefix):
                    scope_counter += 1
                    scope = f"alternative-{scope_counter}"
                    paragraph_excluded = True
                    recent_formulas.clear()
                    if colon and not formulas:
                        pending_formula = "excluded"
                        formula_intro = True
                if BACKGROUND_SCOPE.search(prefix):
                    paragraph_excluded = True
                    recent_formulas.clear()
                    if colon and not formulas:
                        pending_formula = "excluded"
                        formula_intro = True
                if re.match(r"一种[^，,。；;：:]+(?:[，,])?包括", prefix) and not (scope or "").startswith("orig-claim-"):
                    scope_counter += 1
                    scope = f"device-{scope_counter}"
                declaration = prefix.startswith("以下全部为原创合成练习材料") or prefix == "不是真实申请"
                negative = not declaration and (NEGATION.search(prose) or EN_NEGATION.search(prose))
                formula_cue = FORMULA_SCOPE_CUE.search(prose)
                cue = formula_cue or FORMULA_FORWARD_CUE.search(prose)
                formula_backref = bool(negative and formula_cue and FORMULA_BACKREF.search(prose)
                                       and not FORMULA_FORWARD_CUE.search(prose))
                if formula_backref:
                    targeted = (recent_formulas if FORMULA_COLLECTIVE.search(prose) else
                                next(([row] for row in reversed(recent_formulas) if row["expression"] is not None), []))
                    for prior in targeted:
                        _record_negated_formula(coverage, prior, prior["expression"])
                        prior.update(expression=None, contextual=True)
                    replacement = bool((len(anchors) == len(formulas) == 1 or (colon and not anchors))
                                       and FORMULA_REPLACEMENT.search(prefix))
                if negative and (cue or colon or formulas) and not replacement:
                    if colon and not formulas:
                        pending_formula = "negated"
                        # A colon with a forward cue may be followed by an inline explanation.
                        formula_intro = not formula_backref
                    elif not formula_backref or formulas:
                        restricted_formula = "negated"
                elif cue and (UNCERTAIN.search(prose) or EN_UNCERTAIN.search(prose)) and not restricted_formula:
                    restricted_formula = "uncertain"
                source_constraint |= declaration or bool(negative and (cue or colon or formulas) and not (formulas and replacement))
            excluded_formula = original and bool(formulas) and (
                excluded_level is not None or paragraph_excluded or dependent_formula or restricted_formula or carried)
            scoped_out = excluded_level is not None or paragraph_excluded or dependent_formula or carried == "excluded"
            if excluded_formula and not scoped_out and (restricted_formula == "negated" or carried == "negated"):
                for anchor in formulas:
                    a_start, a_end = anchor[:2]
                    base = offset + content_start
                    _record_negated_formula(coverage, {"artifact_id": artifact_id, "start": base + a_start,
                                                     "end": base + a_end, "quote": content[a_start:a_end]},
                                            _anchor_relation(anchor))
            segments = [(0, literal)] if bare_formula or anchors else _segments(literal, aliases, context)
            for local, fragment in segments:
                if not _plain(fragment):
                    continue
                start = offset + content_start + match.start() + local
                value = _plain(fragment)
                anchor = anchors[0] if len(anchors) == 1 and (not prefix or (formulas and (label or replacement))) else None
                if anchor is not None and prefix and _plain(content[anchor[1]:match.end()].replace("**", "")).strip():
                    anchor = None  # 只认可前置的中性公式标签，不忽略公式后的自然语言。
                # 原文的材料声明不是技术事实，也不能为最终技术标题提供豁免。
                words = prose if anchors else MATH_SCRIPT.sub(" ", value)
                is_uncertain_val = not bare_formula and bool(UNCERTAIN.search(words) or EN_UNCERTAIN.search(words))
                contextual = original and (bare_formula or excluded_formula or is_uncertain_val or source_constraint
                                           or value == "也没有其他方案"
                                           or value.startswith("没有尺寸"))
                formula_only_context = False
                if contextual or bare_formula:
                    expr = None
                elif anchor is not None:
                    expr = _anchor_relation(anchor)
                else:
                    expr = None if anchors else _expression(fragment, aliases, context)
                    if original and expr is None and negative and not cue and not re.search(r"[,，]", value):
                        contextual = formula_only_context = True
                if contextual:
                    coverage.append({"artifact_id": artifact_id, "start": start, "end": start + len(fragment),
                                     "quote": fragment, "state": ("formula_source_excluded" if bare_formula or excluded_formula
                                                                   else "unknown" if is_uncertain_val else "source_constraint"),
                                     "scope_id": scope})
                row = {"artifact_id": artifact_id, "start": start, "end": start + len(fragment),
                       "quote": fragment, "expression": expr, "paragraph": paragraph,
                       "combined": scope is not None, "scope_id": scope,
                       "contextual": bool(contextual), "claim_id": current["id"] if current else None}
                if formula_backref:
                    row["formula_backref"] = True
                if formula_only_context:
                    row["formula_only_context"] = True
                if original and formulas:
                    if expr is None or (recent_formulas and recent_formulas[-1]["paragraph"] != paragraph):
                        recent_formulas.clear()
                    if expr is not None:
                        recent_formulas.append(row)
                if current is None and (claims_section or after_claim_break or description_section):
                    row["prose_boundary"] = ("claims_section" if claims_section else
                                             "description_section" if description_section else "after_claim_break")
                    if (standalone_independent and isinstance(expr, dict) and expr.get("kind") == "membership"
                            and prefix.startswith("一种") and expr["owner"] in context["devices"]):
                        standalone_row = row
                result.append(row)
                if current is not None:
                    current["clause_indexes"].append(len(result) - 1)
                require(len(result) <= MAX_CLAUSES, "final_text_clause_budget")
        offset += len(line)
    # 兼容显式“独立权利要求”标题下仅有的一条装置构成句，不豁免编号权项后的散文。
    if standalone_row is not None and len(result) == 1 and not claims:
        standalone_row.pop("prose_boundary")
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
    if raw_text != text:
        # 仅对解析视图消除格式字符；回证必须仍能按原文偏移逐字重读。
        positions = [pos for pos, ch in enumerate(raw_text) if unicodedata.category(ch) != "Cf"]
        for row in (*result, *coverage[coverage_start:], *issues[issue_start:]):
            start, end = positions[row["start"]], positions[row["end"] - 1] + 1
            row.update(start=start, end=end)
            if "quote" in row:
                row["quote"] = raw_text[start:end]
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


def _audit(texts, sources, *, formula_blocks=None, heading_ids=()):
    formula_blocks = {} if formula_blocks is None else formula_blocks
    require(isinstance(texts, dict) and bool(texts or formula_blocks), "final_texts_required")
    require(not texts.keys() & formula_blocks.keys(), "final_artifact_duplicate")
    require(isinstance(sources, list) and 0 < len(sources) <= 64, "final_original_sources_required")
    manuscripts = texts | formula_blocks
    _check_nesting(manuscripts, "final_gate_input_nesting_exceeded", max_bytes=MAX_BYTES,
                   budget_code="final_text_byte_budget")
    _check_nesting(sources, "final_gate_input_nesting_exceeded", max_bytes=MAX_BYTES,
                   budget_code="final_source_byte_budget")
    require(len(canonical_bytes(manuscripts)) <= MAX_BYTES, "final_text_byte_budget")
    require(len(canonical_bytes(sources)) <= MAX_BYTES, "final_source_byte_budget")
    issues, originals, identities, source_coverage = [], [], set(), []
    formula_only_sources = []
    for source in sources:
        require(isinstance(source, dict), "final_source_object_required")
        for key in ("id", "version", "text", "sha256"):
            require(isinstance(source.get(key), str) and bool(source[key].strip()), "final_source_fields_required")
        require(source.get("role") == "original", "final_source_original_required")
        require(source["id"] not in identities, "final_source_duplicate")
        identities.add(source["id"])
        require(source["sha256"] == sha256_bytes(source["text"].encode("utf-8")), "final_source_hash_mismatch")
        source_issues = []
        source_prose = _format_free(source["text"])
        context = _context(source_prose)
        clauses, source_claims = _clauses(source["text"], source["id"], source_issues, original=True,
                                          aliases=context["aliases"], context=context, coverage=source_coverage)
        # 对非互斥实施方式原句（含未分作用域、scope-*、device-*）及独立权项核查否定矛盾（不误跨 alternative-* 互斥实施例）。
        unscoped_orig = [row["expression"] for row in clauses
                         if row["scope_id"] is None and row["claim_id"] is None and row["expression"] is not None]
        non_alt_orig = [row["expression"] for row in clauses
                        if not (row["scope_id"] or "").startswith("alternative-")
                        and row["claim_id"] is None and row["expression"] is not None]
        if any(isinstance(item, dict) and item.get("kind") == "negation"
               and _proof(item["proposition"], [other for other in non_alt_orig if other is not item],
                          [MAX_LOGIC_WORK])["relation"] == "entailed" for item in non_alt_orig):
            issues.append({"code": "original_statements_conflict", "document_id": source["id"]})
        for sclaim in source_claims:
            if not sclaim["parent_ids"]:
                ind_exprs = [clauses[idx]["expression"] for idx in sclaim["clause_indexes"]
                             if clauses[idx]["expression"] is not None]
                combined_ind = non_alt_orig + ind_exprs
                if any(isinstance(item, dict) and item.get("kind") == "negation"
                       and _proof(item["proposition"], [other for other in combined_ind if other is not item],
                                  [MAX_LOGIC_WORK])["relation"] == "entailed" for item in combined_ind):
                    issues.append({"code": "original_statements_conflict", "document_id": source["id"],
                                   "claim_id": sclaim["id"]})
        inherited_claim_groups = []
        if (any(row["parent_ids"] for row in source_claims)
                or CN_PARENT_REF.search(source_prose)
                or EN_PARENT_REF.search(source_prose)):
            # 解析单一父项无环从属链，并将从属子句严格绑定到全部继承前提，防中间概括漏父项限定。
            src_by_id = {}
            dep_valid = bool(source_claims)
            for sclaim in source_claims:
                cid = sclaim["id"]
                if cid in src_by_id or len(sclaim["parent_ids"]) > 1:
                    dep_valid = False
                    break
                pid = sclaim["parent_ids"][0] if sclaim["parent_ids"] else None
                if pid is not None and (pid not in src_by_id or pid >= cid):
                    dep_valid = False
                    break
                own_rows = [clauses[idx] for idx in sclaim["clause_indexes"]]
                if not own_rows or any(r["expression"] is None and not r["contextual"] for r in own_rows):
                    dep_valid = False
                    break
                parent_rows = list(src_by_id[pid]["all_rows"]) if pid is not None else []
                src_by_id[cid] = {"all_rows": parent_rows + own_rows, "own_rows": own_rows, "parent_id": pid}
            if not dep_valid:
                source_issues.append({"code": "original_claim_dependency_unsupported"})
                issues.append({"code": "original_claim_dependency_unsupported", "document_id": source["id"]})
            else:
                for cid, entry in sorted(src_by_id.items()):
                    if entry["parent_id"] is not None:
                        inherited_claim_groups.append((cid, entry["all_rows"], entry["own_rows"]))
                # 仅独立项的条款留在普通原句组中；从属项子句不得脱离父项被单独引用。
                dep_clause_starts = {
                    row["start"] for _, _, own_rows in inherited_claim_groups for row in own_rows
                }
                clauses = [row for row in clauses if row["start"] not in dep_clause_starts]
        if source_issues or any(row["expression"] is None and not row["contextual"] for row in clauses):
            issues.append({"code": "original_text_not_fully_parsed", "document_id": source["id"]})
        elif any(row.get("formula_only_context") for row in clauses):
            formula_only_sources.append(source["id"])
        # 回指的不确定性可能跨段撤销前文；范围无法唯一确定时不择取肯定句。
        unresolved_scope = any(row["contextual"] and not row.get("formula_backref")
                               and UNCERTAIN_SCOPE.search(_format_free(row["quote"])) for row in clauses)
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
            conflict_pool = supported if key.startswith("alternative-") else (supported + unscoped_orig)
            if any(isinstance(expr, dict) and expr.get("kind") == "negation"
                   and _proof(expr["proposition"], [other for other in conflict_pool if other is not expr],
                              [MAX_LOGIC_WORK])["relation"] == "entailed" for expr in conflict_pool):
                issues.append({"code": "original_statements_conflict", "document_id": source["id"], "scope_id": key})
                supported = []
            originals.append({"document": source, "paragraph": group[0]["paragraph"], "scope_id": key,
                              "clauses": group, "combined": bool(group[0]["scope_id"]),
                              "expressions": [] if unresolved_scope else supported,
                              "derivations": derivations, "context": context, "requires_inherited": []})
        for cid, all_rows, own_rows in inherited_claim_groups:
            req_exprs = [r["expression"] for r in all_rows if r not in own_rows and r["expression"] is not None]
            full_exprs = [r["expression"] for r in all_rows if r["expression"] is not None]
            chain_pool = full_exprs + non_alt_orig
            chain_conflict = any(
                isinstance(expr, dict) and expr.get("kind") == "negation"
                and _proof(expr["proposition"], [other for other in chain_pool if other is not expr],
                           [MAX_LOGIC_WORK])["relation"] == "entailed"
                for expr in chain_pool
            )
            if chain_conflict:
                issues.append({"code": "original_statements_conflict", "document_id": source["id"],
                               "scope_id": f"orig-claim-chain-{source['id']}-{cid}"})
            originals.append({
                "document": source,
                "paragraph": own_rows[0]["paragraph"],
                "scope_id": f"orig-claim-chain-{source['id']}-{cid}",
                "clauses": all_rows,
                "combined": True,
                "expressions": [] if (unresolved_scope or chain_conflict) else full_exprs,
                "derivations": [],
                "context": context,
                "requires_inherited": req_exprs,
            })
    # 跨原文文件核查非互斥实施例语句（含原文从属权项链）间的否定矛盾（不误跨 alternative-* 互斥方案）。
    cross_orig_exprs = [
        expr for item in originals
        if not item["scope_id"].startswith("alternative-") and not item.get("requires_inherited")
        for expr in item["expressions"]
    ]
    if any(isinstance(expr, dict) and expr.get("kind") == "negation"
           and _proof(expr["proposition"], [other for other in cross_orig_exprs if other is not expr],
                      [MAX_LOGIC_WORK])["relation"] == "entailed" for expr in cross_orig_exprs):
        issues.append({"code": "original_statements_conflict"})
        for item in originals:
            if not item["scope_id"].startswith("alternative-"):
                item["expressions"] = []
    for item in originals:
        if item["scope_id"].startswith("orig-claim-chain-") and item["expressions"]:
            chain_cross = item["expressions"] + cross_orig_exprs
            if any(isinstance(expr, dict) and expr.get("kind") == "negation"
                   and _proof(expr["proposition"], [other for other in chain_cross if other is not expr],
                              [MAX_LOGIC_WORK])["relation"] == "entailed" for expr in chain_cross):
                issues.append({"code": "original_statements_conflict",
                               "document_id": item["document"]["id"], "scope_id": item["scope_id"]})
                item["expressions"] = []
    all_clauses, all_claims, remaining, by_id, coverage = [], [], [MAX_LOGIC_WORK], {}, []
    claim_groups, current_claim_group = [], []
    negated_formulas = {_formula_key(row["expression"])
                        for row in source_coverage if row["state"] == "original_formula_negated"}
    formula_bindings = []
    for artifact_id, text in manuscripts.items():
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
        is_formula_block = artifact_id in formula_blocks
        heading_text = _format_free(text).strip() if artifact_id in heading_ids else None
        if is_formula_block:
            expr = _formula_content(artifact_id, _format_free(text))
            clauses, claims = [{"artifact_id": artifact_id, "start": 0, "end": len(text), "quote": text,
                                "expression": expr, "paragraph": 0, "scope_id": None, "combined": False,
                                "contextual": False, "claim_id": None}], []
        elif heading_text and (heading_text.casefold() in HEADINGS or heading_text in context["devices"]):
            coverage.append({"artifact_id": artifact_id, "start": 0, "end": len(text), "quote": text,
                             "state": "structure"})
            continue
        else:
            clauses, claims = _clauses(text, artifact_id, issues, aliases=aliases, context=context, coverage=coverage)
        if not clauses and _format_free(text).strip() != NOTICE:
            issues.append({"code": "artifact_technical_text_missing", "artifact_id": artifact_id})
        require(len(all_clauses) + len(clauses) <= MAX_CLAUSES, "final_text_clause_budget")
        for row in clauses:
            row["support"] = []
            expr = row["expression"]
            if expr is None:
                issues.append({"code": "final_formula_content_not_supported" if is_formula_block else
                               "final_clause_unparsed_or_uncertain", **_location(row)})
                continue
            formula_content = isinstance(expr, dict) and expr.get("kind") == "formula_content"
            formula_key = _formula_key(expr)
            for original in originals:
                if formula_key is not None and (expr not in original["expressions"] or original["requires_inherited"]
                                                or formula_key in negated_formulas
                                                or original["scope_id"].startswith("alternative-")):
                    continue
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
                                           "requires_inherited": original.get("requires_inherited", []),
                                           "citations": [_location(item) for item in relevant],
                                           "derivations": original["derivations"]})
                    if relevant and all(item.get("prose_boundary") in {"description_section", "after_claim_break"} for item in relevant):
                        row["support"][-1]["separate_prose"] = True
            if not row["support"]:
                issues.append({"code": "final_formula_content_not_supported" if formula_content else
                               _unsupported_reason(expr, originals), **_location(row)})
            elif all(s.get("requires_inherited") for s in row["support"]):
                # 仅由原文从属链支持但未落入含父项限定的权项时，稍后在权项级核对是否满足继承前提。
                row["needs_inherited_check"] = True
            if ((row.get("prose_boundary") == "claims_section")
                    or (row.get("prose_boundary") == "after_claim_break"
                        and not any(s.get("separate_prose") for s in row["support"]))):
                issues.append({"code": "claim_paragraph_boundary_unconfirmed", **_location(row)})
            if is_formula_block and row["support"]:
                formula_bindings.append({"block_id": artifact_id, "structure_sha256": expr["structure_sha256"],
                                         "source_scopes": [{"document_id": s["document_id"], "scope_id": s["scope_id"]}
                                                           for s in row["support"]]})
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
            claim_exprs = [r["expression"] for r in claim["all_clauses"] if r["expression"] is not None]
            for row in own:
                if row.get("needs_inherited_check"):
                    satisfied = False
                    for sup in row["support"]:
                        reqs = sup.get("requires_inherited", [])
                        if not reqs or all(_proof(req, claim_exprs, remaining)["relation"] == "entailed" for req in reqs):
                            satisfied = True
                            break
                    if not satisfied:
                        issues.append({"code": "inherited_original_limitation_omitted",
                                       "artifact_id": artifact_id, "claim_id": claim["id"], **_location(row)})
            by_id[claim["id"]] = claim
            all_claims.append({key: claim[key] for key in ("artifact_id", "id", "parent_ids")})
        # 非权项段落中若直接引用了依赖原文从属链的子句，同样必须满足同工件内全部继承前提。
        claim_clause_ids = {idx for claim in claims for idx in claim["clause_indexes"]}
        non_claim_exprs = [r["expression"] for i, r in enumerate(clauses)
                           if i not in claim_clause_ids and r["expression"] is not None]
        for idx, row in enumerate(clauses):
            if idx not in claim_clause_ids and row.get("needs_inherited_check"):
                satisfied = any(
                    not sup.get("requires_inherited")
                    or all(_proof(req, non_claim_exprs, remaining)["relation"] == "entailed"
                           for req in sup["requires_inherited"])
                    for sup in row["support"]
                )
                if not satisfied:
                    issues.append({"code": "inherited_original_limitation_omitted", **_location(row)})
        all_clauses.extend(clauses)
    claim_groups.append(current_claim_group)
    if any(group != list(range(1, len(group) + 1)) for group in claim_groups):
        issues.append({"code": "claim_numbering_gap_or_order"})
    if not all_clauses:
        issues.append({"code": "final_technical_text_missing"})
    if formula_only_sources and any(row["expression"] is not None and _formula_key(row["expression"]) is None
                                    for row in all_clauses):
        # 独立否定句可与公式无关，但不能因此为未完整解析的普通技术正文放行。
        issues.extend({"code": "original_text_not_fully_parsed", "document_id": sid} for sid in formula_only_sources)
    inputs = {"texts": texts, "sources": sources}
    if formula_blocks:
        inputs["formula_blocks"] = formula_blocks
    if heading_ids:
        inputs["heading_ids"] = sorted(heading_ids)
    input_binding = {"input_hash": digest(inputs),
                     "text_bindings": {key: sha256_bytes(value.encode("utf-8")) for key, value in manuscripts.items()},
                     "source_bindings": [{key: row[key] for key in ("id", "version", "sha256")} for row in sources]}
    return {"contract_version": VERSION, "status": "blocked" if issues else "checked",
            "input_binding": input_binding, "input_hash": input_binding["input_hash"],
            "text_bindings": input_binding["text_bindings"],
            "source_bindings": [{key: row[key] for key in ("id", "version", "sha256")} for row in sources],
            "clauses": all_clauses, "claims": all_claims, "issues": issues,
            "context_coverage": coverage, "source_coverage": source_coverage,
            "coverage_ledger": coverage + [{**_location(row), "state": "supported" if row["support"] else
                                           "unparsed" if row["expression"] is None else "unsupported"}
                                          for row in all_clauses],
            "logic_work_units": MAX_LOGIC_WORK - remaining[0],
            "scope": "bounded_chinese_and_english_relations_single_parent_claims_and_typed_anchors",
            "coverage": "complete_supplied_text_in_supported_subset" if not issues else "incomplete_or_rejected",
            **({"formula_blocks_verified": len(formula_bindings), "formula_bindings": formula_bindings}
               if formula_blocks else {}),
            "dependent_addition_check": "typed_relations_and_finite_implication_only",
            "source_authenticity": "not_verified", "natural_language_verified": False,
            "professional_review": "not_performed", "external_action": "not_performed"}


def _location(row):
    return {key: row[key] for key in ("artifact_id", "start", "end", "quote")}


def _audit_safely(texts, sources, **kwargs):
    try:
        return _audit(texts, sources, **kwargs)
    except (ContractError, UnicodeError, RecursionError, TypeError, KeyError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ContractError) else "final_gate_input_invalid"
        return {"contract_version": VERSION, "status": "blocked", "issues": [{"code": code}],
                "claims": [], "clauses": [], "input_binding": {},
                "coverage": "not_checked", "natural_language_verified": False,
                "professional_review": "not_performed", "external_action": "not_performed"}


def audit_final_text(texts: dict[str, str], sources: list[dict]) -> dict:
    """重读实际字符生成验收报告；不采信调用者公式、分类或历史passed。"""
    return _audit_safely(texts, sources)


def _require_checked(report):
    if report["status"] != "checked":
        error = ContractError("final_text_gate_blocked")
        error.report = report
        raise error
    return report


def require_final_text(texts: dict[str, str], sources: list[dict]) -> dict:
    """失败直接抛错，调用者必须在写出最终正文／候选清单前调用。"""
    return _require_checked(audit_final_text(texts, sources))


def require_final_document(blocks: list[dict], sources: list[dict]) -> dict:
    """审计已解析的正文块；公式块必须与同一原文范围的有效锚点匹配。"""
    require(isinstance(blocks, list), "final_document_blocks_invalid")
    texts, formula_blocks, heading_ids = {}, {}, set()
    for block in blocks:
        require(isinstance(block, dict) and all(isinstance(block.get(k), str) for k in ("id", "kind", "text")),
                "final_document_block_invalid")
        identity, kind, text = block["id"], block["kind"], block["text"]
        require(identity not in texts and identity not in formula_blocks, "final_artifact_duplicate")
        if kind == "formula":
            formula_blocks[identity] = text
        else:
            texts[identity] = text
            if kind in {"heading1", "heading2", "heading3", "heading4"}:
                heading_ids.add(identity)
    return _require_checked(_audit_safely(texts, sources, formula_blocks=formula_blocks, heading_ids=heading_ids))


_OA_OVERCLAIM = re.compile(
    r"(?i)审查员已(?:同意|确认|认可)|examiner\s+(?:conceded|agreed|confirmed)"
    r"|绝对具有新颖性|全球可授权|globally\s+patentable|guaranteed\s+(?:grant|allowance)"
)
_OA_PLACEHOLDER = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:TODO|TBD|FIXME|TO\s*CONFIRM)(?![A-Za-z0-9_])|待确认|待补证|待核实|待补充确认"
)
_OA_PARAGRAPH_BREAK = re.compile(r"\r?\n[^\S\r\n]*\r?\n|\u2029")


def _oa_paragraphs(body):
    def paragraph(start, end):
        raw = body[start:end]
        return raw.strip(), start + len(raw) - len(raw.lstrip())

    start = 0
    for match in _OA_PARAGRAPH_BREAK.finditer(body):
        text, offset = paragraph(start, match.start())
        if text:
            yield text, offset
        start = match.end()
    text, offset = paragraph(start, len(body))
    if text:
        yield text, offset


def audit_oa_response(
    *,
    replacement_texts: dict[str, str],
    original_sources: list[dict],
    notice_opinions: list[dict],
    arguments: list[dict],
    cited_references: list[dict] | None = None,
    extra_response_texts: dict[str, str] | None = None,
    replacement_required: bool = False,
) -> dict:
    """校验替换稿和实际答复；`response:<意见ID>` 须逐段匹配论证，并包含逐字核对的引文。"""
    try:
        return _audit_oa_response(
            replacement_texts, original_sources, notice_opinions, arguments, cited_references,
            extra_response_texts, replacement_required,
        )
    except (ContractError, UnicodeError, RecursionError, TypeError, KeyError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ContractError) else "oa_input_invalid"
        return {"contract_version": VERSION, "gate_mode": "oa_dual_track", "status": "blocked",
                "input_hash": None,
                "amendment_support_track": {"status": "not_performed", "issues": []},
                "argument_evidence_track": {"status": "blocked", "issues": [{"code": code}]},
                "legal_persuasiveness_verified": False, "professional_review": "not_performed",
                "external_action": "not_performed"}


def _audit_oa_response(replacement_texts, original_sources, notice_opinions, arguments, cited_references,
                       extra_response_texts, replacement_required):
    cited_references = [] if cited_references is None else cited_references
    extra_response_texts = {} if extra_response_texts is None else extra_response_texts
    inputs = {"replacement_texts": replacement_texts, "original_sources": original_sources,
              "notice_opinions": notice_opinions, "arguments": arguments, "cited_references": cited_references,
              "extra_response_texts": extra_response_texts, "replacement_required": replacement_required}
    _check_nesting(inputs, "oa_input_nesting_exceeded", max_bytes=MAX_BYTES, budget_code="oa_input_byte_budget")
    encoded = canonical_bytes(inputs)
    require(len(encoded) <= MAX_BYTES, "oa_input_byte_budget")
    require(type(replacement_required) is bool, "oa_replacement_required_boolean")
    require(isinstance(replacement_texts, dict), "oa_replacement_texts_invalid")
    arg_issues: list[dict] = []

    if not isinstance(original_sources, list) or not isinstance(cited_references, list):
        arg_issues.append({"code": "oa_sources_list_required"})
        original_sources = []
        cited_references = []
    if not isinstance(notice_opinions, list) or not isinstance(arguments, list):
        arg_issues.append({"code": "oa_opinions_and_arguments_list_required"})
        notice_opinions = []
        arguments = []

    if replacement_required and not replacement_texts:
        amendment_report = {
            "contract_version": VERSION, "status": "blocked",
            "issues": [{"code": "oa_replacement_text_missing"}], "claims": [], "clauses": [],
        }
    elif replacement_texts:
        amendment_report = audit_final_text(replacement_texts, original_sources)
    else:
        amendment_report = {
            "contract_version": VERSION, "status": "not_applicable", "issues": [], "claims": [], "clauses": [],
        }

    doc_index: dict[str, dict] = {}
    for group_name, docs in (("original", original_sources), ("prior_art", cited_references)):
        for doc in docs:
            if (not isinstance(doc, dict) or not all(isinstance(doc.get(k), str) and doc[k].strip()
                    for k in ("id", "text", "sha256", "version", "role")) or doc["role"] != group_name):
                arg_issues.append({"code": "oa_reference_invalid", "group": group_name})
                continue
            if doc["id"] in doc_index:
                arg_issues.append({"code": "oa_reference_duplicate", "document_id": doc["id"]})
                continue
            if doc["sha256"] != sha256_bytes(doc["text"].encode("utf-8")):
                arg_issues.append({"code": "oa_reference_hash_mismatch", "document_id": doc["id"]})
                continue
            doc_index[doc["id"]] = doc

    opinion_ids: set[str] = set()
    for row in notice_opinions:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
            arg_issues.append({"code": "oa_notice_opinion_invalid"})
            continue
        oid = row["id"].strip()
        if oid in opinion_ids:
            arg_issues.append({"code": "oa_notice_opinion_duplicate", "opinion_id": oid})
            continue
        opinion_ids.add(oid)
    if not opinion_ids:
        arg_issues.append({"code": "oa_notice_opinions_required"})

    # Only the actual, opinion-keyed response may carry checked argument paragraphs.
    opinion_response_keys = {"response:" + oid for oid in opinion_ids}
    if not isinstance(extra_response_texts, dict):
        arg_issues.append({"code": "oa_extra_response_texts_invalid"})
        extra_response_texts = {}
    else:
        for rkey, rtext in extra_response_texts.items():
            if not isinstance(rkey, str) or rkey not in opinion_response_keys:
                arg_issues.append({"code": "oa_response_unknown_opinion"})
                continue
            if not isinstance(rtext, str) or not rtext.strip():
                arg_issues.append({"code": "oa_response_text_invalid", "key": str(rkey)})
                continue
            visible = _format_free(rtext)
            if _OA_OVERCLAIM.search(visible):
                arg_issues.append({"code": "oa_unverified_concession_or_overclaim", "response_key": str(rkey)})
            if _OA_PLACEHOLDER.search(visible):
                arg_issues.append({"code": "oa_unresolved_placeholder_in_response", "response_key": str(rkey)})

    paragraphs: dict[str, list[tuple[str, list, dict, bool]]] = {}
    checked_args = []
    for arg in arguments:
        if not isinstance(arg, dict) or not isinstance(arg.get("opinion_id"), str) or not isinstance(arg.get("text"), str):
            arg_issues.append({"code": "oa_argument_record_invalid"})
            continue
        oid = arg["opinion_id"].strip()
        if oid not in opinion_ids:
            arg_issues.append({"code": "oa_argument_unknown_opinion", "opinion_id": oid})
            continue
        text = arg["text"].strip()
        if not text:
            arg_issues.append({"code": "oa_argument_text_empty", "opinion_id": oid})
            continue
        issue_count = len(arg_issues)
        visible = _format_free(text)
        if _OA_OVERCLAIM.search(visible):
            arg_issues.append({"code": "oa_unverified_concession_or_overclaim", "opinion_id": oid})
        if _OA_PLACEHOLDER.search(visible):
            arg_issues.append({"code": "oa_unresolved_placeholder_in_argument", "opinion_id": oid})
        citations = arg.get("citations", [])
        if not isinstance(citations, list) or not citations:
            arg_issues.append({"code": "oa_argument_citations_missing", "opinion_id": oid})
        verified_cites = []
        for cite in citations if isinstance(citations, list) else []:
            if (not isinstance(cite, dict)
                    or not {"document_id", "start", "end", "quote"} <= set(cite)
                    or not isinstance(cite["document_id"], str)):
                arg_issues.append({"code": "oa_citation_fields_invalid", "opinion_id": oid})
                continue
            doc = doc_index.get(cite["document_id"])
            if doc is None:
                arg_issues.append({"code": "oa_citation_document_unknown", "opinion_id": oid,
                                   "document_id": cite["document_id"]})
                continue
            s, e, quote = cite["start"], cite["end"], cite["quote"]
            if not (type(s) is int and type(e) is int and isinstance(quote, str)
                    and len(quote.strip()) >= 2
                    and 0 <= s < e <= len(doc["text"])
                    and doc["text"][s:e] == quote):
                arg_issues.append({"code": "oa_citation_quote_mismatch", "opinion_id": oid,
                                   "document_id": cite["document_id"]})
                continue
            response_offset = text.find(quote)
            if response_offset == -1:
                arg_issues.append({"code": "oa_citation_quote_missing_in_response_paragraph", "opinion_id": oid,
                                   "document_id": cite["document_id"]})
                continue
            verified_cites.append({"document_id": cite["document_id"], "start": s, "end": e,
                                   "response_start": response_offset, "response_end": response_offset + len(quote)})
        checked = {"opinion_id": oid, "verified_citations": 0,
                   "disposition": arg.get("disposition", "argued")}
        paragraphs.setdefault(oid, []).append((text, verified_cites, checked, len(arg_issues) == issue_count))
        checked_args.append(checked)

    addressed = set()
    for oid in sorted(opinion_ids):
        key = "response:" + oid
        body = extra_response_texts.get(key)
        if not isinstance(body, str) or not body.strip():
            arg_issues.append({"code": "oa_actual_response_missing", "opinion_id": oid})
            continue
        bound = paragraphs.get(oid, [])
        actual = list(_oa_paragraphs(body))
        if [text for text, _ in actual] != [text for text, _, _, _ in bound]:
            arg_issues.append({"code": "oa_actual_response_argument_mismatch", "opinion_id": oid})
            continue
        for (text, offset), (_, citations, checked, _) in zip(actual, bound):
            checked.update(response_key=key, response_start=offset, response_end=offset + len(text),
                           verified_citations=len(citations),
                           citation_bindings=[{**cite, "response_start": offset + cite["response_start"],
                                               "response_end": offset + cite["response_end"]} for cite in citations])
        if all(valid for _, _, _, valid in bound):
            addressed.add(oid)

    missing_opinions = sorted(opinion_ids - addressed)
    if missing_opinions:
        arg_issues.append({"code": "oa_opinions_unaddressed", "opinion_ids": missing_opinions})

    amendment_ok = amendment_report["status"] in {"checked", "not_applicable"}
    argument_ok = not arg_issues
    overall = "checked" if (amendment_ok and argument_ok) else "blocked"
    return {
        "contract_version": VERSION,
        "gate_mode": "oa_dual_track",
        "status": overall,
        "input_hash": sha256_bytes(encoded),
        "amendment_support_track": amendment_report,
        "argument_evidence_track": {
            "status": "checked" if argument_ok else "blocked",
            "opinions_total": len(opinion_ids),
            "opinions_addressed": len(addressed),
            "missing_opinions": missing_opinions,
            "arguments": checked_args,
            "issues": arg_issues,
        },
        "legal_persuasiveness_verified": False,
        "professional_review": "not_performed",
        "external_action": "not_performed",
    }


def require_oa_response(**kwargs) -> dict:
    report = audit_oa_response(**kwargs)
    if report["status"] != "checked":
        error = ContractError("oa_dual_track_gate_blocked")
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
