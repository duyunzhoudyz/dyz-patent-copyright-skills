"""Phase D2: 声明式外部 Word 模板安全审计与映射器（纯标准库）。

允许用户传入合法授权的组织 .docx/.dotx 模板，按显式映射表灌入内容：
1. 流式限量防 Zip Bomb（按实际解压字节累计，不采信伪造 ZIP 头 file_size）；
2. Expat XML 解析钩子全面拦截 UTF-8/UTF-16/UTF-32 任意编码 DTD 与实体展开；
3. 审计全部 XML 部件（含自定义页眉页脚、glossary、settings、docProps），拦截宏/ActiveX/OLE/外链/
   修订/隐藏/域注入，仅在页眉/页脚中放行无 ffData 且严格配对的 PAGE/NUMPAGES 页码域；
4. 保留原模板 <w:document> 所有 xmlns:* 命名空间声明（含 mc:Ignorable 引用的前缀），且不污染进程全局
   ElementTree 命名空间注册表；自动转换 .dotx 为 .docx 并分配无冲突书签 ID。
"""
from __future__ import annotations

import io
import lzma
import os
import re
import stat
import unicodedata
import zipfile
import zlib
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote
from xml.dom import XMLNS_NAMESPACE, XML_NAMESPACE, minidom
from xml.etree import ElementTree as ET
from xml.parsers import expat

from tools import bundle, core, media_prep
from tools.core import ContractError, require, require_fields, sha256_bytes

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

MAX_TEMPLATE_BYTES = 20_000_000
MAX_MEMBER_COUNT = 250
MAX_UNCOMPRESSED_BYTES = 40_000_000
MAX_PART_BYTES = 8_000_000
MAX_XML_DEPTH = 128
MAX_XML_NODES = 150_000
REL_CONTENT_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
LICENSE_PLACEHOLDERS = {
    "unknown", "unspecified", "pending", "none", "n/a", "tbd", "todo", "未知", "待定", "未确认",
}
LICENSE_DENIED_EXACT = frozenset({
    "false", "no", "deny", "denied", "0", "否", "无", "不确认", "不同意", "不允许", "禁止",
    "保密", "机密", "绝密", "受限",
})
LICENSE_DENIED_EN_RE = re.compile(
    r"(?i)(?<![A-Za-z])("
    r"no\s+(?:(?:valid|legal|written|explicit|usage|use|distribution|redistribution|copy|template|commercial|copyright)\s+)*"
    r"(?:licen[cs]es?|permissions?|rights?|authori[sz]ation|authority|consent|approval|ownership)"
    r"|no\s+grant\s+of\s+(?:rights?|licen[cs]es?|permissions?)"
    r"|without\s+(?:prior\s+|written\s+|explicit\s+|valid\s+|legal\s+|owner\s+|holder\s+)?(?:a\s+|any\s+)?"
    r"(?:licen[cs]es?|permissions?|rights?|authori[sz]ation|consent|approval)"
    r"|unauthori[sz]ed|unlicen[cs]ed|unconfirmed|unverified|unapproved|unpermitted"
    r"|not\s+(?:yet\s+)?(?:authori[sz]ed|licen[cs]ed|permitted|allowed|confirmed|verified|granted|approved|cleared"
    r"|for\s+(?:use|distribution|redistribution|commercial|public|external|sharing))"
    r"|lacks?\s+(?:a\s+|any\s+)?(?:licen[cs]es?|permissions?|rights?|authori[sz]ation)"
    r"|lacking\s+(?:a\s+|any\s+)?(?:licen[cs]es?|permissions?|rights?|authori[sz]ation)"
    r"|(?:do|does|did)\s+not\s+have\s+(?:a\s+|any\s+)?(?:licen[cs]es?|permissions?|rights?|authori[sz]ation)"
    r"|(?:don'?t|doesn'?t)\s+have\s+(?:a\s+|any\s+)?(?:licen[cs]es?|permissions?|rights?|authori[sz]ation)"
    r"|(?:has|have|had)\s+not\s+been\s+(?:authori[sz]ed|licen[cs]ed|permitted|approved|granted|confirmed|verified)"
    r"|not\s+(?:yet\s+)?(?:entitled\s+to|the\s+(?:copyright|rights?)\s+(?:owner|holder)|the\s+owner|mine|ours)"
    r"|(?:not|never)\s+(?:obtained|received|secured|confirmed|granted)\b[^.!?;,:]{0,60}?"
    r"\b(?:licen[cs]es?|permissions?|rights?|authori[sz]ation|consent|approval)"
    r"|(?:do(?:es)?\s+not|don'?t|doesn'?t)\s+(?:own|hold|confirm)\b[^.!?;,:]{0,60}?"
    r"\b(?:copyright|template|licen[cs]es?|permissions?|rights?|authori[sz]ation)"
    r"|(?:licen[cs]es?|permissions?|rights?|authori[sz]ation|use|usage|redistribution|distribution)\s+"
    r"(?:is\s+|are\s+|was\s+|were\s+)?(?:not\s+(?:granted|obtained|confirmed|verified|given|available|permitted|allowed|authori[sz]ed)"
    r"|denied|refused|revoked|prohibited|forbidden|restricted|missing|absent|unavailable)"
    r"|(?:requires?|needs?|awaiting|pending|subject\s+to)\s+(?:prior\s+)?(?:explicit\s+|express\s+|formal\s+)?(?:written\s+)?"
    r"(?:authori[sz]ation|permission|licen[cs]e|consent|approval)"
    r"|(?:prior\s+)?(?:explicit\s+|express\s+|formal\s+)?(?:written\s+)?"
    r"(?:authori[sz]ation|permission|licen[cs]e|consent|approval)\s+(?:is\s+|are\s+)?(?:required|needed|necessary|pending|missing)"
    r"|prohibited|forbidden|denied|revoked|disallowed|refused|rejected|pirated|infringing|stolen|illegally\s+obtained"
    r"|(?:do\s+not|don'?t|cannot|can\s+not|must\s+not|may\s+not|shall\s+not)\s+(?:be\s+)?"
    r"(?:used?|redistributed?|distributed?|copied|copy|shared?|modified|modify|reused?|published|mapped)"
    r"|proprietary|confidential|trade\s+secret|classified"
    r"|restricted\s+(?:access|template|document|material|use)"
    r"|(?:for\s+)?(?:reference|internal\s+(?:use|reference|review)|view|read|evaluation|inspection|non\s*commercial)\s+only"
    r")(?![A-Za-z])"
)
LICENSE_DENIED_ZH_RE = re.compile(
    r"无权(?:使用|复制|修改|处理|访问|映射|套用|分发|再分发|传播|发布|商用|提供)?"
    r"|(?:无|没有|缺乏|缺少)(?:任何|有效|合法|正式|书面|明确)?(?:使用|分发|再分发|复制|修改|映射|商业|商用|模板)?(?:授权|许可|使用权|分发权|复制权|权利)"
    r"|(?:没有|无)(?:任何|有效|合法)?(?:版权|著作权)"
    r"|不(?:享有|拥有|具备|具有|持有).{0,6}?(?:使用权|分发权|复制权|修改权|著作权|版权|知识产权|授权|许可|权利)"
    r"|(?:未|没有|没|尚未)(?:被|获|获得|取得|拿到|拥有|具备|享有)[^，。；！？,.!?;]{0,32}?(?:授权|许可|批准|允许|同意|使用权|分发权|版权|著作权|权利)"
    r"|未经.{0,8}?(?:授权|许可|批准|允许|同意)"
    r"|(?:未|非|待|尚未)(?:被)?(?:授权|许可|确认|核实)"
    r"|(?:无|不)(?:授权|许可)(?:使用|映射|复制|分发|再分发|商用)"
    r"|(?:尚需|仍需|有待|须另行|需先)(?:取得|获得|征得)?[^，。；！？,.!?;]{0,16}?(?:授权|许可|同意)"
    r"|(?:不是|并非)(?:本模板|该模板)?(?:的)?(?:权利人|著作权人|版权方|所有者|自有模板|原创模板)"
    r"|(?:不予|未予|暂不|暂未)(?:提供)?(?:授权|许可|批准|同意)"
    r"|(?:禁止|严禁|不得|不准|不可|不允许)(?:用于|使用|复制|修改|处理|映射|套用|分发|再分发|传播|外传|泄露|商用|商业使用|二次开发|对外提供)"
    r"|拒绝(?:提供)?(?:授权|许可|使用|分发)|(?:撤销|撤回)(?:授权|许可)"
    r"|仅(?:限|供|作)(?:内部)?(?:参考|查阅|阅览|预览|学习|观摩)"
    r"|(?:内部|公司|企业|机构|商业|高度)?(?:保密|机密|绝密)|内部受限|保密(?:文件|模板|材料|资料)"
    r"|侵权|盗版|非法来源|来历不明|来源不明"
)
LICENSE_RESERVED_RE = re.compile(
    r"(?i)(?<![A-Za-z])all\s+rights?\s+reserved(?![A-Za-z])"
    r"|保留(?:所有|一切|全部)权利"
)
LICENSE_EXPLICIT_WRITTEN_GRANT_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?:"
    r"(?:explicit|express|formal)?\s*written\s+"
    r"(?:authori[sz]ation|permission|licen[cs]e|consent|grant)\s+"
    r"(?:has\s+been\s+|was\s+|is\s+)?(?:granted|obtained|received|issued|confirmed|approved|verified|held|given|secured)"
    r"|(?:has|have|had|obtained|received|granted|confirmed|verified|holds?|secured)\s+"
    r"(?:an?\s+|the\s+|owner'?s?\s+|holder'?s?\s+)?"
    r"(?:explicit|express|formal)?\s*written\s+"
    r"(?:authori[sz]ation|permission|licen[cs]e|consent|grant)"
    r")(?![A-Za-z])"
    r"|(?:已|已经)(?:获|获得|取得|持有|收到)(?:权利人|版权方|著作权人)?(?:明确|正式)?书面(?:授权|许可|同意)"
)
_ZH_CLEARED_ITEM = (
    r"(?:(?:第三方|外部|他人)(?:的)?)?"
    r"(?:(?:未(?:经|获)?(?:授权|许可|批准)|未经(?:他人|权利人|第三方)?(?:授权|许可)|侵权|盗版|受限|保密|机密|绝密|专有)"
    r"(?:或|及|与|、)?){1,3}"
    r"(?:的)?(?:第三方|外部|他人)?(?:的)?"
    r"(?:材料|内容|素材|组件|代码|信息|数据|元素|文件|文档|片段|部分|资产|资料|部件|资源)"
)
_ZH_BENIGN_CLEARANCE_RE = re.compile(
    r"(?<!并非)(?<!不是)(?:"
    r"(?:无|没有|不存在|不涉及|不含|不包含)(?:任何)?"
    r"(?:第三方|外部|他人|其他方?)?(?:的)?"
    r"(?:版权|著作权|知识产权|权利|授权|许可|使用|分发|再分发|商用|商业使用)"
    r"(?:限制|约束|障碍|争议|纠纷|瑕疵|负担|冲突|风险|问题|壁垒)"
    r"|(?:不含|不包含|不存在|无|没有|不涉及|未含|未包含|未引入|已清除|已移除|已剔除)(?:任何)?"
    + _ZH_CLEARED_ITEM
    + r"(?:(?:及|与|或|和|、)"
    + _ZH_CLEARED_ITEM
    + r"){0,2}"
    r"|非(?:保密|机密|绝密|受限)"
    r"|(?:不构成|无|没有|不存在)(?:任何)?(?:侵权|盗版)(?:行为|风险|问题|争议|纠纷)?"
    r")"
)
_EN_CLEARED_MOD = (
    r"(?:unauthori[sz]ed|unlicen[cs]ed|unapproved|unpermitted|infringing|pirated"
    r"|proprietary|confidential|classified|restricted)"
)
_EN_CLEARED_NOUN = (
    r"(?:materials?|contents?|assets?|code|components?|elements?|data|information|files?|parts?|sections?|templates?)"
)
_EN_CLEARED_ITEM = (
    r"(?:(?:third[\s\-]?party|external)\s+)?"
    + _EN_CLEARED_MOD
    + r"(?:\s*(?:,|or|and)\s*"
    + _EN_CLEARED_MOD
    + r"){0,2}\s+"
    r"(?:(?:third[\s\-]?party|external)\s+)?"
    + _EN_CLEARED_NOUN
)
_EN_BENIGN_CLEARANCE_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?<!not\s)(?:"
    r"(?:no|without|free\s+(?:of|from))\s+(?:any\s+)?"
    r"(?:third[\s\-]?party\s+|external\s+)?"
    r"(?:copyright|ip|intellectual\s+property|licen[cs]e|permission|rights?|usage|use|distribution|redistribution)\s+"
    r"(?:restrictions?|limitations?|encumbrances?|conflicts?|disputes?|claims?|barriers?|issues?)"
    r"|(?:contains?\s+no|does\s+not\s+contain|do\s+not\s+contain|without|free\s+(?:of|from)|no)\s+(?:any\s+)?"
    + _EN_CLEARED_ITEM
    + r"(?:\s*(?:,|or|and)\s*"
    + _EN_CLEARED_ITEM
    + r"){0,2}"
    r"|non[\s\-]?(?:confidential|proprietary|restricted|infringing)"
    r")(?![A-Za-z])"
)
_EN_SEP_RE = re.compile(r"[\s_\-./\\·•*|`'\"~+\u2010-\u2015\u2212]+")
_EN_INTERLETTER_PUNCT_RE = re.compile(r"(?<=[A-Za-z])[._·•*\-](?=[A-Za-z])")
_EN_SPACED_LETTERS_RE = re.compile(r"(?<![A-Za-z])(?:[A-Za-z] )+[A-Za-z](?![A-Za-z])")
_ZH_SINGLE_CHAR_SPLIT_RE = re.compile(
    r"(?<![\u4e00-\u9fff])(?:[\u4e00-\u9fff][,，、;；:：]){2,}[\u4e00-\u9fff](?![\u4e00-\u9fff])"
)
_FORBIDDEN_INVISIBLE_CHARS = frozenset({
    "\u034f",  # COMBINING GRAPHEME JOINER
    "\u115f",  # HANGUL CHOSEONG FILLER
    "\u1160",  # HANGUL JUNGSEONG FILLER
    "\u180e",  # MONGOLIAN VOWEL SEPARATOR
    "\u2800",  # BRAILLE PATTERN BLANK
    "\u3164",  # HANGUL FILLER
    "\uffa0",  # HALFWIDTH HANGUL FILLER
})
_EDGE_PUNCT_STRIP = " \t\r\n,，.。;；:：!！?？()（）[]【】{}《》\"'“”‘’、/\\|·•*_-~"

FORBIDDEN_INLINE_LOCAL = frozenset({
    "txbxcontent", "txbody", "object", "oleobject", "altchunk", "ffdata", "flddata", "delinstrtext",
    "deltext", "fldchar", "fldsimple", "instrtext", "ins", "del", "cellins", "celldel", "cellmerge",
    "customxml", "datastoreitem", "subdoc", "contentpart", "vanish", "webhidden",
    "specvanish", "trackrevisions", "script",
    "pict", "sdt", "control", "alternatecontent", "commentrangestart", "commentrangeend",
    "comment", "annotationref", "commentreference", "movefrom", "moveto", "movefromrangestart", "movefromrangeend",
    "movetorangestart", "movetorangeend",
})
FORBIDDEN_CT_FRAGMENTS = ("macroenabled", "vbaproject", "vbadata", "oleobject", "activex")
FORBIDDEN_REL_TYPES = ("vbaproject", "oleobject", "activex", "attachedtemplate", "afchunk", "frame", "subdocument")
BOOKMARK_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,38}$")
XML_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _has_forbidden_license_ctrl(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        cat = unicodedata.category(ch)
        if (
            cat in {"Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
            or (cat == "Cc" and ch not in "\t\n\r")
            or ch in _FORBIDDEN_INVISIBLE_CHARS
            or 0xFE00 <= code <= 0xFE0F
            or 0xE0100 <= code <= 0xE01EF
        ):
            return True
    return False


def _strip_benign_clearance_phrases(text: str) -> str:
    cleaned = _ZH_BENIGN_CLEARANCE_RE.sub(" ", text)
    cleaned = _EN_BENIGN_CLEARANCE_RE.sub(" ", cleaned)
    return cleaned


def _unspace_letters(text: str) -> str:
    prep = re.sub(r"[ \t\r\n]{2,}", "  ", text)
    prep = re.sub(r"[\t\r\n]", " ", prep)
    merged = _EN_SPACED_LETTERS_RE.sub(lambda m: m.group(0).replace(" ", ""), prep)
    return re.sub(r"\s+", " ", merged).strip()


def _validate_license_declaration(decl: object) -> None:
    require(isinstance(decl, dict), "template_license_declaration_required")
    fields = ("origin", "license_basis", "user_confirmed_rights")
    require(decl.keys() == set(fields), "template_license_declaration_required")
    has_reserved = False
    has_written_grant = False
    for k in fields:
        raw_val = decl.get(k)
        require(isinstance(raw_val, str) and bool(raw_val.strip()), "template_license_declaration_required")
        require(not _has_forbidden_license_ctrl(raw_val), "template_license_denied_or_unconfirmed")
        nfkc = unicodedata.normalize("NFKC", raw_val)
        require(not _has_forbidden_license_ctrl(nfkc), "template_license_denied_or_unconfirmed")
        # 权利措辞检测剥离组合标记，保留原声明供回读。
        normalized_declaration = unicodedata.normalize(
            "NFKC", "".join(ch for ch in unicodedata.normalize("NFKD", nfkc)
                            if unicodedata.category(ch) not in {"Mn", "Me"}),
        )
        norm = re.sub(r"\s+", "", normalized_declaration).strip(_EDGE_PUNCT_STRIP).casefold()
        require(bool(norm) and norm not in LICENSE_PLACEHOLDERS,
                "template_license_declaration_required")

        # 仅剥离明确排除第三方/负向障碍的局部短语，对剩余文本执行全量否定词与反混淆校验
        cleared_raw = _strip_benign_clearance_phrases(normalized_declaration)
        cleared_norm = re.sub(r"\s+", " ", cleared_raw).strip()
        cleared_edge = cleared_norm.strip(_EDGE_PUNCT_STRIP)
        en_sep = _EN_SEP_RE.sub(" ", cleared_norm).strip()
        en_deobf = _EN_INTERLETTER_PUNCT_RE.sub("", cleared_norm)
        en_unspaced_raw = _unspace_letters(cleared_raw)
        en_unspaced_sep = _EN_SPACED_LETTERS_RE.sub(lambda m: m.group(0).replace(" ", ""), en_sep)
        en_unspaced_sep = re.sub(r"\s+", " ", en_unspaced_sep).strip()
        zh_compact = _EN_SEP_RE.sub("", cleared_norm)
        zh_split_merged = _ZH_SINGLE_CHAR_SPLIT_RE.sub(
            lambda m: re.sub(r"[,，、;；:：]+", "", m.group(0)),
            zh_compact,
        )

        exact_candidates = (
            cleared_norm,
            cleared_edge,
            en_sep,
            en_deobf,
            en_unspaced_raw,
            en_unspaced_sep,
            zh_compact,
            zh_split_merged,
        )
        en_candidates = (cleared_norm, en_sep, en_deobf, en_unspaced_raw, en_unspaced_sep)
        zh_candidates = (cleared_norm, zh_compact, zh_split_merged)
        require(
            all(cand.casefold() not in LICENSE_DENIED_EXACT for cand in exact_candidates)
            and all(LICENSE_DENIED_EN_RE.search(cand) is None for cand in en_candidates)
            and all(LICENSE_DENIED_ZH_RE.search(cand) is None for cand in zh_candidates),
            "template_license_denied_or_unconfirmed",
        )

        norm_declaration = re.sub(r"\s+", " ", normalized_declaration).strip()
        full_en_sep = _EN_SEP_RE.sub(" ", norm_declaration).strip()
        full_en_deobf = _EN_INTERLETTER_PUNCT_RE.sub("", norm_declaration)
        full_en_unspaced_raw = _unspace_letters(normalized_declaration)
        full_en_unspaced = _EN_SPACED_LETTERS_RE.sub(lambda m: m.group(0).replace(" ", ""), full_en_sep)
        full_zh_compact = _EN_SEP_RE.sub("", norm_declaration)
        if (
            LICENSE_RESERVED_RE.search(full_en_sep) is not None
            or LICENSE_RESERVED_RE.search(full_en_deobf) is not None
            or LICENSE_RESERVED_RE.search(full_en_unspaced_raw) is not None
            or LICENSE_RESERVED_RE.search(full_en_unspaced) is not None
            or LICENSE_RESERVED_RE.search(full_zh_compact) is not None
        ):
            has_reserved = True
        if (
            LICENSE_EXPLICIT_WRITTEN_GRANT_RE.search(full_en_sep) is not None
            or LICENSE_EXPLICIT_WRITTEN_GRANT_RE.search(full_zh_compact) is not None
        ):
            has_written_grant = True
    if has_reserved:
        require(has_written_grant, "template_license_denied_or_unconfirmed")


def _is_custom_xml_path(name: str) -> bool:
    first = unquote(name)
    second = unquote(first)
    return any("customxml" in variant.lower() for variant in (name, first, second))


def _w(tag: str) -> str:
    return "{" + W + "}" + tag


def _reject_dtd_expat(raw: bytes) -> None:
    """使用 Expat 解析钩子拒绝任何编码（UTF-8/UTF-16/UTF-32）的 DTD 与实体声明。"""
    def _deny(*_args, **_kwargs):
        raise ContractError("template_dtd_forbidden")

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = _deny
    parser.EntityDeclHandler = _deny
    parser.UnparsedEntityDeclHandler = _deny
    parser.ExternalEntityRefHandler = _deny
    try:
        parser.Parse(raw, True)
    except ContractError:
        raise
    except expat.ExpatError as exc:
        raise ContractError("template_xml_invalid") from exc


def _parse_xml_strict(raw: bytes, code: str = "template_xml_invalid") -> ET.Element:
    _reject_dtd_expat(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ContractError(code) from exc
    stack = [iter((root,))]
    count = 0
    while stack:
        node = next(stack[-1], None)
        if node is None:
            stack.pop()
            continue
        count += 1
        require(count <= MAX_XML_NODES and len(stack) <= MAX_XML_DEPTH, "template_xml_limits_exceeded")
        if len(node):
            stack.append(iter(node))
    return root


def _read_zip_parts(template_bytes: bytes) -> tuple[list[str], dict[str, bytes]]:
    require(isinstance(template_bytes, (bytes, bytearray)) and 0 < len(template_bytes) <= MAX_TEMPLATE_BYTES,
            "template_size_invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(template_bytes)) as archive:
            infos = archive.infolist()
            require(0 < len(infos) <= MAX_MEMBER_COUNT, "template_member_limit_exceeded")
            names: list[str] = []
            seen_lower: set[str] = set()
            total_uncompressed = 0
            parts: dict[str, bytes] = {}
            for info in infos:
                name = info.filename
                if info.is_dir() or name.endswith("/"):
                    continue
                unq_name = unquote(name)
                low_name = name.lower()
                unq_low = unq_name.lower()
                require(low_name not in seen_lower and unq_low not in seen_lower, "template_duplicate_zip_member")
                require(not (info.flag_bits & 1), "template_encrypted_zip_forbidden")
                for variant in (name, unq_name):
                    require(
                        "\x00" not in variant
                        and not variant.startswith(("/", "\\")) and "\\" not in variant
                        and all(part not in {"", ".", ".."} for part in variant.split("/")),
                        "template_unsafe_zip_member_path",
                    )
                # 流式限量解压，按真实解压字节累计，完全不信任伪造的 info.file_size
                with archive.open(info, "r") as stream:
                    raw = stream.read(MAX_PART_BYTES + 1)
                require(len(raw) <= MAX_PART_BYTES, "template_part_size_exceeded")
                total_uncompressed += len(raw)
                require(total_uncompressed <= MAX_UNCOMPRESSED_BYTES, "template_uncompressed_limit_exceeded")
                seen_lower.add(low_name)
                seen_lower.add(unq_low)
                names.append(name)
                parts[name] = raw
    except (zipfile.BadZipFile, zlib.error, lzma.LZMAError, EOFError, OSError, NotImplementedError, RuntimeError) as exc:
        raise ContractError("template_zip_invalid") from exc
    return names, parts


def _benign_hf_pagination_only(tree: ET.Element) -> bool:
    """按严格文档顺序状态机检查页眉/页脚域：仅允许无子节点的 begin -> instrText(PAGE|NUMPAGES) -> separate -> end。"""
    state = "idle"
    for node in tree.iter():
        local = node.tag.rsplit("}", 1)[-1].lower()
        if local in {"ffdata", "flddata", "fldsimple", "delinstrtext"}:
            return False
        if local == "fldchar":
            if len(node) != 0:
                return False
            ftype = (node.get(_w("fldCharType")) or "").strip().lower()
            if ftype == "begin" and state == "idle":
                state = "begin"
            elif ftype == "separate" and state == "instr":
                state = "separate"
            elif ftype == "end" and state == "separate":
                state = "idle"
            else:
                return False
        elif local == "instrtext":
            if len(node) != 0 or state != "begin":
                return False
            val = "".join(node.itertext()).strip().lower()
            if val not in {"page", "numpages"}:
                return False
            state = "instr"
    return state == "idle"


def _is_external_rel_target(tmode: str, target: str) -> bool:
    if tmode == "external":
        return True
    if not target:
        return False
    for variant in (target, unquote(target)):
        if ":" in variant or "\\" in variant or variant.startswith("//"):
            return True
    return False


def _normalize_word_rel_target(target: str) -> set[str]:
    results: set[str] = set()
    if not target:
        return results
    for variant in (target, unquote(target)):
        if "\\" in variant or ":" in variant or variant.startswith("//"):
            return set()
        clean = variant.lstrip("/")
        parts = clean.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return set()
        if not clean.lower().startswith("word/"):
            clean = "word/" + clean
        low = clean.lower()
        if low == "word/document.xml":
            return set()
        results.add(low)
    return results


def _is_rels_location(low_path: str) -> bool:
    if low_path == "_rels/.rels":
        return True
    parts = low_path.split("/")
    return len(parts) >= 2 and parts[-2] == "_rels" and parts[-1] != ".rels" and parts[-1].endswith(".rels")


def audit_template(template_bytes: bytes) -> dict:
    """只读审计外部 DOCX/DOTX 模板：覆盖全部 XML/rels 部件（大小写与 OPC 编码无关），拦截宏/ActiveX/OLE/外链/隐藏/DTD。"""
    names, parts = _read_zip_parts(template_bytes)
    by_lower = {name.lower(): name for name in names}
    doc_name = by_lower.get("word/document.xml")
    ct_name = by_lower.get("[content_types].xml")
    styles_name = by_lower.get("word/styles.xml")
    require(doc_name is not None and ct_name is not None, "template_opc_parts_missing")

    forbidden_parts: list[str] = []
    forbidden_custom_xml_parts: list[str] = []
    for name in names:
        variants = (name.lower(), unquote(name).lower())
        if _is_custom_xml_path(name):
            forbidden_custom_xml_parts.append(name)
        if any(
            v.endswith(".bin")
            or "vbaproject" in v
            or "vbadata" in v
            or v.startswith("word/embeddings/")
            or v.startswith("word/activex/")
            for v in variants
        ):
            forbidden_parts.append(name)

    ct_tree = _parse_xml_strict(parts[ct_name])
    default_cts: dict[str, set[str]] = {}
    override_cts: dict[str, set[str]] = {}
    for node in ct_tree.iter():
        local_ct = node.tag.rsplit("}", 1)[-1].lower()
        ctype = (node.get("ContentType") or "").strip().lower()
        part_name = (node.get("PartName") or "").strip().lower()
        unq_part_name = unquote(part_name)
        if local_ct == "default":
            ext = (node.get("Extension") or "").strip().lower().lstrip(".")
            if ext:
                if ext in default_cts:
                    forbidden_parts.append(f"duplicate_content_type_default:{ext}")
                default_cts.setdefault(ext, set()).add(ctype)
        elif local_ct == "override" and part_name:
            norm_raw = part_name.lstrip("/")
            norm_unq = unquote(norm_raw)
            if norm_raw in override_cts or norm_unq in override_cts:
                forbidden_parts.append(f"duplicate_content_type_override:{norm_raw}")
            override_cts.setdefault(norm_raw, set()).add(ctype)
            override_cts.setdefault(norm_unq, set()).add(ctype)
        if ("customxml" in ctype or _is_custom_xml_path(part_name)):
            forbidden_custom_xml_parts.append(f"content_type:{node.get('PartName') or ctype}")
        if (any(frag in ctype for frag in FORBIDDEN_CT_FRAGMENTS)
                or "vbadata" in part_name or "vbaproject" in part_name
                or "vbadata" in unq_part_name or "vbaproject" in unq_part_name
                or "vmldrawing" in ctype or "svg+xml" in ctype):
            forbidden_parts.append(f"content_type:{node.get('PartName') or ctype}")

    def content_types(name):
        decoded = unquote(name)
        overrides = override_cts.get(name, set()) | override_cts.get(decoded, set())
        if overrides:
            return overrides
        return default_cts.get(decoded.rsplit(".", 1)[-1], set())

    external_links = []
    hf_targets: set[str] = set()
    verified_rels_parts: set[str] = set()
    for name, raw in parts.items():
        low_rel = name.lower()
        unq_rel = unquote(low_rel)
        effective_rel_cts = content_types(low_rel)
        rel_extension = low_rel.endswith(".rels") or unq_rel.endswith(".rels")
        if rel_extension or REL_CONTENT_TYPE in effective_rel_cts:
            if not (_is_rels_location(low_rel) and _is_rels_location(unq_rel)):
                forbidden_parts.append(f"misplaced_rels:{name}")
                if REL_CONTENT_TYPE not in effective_rel_cts:
                    continue
            if effective_rel_cts and effective_rel_cts != {REL_CONTENT_TYPE}:
                forbidden_parts.append(f"rels_content_type_override:{name}")
                continue
            tree = _parse_xml_strict(raw)
            if (tree.tag != "{" + REL + "}Relationships"
                    or any(c.tag != "{" + REL + "}Relationship" or len(c) != 0 for c in tree)):
                forbidden_parts.append(f"invalid_rels_structure:{name}")
                continue
            verified_rels_parts.add(low_rel)
            for rel in tree.findall("{" + REL + "}Relationship"):
                tmode = (rel.get("TargetMode") or "").strip().lower()
                rtype = (rel.get("Type") or "").strip().lower()
                target = (rel.get("Target") or "").strip()
                if _is_external_rel_target(tmode, target):
                    external_links.append({"part": name, "id": rel.get("Id"), "target": target})
                if "customxml" in rtype or _is_custom_xml_path(target):
                    forbidden_custom_xml_parts.append(f"rel:{name}:{rel.get('Id')}")
                if any(frag in rtype for frag in FORBIDDEN_REL_TYPES):
                    forbidden_parts.append(f"rel:{name}:{rel.get('Id')}")
                # _rels/.rels 中的 officeDocument 必须指向 word/document.xml，防止通过替换主文档路径绕过审计！
                if (low_rel == "_rels/.rels" or unq_rel == "_rels/.rels") and rtype.endswith("/officedocument"):
                    norm_doc = unquote(target).lstrip("/").lower()
                    if norm_doc != "word/document.xml":
                        forbidden_parts.append(f"rel_officedocument:{target}")
                # 仅信任 word/_rels/document.xml.rels 中的合法页眉/页脚目标，且绝不允许将 document.xml 冒充页眉/页脚
                if (low_rel == "word/_rels/document.xml.rels" or unq_rel == "word/_rels/document.xml.rels") and (
                    rtype.endswith("/header") or rtype.endswith("/footer")
                ):
                    hf_targets.update(_normalize_word_rel_target(target))

    styles = []
    paragraph_styles = []
    styles_tree = None
    if styles_name is not None:
        styles_tree = _parse_xml_strict(parts[styles_name])
        for style in styles_tree.findall(_w("style")):
            sid = style.get(_w("styleId"))
            stype = (style.get(_w("type")) or "paragraph").lower()
            if sid:
                styles.append(sid)
                if stype == "paragraph":
                    paragraph_styles.append(sid)

    doc_tree = _parse_xml_strict(parts[doc_name])
    bookmark_names = [node.get(_w("name")) for node in doc_tree.iter(_w("bookmarkStart"))
                      if node.get(_w("name"))]
    bookmarks = sorted(set(bookmark_names))
    duplicate_bookmark = len({name.casefold() for name in bookmark_names}) != len(bookmark_names)
    tables = list(doc_tree.findall("./" + _w("body") + "/" + _w("tbl")))

    # 全面审计所有 XML 类部件（统一按原始名与 OPC unquote 名双重匹配扩展名、ContentType 与 rels 目标）！
    unsupported_inline: set[str] = set()
    unsafe_attachments = []
    for pname in names:
        low_p = pname.lower()
        unq_p = unquote(low_p)
        if low_p == "[content_types].xml" or low_p in verified_rels_parts:
            continue
        declared_cts = content_types(low_p)
        if (low_p.endswith((".vml", ".svg"))
                or unq_p.endswith((".vml", ".svg"))
                or any("vmldrawing" in ct or "svg+xml" in ct for ct in declared_cts)):
            forbidden_parts.append(f"xml_part:{pname}")
        is_allowed_xml_path = low_p.endswith(".xml") and unq_p.endswith(".xml")
        is_xml_like = (
            is_allowed_xml_path
            or low_p.endswith((".vml", ".svg", ".rels"))
            or unq_p.endswith((".vml", ".svg", ".rels"))
            or any("xml" in ct or "vml" in ct for ct in declared_cts)
            or low_p in hf_targets
            or unq_p in hf_targets
        )
        if not is_xml_like:
            if (declared_cts == {"image/png"}
                    and low_p == unq_p
                    and re.fullmatch(r"word/media/[a-z0-9_.-]+\.png", low_p)):
                try:
                    checked = media_prep.strip_png_ancillary_chunks(parts[pname])
                    if not checked["stripped_chunks"]:
                        continue
                except ContractError:
                    pass
            unsafe_attachments.append(pname)
            continue
        if not is_allowed_xml_path or (declared_cts and not all("xml" in ct for ct in declared_cts)):
            unsafe_attachments.append(pname)
        if pname == doc_name:
            tree = doc_tree
        elif pname == styles_name and styles_tree is not None:
            tree = styles_tree
        else:
            try:
                tree = _parse_xml_strict(parts[pname])
            except ContractError as exc:
                if not is_allowed_xml_path and str(exc) == "template_xml_invalid":
                    continue
                raise
        is_hf = (low_p != "word/document.xml" and unq_p != "word/document.xml") and (
            low_p in hf_targets
            or unq_p in hf_targets
            or bool(re.fullmatch(r"word/(?:header|footer)\d*\.xml", low_p))
            or bool(re.fullmatch(r"word/(?:header|footer)\d*\.xml", unq_p))
        )
        hf_fields_benign = is_hf and _benign_hf_pagination_only(tree)
        for node in tree.iter():
            tag_low = node.tag.lower()
            ns_part = tag_low.split("}", 1)[0] if "}" in tag_low else ""
            local = tag_low.rsplit("}", 1)[-1]
            if "customxml" in ns_part:
                forbidden_custom_xml_parts.append(f"xml_ns:{pname}")
            if local in FORBIDDEN_INLINE_LOCAL or local.endswith("change"):
                if hf_fields_benign and local in {"fldchar", "instrtext"}:
                    continue
                unsupported_inline.add(local)

    blocked_reasons = []
    if forbidden_parts:
        blocked_reasons.append("template_macros_or_ole_forbidden")
    if forbidden_custom_xml_parts:
        blocked_reasons.append("template_custom_xml_parts_forbidden")
    if external_links:
        blocked_reasons.append("template_external_links_forbidden")
    if unsupported_inline:
        blocked_reasons.append("template_unsupported_inline_objects_forbidden")
    if unsafe_attachments:
        blocked_reasons.append("template_attachment_unsupported")
    if duplicate_bookmark:
        blocked_reasons.append("template_bookmark_name_collision")

    return {
        "schema": "dyz-template-audit-v1",
        "template_sha256": sha256_bytes(template_bytes),
        "status": "rejected" if blocked_reasons else "audited_ready_for_declarative_mapping",
        "blocked_reasons": blocked_reasons,
        "forbidden_parts": sorted(set(forbidden_parts)),
        "forbidden_custom_xml_parts": sorted(set(forbidden_custom_xml_parts)),
        "external_links": external_links,
        "unsupported_attachments": unsafe_attachments,
        "styles": sorted(set(styles)),
        "paragraph_styles": sorted(set(paragraph_styles)),
        "bookmarks": bookmarks,
        "table_count": len(tables),
        "unsupported_inline_objects": sorted(unsupported_inline),
        "official_compliance_claimed": False,
        "visual_review": "not_performed",
    }


def _template_path(base: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(relative), "relative_path_required")
    parts = relative.replace("\\", "/").split("/")
    require(not PureWindowsPath(relative).drive and not any(c in relative for c in ":\x00")
            and all(part not in {"", ".", ".."} and part == part.rstrip(" .")
                    and not core.is_reserved_windows_name(part) for part in parts), "unsafe_path")
    return base.joinpath(*parts)


def _read_template(src: Path, *, propagate_io: bool = False) -> bytes:
    try:
        info = core.checked_path(src)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "template_file_or_link_invalid")
        require(0 < info.st_size <= MAX_TEMPLATE_BYTES, "template_size_invalid")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(src, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            require(os.path.samestat(info, opened) and opened.st_nlink == 1, "template_file_changed")
            raw = stream.read(MAX_TEMPLATE_BYTES + 1)
        require(len(raw) == info.st_size, "template_file_changed")
        return raw
    except (OSError, bundle.BundleError) as exc:
        if propagate_io:
            if isinstance(exc, OSError):
                raise
            if str(exc) == "bundle_path_missing":
                raise FileNotFoundError("template_missing") from None
        raise ContractError("template_path_invalid") from None


def inspect_template(root: str | Path, relative: str) -> dict:
    """只读取获准根目录内的模板，不运行 Office 或写入文件。"""
    try:
        src = _template_path(bundle._absolute(root), relative)
    except bundle.BundleError:
        raise ContractError("template_path_invalid") from None
    return audit_template(_read_template(src, propagate_io=True))


def _max_bookmark_id(doc_tree: minidom.Document) -> int:
    highest = 0
    for tag in ("bookmarkStart", "bookmarkEnd"):
        for node in doc_tree.getElementsByTagNameNS(W, tag):
            raw_id = node.getAttributeNS(W, "id")
            if raw_id and raw_id.isascii() and raw_id.isdigit():
                highest = max(highest, int(raw_id))
    return highest


def apply_template_mapping(
    root: str | Path,
    *,
    template_path: str,
    output_path: str,
    mapping_spec: dict,
    sections: list[dict],
) -> dict:
    """按声明式样式映射表把分段内容写入用户提供的合法模板副本，原模板字节保持不变。"""
    require(isinstance(mapping_spec, dict), "template_mapping_spec_required")
    require_fields(mapping_spec, ("profile_id", "license_and_origin_declaration", "style_map"))
    require(mapping_spec.keys() == {"profile_id", "license_and_origin_declaration", "style_map"},
            "template_mapping_spec_invalid")
    decl = mapping_spec["license_and_origin_declaration"]
    _validate_license_declaration(decl)
    require(isinstance(sections, list) and bool(sections), "template_sections_required")

    try:
        base = bundle._absolute(root)
        src = _template_path(base, template_path)
        dst = _template_path(base, output_path)
        require(core.checked_path(dst, missing_leaf=True) is None, "template_output_exists")
    except (OSError, bundle.BundleError):
        raise ContractError("template_path_invalid") from None
    raw_tpl = _read_template(src)
    audit = audit_template(raw_tpl)
    require(audit["status"] == "audited_ready_for_declarative_mapping",
            "template_audit_rejected:" + ",".join(audit["blocked_reasons"]))

    style_map = mapping_spec["style_map"]
    require(isinstance(style_map, dict) and bool(style_map), "template_style_map_required")
    known_para_styles = set(audit["paragraph_styles"]) or set(audit["styles"])
    for role, style_id in style_map.items():
        require(isinstance(role, str) and isinstance(style_id, str) and style_id in known_para_styles,
                f"template_style_unknown:{style_id}")

    names, parts = _read_zip_parts(raw_tpl)
    by_lower = {name.lower(): name for name in names}
    doc_name = by_lower["word/document.xml"]
    ct_name = by_lower["[content_types].xml"]
    doc_tree = minidom.parseString(parts[doc_name])
    root_el = doc_tree.documentElement
    body = next((node for node in root_el.childNodes if node.namespaceURI == W and node.localName == "body"), None)
    require(body is not None, "template_body_missing")
    sect_pr = next((node for node in body.childNodes if node.namespaceURI == W and node.localName == "sectPr"), None)

    def word(parent, tag, **attrs):
        node = doc_tree.createElementNS(W, "w:" + tag)
        for key, value in attrs.items():
            node.setAttributeNS(W, "w:" + key, value)
        if parent is not None:
            parent.appendChild(node)
        return node

    next_bm_id = _max_bookmark_id(doc_tree) + 1
    existing_bm_names = {name.casefold() for name in audit["bookmarks"]}
    mapped_blocks = []
    for sec in sections:
        require(isinstance(sec, dict) and {"id", "role", "text"} <= set(sec), "template_section_fields_required")
        sec_id = sec["id"]
        require(isinstance(sec_id, str) and BOOKMARK_NAME_RE.fullmatch(sec_id) is not None,
                "template_section_id_invalid")
        require(sec_id.casefold() not in existing_bm_names, "template_bookmark_name_collision")
        existing_bm_names.add(sec_id.casefold())
        role = sec["role"]
        require(role in style_map, f"template_section_role_unmapped:{role}")
        text = sec["text"]
        require(isinstance(text, str) and not XML_CTRL_RE.search(text), "template_section_text_invalid")

        p = word(None, "p")
        p.setAttributeNS(XMLNS_NAMESPACE, "xmlns:w", W)
        word(word(p, "pPr"), "pStyle", val=style_map[role])
        bm_id = str(next_bm_id)
        next_bm_id += 1
        word(p, "bookmarkStart", id=bm_id, name=sec_id)
        r = word(p, "r")
        lines = text.split("\n")
        for li, line in enumerate(lines):
            if li > 0:
                word(r, "br")
            segs = line.split("\t")
            for si, seg in enumerate(segs):
                if si > 0:
                    word(r, "tab")
                t = word(r, "t")
                t.setAttributeNS(XML_NAMESPACE, "xml:space", "preserve")
                t.appendChild(doc_tree.createTextNode(seg))
        word(p, "bookmarkEnd", id=bm_id)
        body.insertBefore(p, sect_pr)
        mapped_blocks.append({"id": sec_id, "role": role, "style": style_map[role]})

    new_doc_xml = doc_tree.toxml(encoding="utf-8")
    new_ct_xml = parts[ct_name]
    ct_tree = minidom.parseString(new_ct_xml)
    ct_changed = False
    for node in ct_tree.getElementsByTagNameNS(CT_NS, "Override"):
        if (node.getAttribute("PartName").casefold().lstrip("/") == doc_name.casefold()
                and node.getAttribute("ContentType").casefold() ==
                "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"):
            node.setAttribute("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
            ct_changed = True
    if ct_changed:
        new_ct_xml = ct_tree.toxml(encoding="utf-8")

    out_buf = io.BytesIO()
    replacements = {doc_name: new_doc_xml, ct_name: new_ct_xml}
    with zipfile.ZipFile(out_buf, "w") as zout:
        for name in names:
            require(not _is_custom_xml_path(name), "template_custom_xml_parts_forbidden")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.external_attr = 0
            info.flag_bits = 0
            zout.writestr(info, replacements.get(name, parts[name]), compress_type=zipfile.ZIP_DEFLATED)
            info.external_attr = 0
    out_bytes = out_buf.getvalue()
    template_unchanged = sha256_bytes(_read_template(src)) == audit["template_sha256"]
    try:
        require(core.checked_path(dst, missing_leaf=True) is None, "template_output_exists")
        with dst.open("xb") as fh:
            fh.write(out_bytes)
    except (OSError, bundle.BundleError):
        raise ContractError("template_output_write_failed") from None

    return {
        "schema": "dyz-template-mapping-result-v1",
        "status": "mapped_needs_visual_and_professional_review",
        "profile_id": mapping_spec["profile_id"],
        "template_sha256": audit["template_sha256"],
        "template_unchanged": template_unchanged,
        "license_and_origin_declaration": dict(decl),
        "output_path": output_path,
        "output_sha256": sha256_bytes(out_bytes),
        "mapped_count": len(mapped_blocks),
        "mapped_blocks": mapped_blocks,
        "visual_review": "not_performed",
        "professional_review": "not_performed",
    }
