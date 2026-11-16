"""发布前范围与事实门禁：仅使用临时合成树，不修改实际元数据或Git。"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evals import release_check


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dyz-release-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inventory = tuple(sorted(release_check.RELEASE_FILES | {"tools/__init__.py"}))
        self.paths = set(self.inventory) | {
            "LICENSE", "COMMERCIAL-LICENSE.md", "THIRD-PARTY-NOTICES.md",
            ".github/workflows/ci.yml", ".github/PULL_REQUEST_TEMPLATE.md",
        }
        for name in self.paths:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic fixture\n", encoding="utf-8")
        for index in range(6):
            name = "synthetic-" + str(index)
            path = self.root / "skills" / name / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"---\nname: {name}\ndescription: synthetic fixture\n---\n", encoding="utf-8")
            self.paths.add(path.relative_to(self.root).as_posix())
        self.metadata = json.loads((release_check.ROOT / "release.json").read_text(encoding="utf-8"))
        for key in release_check.REQUIRED_FACTS:
            self.metadata[key] = None
        self.write_metadata()
        patches = (
            patch.object(release_check, "ROOT", self.root),
            patch.object(release_check.bundle, "BUNDLE_FILES", self.inventory),
            patch.object(release_check, "_git_paths", side_effect=self.git_paths),
        )
        self.tracked = set()
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def git_paths(self, *args):
        return self.tracked if "--cached" in args else self.paths - self.tracked

    def write_metadata(self):
        (self.root / "release.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_missing_facts_allow_candidate_and_block_publication(self):
        candidate = release_check.inspect_release()
        self.assertEqual([], candidate["errors"])
        self.assertEqual("candidate_checks_passed", candidate["status"])
        self.assertFalse(candidate["publication_performed"])
        publication = release_check.inspect_release(publication=True)
        self.assertEqual(["publication_facts_incomplete"], publication["errors"])
        self.assertEqual(list(release_check.REQUIRED_FACTS), publication["missing_publication_facts"])

    def test_supplied_synthetic_facts_pass_structure_without_claiming_authentication(self):
        self.metadata.update(license_holder="Synthetic Test Owner",
                             repository_url="https://fixture.invalid/owner/repository",
                             commercial_contact="synthetic test channel",
                             security_contact="synthetic private test channel")
        self.write_metadata()
        report = release_check.inspect_release(publication=True)
        self.assertEqual([], report["errors"])
        self.assertEqual("not_performed", report["identity_license_secret_scan_professional_checks"])
        self.assertFalse(report["publication_performed"])

    def test_tracked_research_and_deleted_source_are_rejected(self):
        name = "竞品对比/标准/standards-review/restricted.pdf"
        path = self.root / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b"synthetic fixture")
        self.tracked.add(name)
        (self.root / "LICENSE").unlink()
        errors = release_check.inspect_release()["errors"]
        self.assertIn("source_scope_forbidden:" + name, errors)
        self.assertIn("source_member_missing:LICENSE", errors)

    def test_missing_contribution_document_and_runtime_dependency_are_rejected(self):
        (self.root / "CONTRIBUTOR-LICENSE.md").unlink()
        (self.root / "tools/__init__.py").write_text("from . import missing_runtime\n", encoding="utf-8")
        errors = release_check.inspect_release()["errors"]
        self.assertIn("bundle_member_missing:CONTRIBUTOR-LICENSE.md", errors)
        self.assertIn("bundle_dependency_missing:tools/missing_runtime.py", errors)

    def test_locally_present_bundle_source_excluded_from_git_is_rejected(self):
        self.paths.remove("tools/__init__.py")
        self.assertTrue((self.root / "tools/__init__.py").is_file())
        self.assertIn("bundle_source_not_in_git_scope:tools/__init__.py",
                      release_check.inspect_release()["errors"])

    def test_absolute_package_import_dependency_is_required(self):
        (self.root / "tools/__init__.py").write_text("from tools import missing_runtime\n", encoding="utf-8")
        self.assertIn("bundle_dependency_missing:tools/missing_runtime.py",
                      release_check.inspect_release()["errors"])

    def test_duplicate_metadata_key_and_wrong_version_are_rejected(self):
        (self.root / "release.json").write_text('{"version":"first","version":"second"}', encoding="utf-8")
        self.assertIn("release_metadata_invalid:ValueError", release_check.inspect_release()["errors"])
        self.metadata["version"] = "999.0.0"
        self.write_metadata()
        self.assertIn("version_mismatch", release_check.inspect_release()["errors"])

    def test_placeholder_contact_and_repository_credentials_are_rejected(self):
        self.metadata.update(security_contact="TODO", repository_url="https://user:synthetic@fixture.invalid/o/r")
        self.write_metadata()
        errors = release_check.inspect_release()["errors"]
        self.assertIn("release_fact_invalid:security_contact", errors)
        self.assertIn("repository_url_invalid", errors)

    def test_cli_publication_failure_is_json_and_exit_two(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = release_check.main(["--publication"])
        self.assertEqual(2, status)
        self.assertEqual("rejected", json.loads(output.getvalue())["status"])


class ReleaseIdentityTests(unittest.TestCase):
    def test_original_six_skill_names_and_descriptions_are_preserved(self):
        # 只锁发现身份；正文可在既定入口下继续改进。
        expected = {
            "dyz-patent": "a1f4ab321238627ecb8e6bf1b490ce62705a7f2e1efd81a0aa49737a9c387b14",
            "dyz-procedure": "1e8b32e47e392aff1a4fabf6eac1fc2a92465912d0e92d36aa95fbdd1ff38bef",
            "dyz-rendering": "6d1b2ad819596bbafb10c057f0bb141a95b0012f4fa9ebd7bbfb764a55f82ca1",
            "dyz-software": "96c53b77d305ea9fc1f3d540e141f99b657f591344d3e06895b7f6e835144058",
            "dyz-standards": "045a19d05154fd267dc7157627fd96af5ba50db022c5601eb00a03b5b02c48a3",
            "dyz-workbench": "c223e53620d228a57adf7744e93fda24d861e11028ec262aabb3788f42e79b6e",
        }
        actual = {path.parent.name: hashlib.sha256(path.read_text(encoding="utf-8-sig")
                  .split("---", 2)[1].encode("utf-8")).hexdigest()
                  for path in (release_check.ROOT / "skills").glob("*/SKILL.md")}
        self.assertEqual(expected, actual)

    def test_original_eleven_domains_and_83_ids_are_preserved(self):
        expected = {f"{prefix}-{index:02}" for prefix, count in (
            ("ANALYSIS", 8), ("CORE", 7), ("DRAFT", 8), ("FIG", 5), ("LIFE", 4),
            ("PROC", 9), ("REVIEW", 7), ("RIGHTS", 7), ("SEARCH", 8), ("STD", 12),
            ("SW", 8)) for index in range(1, count + 1)}
        rows = release_check.catalog()
        self.assertEqual(83, len(rows))
        self.assertEqual(expected, {row["capability"] for row in rows})
        self.assertTrue(all(row["support"] == "synthetic_helper_only" and
                            row["availability"] == "available" for row in rows))


if __name__ == "__main__":
    unittest.main()
