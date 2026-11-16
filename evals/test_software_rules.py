"""软件官方来源索引的离线契约测试；不是法律或在线服务验收。

根目录运行：python -m unittest evals.test_software_rules -v
不联网、不读取真实申请材料、不把通过结果提升为专业审阅。
"""

import copy
from datetime import date, datetime
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "references" / "jurisdictions" / "software-rules.json"
OFFICIAL_HOSTS = {
    "www.gov.cn", "www.ncac.gov.cn", "www.ccopyright.com.cn",
    "register.ccopyright.com.cn", "www.copyright.gov",
}
REQUIRED_FIELDS = {
    "rule_id", "version", "business", "scope", "source", "locator",
    "published_at", "effective_from", "effective_until", "date_basis",
    "verified_at", "verification_status", "exceptions", "license",
    "review_status", "related_capabilities", "evidence_summary",
}
EXPECTED_IDS = {
    "SW-CN-PROTECTION-SCOPE", "SW-CN-REGISTRATION-DEPOSIT",
    "SW-CN-EXCEPTION-DEPOSIT", "SW-CN-OWNERSHIP-UPGRADE",
    "SW-CN-CORRECTION-CHANGE", "SW-CN-CCPC-FORM-DEPOSIT",
    "SW-CN-CCPC-IDENTITY", "SW-CN-CCPC-UPGRADE",
    "SW-CN-CCPC-CORRECTION-ENTRY", "SW-US-REGISTRATION-CLAIMS",
    "SW-US-DEPOSIT-SECRETS", "SW-US-AI-AUTHORSHIP",
    "SW-US-AI-2025-REPORT-NOTICE",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def official_url(value: str) -> None:
    parsed = urlsplit(value)
    require(parsed.scheme == "https", "https_required")
    require(parsed.hostname in OFFICIAL_HOSTS, "unapproved_source_host")
    require(not parsed.username and not parsed.password, "credentials_in_url")


def validate_index(index: dict, capabilities: set[str]) -> None:
    """验证索引数据边界，不判定原文真实性、有效性或案件适用性。"""
    require(index["schema_version"] == "1.0", "unsupported_schema")
    require(index["business"] == "software", "wrong_business")
    require(index["status"] == "source_research_not_professional_validation",
            "unsupported_index_status")
    require(bool(index["rules"]), "empty_rules")
    ids = set()
    for rule in index["rules"]:
        require(REQUIRED_FIELDS <= rule.keys(), "missing_required_field")
        require(rule["rule_id"] not in ids, "duplicate_rule_id")
        ids.add(rule["rule_id"])
        require(bool(re.fullmatch(r"SW-(CN|US)-[A-Z0-9-]+", rule["rule_id"])),
                "invalid_rule_id")
        require(rule["business"] == "software", "wrong_business")
        require(bool(rule["version"]), "missing_version")
        scope = rule["scope"]
        require(scope["jurisdiction"] in {"CN", "US"}, "unsupported_jurisdiction")
        require(scope["right_type"] == "software_copyright", "wrong_right_type")
        require(bool(scope["stage"]), "missing_stage")
        source = rule["source"]
        for field in ("url", "publisher", "title", "kind"):
            require(bool(source[field]), "missing_source_metadata")
        for key in ("url", "corroborating_url", "entry_discovered_at", "entry_url"):
            if key in source:
                official_url(source[key])
        require(bool(rule["locator"]) and bool(rule["evidence_summary"]),
                "missing_evidence_location")
        require(bool(rule["date_basis"]), "missing_date_basis")
        verified = datetime.fromisoformat(rule["verified_at"])
        require(verified.utcoffset() is not None, "timezone_required")
        for key in ("published_at", "effective_from", "effective_until"):
            if rule[key] is not None:
                require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", rule[key])),
                        "legal_date_precision")
                date.fromisoformat(rule[key])
        if rule["effective_from"] and rule["effective_until"]:
            require(rule["effective_from"] < rule["effective_until"],
                    "invalid_effective_interval")
        require(rule["verification_status"] in {
            "official_text_read", "metadata_only", "unknown",
        }, "unsupported_verification_status")
        require(rule["review_status"] == "not_professionally_reviewed",
                "professional_review_not_provided")
        require("review_evidence" not in rule, "fabricated_review_evidence")
        require(isinstance(rule["exceptions"], list) and bool(rule["exceptions"]),
                "exceptions_required")
        require(all(isinstance(item, str) and item for item in rule["exceptions"]),
                "invalid_exception")
        related = rule["related_capabilities"]
        require(bool(related) and len(set(related)) == len(related),
                "invalid_capability_links")
        require(set(related) <= capabilities, "unknown_capability")
        require(any(item.startswith("SW-") for item in related),
                "software_capability_required")
        license_record = rule["license"]
        require({"access", "processing", "copying", "redistribution", "note"}
                <= license_record.keys(), "permission_axes_required")
        require(license_record["access"] == "public_read_observed",
                "unexpected_access_claim")
        for axis in ("processing", "copying", "redistribution"):
            require(license_record[axis] == "unknown", "unverified_license_grant")
        require(bool(license_record["note"]), "permission_note_required")


class SoftwareRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.rules = {item["rule_id"]: item for item in cls.index["rules"]}
        contracts = (ROOT / "docs" / "capability-contracts.md").read_text(
            encoding="utf-8")
        cls.capabilities = set(re.findall(
            r"^\| ([A-Z]+-\d{2}) \|", contracts, flags=re.MULTILINE))

    def test_index_contract(self):
        validate_index(self.index, self.capabilities)

    def test_assigned_topics_are_present(self):
        self.assertEqual(set(self.rules), EXPECTED_IDS)
        linked = {cap for rule in self.rules.values()
                  for cap in rule["related_capabilities"]}
        self.assertTrue({f"SW-{number:02}" for number in range(1, 9)} <= linked)
        self.assertEqual(self.index["work_package"], "WP-03")

    def test_actual_verification_session_is_timestamped(self):
        instant = datetime.fromisoformat(self.index["verified_at"])
        self.assertIsNotNone(instant.utcoffset())
        self.assertEqual(instant.date(), date(2026, 10, 31))
        self.assertTrue(all(rule["verified_at"] == self.index["verified_at"]
                            for rule in self.rules.values()))

    def test_law_version_dates_are_not_web_upload_dates(self):
        regulation = self.rules["SW-CN-PROTECTION-SCOPE"]
        self.assertEqual(regulation["published_at"], "2013-01-30")
        self.assertEqual(regulation["effective_from"], "2013-03-01")
        registration = self.rules["SW-CN-REGISTRATION-DEPOSIT"]
        self.assertEqual(registration["effective_from"], "2002-02-20")
        self.assertIn("202410", registration["source"]["corroborating_url"])
        ai = self.rules["SW-US-AI-AUTHORSHIP"]
        self.assertEqual(ai["published_at"], "2023-03-16")
        self.assertEqual(ai["effective_from"], "2023-03-16")

    def test_undated_guides_and_circular_month_stay_unknown(self):
        for rule in self.rules.values():
            if rule["source"]["kind"] in {
                "official_service_guidance", "official_circular",
            }:
                with self.subTest(rule=rule["rule_id"]):
                    self.assertIsNone(rule["published_at"])
                    self.assertIsNone(rule["effective_from"])
            self.assertIsNone(rule["effective_until"])

    def test_cn_us_deposit_boundaries_remain_distinct(self):
        cn = self.rules["SW-CN-REGISTRATION-DEPOSIT"]["observed_parameters"]
        us = self.rules["SW-US-DEPOSIT-SECRETS"]["observed_parameters"]
        self.assertEqual((cn["front_pages"], cn["back_pages"]), (30, 30))
        self.assertEqual(cn["entire_if_pages_less_than"], 60)
        self.assertEqual((us["front_pages"], us["back_pages"]), (25, 25))
        self.assertEqual(us["entire_if_pages_at_most"], 50)
        exception = self.rules["SW-CN-EXCEPTION-DEPOSIT"]["observed_parameters"]
        self.assertIs(exception["redaction_boundary_inclusive"], True)
        self.assertIs(us["redaction_boundary_inclusive"], False)

    def test_notice_is_not_report_full_text_or_effective_law(self):
        notice = self.rules["SW-US-AI-2025-REPORT-NOTICE"]
        self.assertIs(notice["source"]["report_full_text_read"], False)
        self.assertEqual(notice["published_at"], "2025-01-29")
        self.assertIsNone(notice["effective_from"])

    def test_account_entry_not_promoted_to_verified_workflow(self):
        entry = self.rules["SW-CN-CCPC-CORRECTION-ENTRY"]["source"]
        self.assertEqual(entry["entry_verification_status"], "metadata_only")
        self.assertEqual(urlsplit(entry["entry_url"]).fragment, "/registerSoft")

    def test_access_failures_and_use_limits_are_kept(self):
        issues = self.index["retrieval_issues"]
        self.assertTrue(any(item["outcome"] == "failed" for item in issues))
        self.assertTrue(all(item["impact"] for item in issues))
        contract = self.index["use_contract"]
        self.assertIn("select_rules", contract["selector_compatibility"])
        self.assertIn("null", contract["unknown_behavior"])
        self.assertTrue(contract["change_behavior"])
        self.assertTrue(self.index["research_limits"])

    def assert_rejected(self, mutate, expected):
        candidate = copy.deepcopy(self.index)
        mutate(candidate)
        with self.assertRaisesRegex(ValueError, expected):
            validate_index(candidate, self.capabilities)

    def test_reject_missing_required_field(self):
        self.assert_rejected(lambda data: data["rules"][0].pop("locator"),
                             "missing_required_field")

    def test_reject_duplicate_rule_id(self):
        self.assert_rejected(lambda data: data["rules"].append(data["rules"][0]),
                             "duplicate_rule_id")

    def test_reject_nonofficial_source(self):
        self.assert_rejected(lambda data: data["rules"][0]["source"].update(
            url="https://www.gov.cn.example.invalid/rule"),
            "unapproved_source_host")

    def test_reject_bad_date_and_naive_verification_time(self):
        self.assert_rejected(lambda data: data["rules"][0].update(
            effective_from="2013-03"), "legal_date_precision")
        self.assert_rejected(lambda data: data["rules"][0].update(
            verified_at="2026-10-31T11:55:00"), "timezone_required")

    def test_reject_unknown_capability(self):
        self.assert_rejected(lambda data: data["rules"][0].update(
            related_capabilities=["SW-99"]), "unknown_capability")

    def test_reject_professional_or_blanket_license_promotion(self):
        self.assert_rejected(lambda data: data["rules"][0].update(
            review_status="professionally_verified"),
            "professional_review_not_provided")
        self.assert_rejected(lambda data: data["rules"][0]["license"].update(
            redistribution="allowed"), "unverified_license_grant")

    def test_reject_invented_status_or_reversed_interval(self):
        self.assert_rejected(lambda data: data["rules"][0].update(
            verification_status="legally_valid"), "unsupported_verification_status")
        self.assert_rejected(lambda data: data["rules"][0].update(
            effective_until="2013-02-28"), "invalid_effective_interval")


if __name__ == "__main__":
    unittest.main()
