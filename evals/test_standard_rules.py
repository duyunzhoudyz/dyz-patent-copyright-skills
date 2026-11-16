"""WP-03标准来源索引离线检查，不证明现行法律、许可授权或专业AC通过。

仓库根目录：python -m unittest evals.test_standard_rules -v
Python 3.11标准库；不联网、不下载标准、不填写声明、不调用规则选择器。
"""

from datetime import date
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "references" / "standards" / "organization-rules.json"


def unique_object(pairs):
    """JSON重复键会掩盖版本/权限事实，读取时拒绝而非静默覆盖。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_key:{key}")
        result[key] = value
    return result


class StandardRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(INDEX.read_text(encoding="utf-8"),
                               object_pairs_hook=unique_object)
        cls.rules = cls.index["rules"]
        cls.by_id = {rule["rule_id"]: rule for rule in cls.rules}
        cls.sources = {source["url"]: source for source in cls.index["sources"]}

    def test_index_is_non_executable_research_not_approval(self):
        self.assertEqual(self.index["schema_version"], "1.0.0")
        self.assertEqual(self.index["index_kind"], "source_index_not_executable_rules")
        self.assertEqual(self.index["support_status"], "source_research_only")
        self.assertEqual(self.index["review_status"], "not_professionally_reviewed")
        self.assertEqual(self.index["verification_precision"], "day")
        for key in ("purpose", "consumer", "dates", "version_change",
                    "not_applicable", "copyright", "runtime_boundary"):
            self.assertTrue(self.index["usage"][key].strip())
        self.assertIn("不直接传入tools.core.select_rules", self.index["usage"]["consumer"])

    def test_ids_unique_and_required_research_areas_present(self):
        expected = {
            "STD-CN-STANDARDIZATION-LAW-2017", "STD-CN-GBT1-1-2020",
            "STD-CN-GBT1-2-2020", "STD-ISOIEC-DIRECTIVES-PART1",
            "STD-ISOIEC-DIRECTIVES-PART2", "STD-ITU-ISO-IEC-COMMON-PATENT-POLICY",
            "STD-ITU-ISO-IEC-PATENT-GUIDELINES-2022", "STD-ISO-PATENT-DECLARATION-PORTAL",
            "STD-ISOIEC-GUIDE21-1-2005", "STD-ISO-COPYRIGHT-NOTICE",
            "STD-ISO-CUSTOMER-LICENCE-2026", "STD-IEC-COPYRIGHT-NOTICE",
        }
        self.assertEqual(len(self.by_id), len(self.rules))
        self.assertTrue(expected.issubset(self.by_id))
        source_ids = [source["source_id"] for source in self.index["sources"]]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(len(self.sources), len(self.index["sources"]))

    def test_every_record_has_scope_locator_and_explicit_unknowns(self):
        required = {
            "rule_id", "version", "business", "scope", "source", "locator",
            "published_at", "effective_from", "effective_until", "verified_at",
            "verification_status", "exceptions", "license", "review_status",
            "related_capabilities", "evidence_summary",
        }
        for rule in self.rules:
            with self.subTest(rule=rule["rule_id"]):
                self.assertTrue(required.issubset(rule))
                self.assertRegex(rule["rule_id"], r"^STD-[A-Z0-9-]+$")
                self.assertEqual(rule["business"], "standards")
                self.assertEqual(rule["review_status"], "not_professionally_reviewed")
                for key in ("version", "locator", "evidence_summary"):
                    self.assertIsInstance(rule[key], str)
                    self.assertTrue(rule[key].strip())
                self.assertIsInstance(rule["exceptions"], list)
                self.assertTrue(rule["exceptions"])
                self.assertTrue(all(isinstance(item, str) and item.strip()
                                    for item in rule["exceptions"]))
                self.assertIsInstance(rule["scope"]["jurisdiction"], str)
                for key in ("organizations", "standard_types", "stages"):
                    self.assertIsInstance(rule["scope"][key], list)
                    self.assertTrue(rule["scope"][key])

    def test_capabilities_resolve_to_existing_contract_ids(self):
        contracts = (ROOT / "docs" / "capability-contracts.md").read_text(encoding="utf-8")
        existing = set(re.findall(r"\| ([A-Z]+-\d{2}) \|", contracts))
        for rule in self.rules:
            with self.subTest(rule=rule["rule_id"]):
                linked = rule["related_capabilities"]
                self.assertTrue(linked)
                self.assertEqual(len(linked), len(set(linked)))
                self.assertTrue(set(linked).issubset(existing), set(linked) - existing)

    def test_urls_are_official_and_all_rule_and_licence_sources_resolve(self):
        hosts = {"www.cnipa.gov.cn", "openstd.samr.gov.cn", "www.iso.org", "www.itu.int", "www.iec.ch"}
        for source in self.index["sources"]:
            parsed = urlsplit(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, hosts)
            self.assertIsNone(parsed.username)
            self.assertIsNone(parsed.password)
            self.assertTrue(source["observation"].strip())
            self.assertIn(source["access_status"], {"extracted", "extraction_failed", "search_observed"})
        for rule in self.rules:
            self.assertIn(rule["source"], self.sources)
            self.assertTrue(rule["license"]["basis_urls"])
            for url in rule["license"]["basis_urls"]:
                self.assertIn(url, self.sources)

    def test_dates_use_actual_precision_and_have_consistent_order(self):
        observed = date.fromisoformat(self.index["verified_at"])
        self.assertLessEqual(observed, date.today())
        for source in self.index["sources"]:
            self.assertEqual(date.fromisoformat(source["checked_at"]), observed)
        for rule in self.rules:
            with self.subTest(rule=rule["rule_id"]):
                checked = date.fromisoformat(rule["verified_at"])
                self.assertEqual(checked, observed)
                dates = {}
                for key in ("published_at", "effective_from", "effective_until"):
                    value = rule[key]
                    if value is not None:
                        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}$")
                        dates[key] = date.fromisoformat(value)
                if "published_at" in dates:
                    self.assertLessEqual(dates["published_at"], checked)
                if {"published_at", "effective_from"}.issubset(dates):
                    self.assertLessEqual(dates["published_at"], dates["effective_from"])
                if {"effective_from", "effective_until"}.issubset(dates):
                    self.assertLessEqual(dates["effective_from"], dates["effective_until"])

    def test_missing_effective_dates_not_filled_from_publication_or_access(self):
        for rule in self.rules:
            if rule["rule_id"] not in {
                "STD-CN-STANDARDIZATION-LAW-2017", "STD-CN-GBT1-1-2020", "STD-CN-GBT1-2-2020"
            }:
                self.assertIsNone(rule["effective_from"], rule["rule_id"])
            self.assertIsNone(rule["effective_until"], rule["rule_id"])
        law = self.by_id["STD-CN-STANDARDIZATION-LAW-2017"]
        self.assertIsNone(law["published_at"])
        self.assertEqual(law["effective_from"], "2018-01-01")
        guide = self.by_id["STD-ISOIEC-GUIDE21-1-2005"]
        self.assertEqual(guide["published_at"], "2005-05-12")
        self.assertEqual(guide["confirmed_at"], "2023-10-12")

    def test_posting_update_and_draft_boundary_dates_not_legal_effect(self):
        guideline = self.by_id["STD-ITU-ISO-IEC-PATENT-GUIDELINES-2022"]
        self.assertEqual(guideline["posting_dates"], {"English": "2022-12-16", "Chinese": "2023-03-17"})
        self.assertIsNone(guideline["published_at"])
        terms = self.by_id["STD-ISO-CUSTOMER-LICENCE-2026"]
        self.assertEqual(terms["webpage_updated_at"], "2026-05-29")
        self.assertIsNone(terms["effective_from"])
        part2 = self.by_id["STD-ISOIEC-DIRECTIVES-PART2"]
        self.assertEqual(part2["applicability_observation"]["registered_after"], "2021-10-01")
        self.assertIs(part2["applicability_observation"]["inclusive"], False)
        self.assertIsNone(part2["effective_from"])

    def test_verification_level_matches_actual_source_evidence(self):
        levels = {
            "metadata_verified": "official_metadata",
            "official_text_read": "official_text",
            "official_text_read_partial": "official_text",
            "search_snippet_only": "search_snippet",
        }
        for rule in self.rules:
            with self.subTest(rule=rule["rule_id"]):
                status = rule["verification_status"]
                self.assertIn(status, levels)
                source = self.sources[rule["source"]]
                self.assertEqual(source["evidence_level"], levels[status])
                if status != "search_snippet_only":
                    self.assertEqual(source["access_status"], "extracted")
                if source["access_status"] == "extraction_failed":
                    self.assertEqual(status, "search_snippet_only")

    def test_licence_dimensions_never_inherit_from_public_access(self):
        for rule in self.rules:
            with self.subTest(rule=rule["rule_id"]):
                rights = rule["license"]
                self.assertIsInstance(rights["acquisition"], str)
                self.assertTrue(rights["acquisition"])
                # 没有具体材料授权证明，本研究切片不自动授予下列任何权利。
                for operation in ("processing", "copying", "translation", "redistribution"):
                    self.assertEqual(rights[operation], "unknown")
                self.assertTrue(rights["limitations"].strip())
        terms = self.by_id["STD-ISO-CUSTOMER-LICENCE-2026"]
        self.assertIn("B§7(b)", terms["locator"])
        self.assertIn("Open data", " ".join(terms["exceptions"]))

    def test_domestic_routes_and_recommended_legal_effect_are_separate(self):
        law = self.by_id["STD-CN-STANDARDIZATION-LAW-2017"]
        expected = {"national_mandatory", "national_recommended", "industry", "local", "association", "enterprise"}
        self.assertEqual({route["type"] for route in law["routes"]}, expected)
        for route in law["routes"]:
            self.assertTrue(route["locator"])
            self.assertTrue(route["summary"])
        self.assertIn("不能由条文中的应推定", " ".join(law["exceptions"]))
        self.assertEqual(self.by_id["STD-CN-GBT1-1-2020"]["effective_from"], "2020-10-01")
        self.assertEqual(self.by_id["STD-CN-GBT1-2-2020"]["effective_from"], "2021-06-01")

    def test_failures_are_retained_and_not_reported_as_empty_success(self):
        failures = self.index["failed_attempts"]
        self.assertGreaterEqual(len(failures), 3)
        for attempt in failures:
            self.assertIn(attempt["status"], {"no_extracted_content_returned", "extraction_failed"})
            self.assertEqual(attempt["checked_at"], self.index["verified_at"])
            self.assertTrue(attempt["resolution"])
        policy = self.by_id["STD-ITU-ISO-IEC-COMMON-PATENT-POLICY"]
        self.assertEqual(policy["verification_status"], "search_snippet_only")
        self.assertIsNone(policy["effective_from"])

    def test_index_stores_no_fulltext_templates_or_machine_rule_payload(self):
        forbidden_keys = {"fulltext", "full_text", "translated_text", "template_content", "html", "base64", "executable_rules"}

        def check(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden_keys.intersection(value))
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
            elif isinstance(value, str):
                self.assertNotIn(".references/", value)
                self.assertNotIn("<html", value.lower())

        check(self.index)
        for rule in self.rules:
            self.assertLess(len(rule["evidence_summary"]), 600)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate_key:version"):
            json.loads('{"version": "old", "version": "new"}', object_pairs_hook=unique_object)


if __name__ == "__main__":
    unittest.main()
