"""Phase B4: 纯 Python 标准库原生 Office Math (OMML) 序列化与结构回读检查。

支持受控 LaTeX 数学子集（上下标、分式、根号含 n 次根、求和/积分/连乘、基础矩阵、
希腊字母与常见数学函数/运算符），生成符合 WordprocessingML (OOXML Math) 的
m:oMathPara / m:oMath 节点，并支持结构槽位与修订/隐藏节点回读校验。
超出子集或括号不平衡的表达式一律显式拒绝，不静默输出破损 XML。
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from tools.core import ContractError, canonical_bytes, require, sha256_bytes

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ET.register_namespace("m", M)

MAX_EXPR_LENGTH = 1024
MAX_AST_DEPTH = 16
MAX_XML_DEPTH = 128

MATH_CONTENT_TAGS = frozenset({
    "r", "sSup", "sSub", "sSubSup", "f", "rad", "nary", "m", "d",
})
ALLOWED_OMML_CHILDREN: dict[str, frozenset[str]] = {
    "oMathPara": frozenset({"oMathParaPr", "oMath"}),
    "oMath": MATH_CONTENT_TAGS,
    "e": MATH_CONTENT_TAGS,
    "num": MATH_CONTENT_TAGS,
    "den": MATH_CONTENT_TAGS,
    "sub": MATH_CONTENT_TAGS,
    "sup": MATH_CONTENT_TAGS,
    "deg": MATH_CONTENT_TAGS,
    "r": frozenset({"rPr", "t"}),
    "t": frozenset(),
    "f": frozenset({"fPr", "num", "den"}),
    "sSup": frozenset({"sSupPr", "e", "sup"}),
    "sSub": frozenset({"sSubPr", "e", "sub"}),
    "sSubSup": frozenset({"sSubSupPr", "e", "sub", "sup"}),
    "rad": frozenset({"radPr", "deg", "e"}),
    "nary": frozenset({"naryPr", "sub", "sup", "e"}),
    "m": frozenset({"mPr", "mr"}),
    "mr": frozenset({"e"}),
    "d": frozenset({"dPr", "e"}),
    "oMathParaPr": frozenset({"ctrlPr"}),
    "rPr": frozenset({"ctrlPr"}),
    "fPr": frozenset({"ctrlPr"}),
    "sSupPr": frozenset({"ctrlPr"}),
    "sSubPr": frozenset({"ctrlPr"}),
    "sSubSupPr": frozenset({"ctrlPr"}),
    "radPr": frozenset({"degHide", "ctrlPr"}),
    "naryPr": frozenset({"chr", "subHide", "supHide", "ctrlPr"}),
    "mPr": frozenset({"ctrlPr"}),
    "dPr": frozenset({"begChr", "endChr", "ctrlPr"}),
    "ctrlPr": frozenset(),
    "degHide": frozenset(),
    "chr": frozenset(),
    "subHide": frozenset(),
    "supHide": frozenset(),
    "begChr": frozenset(),
    "endChr": frozenset(),
}

SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "phi": "φ", "omega": "ω",
    "Delta": "Δ", "Gamma": "Γ", "Lambda": "Λ", "Sigma": "Σ", "Omega": "Ω",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "pm": "±", "mp": "∓", "times": "×", "cdot": "·",
    "div": "÷", "in": "∈", "notin": "∉", "infty": "∞", "to": "→", "rightarrow": "→",
    "sin": "sin", "cos": "cos", "tan": "tan", "log": "log", "ln": "ln",
    "exp": "exp", "max": "max", "min": "min",
}
NARY_OPS = {"sum": "∑", "int": "∫", "prod": "∏"}
NAMED_FUNCTIONS = frozenset({"sin", "cos", "tan", "log", "ln", "exp", "max", "min"})
MATRIX_ENVS = {
    "matrix": (None, None),
    "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"),
}

SUPPORTED_OMML_TAGS = frozenset({
    "oMath", "oMathPara", "oMathParaPr", "r", "rPr", "t",
    "sSup", "sSupPr", "sSub", "sSubPr", "sSubSup", "sSubSupPr",
    "f", "fPr", "num", "den",
    "rad", "radPr", "deg", "degHide",
    "nary", "naryPr", "chr", "sub", "sup", "subHide", "supHide",
    "m", "mPr", "mr", "d", "dPr", "begChr", "endChr",
    "e", "ctrlPr",
})
UNRESOLVED_WORD_CONTENT = frozenset({
    "del", "delText", "ins", "moveFrom", "moveTo", "fldChar", "fldSimple", "instrText",
})
REVISION_OR_HIDDEN_LOCAL = UNRESOLVED_WORD_CONTENT | frozenset({
    "rPrChange", "pPrChange", "bookmarkStart", "bookmarkEnd",
    "commentRangeStart", "commentRangeEnd", "commentReference",
})
WORD_HIDDEN_PROPERTIES = frozenset({"vanish", "specVanish", "webHidden"})
ALLOWED_WORD_RPR_CHILDREN = frozenset({
    "rFonts", "sz", "szCs", "i", "iCs", "b", "bCs", "lang", "noProof",
}) | WORD_HIDDEN_PROPERTIES


@dataclass(frozen=True)
class _Tok:
    kind: str
    value: str


def _is_ascii_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ascii_alpha(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _tokenize(expr: str) -> list[_Tok]:
    require(isinstance(expr, str) and bool(expr.strip()), "omml_expression_empty")
    require(len(expr) <= MAX_EXPR_LENGTH, "omml_expression_too_long")
    tokens: list[_Tok] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "\\":
            if i + 1 < n and expr[i + 1] == "\\":
                tokens.append(_Tok("ROWSEP", "\\\\"))
                i += 2
                continue
            j = i + 1
            while j < n and _is_ascii_alpha(expr[j]):
                j += 1
            cmd = expr[i + 1:j]
            require(bool(cmd), "omml_empty_command")
            tokens.append(_Tok("CMD", cmd))
            i = j
        elif ch in "{}_^&":
            tokens.append(_Tok(ch, ch))
            i += 1
        elif _is_ascii_digit(ch) or (ch == "." and i + 1 < n and _is_ascii_digit(expr[i + 1])):
            j = i
            seen_dot = False
            while j < n and (_is_ascii_digit(expr[j]) or (expr[j] == "." and not seen_dot)):
                if expr[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(_Tok("NUMBER", expr[i:j]))
            i = j
        elif _is_ascii_alpha(ch):
            tokens.append(_Tok("ATOM", ch))
            i += 1
        elif ch in "+-=<>(),[]|/:!%*'":
            tokens.append(_Tok("ATOM", ch))
            i += 1
        else:
            raise ContractError("omml_unsupported_character")
    require(bool(tokens), "omml_expression_empty")
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Tok]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> _Tok | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def pop(self) -> _Tok:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse_seq(self, *, stop_on_rbrace: bool = False, stop_on_rbracket: bool = False,
                  stop_on_matrix_sep: bool = False, depth: int = 0) -> list[dict]:
        require(depth <= MAX_AST_DEPTH, "omml_nesting_exceeded")
        nodes: list[dict] = []
        bracket_depth = 0
        while (tok := self.peek()) is not None:
            if tok.kind == "}":
                if stop_on_rbrace:
                    self.pop()
                    return nodes
                raise ContractError("omml_unbalanced_brace")
            if stop_on_rbracket and tok.kind == "ATOM":
                if tok.value == "[":
                    bracket_depth += 1
                elif tok.value == "]":
                    if bracket_depth == 0:
                        self.pop()
                        return nodes
                    bracket_depth -= 1
            if stop_on_matrix_sep and (
                tok.kind in {"&", "ROWSEP"} or (tok.kind == "CMD" and tok.value == "end")
            ):
                return nodes
            nodes.append(self.parse_scripted(depth))
        if stop_on_rbrace:
            raise ContractError("omml_unbalanced_brace")
        if stop_on_rbracket:
            raise ContractError("omml_unbalanced_bracket")
        return nodes

    def argument_token(self, *, for_script: bool = False) -> _Tok:
        tok = self.peek()
        require(tok is not None, "omml_expected_argument")
        if tok.kind == "ATOM" and tok.value in {"-", "+", "(", "["}:
            if for_script and tok.value in {"-", "+"}:
                raise ContractError("omml_braces_required_for_signed_script")
            raise ContractError("omml_braces_required_for_argument")
        return tok

    def parse_group(self, depth: int, *, for_script: bool = False) -> list[dict]:
        tok = self.argument_token(for_script=for_script)
        if tok.kind == "{":
            self.pop()
            inner = self.parse_seq(stop_on_rbrace=True, depth=depth + 1)
            require(bool(inner), "omml_empty_group")
            return inner
        return [self.parse_atom(depth + 1)]

    def _parse_env_name(self, depth: int) -> str:
        group = self.parse_group(depth + 1)
        require(all(item.get("kind") == "run" for item in group), "omml_env_name_invalid")
        return "".join(item["text"] for item in group)

    def _parse_matrix(self, env_name: str, depth: int) -> dict:
        require(env_name in MATRIX_ENVS, "omml_unsupported_environment:" + env_name)
        rows: list[list[list[dict]]] = []
        current_row: list[list[dict]] = []
        while True:
            cell = self.parse_seq(stop_on_matrix_sep=True, depth=depth + 1)
            require(bool(cell), "omml_matrix_empty_cell")
            current_row.append(cell)
            tok = self.peek()
            require(tok is not None, "omml_unterminated_environment")
            if tok.kind == "&":
                self.pop()
                continue
            if tok.kind == "ROWSEP":
                self.pop()
                rows.append(current_row)
                current_row = []
                continue
            if tok.kind == "CMD" and tok.value == "end":
                self.pop()
                end_name = self._parse_env_name(depth)
                require(end_name == env_name, "omml_environment_mismatch")
                rows.append(current_row)
                break
            raise ContractError("omml_unexpected_token")
        col_count = len(rows[0])
        require(all(len(r) == col_count for r in rows), "omml_matrix_ragged_rows")
        beg, end = MATRIX_ENVS[env_name]
        return {"kind": "matrix", "rows": rows, "beg": beg, "end": end}

    def parse_atom(self, depth: int) -> dict:
        require(depth <= MAX_AST_DEPTH, "omml_nesting_exceeded")
        tok = self.peek()
        require(tok is not None, "omml_unexpected_eof")
        if tok.kind == "{":
            self.pop()
            inner = self.parse_seq(stop_on_rbrace=True, depth=depth + 1)
            require(bool(inner), "omml_empty_group")
            return {"kind": "group", "items": inner}
        if tok.kind in {"ATOM", "NUMBER"}:
            self.pop()
            return {"kind": "run", "text": tok.value, "token": tok.kind}
        if tok.kind == "CMD":
            self.pop()
            cmd = tok.value
            if cmd == "begin":
                env_name = self._parse_env_name(depth)
                return self._parse_matrix(env_name, depth + 1)
            if cmd == "frac":
                num = self.parse_group(depth + 1)
                den = self.parse_group(depth + 1)
                return {"kind": "frac", "num": num, "den": den}
            if cmd == "sqrt":
                deg = None
                nxt = self.peek()
                if nxt is not None and nxt.kind == "ATOM" and nxt.value == "[":
                    self.pop()
                    deg = self.parse_seq(stop_on_rbracket=True, depth=depth + 1)
                    require(bool(deg), "omml_empty_radical_degree")
                radicand = self.parse_group(depth + 1)
                return {"kind": "sqrt", "deg": deg, "e": radicand}
            if cmd in NARY_OPS:
                sub = None
                sup = None
                while (nxt := self.peek()) is not None and nxt.kind in {"_", "^"}:
                    op = self.pop().kind
                    arg = self.parse_group(depth + 1, for_script=True)
                    if op == "_":
                        require(sub is None, "omml_duplicate_subscript")
                        sub = arg
                    else:
                        require(sup is None, "omml_duplicate_superscript")
                        sup = arg
                # 被求和/被积主体按 parse_scripted 解析，确保 \sum_{i=1}^n x_i^2 正确结合 x_i^2！
                self.argument_token()
                body = [self.parse_scripted(depth + 1)]
                return {"kind": "nary", "op": NARY_OPS[cmd], "sub": sub, "sup": sup, "e": body}
            if cmd in SYMBOLS:
                return {"kind": "run", "text": SYMBOLS[cmd],
                        "token": "FUNCTION" if cmd in NAMED_FUNCTIONS else "ATOM"}
            raise ContractError("omml_unsupported_command:" + cmd)
        raise ContractError("omml_unexpected_token")

    def parse_scripted(self, depth: int) -> dict:
        base = self.parse_atom(depth)
        sub = None
        sup = None
        while (nxt := self.peek()) is not None and nxt.kind in {"_", "^"}:
            op = self.pop().kind
            arg = self.parse_group(depth + 1, for_script=True)
            if op == "_":
                require(sub is None, "omml_duplicate_subscript")
                sub = arg
            else:
                require(sup is None, "omml_duplicate_superscript")
                sup = arg
        if sub is not None and sup is not None:
            return {"kind": "subsup", "base": [base], "sub": sub, "sup": sup}
        if sup is not None:
            return {"kind": "sup", "base": [base], "sup": sup}
        if sub is not None:
            return {"kind": "sub", "base": [base], "sub": sub}
        return base


def _m(tag: str) -> str:
    return "{" + M + "}" + tag


def _flatten_groups(nodes: list[dict]):
    for node in nodes:
        if node["kind"] == "group":
            yield from _flatten_groups(node["items"])
        else:
            yield node


def _emit_nodes(parent: ET.Element, nodes: list[dict]) -> None:
    # 合并相邻纯文本 run，避免多字母下标拆成碎节点
    nodes = list(_flatten_groups(nodes))
    i = 0
    while i < len(nodes):
        node = nodes[i]
        kind = node["kind"]
        if kind == "run":
            buf = [node["text"]]
            while i + 1 < len(nodes) and nodes[i + 1]["kind"] == "run":
                left, right = nodes[i], nodes[i + 1]
                if (left["token"] == right["token"] == "NUMBER" or
                        ("FUNCTION" in (left["token"], right["token"]) and
                         (left["text"][-1].isalnum() or left["token"] == "NUMBER") and
                         (right["text"][0].isalnum() or right["token"] == "NUMBER"))):
                    buf.append(" ")
                i += 1
                buf.append(right["text"])
            r = ET.SubElement(parent, _m("r"))
            t = ET.SubElement(r, _m("t"))
            t.text = "".join(buf)
        elif kind == "sup":
            el = ET.SubElement(parent, _m("sSup"))
            _emit_nodes(ET.SubElement(el, _m("e")), node["base"])
            _emit_nodes(ET.SubElement(el, _m("sup")), node["sup"])
        elif kind == "sub":
            el = ET.SubElement(parent, _m("sSub"))
            _emit_nodes(ET.SubElement(el, _m("e")), node["base"])
            _emit_nodes(ET.SubElement(el, _m("sub")), node["sub"])
        elif kind == "subsup":
            el = ET.SubElement(parent, _m("sSubSup"))
            _emit_nodes(ET.SubElement(el, _m("e")), node["base"])
            _emit_nodes(ET.SubElement(el, _m("sub")), node["sub"])
            _emit_nodes(ET.SubElement(el, _m("sup")), node["sup"])
        elif kind == "frac":
            el = ET.SubElement(parent, _m("f"))
            _emit_nodes(ET.SubElement(el, _m("num")), node["num"])
            _emit_nodes(ET.SubElement(el, _m("den")), node["den"])
        elif kind == "sqrt":
            el = ET.SubElement(parent, _m("rad"))
            pr = ET.SubElement(el, _m("radPr"))
            deg_el = ET.SubElement(el, _m("deg"))
            if node.get("deg"):
                ET.SubElement(pr, _m("degHide"), {_m("val"): "0"})
                _emit_nodes(deg_el, node["deg"])
            else:
                ET.SubElement(pr, _m("degHide"), {_m("val"): "1"})
            _emit_nodes(ET.SubElement(el, _m("e")), node["e"])
        elif kind == "nary":
            el = ET.SubElement(parent, _m("nary"))
            pr = ET.SubElement(el, _m("naryPr"))
            ET.SubElement(pr, _m("chr"), {_m("val"): node["op"]})
            if not node["sub"]:
                ET.SubElement(pr, _m("subHide"), {_m("val"): "1"})
            if not node["sup"]:
                ET.SubElement(pr, _m("supHide"), {_m("val"): "1"})
            sub_el = ET.SubElement(el, _m("sub"))
            if node["sub"]:
                _emit_nodes(sub_el, node["sub"])
            sup_el = ET.SubElement(el, _m("sup"))
            if node["sup"]:
                _emit_nodes(sup_el, node["sup"])
            _emit_nodes(ET.SubElement(el, _m("e")), node["e"])
        elif kind == "matrix":
            target = parent
            if node.get("beg") or node.get("end"):
                d_el = ET.SubElement(parent, _m("d"))
                dpr = ET.SubElement(d_el, _m("dPr"))
                if node.get("beg"):
                    ET.SubElement(dpr, _m("begChr"), {_m("val"): node["beg"]})
                if node.get("end"):
                    ET.SubElement(dpr, _m("endChr"), {_m("val"): node["end"]})
                target = ET.SubElement(d_el, _m("e"))
            m_el = ET.SubElement(target, _m("m"))
            for row in node["rows"]:
                mr = ET.SubElement(m_el, _m("mr"))
                for cell in row:
                    _emit_nodes(ET.SubElement(mr, _m("e")), cell)
        else:
            raise ContractError("omml_unknown_ast_node")
        i += 1


def latex_to_omml_element(expr: str, *, display_para: bool = False) -> ET.Element:
    """将受支持 LaTeX 数学表达式转为原生 OOXML m:oMath 或 m:oMathPara 节点。"""
    tokens = _tokenize(expr)
    parser = _Parser(tokens)
    ast_nodes = parser.parse_seq()
    require(parser.pos == len(tokens) and bool(ast_nodes), "omml_parse_incomplete")
    omath = ET.Element(_m("oMath"))
    _emit_nodes(omath, ast_nodes)
    if display_para:
        para = ET.Element(_m("oMathPara"))
        para.append(omath)
        return para
    return omath


def latex_to_omml_xml(expr: str, *, display_para: bool = False) -> bytes:
    return ET.tostring(latex_to_omml_element(expr, display_para=display_para), encoding="utf-8")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _word_hidden_on(prop: ET.Element) -> bool:
    return (prop.tag.startswith("{" + W + "}") and _local(prop.tag) in WORD_HIDDEN_PROPERTIES
            and prop.get("{" + W + "}val", "true").strip().lower() not in {"0", "false", "off"})


def _run_is_hidden(run_el: ET.Element) -> bool:
    return any(_word_hidden_on(prop) for child in run_el
               if child.tag in {_m("rPr"), "{" + W + "}rPr"} for prop in child.iter())


def _merge_ast_items(items: list) -> list:
    merged: list = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, list):
            for sub in item:
                if merged and isinstance(merged[-1], dict) and merged[-1].get("k") == "t" and isinstance(sub, dict) and sub.get("k") == "t":
                    merged[-1] = {"k": "t", "v": merged[-1]["v"] + sub["v"]}
                else:
                    merged.append(sub)
        elif merged and isinstance(merged[-1], dict) and merged[-1].get("k") == "t" and isinstance(item, dict) and item.get("k") == "t":
            merged[-1] = {"k": "t", "v": merged[-1]["v"] + item["v"]}
        else:
            merged.append(item)
    return merged


def _omml_flag_on(pr: ET.Element | None, tag_name: str) -> bool:
    if pr is None:
        return False
    for el in pr.findall(_m(tag_name)):
        val = (el.get(_m("val")) or "1").strip().lower()
        if val not in {"0", "false", "off"}:
            return True
    return False


def _omml_slot(slot: ET.Element | None, depth: int = 0) -> list:
    if slot is None:
        return []
    if depth > MAX_XML_DEPTH:
        raise ContractError("omml_nesting_exceeded")
    items = _merge_ast_items([_omml_ast(child, depth + 1) for child in slot])
    # Keep spaces between text runs without counting a blank slot as math content.
    return [item for item in items if item["k"] != "t" or item["v"].strip()]


def _omml_ast(node: ET.Element, depth: int = 0):
    """将 OMML 节点投影为无歧义结构化 AST，消除逗号/括号分隔符碰撞并跳过删除/隐藏节点。"""
    if depth > MAX_XML_DEPTH:
        raise ContractError("omml_nesting_exceeded")
    local = _local(node.tag)
    if (node.tag.startswith("{" + W + "}") and local in UNRESOLVED_WORD_CONTENT) or local in {
        "rPr", "fPr", "sSupPr", "sSubPr", "sSubSupPr", "radPr", "naryPr", "mPr", "dPr", "oMathParaPr", "ctrlPr",
    }:
        return None
    if node.tag == _m("oMathPara"):
        return {
            "k": "para",
            "items": [_omml_slot(child, depth + 1) for child in node if child.tag == _m("oMath")],
        }
    if local in {"oMath", "e", "num", "den", "sub", "sup", "deg"}:
        return _omml_slot(node, depth)
    if node.tag == _m("r"):
        if _run_is_hidden(node):
            return None
        val = "".join((child.text or "") for child in node if child.tag == _m("t"))
        return {"k": "t", "v": val} if val else None
    if node.tag == _m("f"):
        return {"k": "f", "n": _omml_slot(node.find(_m("num")), depth + 1),
                "d": _omml_slot(node.find(_m("den")), depth + 1)}
    if node.tag == _m("sSup"):
        return {"k": "sup", "e": _omml_slot(node.find(_m("e")), depth + 1),
                "p": _omml_slot(node.find(_m("sup")), depth + 1)}
    if node.tag == _m("sSub"):
        return {"k": "sub", "e": _omml_slot(node.find(_m("e")), depth + 1),
                "b": _omml_slot(node.find(_m("sub")), depth + 1)}
    if node.tag == _m("sSubSup"):
        return {
            "k": "subsup",
            "e": _omml_slot(node.find(_m("e")), depth + 1),
            "b": _omml_slot(node.find(_m("sub")), depth + 1),
            "p": _omml_slot(node.find(_m("sup")), depth + 1),
        }
    if node.tag == _m("rad"):
        pr = node.find(_m("radPr"))
        deg_hide = _omml_flag_on(pr, "degHide")
        deg = [] if deg_hide else _omml_slot(node.find(_m("deg")), depth + 1)
        return {"k": "rad", "g": deg, "e": _omml_slot(node.find(_m("e")), depth + 1)}
    if node.tag == _m("nary"):
        pr = node.find(_m("naryPr"))
        chr_el = pr.find(_m("chr")) if pr is not None else None
        op = chr_el.get(_m("val"), "∫") if chr_el is not None else "∫"
        sub_hide = _omml_flag_on(pr, "subHide")
        sup_hide = _omml_flag_on(pr, "supHide")
        return {
            "k": "nary",
            "op": op,
            "b": [] if sub_hide else _omml_slot(node.find(_m("sub")), depth + 1),
            "p": [] if sup_hide else _omml_slot(node.find(_m("sup")), depth + 1),
            "e": _omml_slot(node.find(_m("e")), depth + 1),
        }
    if node.tag == _m("m"):
        rows = [
            [_omml_slot(e, depth + 2) for e in mr.findall(_m("e"))]
            for mr in node.findall(_m("mr"))
        ]
        return {"k": "m", "rows": rows}
    if node.tag == _m("d"):
        pr = node.find(_m("dPr"))
        beg = pr.find(_m("begChr")).get(_m("val"), "(") if pr is not None and pr.find(_m("begChr")) is not None else "("
        end = pr.find(_m("endChr")).get(_m("val"), ")") if pr is not None and pr.find(_m("endChr")) is not None else ")"
        return {"k": "d", "beg": beg, "end": end, "e": [_omml_slot(e, depth + 1) for e in node.findall(_m("e"))]}
    return _omml_slot(node, depth)


def _canonical_omml(node: ET.Element) -> str:
    """生成保结构无歧义规范 JSON 签名：杜绝逗号/文本字面碰撞并跳过删除/隐藏节点。"""
    ast = _omml_ast(node)
    if not ast:
        return ""
    return canonical_bytes(ast).decode("utf-8")


def inspect_omml(element: ET.Element) -> dict:
    """回读 m:oMath 节点，严格校验父子结构槽位、隐藏属性、修订节点及深度限制，生成保结构哈希。"""
    issues: list[str] = []
    counts = {"sup": 0, "sub": 0, "subsup": 0, "frac": 0, "rad": 0, "nary": 0, "matrix": 0, "runs": 0}
    texts: list[str] = []
    revision_or_hidden: list[str] = []
    unsupported_tags: list[str] = []

    def has_content(slot: ET.Element | None) -> bool:
        if slot is None:
            return False
        try:
            return bool(_omml_slot(slot))
        except ContractError:
            return False

    def scan(node: ET.Element, parent_tag: str | None = None, in_unresolved: bool = False,
             in_hidden: bool = False, in_w_rpr: bool = False, depth: int = 0) -> None:
        if depth > MAX_XML_DEPTH:
            issues.append("omml_nesting_exceeded")
            return
        local = _local(node.tag)
        if ((node.tag != _m("t") and node.text) or (parent_tag is not None and node.tail)):
            issues.append("omml_unexpected_xml_text")
        if node.tag.startswith("{" + M + "}"):
            if local not in SUPPORTED_OMML_TAGS:
                unsupported_tags.append(local)
            elif parent_tag is None:
                if local not in {"oMath", "oMathPara"}:
                    unsupported_tags.append("root:" + local)
            elif parent_tag.startswith("{" + M + "}"):
                parent_local = _local(parent_tag)
                if local not in ALLOWED_OMML_CHILDREN.get(parent_local, frozenset()):
                    unsupported_tags.append(f"{parent_local}>{local}")
            else:
                unsupported_tags.append(f"non_math_parent>{local}")
        elif node.tag.startswith("{" + W + "}"):
            if local in REVISION_OR_HIDDEN_LOCAL or _word_hidden_on(node):
                revision_or_hidden.append(local)
            allow_w_rpr = parent_tag in {_m("r"), _m("ctrlPr")}
            is_allowed_w = (
                (local == "rPr" and allow_w_rpr)
                or (in_w_rpr and local in ALLOWED_WORD_RPR_CHILDREN)
            )
            if not is_allowed_w and local not in REVISION_OR_HIDDEN_LOCAL:
                unsupported_tags.append("w:" + local)
        else:
            unsupported_tags.append(node.tag)

        unresolved_here = in_unresolved or (node.tag.startswith("{" + W + "}") and local in UNRESOLVED_WORD_CONTENT)
        hidden_here = in_hidden or (node.tag == _m("r") and _run_is_hidden(node))

        if node.tag == _m("t") and not unresolved_here and not hidden_here:
            val = node.text or ""
            if val:
                texts.append(val)
            if val.strip():
                counts["runs"] += 1
        elif node.tag == _m("oMathPara"):
            omaths = node.findall(_m("oMath"))
            if len(omaths) < 1 or len(node.findall(_m("oMathParaPr"))) > 1 or any(not has_content(m) for m in omaths):
                issues.append("omml_para_slot_invalid")
        elif node.tag == _m("sSup"):
            counts["sup"] += 1
            e_list, sup_list = node.findall(_m("e")), node.findall(_m("sup"))
            if (len(e_list) != 1 or len(sup_list) != 1 or len(node.findall(_m("sSupPr"))) > 1
                    or not has_content(e_list[0]) or not has_content(sup_list[0])):
                issues.append("omml_sup_slot_empty")
        elif node.tag == _m("sSub"):
            counts["sub"] += 1
            e_list, sub_list = node.findall(_m("e")), node.findall(_m("sub"))
            if (len(e_list) != 1 or len(sub_list) != 1 or len(node.findall(_m("sSubPr"))) > 1
                    or not has_content(e_list[0]) or not has_content(sub_list[0])):
                issues.append("omml_sub_slot_empty")
        elif node.tag == _m("sSubSup"):
            counts["subsup"] += 1
            e_list, sub_list, sup_list = node.findall(_m("e")), node.findall(_m("sub")), node.findall(_m("sup"))
            if (len(e_list) != 1 or len(sub_list) != 1 or len(sup_list) != 1
                    or len(node.findall(_m("sSubSupPr"))) > 1
                    or not has_content(e_list[0]) or not has_content(sub_list[0]) or not has_content(sup_list[0])):
                issues.append("omml_subsup_slot_empty")
        elif node.tag == _m("f"):
            counts["frac"] += 1
            num_list, den_list = node.findall(_m("num")), node.findall(_m("den"))
            if (len(num_list) != 1 or len(den_list) != 1 or len(node.findall(_m("fPr"))) > 1
                    or not has_content(num_list[0]) or not has_content(den_list[0])):
                issues.append("omml_frac_slot_empty")
        elif node.tag == _m("rad"):
            counts["rad"] += 1
            e_list, deg_list, pr_list = node.findall(_m("e")), node.findall(_m("deg")), node.findall(_m("radPr"))
            if len(e_list) != 1 or len(deg_list) > 1 or len(pr_list) > 1 or not has_content(e_list[0]):
                issues.append("omml_rad_slot_empty")
            pr = pr_list[0] if pr_list else None
            if deg_list and _omml_flag_on(pr, "degHide") and has_content(deg_list[0]):
                revision_or_hidden.append("degHide")
        elif node.tag == _m("nary"):
            counts["nary"] += 1
            e_list, sub_list, sup_list, pr_list = (
                node.findall(_m("e")), node.findall(_m("sub")), node.findall(_m("sup")), node.findall(_m("naryPr")),
            )
            if (len(e_list) != 1 or len(sub_list) > 1 or len(sup_list) > 1 or len(pr_list) > 1
                    or not has_content(e_list[0])):
                issues.append("omml_nary_slot_empty")
            pr = pr_list[0] if pr_list else None
            if sub_list and _omml_flag_on(pr, "subHide") and has_content(sub_list[0]):
                revision_or_hidden.append("subHide")
            if sup_list and _omml_flag_on(pr, "supHide") and has_content(sup_list[0]):
                revision_or_hidden.append("supHide")
        elif node.tag == _m("m"):
            counts["matrix"] += 1
            rows = node.findall(_m("mr"))
            if (not rows or len(node.findall(_m("mPr"))) > 1
                    or any(not r.findall(_m("e")) or any(not has_content(c) for c in r.findall(_m("e"))) for r in rows)):
                issues.append("omml_matrix_slot_empty")
        elif node.tag == _m("d"):
            e_list = node.findall(_m("e"))
            if not e_list or len(node.findall(_m("dPr"))) > 1 or any(not has_content(e) for e in e_list):
                issues.append("omml_delim_slot_empty")
        elif node.tag == _m("r"):
            if len(node.findall(_m("rPr"))) > 1 or len(node.findall("{" + W + "}rPr")) > 1:
                unsupported_tags.append("duplicate_child:r>rPr")
        elif node.tag == _m("radPr"):
            for cname in ("degHide", "ctrlPr"):
                if len(node.findall(_m(cname))) > 1:
                    unsupported_tags.append(f"duplicate_child:radPr>{cname}")
        elif node.tag == _m("naryPr"):
            for cname in ("chr", "subHide", "supHide", "ctrlPr"):
                if len(node.findall(_m(cname))) > 1:
                    unsupported_tags.append(f"duplicate_child:naryPr>{cname}")
        elif node.tag == _m("dPr"):
            for cname in ("begChr", "endChr", "ctrlPr"):
                if len(node.findall(_m(cname))) > 1:
                    unsupported_tags.append(f"duplicate_child:dPr>{cname}")
        elif node.tag in {
            _m("oMathParaPr"), _m("rPr"), _m("fPr"), _m("sSupPr"), _m("sSubPr"), _m("sSubSupPr"), _m("mPr"),
        }:
            if len(node.findall(_m("ctrlPr"))) > 1:
                unsupported_tags.append(f"duplicate_child:{local}>ctrlPr")
        elif node.tag == _m("ctrlPr"):
            if len(node.findall("{" + W + "}rPr")) > 1:
                unsupported_tags.append("duplicate_child:ctrlPr>w:rPr")

        child_in_w_rpr = (node.tag == "{" + W + "}rPr" and parent_tag in {_m("r"), _m("ctrlPr")})
        for child in node:
            scan(child, node.tag, unresolved_here, hidden_here, child_in_w_rpr, depth + 1)

    scan(element)
    try:
        # Complex field markers can enclose sibling runs; do not project any of that formula.
        if "fldChar" in revision_or_hidden:
            texts.clear()
            canonical = ""
        else:
            canonical = _canonical_omml(element)
    except ContractError:
        issues.append("omml_nesting_exceeded")
        canonical = ""
    extracted_text = "".join(texts)
    if not extracted_text.strip() or not canonical.strip():
        issues.append("omml_empty_math_content")
    if revision_or_hidden:
        issues.append("omml_revision_or_hidden_present")
    if unsupported_tags:
        issues.append("omml_unsupported_element_present")
    if issues:
        canonical = ""
    return {
        "valid": not issues,
        "issues": sorted(set(issues)),
        "counts": counts,
        "extracted_text": extracted_text,
        "canonical_form": canonical,
        "structure_sha256": sha256_bytes(canonical.encode("utf-8")),
        "revision_or_hidden_nodes": sorted(set(revision_or_hidden)),
        "unsupported_omml_tags": sorted(set(unsupported_tags)),
        "visual_review": "not_performed",
    }
