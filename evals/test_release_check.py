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


SYNTHETIC_FACTS = {
    "license_holder": "合成测试机构",
    "repository_url": "https://fixture.invalid/owner/repository",
    "commercial_contact": "nonnull@fixture.invalid",
    "security_contact": "synthetic private test channel",
}


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
        (self.root / ".github/workflows/ci.yml").write_text(
            (release_check.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        for index in range(6):
            name = "synthetic-" + str(index)
            path = self.root / "skills" / name / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"---\nname: {name}\ndescription: synthetic fixture\n---\n", encoding="utf-8")
            self.paths.add(path.relative_to(self.root).as_posix())
        self.metadata = json.loads((release_check.ROOT / "release.json").read_text(encoding="utf-8"))
        self.metadata["publication_status"] = "unpublished_candidate"
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

    def test_published_release_requires_each_fact_by_default(self):
        self.metadata.update(SYNTHETIC_FACTS, publication_status="published_release")
        self.write_metadata()
        self.assertEqual([], release_check.inspect_release()["errors"])
        for key in release_check.REQUIRED_FACTS:
            with self.subTest(key=key):
                del self.metadata[key]
                self.write_metadata()
                report = release_check.inspect_release()
                self.metadata[key] = SYNTHETIC_FACTS[key]
                self.assertEqual(["publication_facts_incomplete"], report["errors"])
                self.assertEqual([key], report["missing_publication_facts"])

    def test_published_alpha_is_rejected(self):
        self.metadata.update(SYNTHETIC_FACTS, publication_status="published_release",
                             version="0.1.0a1", proposed_tag="v0.1.0-alpha.1")
        self.write_metadata()
        with patch.object(release_check, "__version__", "0.1.0a1"):
            self.assertEqual(["published_alpha_not_allowed"], release_check.inspect_release()["errors"])

    def test_unknown_publication_status_is_rejected(self):
        for status in ("unknown", []):
            with self.subTest(status=status):
                self.metadata["publication_status"] = status
                self.write_metadata()
                self.assertEqual(["release_scope_mismatch"], release_check.inspect_release()["errors"])

    def test_supplied_synthetic_facts_pass_structure_without_claiming_authentication(self):
        self.metadata.update(SYNTHETIC_FACTS)
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

    def test_proposed_tag_matches_version_format(self):
        for version, tag, errors in (
            ("0.1.0a1", "v0.1.0-alpha.1", []),
            ("0.1.0", "v0.1.0-alpha.1", ["proposed_tag_mismatch"]),
            ("0.1.0a1", "v0.1.0", ["proposed_tag_mismatch"]),
            ("0.1", None, ["proposed_tag_mismatch"]),
            ("０.1.0", "v０.1.0", ["proposed_tag_mismatch"]),
            ("0.1.0a１", "v0.1.0-alpha.１", ["proposed_tag_mismatch"]),
        ):
            with self.subTest(version=version, tag=tag), patch.object(release_check, "__version__", version):
                self.metadata.update(version=version, proposed_tag=tag)
                self.write_metadata()
                self.assertEqual(errors, release_check.inspect_release()["errors"])

    def test_placeholder_contact_and_repository_credentials_are_rejected(self):
        self.metadata.update(security_contact="TODO", repository_url="https://user:synthetic@fixture.invalid/o/r")
        self.write_metadata()
        errors = release_check.inspect_release()["errors"]
        self.assertIn("release_fact_invalid:security_contact", errors)
        self.assertIn("repository_url_invalid", errors)

    def test_release_fact_placeholders_are_rejected(self):
        self.metadata.update(SYNTHETIC_FACTS, publication_status="published_release")
        for key, placeholder in (
            ("license_holder", " TbD "),
            ("repository_url", "https://fixture.invalid/owner/unknown"),
            ("commercial_contact", "None"),
            ("security_contact", "null"),
            ("security_contact", "N/A"),
            ("license_holder", "未填写"),
            ("commercial_contact", "安全渠道待补"),
            ("security_contact", "占位"),
            ("security_contact", "[测试]"),
        ):
            with self.subTest(key=key, placeholder=placeholder):
                self.metadata[key] = placeholder
                self.write_metadata()
                errors = release_check.inspect_release()["errors"]
                self.metadata[key] = SYNTHETIC_FACTS[key]
                self.assertEqual(["release_fact_invalid:" + key], errors)

    def test_cli_publication_failure_is_json_and_exit_two(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = release_check.main(["--publication"])
        self.assertEqual(2, status)
        self.assertEqual("rejected", json.loads(output.getvalue())["status"])

    def test_ci_checkout_sha_tamper_is_rejected(self):
        ci_path = self.root / ".github/workflows/ci.yml"
        original = ci_path.read_text(encoding="utf-8")
        tampered = original.replace(
            "11bd71901bbe5b1630ceea73d27597364c9af683",
            "11bd11901bbe5b1630ceea73d27597364c9af683",
            1,
        )
        self.assertNotEqual(original, tampered)
        ci_path.write_text(tampered, encoding="utf-8")
        errors = release_check.inspect_release()["errors"]
        self.assertIn("ci_checkout_sha_mismatch", errors)

    def test_ci_matrix_missing_python_version_is_rejected(self):
        ci_path = self.root / ".github/workflows/ci.yml"
        original = ci_path.read_text(encoding="utf-8")
        reduced = original.replace(
            "          - os: ubuntu-latest\n            python-version: '3.12'\n",
            "",
            1,
        )
        self.assertNotEqual(original, reduced)
        ci_path.write_text(reduced, encoding="utf-8")
        errors = release_check.inspect_release()["errors"]
        self.assertIn("ci_matrix_mismatch", errors)

    def test_ci_missing_concurrency_and_write_permissions_are_rejected(self):
        ci_path = self.root / ".github/workflows/ci.yml"
        original = ci_path.read_text(encoding="utf-8")
        broken = (original
                  .replace("concurrency:\n  group: ${{ github.workflow }}-${{ github.ref }}\n  cancel-in-progress: true\n", "")
                  .replace("contents: read", "contents: write")
                  .replace("persist-credentials: false", "persist-credentials: true"))
        ci_path.write_text(broken, encoding="utf-8")
        errors = release_check.inspect_release()["errors"]
        self.assertIn("ci_concurrency_missing", errors)
        self.assertIn("ci_permissions_mismatch", errors)

    def test_ci_comment_cannot_mask_job_write_permissions(self):
        ci_path = self.root / ".github/workflows/ci.yml"
        original = ci_path.read_text(encoding="utf-8")
        forged = original.replace(
            "  local-helper-matrix:\n    strategy:\n",
            "  local-helper-matrix:\n"
            "    # permissions:\n"
            "    #   contents: read\n"
            f"    # uses: {release_check.CI_CHECKOUT_PIN}\n"
            "    permissions: write-all\n"
            "    strategy:\n",
            1,
        )
        self.assertNotEqual(original, forged)
        ci_path.write_text(forged, encoding="utf-8")
        self.assertIn("ci_permissions_mismatch", release_check.inspect_release()["errors"])

    def test_ci_extra_job_write_all_is_rejected(self):
        ci_path = self.root / ".github/workflows/ci.yml"
        extra = (
            "\n  privileged-extra:\n"
            "    permissions: write-all\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            f"      - uses: {release_check.CI_CHECKOUT_PIN}\n"
            "        with:\n"
            "          persist-credentials: false\n"
            f"      - uses: {release_check.CI_SETUP_PYTHON_PIN}\n"
        )
        ci_path.write_text(ci_path.read_text(encoding="utf-8").rstrip() + extra, encoding="utf-8")
        self.assertIn("ci_permissions_mismatch", release_check.inspect_release()["errors"])

    def test_ci_commented_pin_does_not_mask_step_sha(self):
        ci_path = self.root / ".github/workflows/ci.yml"
        pin = release_check.CI_SETUP_PYTHON_PIN
        digest = pin.rsplit("@", 1)[1]
        bad = pin.rsplit("@", 1)[0] + "@" + digest[:-1] + ("0" if digest[-1] != "0" else "1")
        original = ci_path.read_text(encoding="utf-8")
        forged = original.replace(
            f"uses: {pin}",
            f"# uses: {pin}\n        uses: {bad}",
            1,
        )
        self.assertNotEqual(original, forged)
        ci_path.write_text(forged, encoding="utf-8")
        errors = release_check.inspect_release()["errors"]
        self.assertIn("ci_setup_python_sha_mismatch", errors)

    def test_inconsistent_platform_claims_in_release_json_are_rejected(self):
        extra_platforms = ["Windows", "Linux", "macOS", "FreeBSD"]
        for overrides in (
            {"supported_platforms": extra_platforms},
            {"supported_platforms": extra_platforms, "verified_platforms": extra_platforms},
            {"target_ci_platforms": ["Windows", "Linux"]},
        ):
            with self.subTest(**overrides), patch.dict(self.metadata, overrides):
                self.write_metadata()
                errors = release_check.inspect_release()["errors"]
                self.assertIn("release_scope_mismatch", errors)
                self.assertIn("release_platform_subset_mismatch", errors)

    def _ci_text(self):
        return (self.root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    def _write_ci(self, text):
        path = self.root / ".github/workflows/ci.yml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_ci_quoted_uses_and_hash_inside_quotes_stay_valid(self):
        text = self._ci_text()
        text = text.replace(
            f"uses: {release_check.CI_CHECKOUT_PIN}",
            f'uses: "{release_check.CI_CHECKOUT_PIN}"',
        ).replace(
            f"uses: {release_check.CI_SETUP_PYTHON_PIN}",
            f"uses: '{release_check.CI_SETUP_PYTHON_PIN}'",
        ).replace(
            "      - name: Check out source\n",
            "      - name: \"check # out\"\n"
            "        run: \"echo # uses: evil/action@v1 persist-credentials: false\"\n"
            "      - name: Check out source\n",
            1,
        )
        self._write_ci(text)
        self.assertEqual([], release_check.inspect_release()["errors"])

    def test_ci_block_scalar_cannot_forge_or_satisfy_checkout(self):
        original = self._ci_text()
        checkout = (
            "      - name: Check out source\n"
            f"        uses: {release_check.CI_CHECKOUT_PIN} # v4.2.2\n"
            "        with:\n"
            "          persist-credentials: false\n"
        )
        forged = original.replace(
            checkout,
            "      - name: Check out source\n"
            "        run: |\n"
            f"          uses: {release_check.CI_CHECKOUT_PIN}\n"
            "          persist-credentials: false\n",
            1,
        )
        self.assertNotEqual(original, forged)
        self._write_ci(forged)
        self.assertIn("ci_checkout_sha_mismatch", release_check.inspect_release()["errors"])
        hidden = original.replace(
            "        with:\n          persist-credentials: false\n",
            "        run: |\n          persist-credentials: false\n",
            1,
        )
        self._write_ci(hidden)
        self.assertIn("ci_permissions_mismatch", release_check.inspect_release()["errors"])
        moved = original.replace(
            "        with:\n          persist-credentials: false\n",
            "\n",
            1,
        ).replace(
            "          python-version: ${{ matrix.python-version }}\n",
            "          python-version: ${{ matrix.python-version }}\n"
            "          persist-credentials: false\n",
            1,
        )
        self._write_ci(moved)
        self.assertIn("ci_permissions_mismatch", release_check.inspect_release()["errors"])

    def test_ci_flow_anchor_duplicate_and_quoted_keys_are_rejected(self):
        original = self._ci_text()
        cases = {
            "flow-step": original.replace(
                f"        uses: {release_check.CI_CHECKOUT_PIN} # v4.2.2\n",
                f"      - {{ uses: {release_check.CI_CHECKOUT_PIN} }}\n",
                1,
            ),
            "anchor": original.replace(
                "permissions:\n  contents: read\n",
                "permissions: &baseline\n  contents: read\n",
                1,
            ),
            "merge": original.replace(
                "permissions:\n  contents: read\n",
                "permissions:\n  <<: *extra\n  contents: read\n",
                1,
            ),
            "duplicate-job": original.replace(
                "jobs:\n  local-helper-matrix:\n",
                "jobs:\n  local-helper-matrix:\n    runs-on: ubuntu-latest\n  local-helper-matrix:\n",
                1,
            ),
            "duplicate-top-jobs": original.rstrip() + "\njobs:\n  other:\n    runs-on: ubuntu-latest\n",
            "quoted-permissions": original.replace(
                "  local-helper-matrix:\n",
                "  local-helper-matrix:\n    \"permissions\": write-all\n",
                1,
            ),
            "flow-permissions": original.replace(
                "  local-helper-matrix:\n",
                "  local-helper-matrix:\n    permissions: { contents: read }\n",
                1,
            ),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(original, text)
                self._write_ci(text)
                self.assertIn("ci_workflow_syntax_rejected", release_check.inspect_release()["errors"])

    def test_ci_empty_job_permissions_pass_and_reusable_workflow_is_rejected(self):
        original = self._ci_text()
        self._write_ci(original.replace(
            "  local-helper-matrix:\n",
            "  local-helper-matrix:\n    permissions: {}\n",
            1,
        ))
        self.assertEqual([], release_check.inspect_release()["errors"])
        pinned = "0123456789abcdef0123456789abcdef01234567"
        for uses in (
            "example/repo/.github/workflows/caller.yml@v1",
            "example/repo/.github/workflows/caller.yml@" + pinned,
        ):
            with self.subTest(uses=uses):
                self._write_ci(original.rstrip() + f"\n  reusable-caller:\n    uses: {uses}\n")
                self.assertIn("ci_action_unpinned", release_check.inspect_release()["errors"])

    def test_ci_cartesian_matrix_passes_and_exclude_of_required_pair_fails(self):
        original = self._ci_text()
        body = (
            "      matrix:\n"
            "        os:\n"
            "          - windows-latest\n"
            "          - ubuntu-latest\n"
            "          - macos-latest\n"
            "        python-version:\n"
            "          - '3.11'\n"
            "          - '3.12'\n"
            "          - '3.13'\n"
            "          - '3.14'\n"
        )
        start = original.index("      matrix:\n")
        end = original.index("    runs-on:")
        self._write_ci(original[:start] + body + original[end:])
        self.assertEqual([], release_check.inspect_release()["errors"])
        excluded = body + (
            "        exclude:\n"
            "          - os: ubuntu-latest\n"
            "            python-version: '3.12'\n"
        )
        self._write_ci(original[:start] + excluded + original[end:])
        self.assertIn("ci_matrix_mismatch", release_check.inspect_release()["errors"])

    def test_ci_scans_every_workflow_file(self):
        original = self._ci_text()
        extra = self.root / ".github/workflows/nightly.yaml"
        extra.write_text(original, encoding="utf-8")
        self.assertEqual([], release_check.inspect_release()["errors"])
        extra.write_text("permissions: write-all\n", encoding="utf-8")
        self.assertIn("ci_permissions_mismatch", release_check.inspect_release()["errors"])
        self._write_ci(original)
        (self.root / ".github/workflows/ci.yml").unlink()
        extra.write_text(original, encoding="utf-8")
        self.assertIn("ci_workflow_missing", release_check.inspect_release()["errors"])

    def _insert_before_checkout(self, step, base):
        marker = "      - name: Check out source\n"
        self.assertIn(marker, base)
        self._write_ci(base.replace(marker, step + marker, 1))

    def _evil_digest(self, pin):
        digest = pin.split("@", 1)[1]
        return digest[:-1] + ("0" if digest[-1] != "0" else "1")

    def test_ci_sequence_block_scalar_does_not_swallow_step_keys(self):
        original = self._ci_text()
        pin = release_check.CI_CHECKOUT_PIN
        swallowed_uses = (
            "      - name: |\n"
            "          echo hidden\n"
            "        uses: evil/unpinned@main\n"
        )
        self._insert_before_checkout(swallowed_uses, original)
        self.assertIn("ci_action_unpinned", release_check.inspect_release()["errors"])
        swallowed_checkout = (
            "      - name: |\n"
            "          echo hidden\n"
            f"        uses: {pin}\n"
        )
        self._insert_before_checkout(swallowed_checkout, original)
        self.assertIn("ci_permissions_mismatch", release_check.inspect_release()["errors"])
        block_only = (
            "      - name: |\n"
            "          uses: evil/unpinned@main\n"
            "        run: echo ok\n"
        )
        self._insert_before_checkout(block_only, original)
        self.assertEqual([], release_check.inspect_release()["errors"])

    def test_ci_sequence_spacing_preserves_step_uses_and_with(self):
        original = self._ci_text()
        for first, indent in (
            ("      -  name: Synthetic fixture\n", "         "),
            ("      -   name: |\n            Synthetic fixture\n", "          "),
        ):
            with self.subTest(first=first):
                self._insert_before_checkout(f"{first}{indent}uses: fixture/unpinned@main\n", original)
                self.assertEqual(["ci_action_unpinned"], release_check.inspect_release()["errors"])
                checkout = f"{first}{indent}uses: {release_check.CI_CHECKOUT_PIN}\n{indent}with:\n"
                self._insert_before_checkout(checkout + f"{indent}  persist-credentials: true\n", original)
                self.assertEqual(["ci_permissions_mismatch"], release_check.inspect_release()["errors"])
                self._insert_before_checkout(checkout + f"{indent}  persist-credentials: false\n", original)
                self.assertEqual([], release_check.inspect_release()["errors"])

    def test_ci_scalar_cannot_have_nested_entries(self):
        self._insert_before_checkout(
            "      - name: Synthetic fixture\n"
            "          timeout-minutes: 5\n",
            self._ci_text(),
        )
        self.assertEqual(["ci_workflow_syntax_rejected"], release_check.inspect_release()["errors"])

    def test_ci_tab_indentation_is_rejected(self):
        self._write_ci(self._ci_text().rstrip() + "\n\tuses: fixture/unpinned@main\n")
        self.assertEqual(["ci_workflow_syntax_rejected"], release_check.inspect_release()["errors"])

    def test_ci_action_name_case_cannot_bypass_pin_or_persist(self):
        original = self._ci_text()
        checkout_sha = release_check.CI_CHECKOUT_PIN.split("@", 1)[1]
        setup_pin = release_check.CI_SETUP_PYTHON_PIN
        same_sha = (
            "      - name: Case checkout\n"
            f"        uses: Actions/Checkout@{checkout_sha}\n"
            "        with:\n"
            "          persist-credentials: false\n"
        )
        self._insert_before_checkout(same_sha, original)
        self.assertEqual([], release_check.inspect_release()["errors"])
        missing_persist = (
            "      - name: Case checkout\n"
            f"        uses: Actions/Checkout@{checkout_sha}\n"
        )
        self._insert_before_checkout(missing_persist, original)
        errors = release_check.inspect_release()["errors"]
        self.assertIn("ci_permissions_mismatch", errors)
        self.assertNotIn("ci_checkout_sha_mismatch", errors)
        evil_checkout = (
            "      - name: Case checkout\n"
            f"        uses: Actions/Checkout@{self._evil_digest(release_check.CI_CHECKOUT_PIN)}\n"
            "        with:\n"
            "          persist-credentials: false\n"
        )
        self._insert_before_checkout(evil_checkout, original)
        self.assertIn("ci_checkout_sha_mismatch", release_check.inspect_release()["errors"])
        evil_setup = (
            "      - name: Case setup\n"
            f"        uses: Actions/Setup-Python@{self._evil_digest(setup_pin)}\n"
        )
        self._insert_before_checkout(evil_setup, original)
        self.assertIn("ci_setup_python_sha_mismatch", release_check.inspect_release()["errors"])

    def _cartesian_workflow(self, extra):
        original = self._ci_text()
        body = (
            "      matrix:\n"
            "        os:\n"
            "          - windows-latest\n"
            "          - ubuntu-latest\n"
            "          - macos-latest\n"
            "        python-version:\n"
            "          - '3.11'\n"
            "          - '3.12'\n"
            "          - '3.13'\n"
            "          - '3.14'\n"
            + extra
        )
        start = original.index("      matrix:\n")
        end = original.index("    runs-on:")
        return original[:start] + body + original[end:]

    def test_ci_matrix_exclude_partial_keys_match(self):
        self._write_ci(self._cartesian_workflow(
            "        exclude:\n"
            "          - os: macos-latest\n"
        ))
        self.assertIn("ci_matrix_mismatch", release_check.inspect_release()["errors"])
        self._write_ci(self._cartesian_workflow(
            "        exclude:\n"
            "          - python-version: '3.11'\n"
        ))
        self.assertIn("ci_matrix_mismatch", release_check.inspect_release()["errors"])
        self._write_ci(self._cartesian_workflow(
            "        exclude:\n"
            "          - os: self-hosted\n"
        ))
        self.assertEqual([], release_check.inspect_release()["errors"])
        restored = (
            "        exclude:\n"
            "          - os: ubuntu-latest\n"
            "        include:\n"
            "          - os: ubuntu-latest\n"
            "            python-version: '3.11'\n"
            "          - os: ubuntu-latest\n"
            "            python-version: '3.12'\n"
            "          - os: ubuntu-latest\n"
            "            python-version: '3.13'\n"
            "          - os: ubuntu-latest\n"
            "            python-version: '3.14'\n"
        )
        self._write_ci(self._cartesian_workflow(restored))
        self.assertEqual([], release_check.inspect_release()["errors"])
        self._write_ci(self._cartesian_workflow(
            "        exclude:\n"
            "          - arch: arm64\n"
        ))
        self.assertIn("ci_workflow_syntax_rejected", release_check.inspect_release()["errors"])
        self._write_ci(self._cartesian_workflow(
            "        exclude:\n"
            "          -\n"
        ))
        self.assertIn("ci_workflow_syntax_rejected", release_check.inspect_release()["errors"])

    def test_ci_job_level_uses_are_never_checkout_or_setup(self):
        original = self._ci_text()
        for pin in (release_check.CI_CHECKOUT_PIN, release_check.CI_SETUP_PYTHON_PIN):
            self._write_ci(original.rstrip() + f"\n  sneaky:\n    uses: {pin}\n")
            errors = release_check.inspect_release()["errors"]
            self.assertIn("ci_action_unpinned", errors)
            self.assertNotIn("ci_checkout_sha_mismatch", errors)
            self.assertNotIn("ci_setup_python_sha_mismatch", errors)
        checkout = (
            "      - name: Check out source\n"
            f"        uses: {release_check.CI_CHECKOUT_PIN} # v4.2.2\n"
            "        with:\n"
            "          persist-credentials: false\n"
        )
        self.assertIn(checkout, original)
        self._write_ci(
            original.replace(checkout, "", 1).rstrip()
            + f"\n  sneaky:\n    uses: {release_check.CI_CHECKOUT_PIN}\n"
        )
        errors = release_check.inspect_release()["errors"]
        self.assertIn("ci_action_unpinned", errors)
        self.assertIn("ci_checkout_sha_mismatch", errors)

    def test_ci_matrix_job_must_bind_runs_on_and_python_version(self):
        original = self._ci_text()
        self._write_ci(original.replace("runs-on: ${{ matrix.os }}", "runs-on: windows-latest", 1))
        self.assertIn("ci_matrix_binding_invalid", release_check.inspect_release()["errors"])
        self._write_ci(original.replace(
            "python-version: ${{ matrix.python-version }}",
            "python-version: '3.11'",
            1,
        ))
        self.assertIn("ci_matrix_binding_invalid", release_check.inspect_release()["errors"])
        spaced = original.replace(
            "runs-on: ${{ matrix.os }}",
            "runs-on: ${{matrix.os}}",
            1,
        ).replace(
            "python-version: ${{ matrix.python-version }}",
            "python-version: ${{  matrix.python-version  }}",
            1,
        )
        self._write_ci(spaced)
        self.assertEqual([], release_check.inspect_release()["errors"])

    def test_ci_matrix_job_requires_its_own_setup_python_step(self):
        original = self._ci_text()
        start = original.index("      - name: Set up Python ")
        end = original.index("      - name: Check release scope and metadata\n", start)
        without_setup = original[:start] + original[end:]
        self._write_ci(without_setup)
        self.assertIn("ci_matrix_binding_invalid", release_check.inspect_release()["errors"])
        self._write_ci(without_setup + (
            "\n  non-matrix-job:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            f"      - uses: {release_check.CI_SETUP_PYTHON_PIN}\n"
            "        with:\n"
            "          python-version: '3.11'\n"
        ))
        self.assertEqual(["ci_matrix_binding_invalid"], release_check.inspect_release()["errors"])

    def test_ci_matrix_binding_rejects_split_identifiers_and_wrong_fields(self):
        original = self._ci_text()
        for valid, invalid in (
            ("runs-on: ${{ matrix.os }}", "runs-on: ${{ m a t r i x . o s }}"),
            ("python-version: ${{ matrix.python-version }}", "python-version: ${{ matrix.python - version }}"),
            ("runs-on: ${{ matrix.os }}", "runs-on: ${{ matrix.python-version }}"),
            ("python-version: ${{ matrix.python-version }}", "python-version: ${{ matrix.os }}"),
        ):
            with self.subTest(invalid=invalid):
                self.assertIn(valid, original)
                self._write_ci(original.replace(valid, invalid, 1))
                self.assertEqual(["ci_matrix_binding_invalid"], release_check.inspect_release()["errors"])

    def test_ci_unspaced_hash_does_not_truncate_scalar(self):
        original = self._ci_text()
        self._write_ci(original.replace(
            "persist-credentials: false",
            "persist-credentials: false#true",
            1,
        ))
        self.assertIn("ci_permissions_mismatch", release_check.inspect_release()["errors"])
        self._write_ci(original.replace(
            "persist-credentials: false",
            "persist-credentials: false #true",
            1,
        ))
        self.assertEqual([], release_check.inspect_release()["errors"])


class ReleaseIdentityTests(unittest.TestCase):
    def test_real_ci_workflow_and_release_metadata_consistency(self):
        metadata = json.loads((release_check.ROOT / "release.json").read_text(encoding="utf-8"))
        self.assertEqual("0.1.1", release_check.__version__)
        self.assertEqual("0.1.1", metadata["version"])
        self.assertEqual("v0.1.1", metadata["proposed_tag"])
        self.assertEqual("published_release", metadata["publication_status"])
        self.assertEqual("https://github.com/duyunzhoudyz/dyz-patent-copyright-skills", metadata["repository_url"])
        self.assertEqual("synthetic_helper_only", metadata["capability_support"])
        self.assertEqual(["Windows", "Linux", "macOS"], metadata["verified_platforms"])
        self.assertEqual(["3.11", "3.12", "3.13", "3.14"], metadata["verified_python"])
        self.assertEqual(["Windows", "Linux", "macOS"], metadata["target_ci_platforms"])
        self.assertEqual(["3.11", "3.12", "3.13", "3.14"], metadata["target_ci_python"])
        self.assertEqual(metadata["verified_platforms"], metadata["supported_platforms"])
        self.assertEqual(metadata["verified_python"], metadata["supported_python"])
        self.assertEqual("杭州溥源智能科技有限公司", metadata["license_holder"])
        self.assertEqual("402784717@qq.com", metadata["commercial_contact"])
        self.assertEqual("AI4anyone(wechat)", metadata["security_contact"])
        ci_errors = release_check.check_ci_workflow(
            release_check.ROOT / ".github/workflows/ci.yml",
            target_platforms=metadata["target_ci_platforms"],
            target_python=metadata["target_ci_python"],
        )
        self.assertEqual([], ci_errors)
        ci_text = (release_check.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn(release_check.CI_CHECKOUT_PIN, ci_text)
        self.assertIn(release_check.CI_SETUP_PYTHON_PIN, ci_text)
        pairs = release_check._parse_ci_matrix_include(ci_text.splitlines())
        self.assertEqual(12, len(pairs))
        self.assertEqual(12, len(set(pairs)))
        # 源码归档没有 Git 索引；仍须通过上面的静态检查。
        if (release_check.ROOT / ".git").exists():
            self.assertEqual([], release_check.inspect_release(publication=True)["errors"])

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
