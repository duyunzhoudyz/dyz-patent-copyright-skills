"""专利官方来源索引的离线结构验收，不验证法律结论或网站实时可达性。

仓库根目录：python -m unittest discover -s evals -p test_patent_rules.py -v
Python 3.11标准库；不联网，不安装依赖，不读取真实案件材料。
"""

import copy
import json
import re
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "references" / "jurisdictions" / "patent-rules.json"
OFFICIAL_HOSTS = {
    "www.cnipa.gov.cn", "www.uspto.gov", "www.epo.org",
    "www.wipo.int", "euipo.europa.eu", "www.euipo.europa.eu",
}
STATUSES = {
    "official_text_read", "official_guidance_read", "official_portal_read",
}
REQUIRED_RULES = {
    "PAT-CN-NOVELTY-22-24", "PAT-CN-DISCLOSURE-26", "PAT-CN-AMENDMENT-33",
    "PAT-CN-SECRECY-4-19", "PAT-CN-GUIDELINES-84", "PAT-US-101-MPEP",
    "PAT-US-101-GUIDANCE-PORTAL", "PAT-US-102-AIA", "PAT-US-103-MPEP",
    "PAT-US-112-MPEP", "PAT-US-PROVISIONAL", "PAT-US-IDS",
    "PAT-EP-GUIDELINES-2026", "PAT-EP-PRIORITY", "PAT-EP-ADDED-MATTER",
    "PAT-EP-COMVIK", "PAT-PCT-INTERNATIONAL-PHASE", "PAT-HAGUE-DESIGN-ROUTE",
    "PAT-EUIPO-DESIGN-2026", "PAT-WIPO-ST26-ENTRY",
}
REQUIRED_FIELDS = {
    "rule_id", "version", "business", "scope", "source", "locator",
    "published_at", "effective_from", "effective_until", "verified_at",
    "verification_status", "exceptions", "license", "review_status",
    "related_capabilities", "evidence_summary", "date_basis",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def iso_day(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
            "日期必须是明确的ISO日，未知用null")
    return date.fromisoformat(value)


def official_url(value):
    require(text(value), "缺少来源URL")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS
            and not parsed.username and not parsed.password and bool(parsed.path),
            "来源必须是已登记官方HTTPS域名，不能有凭证")


def validate_index(index, known_capabilities):
    """检查索引契约；不由字段完整性推导来源真实或法律有效。"""
    require(index.get("schema_version") == "1.0", "未知schema版本")
    require(index.get("business") == "patent", "专业所有权错误")
    require(index.get("executable") is False, "来源索引不得成为可执行法条")
    require(index.get("review_status") == "not_professionally_reviewed",
            "不得冒充专业签核")
    require(index.get("verification_time_precision") == "day", "核验时间精度不明")
    checked = iso_day(index["verified_at"])
    require(checked <= date.today(), "核验时间不能在未来")
    for field in ("purpose", "date_semantics", "consumption_policy", "change_policy",
                  "license_policy"):
        require(text(index.get(field)), f"缺少{field}")
    require(set(index["verification_status_definitions"]) == STATUSES,
            "状态语义必须区分正文、指南和入口")
    require(index.get("research_limitations") and
            all(text(item) for item in index["research_limitations"]), "缺少核验边界")
    rules = index.get("rules")
    require(isinstance(rules, list) and bool(rules), "缺少规则记录")
    ids = set()
    for rule in rules:
        require(REQUIRED_FIELDS <= rule.keys(), "规则缺少必需字段")
        rule_id = rule["rule_id"]
        require(isinstance(rule_id, str) and
                re.fullmatch(r"PAT-[A-Z0-9]+(?:-[A-Z0-9]+)+", rule_id), "规则ID错误")
        require(rule_id not in ids, "重复规则ID")
        ids.add(rule_id)
        require(rule["business"] == "patent", "规则专业所有权错误")
        require(rule["review_status"] == "not_professionally_reviewed",
                "规则不得冒充专业核验")
        require(rule["verification_status"] in STATUSES, "未知或越权核验状态")
        for field in ("version", "locator", "evidence_summary"):
            require(text(rule[field]), f"规则缺少{field}")
        require(len(rule["evidence_summary"]) <= 400, "索引只保留简短原创释义")
        require(not {"full_text", "template", "raw_html"}.intersection(rule),
                "索引不能收录全文或模板")
        official_url(rule["source"])
        require(isinstance(rule["date_basis"], dict), "日期依据必须独立记录")
        official_url(rule["date_basis"]["source"])
        require(text(rule["date_basis"].get("locator")), "缺少日期定位或未知理由")
        for extra in rule.get("additional_sources", []):
            official_url(extra["source"])
            require(text(extra["locator"]) and extra["verification_status"] in STATUSES,
                    "辅助来源缺少已读范围或状态")
        require(iso_day(rule["verified_at"]) <= checked, "逐条核验日超出索引核验日")
        dates = {field: None if rule[field] is None else iso_day(rule[field])
                 for field in ("published_at", "effective_from", "effective_until")}
        if dates["published_at"] is not None:
            require(dates["published_at"] <= checked, "公布日晚于核验日")
        if dates["effective_from"] is not None and dates["effective_until"] is not None:
            require(dates["effective_from"] <= dates["effective_until"], "有效区间倒置")
        scope = rule["scope"]
        require(isinstance(scope, dict), "适配组合必须是对象")
        for field in ("jurisdiction", "organization", "route"):
            require(text(scope.get(field)), f"适配缺少{field}")
        for field in ("right_type", "domain", "stage"):
            require(isinstance(scope.get(field), list) and bool(scope[field]) and
                    all(text(item) for item in scope[field]), f"适配缺少{field}")
        require(isinstance(rule["exceptions"], list) and bool(rule["exceptions"]) and
                all(text(item) for item in rule["exceptions"]), "例外和限制不能为空")
        license_record = rule["license"]
        require(isinstance(license_record, dict) and all(
            text(license_record.get(field))
            for field in ("access", "processing", "copying", "redistribution")),
            "访问、处理、复制、再分发必须分开")
        related = rule["related_capabilities"]
        require(isinstance(related, list) and bool(related), "能力关联不能为空")
        require(all(isinstance(item, str) and item in known_capabilities for item in related),
                "关联能力不在原83项契约内")
        require(len(related) == len(set(related)), "重复能力关联")
    require(REQUIRED_RULES <= ids, "缺少本切片必需主题")


class PatentRuleIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"))
        blueprint = (ROOT / "docs" / "capability-blueprint.md").read_text(encoding="utf-8")
        cls.capabilities = set(re.findall(r"^\| ([A-Z]+-\d{2}) \|", blueprint, re.MULTILINE))

    def test_index_structure_and_original_83_capabilities(self):
        self.assertEqual(len(self.capabilities), 83)
        validate_index(self.index, self.capabilities)

    def test_duplicate_rule_id_is_rejected(self):
        altered = copy.deepcopy(self.index)
        altered["rules"].append(copy.deepcopy(altered["rules"][0]))
        with self.assertRaisesRegex(ValueError, "重复规则ID"):
            validate_index(altered, self.capabilities)

    def test_missing_required_field_is_rejected(self):
        for field in REQUIRED_FIELDS:
            with self.subTest(field=field):
                altered = copy.deepcopy(self.index)
                del altered["rules"][0][field]
                with self.assertRaisesRegex(ValueError, "必需字段"):
                    validate_index(altered, self.capabilities)

    def test_unknown_capability_is_rejected(self):
        altered = copy.deepcopy(self.index)
        altered["rules"][0]["related_capabilities"] = ["PATENT-99"]
        with self.assertRaisesRegex(ValueError, "原83项"):
            validate_index(altered, self.capabilities)

    def test_professional_approval_cannot_be_inferred(self):
        for field, value in (("review_status", "approved"),
                             ("verification_status", "legally_valid")):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.index)
                altered["rules"][0][field] = value
                with self.assertRaises(ValueError):
                    validate_index(altered, self.capabilities)

    def test_index_is_not_an_executable_rule_bundle(self):
        altered = copy.deepcopy(self.index)
        altered["executable"] = True
        with self.assertRaisesRegex(ValueError, "可执行"):
            validate_index(altered, self.capabilities)
        self.assertIn("select_rules", self.index["consumption_policy"])

    def test_invalid_dates_and_reversed_intervals_are_rejected(self):
        for value in ("2026-02-30", "2026-10", "unknown", "2026-01-01T00:00:00Z"):
            with self.subTest(value=value):
                altered = copy.deepcopy(self.index)
                altered["rules"][0]["effective_from"] = value
                with self.assertRaises(ValueError):
                    validate_index(altered, self.capabilities)
        altered = copy.deepcopy(self.index)
        altered["rules"][0]["effective_until"] = "2020-01-01"
        with self.assertRaisesRegex(ValueError, "区间倒置"):
            validate_index(altered, self.capabilities)

    def test_future_verification_is_rejected(self):
        altered = copy.deepcopy(self.index)
        altered["verified_at"] = "9999-12-31"
        with self.assertRaisesRegex(ValueError, "未来"):
            validate_index(altered, self.capabilities)

    def test_unknown_effective_dates_remain_null(self):
        by_id = {rule["rule_id"]: rule for rule in self.index["rules"]}
        for rule_id in ("PAT-US-101-MPEP", "PAT-US-102-AIA", "PAT-US-103-MPEP",
                        "PAT-US-112-MPEP", "PAT-US-IDS", "PAT-US-PROVISIONAL",
                        "PAT-EP-PRIORITY", "PAT-EP-ADDED-MATTER"):
            with self.subTest(rule_id=rule_id):
                self.assertIsNone(by_id[rule_id]["effective_from"])
                self.assertIsNone(by_id[rule_id]["effective_until"])

    def test_publication_and_effective_dates_are_not_conflated(self):
        by_id = {rule["rule_id"]: rule for rule in self.index["rules"]}
        self.assertEqual(by_id["PAT-CN-GUIDELINES-84"]["published_at"], "2025-11-13")
        self.assertEqual(by_id["PAT-CN-GUIDELINES-84"]["effective_from"], "2026-01-01")
        self.assertEqual(by_id["PAT-EP-GUIDELINES-2026"]["effective_from"], "2026-04-01")
        self.assertEqual(by_id["PAT-EUIPO-DESIGN-2026"]["effective_from"], "2026-07-01")
        self.assertEqual(by_id["PAT-WIPO-ST26-ENTRY"]["effective_from"], "2022-07-01")

    def test_bad_source_hosts_and_credentials_are_rejected(self):
        for url in ("https://www.uspto.gov.example.com/page", "http://www.uspto.gov/page",
                    "https://secret@www.uspto.gov/page", "https://example.com/page"):
            with self.subTest(url=url):
                altered = copy.deepcopy(self.index)
                altered["rules"][0]["source"] = url
                with self.assertRaises(ValueError):
                    validate_index(altered, self.capabilities)

    def test_each_permission_dimension_is_required(self):
        for field in ("access", "processing", "copying", "redistribution"):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.index)
                del altered["rules"][0]["license"][field]
                with self.assertRaisesRegex(ValueError, "必须分开"):
                    validate_index(altered, self.capabilities)

    def test_adaptation_and_exception_gaps_are_rejected(self):
        altered = copy.deepcopy(self.index)
        altered["rules"][0]["scope"]["stage"] = []
        with self.assertRaisesRegex(ValueError, "适配缺少"):
            validate_index(altered, self.capabilities)
        altered = copy.deepcopy(self.index)
        altered["rules"][0]["exceptions"] = []
        with self.assertRaisesRegex(ValueError, "例外"):
            validate_index(altered, self.capabilities)

    def test_design_routes_stay_separate_from_epc_and_pct(self):
        by_id = {rule["rule_id"]: rule for rule in self.index["rules"]}
        for rule_id, route, organization in (
            ("PAT-HAGUE-DESIGN-ROUTE", "Hague", "WIPO"),
            ("PAT-EUIPO-DESIGN-2026", "EU_design", "EUIPO"),
            ("PAT-EP-GUIDELINES-2026", "EPC", "EPO"),
            ("PAT-PCT-INTERNATIONAL-PHASE", "PCT", "WIPO"),
        ):
            with self.subTest(rule_id=rule_id):
                self.assertEqual(by_id[rule_id]["scope"]["route"], route)
                self.assertEqual(by_id[rule_id]["scope"]["organization"], organization)
        self.assertEqual(by_id["PAT-EUIPO-DESIGN-2026"]["scope"]["right_type"], ["design"])

    def test_full_text_payload_and_missing_topic_are_rejected(self):
        altered = copy.deepcopy(self.index)
        altered["rules"][0]["full_text"] = "synthetic prohibited payload"
        with self.assertRaisesRegex(ValueError, "全文"):
            validate_index(altered, self.capabilities)
        altered = copy.deepcopy(self.index)
        altered["rules"].pop()
        with self.assertRaisesRegex(ValueError, "必需主题"):
            validate_index(altered, self.capabilities)

    def test_entry_pages_do_not_claim_full_standard_verification(self):
        by_id = {rule["rule_id"]: rule for rule in self.index["rules"]}
        for rule_id in ("PAT-WIPO-ST26-ENTRY", "PAT-US-101-GUIDANCE-PORTAL",
                        "PAT-HAGUE-DESIGN-ROUTE"):
            with self.subTest(rule_id=rule_id):
                self.assertEqual(by_id[rule_id]["verification_status"], "official_portal_read")
                self.assertEqual(by_id[rule_id]["review_status"], "not_professionally_reviewed")


if __name__ == "__main__":
    unittest.main()
