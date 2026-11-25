"""WP-01/WP-10：许可、固定清单、不覆盖、链接拒绝及真实隔离包演示。"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools import bundle

CLASSIC_ZLIB = (
    not hasattr(zlib, "ZLIBNG_VERSION")
    and "zlib-ng" not in getattr(zlib, "ZLIB_VERSION", "").lower()
    and "zlib-ng" not in getattr(zlib, "ZLIB_RUNTIME_VERSION", "").lower()
)

ROOT = Path(__file__).resolve().parents[1]
SOFTWARE_UPGRADE_MODULES = {
    "tools/software_revision.py", "tools/software_import.py",
    "tools/software_discovery.py", "tools/software_batch.py",
}


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-bundle-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        for relative in bundle.BUNDLE_FILES:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("synthetic fixture: " + relative).encode("utf-8"))
        self.destination = self.base / "package"

    def build(self):
        return bundle.build_bundle(self.destination, source_root=self.source)

    def assert_no_partial(self):
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.base.glob(".dyz-bundle-*")))

    def test_explicit_inventory_licenses_hashes_and_exclusions(self):
        expected = {"README.md", "LICENSE", "COMMERCIAL-LICENSE.md", "THIRD-PARTY-NOTICES.md"}
        expected.update("tools/" + name + ".py" for name in (
            "__init__", "__main__", "core", "cli", "disclosure", "patent", "patent_delivery", "patent_gate", "procedure",
            "software", "standards", "rendering", "bundle", "documents", "fidelity", "document_review", "codex_host", "host_bridge", "host_bridge_worker"))
        expected.update("skills/dyz-standards/resources/lifecycle/" + name + ".v2.schema.json"
                        for name in ("compilation-note", "comment-disposition"))
        expected.update(SOFTWARE_UPGRADE_MODULES)
        expected.update("tools/" + name + ".py" for name in (
            "software_delivery", "software_layout", "software_intake",
            "standards_delivery", "standards_contract", "standard_sources", "document_edit", "standard_pdf"))
        expected.update("skills/" + name + "/SKILL.md" for name in (
            "dyz-workbench", "dyz-patent", "dyz-procedure", "dyz-software", "dyz-standards", "dyz-rendering"))
        for skill, resources in {
            "dyz-workbench": ("tools", "package-use", "host-bridge"),
            "dyz-patent": ("examples", "topics", "tools", "cn-core-method", "delivery", "cn-gateway-example", "utility-structure-method", "utility-structure-example", "design-views-method", "design-views-example", "ep-control-method", "ep-control-example", "us-control-method", "us-control-example", "sequence-support-method", "sequence-support-example", "circuit-evidence-method", "circuit-evidence-example"),
            "dyz-procedure": ("topics", "tools", "complex-cn-method", "complex-cn-example", "cn-oa-method", "cn-oa-example", "protection-strategy-method", "protection-strategy-example", "pct-priority-method", "pct-priority-example", "us-fto-method", "us-fto-example"),
            "dyz-software": ("examples", "follow-up", "tools", "cn-core-method", "harbor-example", "complex-cn-method", "complex-cn-example", "us-registration-method", "us-registration-example", "us-expression-method", "us-expression-example"),
            "dyz-standards": ("examples", "follow-up", "tools", "cn-core-method", "river-example", "governance-method", "governance-example", "patent-policy-method", "patent-policy-example", "international-adoption-method", "international-adoption-example", "measurement-decision-method", "measurement-decision-example"),
            "dyz-rendering": ("examples", "review-checklists", "tools", "docx-readback"),
        }.items():
            expected.update(f"skills/{skill}/resources/{name}.md" for name in resources)
        expected.update({"skills/dyz-workbench/resources/example.json", "skills/dyz-patent/example.json",
            "skills/dyz-procedure/resources/example.json", "skills/dyz-procedure/resources/input-contracts.md",
            "skills/dyz-procedure/resources/oa-delivery-example.json",
            "skills/dyz-software/demo.py", "skills/dyz-rendering/demo.py", "skills/dyz-rendering/dom-check.js",
            "references/jurisdictions/patent-rules.json", "references/jurisdictions/software-rules.json",
            "references/standards/organization-rules.json",
            "references/jurisdictions/cn-core-evidence-20261101.md",
            "references/jurisdictions/cn-software-evidence-20261101.md",
            "references/standards/cn-organization-evidence-20261101.md",
            "references/jurisdictions/cn-disputes-evidence-20261101.md",
            "references/jurisdictions/cn-software-followup-evidence-20261101.md",
            "references/standards/cn-governance-evidence-20261101.md",
            "references/jurisdictions/cn-oa-evidence-20261101.md",
            "references/jurisdictions/us-software-evidence-20261101.md",
            "references/standards/common-patent-policy-evidence-20261101.md",
            "skills/dyz-patent/resources/cn-gateway-flow.svg",
            "skills/dyz-patent/resources/utility-structure-views.svg",
            "skills/dyz-patent/resources/design-views.svg",
            "references/jurisdictions/cn-utility-evidence-20261101.md",
            "references/jurisdictions/cn-design-evidence-20261101.md",
            "references/jurisdictions/cn-strategy-evidence-20261101.md",
            "references/jurisdictions/ep-control-evidence-20261101.md",
            "references/jurisdictions/pct-priority-evidence-20261101.md",
            "references/standards/international-adoption-evidence-20261101.md",
            "references/jurisdictions/us-control-evidence-20261101.md",
            "references/jurisdictions/sequence-support-evidence-20261101.md",
            "references/jurisdictions/us-expression-evidence-20261101.md",
            "skills/dyz-patent/resources/sequence-support-views.svg",
            "references/jurisdictions/us-fto-evidence-20261101.md",
            "references/domains/circuit-evidence-20261101.md",
            "references/standards/measurement-decision-evidence-20261101.md",
            "skills/dyz-patent/resources/circuit-evidence-views.svg"})
        expected.update(f"skills/dyz-standards/resources/river-demo/{name}"
                        for name in ("requirements.json", "vectors.json", "model.py"))
        for version in ("v1.0", "v1.1"):
            expected.update(f"skills/dyz-software/resources/harbor-demo/{version}/{name}.py"
                            for name in ("core", "cli", "api"))
        expected.update("docs/" + name + ".md" for name in (
            "capability-blueprint", "capability-contracts", "development-standards",
            "disclosure-and-handoff", "reference-analysis", "roadmap-and-quality"))
        expected.update({"skills/dyz-patent/resources/fact-and-support-review.md",
                         "skills/dyz-patent/resources/fidelity-example.json",
                         "skills/dyz-patent/resources/fidelity-recorder-draft.md",
                         "skills/dyz-patent/resources/fidelity-recorder-notes.md",
                         "skills/dyz-rendering/resources/fidelity-document-example.json"})
        expected.update({"skills/dyz-workbench/resources/reading-scope.md",
                         "skills/dyz-rendering/resources/reading-scope-example.json",
                         "skills/dyz-rendering/resources/reading-scope-records.md",
                         "skills/dyz-rendering/resources/reading-scope-statements.md",
            "skills/dyz-standards/resources/lifecycle/stage-gates.md",
            "skills/dyz-standards/resources/lifecycle/comment-disposition.md",
            "skills/dyz-standards/resources/lifecycle/compilation-note.md",
            "skills/dyz-standards/resources/lifecycle/submission-package.md",
            "skills/dyz-standards/resources/lifecycle/compilation-note.schema.json",
            "skills/dyz-standards/resources/lifecycle/comment-disposition.schema.json"})
        expected.update({"skills/dyz-rendering/resources/document-example.json",
                         "skills/dyz-patent/resources/cn-gateway-flow.png",
                         "docs/github-skill-comparison-20261102.md",
                         "docs/github-skill-comparison-20261102-sources.json"})
        expected.update({"references/jurisdictions/cn-software-guide-20261103.md",
                         "skills/dyz-software/resources/harbor-delivery-v1.2/form-candidate.md",
                         "skills/dyz-software/resources/harbor-delivery-v1.2/form-input.json"})
        expected.update({"references/jurisdictions/patent-public-search-20261103.md",
                         "references/jurisdictions/patent-epo-linked-source-20261103.md",
                         "skills/dyz-patent/resources/cn-epo-search.md",
                         "skills/dyz-patent/resources/cn-epo-search-record.json",
                         "skills/dyz-patent/resources/cn-epo-fulltext-study.md",
                         "skills/dyz-patent/resources/cn-epo-fulltext-record.json",
                         "skills/dyz-patent/resources/cn-priority-family-study.md",
                         "skills/dyz-patent/resources/cn-priority-family-record.json",
                         "skills/dyz-patent/resources/cn-gateway-search.md",
                         "skills/dyz-patent/resources/cn-gateway-search-record.json"})
        expected.add("references/jurisdictions/patent-official-evidence-20261103.md")
        expected.update("skills/dyz-patent/resources/cn-gateway-delivery/" + name for name in (
            "draft-v1.0.md", "draft-v1.1.md", "review-v1.0.md", "review-v1.1.md",
            "draft-v1.0-input.json", "draft-v1.1-input.json", "review-v1.0-input.json", "review-v1.1-input.json",
            "support.json", "change-impact.json", "file-bindings.json",
            "draft-v1.2.md", "review-v1.2.md", "draft-v1.2-input.json", "review-v1.2-input.json",
            "source-update-v1.2.json", "file-bindings-v1.2.json"))
        expected.update({"references/standards/river-source-evidence-20261103.md",
                         "skills/dyz-standards/resources/river-source-profile.md",
                         "skills/dyz-standards/resources/river-demo/source-boundary-vectors.json"})
        expected.add("skills/dyz-rendering/resources/research-documents.md")
        expected.update("skills/dyz-software/resources/harbor-review-readiness/" + name
                        for name in ("evidence-map.json", "review-cases.json", "review-cases.py", "case-results.json",
                                     "review-pack.md", "document-input.json", "file-bindings.json"))
        expected.update("skills/dyz-standards/resources/river-demo/" + name
                        for name in ("v11-boundary-vectors.json", "verify-v11.py"))
        expected.update("skills/dyz-standards/resources/river-v11-verification/" + name
                        for name in ("verification.md", "model-run.json", "document-input.json", "file-bindings.json"))
        expected.update("skills/dyz-standards/resources/river-local-interop/" + name for name in (
            "peer_a.py", "peer_b.py", "run_interop.py", "plan.json", "execution.json",
            "verification.md", "document-input.json", "file-bindings.json"))
        expected.update("skills/dyz-standards/resources/river-review-readiness/" + name
                        for name in ("review-pack.md", "evidence-map.json"))
        expected.update("skills/dyz-standards/resources/river-delivery-source/" + name for name in (
            "draft-v1.0.md", "draft-v1.1.md", "review-v1.0.md", "review-v1.1.md",
            "draft-v1.0-input.json", "draft-v1.1-input.json", "review-v1.0-input.json", "review-v1.1-input.json",
            "model-run.json", "change-impact.json", "file-bindings.json"))
        expected.update("skills/dyz-software/resources/harbor-demo/v1.3/" + name
                        for name in ("api.py", "cli.py", "core.py", "gui.py", "index.html"))
        expected.update("skills/dyz-software/resources/harbor-delivery-v1.3/" + name
                        for name in ("change-impact.json", "facts.json", "form-candidate.md", "form-input.json",
                                     "gui-default.png", "gui-sorted.png", "gui-duplicate-id.png",
                                     "manual-input.json", "manual.md", "scope-and-rights.md",
                                     "source-input.json", "source-lines.json", "source.txt"))
        expected.update({'skills/dyz-software/resources/harbor-delivery-v1.2/source-lines.json', 'skills/dyz-software/resources/harbor-delivery-v1.2/source.txt', 'skills/dyz-software/resources/harbor-demo/v1.2/index.html', 'skills/dyz-software/resources/harbor-demo/v1.2/core.py', 'skills/dyz-software/resources/harbor-demo/v1.2/gui.py', 'skills/dyz-standards/resources/river-delivery/standard-input.json', 'skills/dyz-standards/resources/river-delivery/verification-input.json', 'skills/dyz-software/resources/harbor-delivery-v1.2/gui-success.png', 'skills/dyz-software/resources/harbor-delivery-v1.2/gui-duplicate-id.png', 'skills/dyz-software/resources/harbor-delivery-v1.2/manual.md', 'skills/dyz-software/resources/harbor-delivery-v1.2/facts.json', 'skills/dyz-software/resources/harbor-demo/v1.2/api.py', 'skills/dyz-standards/resources/river-delivery/comments-input.json', 'skills/dyz-standards/resources/river-delivery/explanation-input.json', 'skills/dyz-software/resources/harbor-delivery-v1.2/source-input.json', 'skills/dyz-software/resources/harbor-demo/v1.2/cli.py', 'skills/dyz-standards/resources/river-delivery/comment-bindings.json', 'skills/dyz-software/resources/harbor-delivery-v1.2/manual-input.json'})
        expected.update({"tools/standard_intake.py", "tools/standard_review.py",
                         "skills/dyz-standards/resources/lifecycle/review-rules.v1.json",
                         "skills/dyz-standards/resources/lifecycle/rendering-profile.v2.json",
                         "skills/dyz-standards/resources/lifecycle/table-template-profiles.v1.json"})
        expected.update({"release.json", "RELEASE.md", "CHANGELOG.md", "CONTRIBUTING.md",
                         "CONTRIBUTOR-LICENSE.md", "SECURITY.md"})
        expected.update({
            "tools/mcp_server.py",
            "tools/install.py",
            "tools/patent_ir.py",
            "tools/omml.py",
            "tools/patent_intake.py",
            "tools/media_prep.py",
            "tools/template_mapper.py",
            "tools/connectors/__init__.py",
            "tools/connectors/base.py",
            "tools/connectors/patent_sources.py",
            "tools/connectors/standard_sources_live.py",
            "tools/jurisdiction_analyzers.py",
            "tools/procedure_strategy.py",
            "tools/visual_ledger.py",
            "tools/trial_pack.py",
            "skills/dyz-standards/resources/lifecycle/rendering-profile.v3.json",
            "skills/dyz-standards/resources/terminology-example/terminology-standard.json",
            "skills/dyz-workbench/resources/quickstarts.md",
        })
        self.assertEqual(expected, set(bundle.BUNDLE_FILES))
        self.assertEqual(len(expected), len(bundle.BUNDLE_FILES))
        for relative in (".references/upstream.py", "private/case.json", "outputs/result.json",
                         "tmp/tmp.py", ".git/config", ".breezell/config.json", "evals/test_private.py",
                         "tools/__pycache__/core.pyc", "tools/credentials.py",
                         "skills/dyz-workbench/resources/credentials.json",
                         "skills/dyz-workbench/private/secret.md", "skills/.env",
                         "references/jurisdictions/private.json", "docs/implementation-progress.md",
                         "docs/private.md", ".env", "credentials.json"):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic-excluded-marker")
        files = self.build()
        actual = {p.relative_to(self.destination).as_posix()
                  for p in self.destination.rglob("*") if p.is_file()}
        self.assertEqual(expected | {bundle.MANIFEST_NAME}, actual)
        self.assertEqual(actual, set(files))
        manifest = json.loads((self.destination / bundle.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual("not_provided", manifest["authentication"])
        self.assertEqual("not_performed", manifest["publication"])
        self.assertEqual(expected, {row["path"] for row in manifest["files"]})
        for row in manifest["files"]:
            raw = (self.destination / row["path"]).read_bytes()
            self.assertEqual((self.source / row["path"]).read_bytes(), raw)
            self.assertEqual(len(raw), row["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
            self.assertNotIn(b"synthetic-excluded-marker", raw)

    def test_existing_file_and_empty_directory_are_not_overwritten(self):
        self.destination.write_bytes(b"original")
        with self.assertRaisesRegex(bundle.BundleError, "destination_exists"):
            self.build()
        self.assertEqual(b"original", self.destination.read_bytes())
        self.destination.unlink()
        self.destination.mkdir()
        with self.assertRaisesRegex(bundle.BundleError, "destination_exists"):
            self.build()
        self.assertEqual([], list(self.destination.iterdir()))

    def test_missing_license_or_parent_leaves_nothing(self):
        (self.source / "LICENSE").unlink()
        with self.assertRaisesRegex(bundle.BundleError, "path_missing"):
            self.build()
        self.assert_no_partial()
        with self.assertRaisesRegex(bundle.BundleError, "path_missing"):
            bundle.build_bundle(self.base / "missing" / "package", source_root=self.source)
        self.assertFalse((self.base / "missing").exists())

    def test_invalid_destination_paths(self):
        for path in (self.base / ".." / "escape", self.base / "package:stream"):
            with self.subTest(path=str(path)), self.assertRaises(bundle.BundleError):
                bundle.build_bundle(path, source_root=self.source)
        self.assert_no_partial()

    def test_staging_failure_cleans_only_own_staging(self):
        original = bundle._copy_new
        def fail(source, target):
            original(source, target)
            if source.name == "LICENSE":
                raise OSError("synthetic-copy-failure")
        with patch.object(bundle, "_copy_new", side_effect=fail):
            with self.assertRaises(OSError):
                self.build()
        self.assert_no_partial()
        self.assertTrue((self.source / "LICENSE").is_file())

    def test_delivery_failure_removes_partial_target(self):
        original = Path.open
        def fail(path, *args, **kwargs):
            if path == self.destination / "tools" / "core.py":
                raise OSError("synthetic-delivery-failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", fail):
            with self.assertRaises(OSError):
                self.build()
        self.assert_no_partial()

    def test_partial_write_failure_removes_created_file(self):
        original = bundle.shutil.copyfileobj
        def fail(reader, writer, *args, **kwargs):
            if Path(writer.name) == self.destination / "LICENSE":
                writer.write(b"partial")
                raise OSError("synthetic-disk-full")
            return original(reader, writer, *args, **kwargs)
        with patch.object(bundle.shutil, "copyfileobj", side_effect=fail):
            with self.assertRaises(OSError):
                self.build()
        self.assert_no_partial()

    def test_destination_created_during_staging_is_preserved(self):
        original = bundle._copy_new
        def race(source, target):
            original(source, target)
            if source.name == "LICENSE":
                self.destination.mkdir()
                (self.destination / "other.txt").write_bytes(b"other-owner")
        with patch.object(bundle, "_copy_new", side_effect=race):
            with self.assertRaisesRegex(bundle.BundleError, "destination_exists"):
                self.build()
        self.assertEqual(b"other-owner", (self.destination / "other.txt").read_bytes())
        self.assertEqual(["other.txt"], [p.name for p in self.destination.iterdir()])
        self.assertFalse(list(self.base.glob(".dyz-bundle-*")))

    def test_failed_delivery_does_not_delete_unowned_files(self):
        original = Path.open
        def fail(path, *args, **kwargs):
            if path == self.destination / "tools" / "core.py":
                (self.destination / "other.txt").write_bytes(b"other-owner")
                raise OSError("synthetic-delivery-failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", fail):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual(["other.txt"], [p.name for p in self.destination.iterdir()])
        self.assertEqual(b"other-owner", (self.destination / "other.txt").read_bytes())

    def make_symlink(self, path, target, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc.__class__.__name__}")

    def test_source_file_symlink_and_dangling_symlink_rejected(self):
        path = self.source / "LICENSE"
        path.unlink()
        self.make_symlink(path, self.source / "README.md")
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            self.build()
        path.unlink()
        self.make_symlink(path, self.base / "missing-target")
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            self.build()
        self.assert_no_partial()

    def test_source_directory_symlink_rejected(self):
        actual = self.source / "actual-tools"
        (self.source / "tools").rename(actual)
        self.make_symlink(self.source / "tools", actual, directory=True)
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            self.build()
        self.assert_no_partial()

    def test_destination_and_parent_symlinks_rejected(self):
        self.make_symlink(self.destination, self.base / "absent", directory=True)
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            self.build()
        self.destination.unlink()
        alias = self.base / "alias"
        self.make_symlink(alias, self.source, directory=True)
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            bundle.build_bundle(alias / "new-package", source_root=self.source)
        self.assertFalse((self.source / "new-package").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_windows_junction_rejected_without_following(self):
        actual = self.source / "actual-tools"
        link = self.source / "tools"
        link.rename(actual)
        process = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(actual)],
                                 capture_output=True, check=False)
        self.assertEqual(0, process.returncode, "temporary junction creation failed")
        self.addCleanup(lambda: link.rmdir() if link.exists() else None)
        self.assertTrue(link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            self.build()
        self.assertTrue((actual / "core.py").is_file())
        self.assert_no_partial()

    def test_cli_error_messages_do_not_echo_path(self):
        for error, expected in ((bundle.BundleError("SYNTHETIC_PRIVATE"), (2, "bundle_rejected\n")),
                                (OSError("SYNTHETIC_PRIVATE"), (3, "bundle_io_failed\n"))):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(bundle, "build_bundle", side_effect=error), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = bundle.main(["--destination", "SYNTHETIC_PRIVATE"])
            self.assertEqual((code, err.getvalue()), expected)
            self.assertEqual("", out.getvalue())


class BundleVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-bundle-verify-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        for relative in bundle.BUNDLE_FILES:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("synthetic fixture: " + relative).encode("utf-8"))
        self.package = self.base / "package"
        bundle.build_bundle(self.package, source_root=self.source)
        self.manifest = self.package / bundle.MANIFEST_NAME
        self.original = self.manifest.read_bytes()
        self.expected = hashlib.sha256(self.original).hexdigest()

    def write_manifest(self, value):
        self.manifest.write_text(json.dumps(value), encoding="utf-8")

    def test_inventory_external_hash_and_unlisted_files_are_read_only(self):
        private = self.package / "private" / "unlisted.txt"
        private.parent.mkdir()
        private.write_bytes(b"SYNTHETIC_NOT_TO_BE_READ")
        before = {p: p.read_bytes() for p in [self.manifest, private, *(self.package / x for x in bundle.BUNDLE_FILES)]}
        original_open = Path.open

        def guarded(path, *args, **kwargs):
            self.assertNotEqual(private, path)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded), \
                patch.object(Path, "rglob", side_effect=AssertionError("must not enumerate unlisted paths")):
            internal = bundle.verify_bundle(self.package)
            bound = bundle.verify_bundle(self.package, expected_manifest_sha256=self.expected)
        self.assertEqual("manifest_internal_consistency_only", internal["binding"])
        self.assertEqual("expected_manifest_hash_matched", bound["binding"])
        self.assertEqual((309, self.expected), (bound["source_files"], bound["manifest_sha256"]))
        for historical in (bundle.R21_BUNDLE_FILES, bundle.R22_METADATA_BUNDLE_FILES,
                           bundle.R28_BUNDLE_FILES):
            self.assertFalse(SOFTWARE_UPGRADE_MODULES.intersection(historical))
        for name in ("tools/patent_delivery.py", "tools/patent_gate.py", "skills/dyz-patent/resources/delivery.md"):
            self.assertIn(name, bundle.BUNDLE_FILES)
            self.assertNotIn(name, bundle.R21_BUNDLE_FILES)
            self.assertNotIn(name, bundle.R22_METADATA_BUNDLE_FILES)
            self.assertNotIn(name, bundle.R28_BUNDLE_FILES)
        self.assertIn("skills/dyz-workbench/resources/reading-scope.md", bundle.BUNDLE_FILES)
        self.assertIn("skills/dyz-rendering/resources/reading-scope-example.json", bundle.BUNDLE_FILES)
        self.assertEqual("not_enumerated_or_read", bound["unlisted_paths"])
        self.assertEqual("not_performed", bound["source_execution"])
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))

    def test_arbitrary_legacy_layout_cannot_downgrade_current_inventory(self):
        value = json.loads(self.original)
        value["files"] = [row for row in value["files"] if row["path"] != "tools/codex_host.py"]
        self.write_manifest(value)
        arbitrary_hash = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.assertNotEqual(bundle.R21_MANIFEST_SHA256, arbitrary_hash)
        with self.assertRaisesRegex(bundle.BundleError, "bundle_inventory_changed"):
            bundle.verify_bundle(self.package, expected_manifest_sha256=arbitrary_hash)

    def test_arbitrary_metadata_layout_cannot_select_pinned_r22_exception(self):
        value = json.loads(self.original)
        value['files'] = [row for row in value['files']
                          if row['path'] in bundle.R22_METADATA_BUNDLE_FILES
                          and row['path'] not in SOFTWARE_UPGRADE_MODULES]
        self.assertEqual(250, len(value['files']))
        self.write_manifest(value)
        arbitrary_hash = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.assertNotEqual(bundle.R22_METADATA_MANIFEST_SHA256, arbitrary_hash)
        with self.assertRaisesRegex(bundle.BundleError, 'bundle_inventory_changed'):
            bundle.verify_bundle(self.package, expected_manifest_sha256=arbitrary_hash)

    def test_prior_253_layout_requires_its_exact_external_pin(self):
        value=json.loads(self.original)
        value['files']=[row for row in value['files']
                        if row['path'] in bundle.R28_BUNDLE_FILES
                        and row['path'] not in SOFTWARE_UPGRADE_MODULES]
        self.assertEqual(253,len(value['files']))
        self.write_manifest(value);declared=hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        with self.assertRaisesRegex(bundle.BundleError,'bundle_inventory_changed'):
            bundle.verify_bundle(self.package,expected_manifest_sha256=declared)
        with patch.object(bundle,'R28_MANIFEST_SHA256S',frozenset({declared})):
            out=bundle.verify_bundle(self.package,expected_manifest_sha256=declared)
            self.assertEqual('r25_r28_externally_pinned',out['inventory_layout'])
            with self.assertRaisesRegex(bundle.BundleError,'bundle_inventory_changed'):
                bundle.verify_bundle(self.package)

    def test_external_binding_distinguishes_rewritten_files_and_manifest(self):
        path = self.package / "README.md"
        changed = path.read_bytes() + b"\nsynthetic change\n"
        path.write_bytes(changed)
        manifest = json.loads(self.original)
        manifest["files"][0].update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
        self.write_manifest(manifest)
        self.assertEqual("manifest_internal_consistency_only", bundle.verify_bundle(self.package)["binding"])
        with self.assertRaisesRegex(bundle.BundleError, "manifest_binding_changed"):
            bundle.verify_bundle(self.package, expected_manifest_sha256=self.expected)
        self.manifest.write_bytes(b"not JSON")
        with self.assertRaisesRegex(bundle.BundleError, "manifest_binding_changed"):
            bundle.verify_bundle(self.package, expected_manifest_sha256=self.expected)
        for bad in ("", "A" * 64, "0" * 63, 17):
            with self.subTest(expected_hash=bad), self.assertRaisesRegex(bundle.BundleError, "manifest_hash_invalid"):
                bundle.verify_bundle(self.package, expected_manifest_sha256=bad)

    def test_missing_and_same_length_changed_source_are_rejected(self):
        path = self.package / "LICENSE"
        raw = path.read_bytes()
        path.write_bytes(b"X" + raw[1:])
        with self.assertRaisesRegex(bundle.BundleError, "source_changed"):
            bundle.verify_bundle(self.package)
        path.unlink()
        with self.assertRaisesRegex(bundle.BundleError, "path_missing"):
            bundle.verify_bundle(self.package)

    def test_all_inventory_rows_checked_before_any_source_file_open(self):
        variants = []
        for path in ("../private.txt", "private/unlisted.txt", "LICENSE"):
            item = json.loads(self.original)
            item["files"][-1]["path"] = path
            variants.append(item)
        for change in ("missing", "extra", "reordered", "wrong-byte-type", "negative-bytes", "wrong-sha", "extra-key", "auth"):
            item = json.loads(self.original)
            if change == "missing":
                item["files"].pop()
            elif change == "extra":
                item["files"].append(dict(item["files"][0]))
            elif change == "reordered":
                item["files"].reverse()
            elif change == "wrong-byte-type":
                item["files"][-1]["bytes"] = True
            elif change == "negative-bytes":
                item["files"][-1]["bytes"] = -1
            elif change == "wrong-sha":
                item["files"][-1]["sha256"] = "not-a-hash"
            elif change == "extra-key":
                item["files"][-1]["extra"] = "unexpected"
            else:
                item["authentication"] = "verified"
            variants.append(item)
        original_open = Path.open

        def manifest_only(path, *args, **kwargs):
            self.assertEqual(self.manifest, path, "invalid manifest must not expand or begin source reads")
            return original_open(path, *args, **kwargs)

        for index, value in enumerate(variants):
            with self.subTest(variant=index):
                self.write_manifest(value)
                with patch.object(Path, "open", manifest_only), self.assertRaises(bundle.BundleError):
                    bundle.verify_bundle(self.package)

    def test_malformed_duplicate_and_oversized_manifests_are_rejected(self):
        duplicate = self.original.decode("utf-8").replace('"path": "README.md"', '"path": "README.md", "path": "README.md"', 1)
        self.assertNotEqual(self.original.decode("utf-8"), duplicate)
        for raw in (b"not JSON", b"\xff", b"[]", duplicate.encode("utf-8"), b"[" * 1100 + b"]" * 1100,
                    b" " * (bundle.MAX_MANIFEST_BYTES + 1)):
            self.manifest.write_bytes(raw)
            with self.subTest(length=len(raw)), self.assertRaisesRegex(bundle.BundleError, "manifest_invalid"):
                bundle.verify_bundle(self.package)

    def test_manifest_source_and_root_links_are_rejected(self):
        def link(path, target, directory=False):
            try:
                path.symlink_to(target, target_is_directory=directory)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc.__class__.__name__}")

        saved = self.package / "saved-manifest"
        self.manifest.rename(saved)
        link(self.manifest, saved)
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            bundle.verify_bundle(self.package)
        self.manifest.unlink()
        saved.rename(self.manifest)
        source = self.package / "LICENSE"
        source.unlink()
        link(source, self.source / "LICENSE")
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            bundle.verify_bundle(self.package)
        source.unlink()
        source.write_bytes((self.source / "LICENSE").read_bytes())
        alias = self.base / "package-alias"
        link(alias, self.package, directory=True)
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            bundle.verify_bundle(alias)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_listed_parent_junction_is_rejected_without_following(self):
        actual = self.package / "actual-tools"
        (self.package / "tools").rename(actual)
        link = self.package / "tools"
        self.assertTrue(link.resolve().is_relative_to(self.base))
        self.assertTrue(actual.resolve().is_relative_to(self.base))
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(actual)], capture_output=True)
        self.assertEqual(0, result.returncode)
        self.addCleanup(lambda: link.rmdir() if link.exists() else None)
        with self.assertRaisesRegex(bundle.BundleError, "link_rejected"):
            bundle.verify_bundle(self.package)
        self.assertTrue((actual / "core.py").is_file())

    def test_verify_cli_json_and_private_error_redaction(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = bundle.main(["--verify", str(self.package), "--manifest-sha256", self.expected])
        self.assertEqual((0, ""), (code, err.getvalue()))
        self.assertEqual("matched", json.loads(out.getvalue())["status"])
        for error, expected in ((bundle.BundleError("SYNTHETIC_PRIVATE"), (2, "bundle_rejected\n")),
                                (OSError("SYNTHETIC_PRIVATE"), (3, "bundle_io_failed\n"))):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(bundle, "verify_bundle", side_effect=error), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = bundle.main(["--verify", "SYNTHETIC_PRIVATE"])
            self.assertEqual((code, err.getvalue()), expected)
            self.assertEqual("", out.getvalue())


class IndependentBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="dyz-independent-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.installation = cls.base / "installation"
        cls.environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
        process = subprocess.run([sys.executable, "-E", "-s", "-S", "-B", "-m", "tools.bundle",
                                  "--destination", str(cls.installation)], cwd=ROOT,
                                 env=cls.environment, capture_output=True, text=True)
        if process.returncode != 0 or process.stdout != "bundle_created\n":
            raise AssertionError(process.stderr or process.stdout)

    def command(self, *args, cwd=None):
        process = subprocess.run([sys.executable, "-E", "-s", "-S", "-B", *args],
                                 cwd=cwd or self.installation, env=self.environment,
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, process.returncode, process.stderr)
        return process.stdout

    def test_real_package_license_bytes_and_manifest(self):
        manifest = json.loads((self.installation / bundle.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(309, len(manifest["files"]))
        for row in manifest["files"]:
            raw = (self.installation / row["path"]).read_bytes()
            self.assertEqual((ROOT / row["path"]).read_bytes(), raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"])
        self.assertFalse((self.installation / "evals").exists())
        self.assertFalse((self.installation / ".references").exists())

    def test_complete_package_verifier_runs_from_foreign_directory(self):
        expected = hashlib.sha256((self.installation / bundle.MANIFEST_NAME).read_bytes()).hexdigest()
        report = json.loads(self.command(str(self.installation / "tools/bundle.py"), "--verify", str(self.installation),
                                         "--manifest-sha256", expected, cwd=self.base))
        self.assertEqual((309, expected, "expected_manifest_hash_matched"),
                         (report["source_files"], report["manifest_sha256"], report["binding"]))
        self.assertEqual("not_performed", report["host_installation_or_discovery"])

    def test_patent_delivery_import_uses_only_complete_package(self):
        code = ("import sys; from pathlib import Path; root = Path(sys.argv[1]).resolve(); "
                "sys.path.insert(0, str(root)); from tools import patent_delivery; "
                "assert Path(patent_delivery.__file__).resolve() == root / 'tools/patent_delivery.py'; "
                "assert all(callable(getattr(patent_delivery, name)) for name in "
                "('prepare', 'verify', 'register_package', 'record_confirmation', 'confirmation_status')); "
                "assert (root / 'skills/dyz-patent/resources/delivery.md').is_file(); "
                "from tools.patent_gate import audit_final_text; from tools.core import sha256_bytes; "
                "source = '只有记录已写入，才允许确认。'; "
                "originals = [{'id':'O','version':'1','role':'original','text':source,'sha256':sha256_bytes(source.encode())}]; "
                "assert audit_final_text({'body':source}, originals)['status'] == 'checked'; "
                "assert audit_final_text({'body':'一旦记录已写入，就允许确认。'}, originals)['status'] == 'blocked'; "
                "print('patent_delivery_imported')")
        self.assertEqual("patent_delivery_imported\n",
                         self.command("-c", code, str(self.installation), cwd=self.base))

    def test_procedure_actual_candidate_runs_with_only_complete_package(self):
        self.assertEqual("result_written\n", self.command("-m", "tools", "run", "PROC-05",
            "--synthetic", "--root", str(self.installation),
            "--input", "skills/dyz-procedure/resources/oa-delivery-example.json",
            "--output", "procedure-delivery-result.json"))
        output = json.loads((self.installation / "procedure-delivery-result.json").read_text(encoding="utf-8"))
        self.assertEqual("光学接口", output["artifacts"]["replacement_candidates"][0]["text"])
        self.assertEqual("supplied_partial", output["artifacts"]["replacement_status"])
        self.assertEqual("checked", output["artifacts"]["fidelity"]["status"])
        self.assertEqual("not_performed", output["professional_review"])

    def test_readme_runtime_links_and_declared_development_exclusions(self):
        text = (self.installation / "README.md").read_text(encoding="utf-8")
        self.assertIn("这些开发材料不随本地包分发", text)
        prose = re.sub(r"```.*?```", "", text, flags=re.S)
        missing = set()
        for href in re.findall(r"\[[^\]]*\]\(([^)]+)\)", prose):
            if "://" in href or href.startswith("#"):
                continue
            target = (self.installation / href.split("#", 1)[0]).resolve()
            self.assertTrue(target.is_relative_to(self.installation.resolve()))
            if not target.is_file():
                missing.add(target.relative_to(self.installation.resolve()).as_posix())
        self.assertEqual(set(), missing)

    def test_r11_fields_export_and_reject_changed_fact_dependencies_from_complete_package(self):
        input_name = "skills/dyz-software/resources/harbor-delivery-v1.2/form-input.json"
        args = ("--synthetic", "--root", ".", "--input", input_name, "--output", "generated-r11-fields")
        self.command("-m", "tools.documents", *args)
        self.command("-m", "tools.documents", *args, "--verify")
        generated = self.installation / "generated-r11-fields"
        body = (generated / "body/source.txt").read_text(encoding="utf-8")
        notes = (generated / "internal/notes.txt").read_text(encoding="utf-8")
        manifest = json.loads((generated / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("255物理行", body)
        self.assertIn("未知", body)
        self.assertNotIn("内部核验说明", body)
        self.assertIn("内部核验说明", notes)
        self.assertEqual("needs_review", manifest["status"])
        self.assertEqual("not_performed", manifest["professional_review"])
        spec = json.loads((self.installation / input_name).read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="dyz-r11-facts-") as folder:
            source_root = Path(folder)
            for entry in [*spec["sources"], *spec["dependencies"]]:
                relative = entry["path"]
                target = source_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((self.installation / relative).read_bytes())
            facts_path = source_root / "skills/dyz-software/resources/harbor-delivery-v1.2/facts.json"
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            facts["version"] = "1.3"
            facts_path.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
            copied_input = source_root / input_name
            copied_input.parent.mkdir(parents=True, exist_ok=True)
            copied_input.write_bytes((self.installation / input_name).read_bytes())
            process = subprocess.run([sys.executable, "-E", "-s", "-S", "-m", "tools.documents", "--synthetic",
                                      "--root", str(source_root), "--input", input_name, "--output", "stale-fields"],
                                     cwd=self.installation, env=self.environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(2, process.returncode)
            self.assertFalse((source_root / "stale-fields").exists())
            probe = (
                "import json,sys\nfrom pathlib import Path\n"
                "from tools.documents import build\nfrom tools.core import ContractError\n"
                "root=Path(sys.argv[1]); spec=json.loads((root/sys.argv[2]).read_text(encoding='utf-8'))\n"
                "try:\n    build(root,spec,'stale-fields-direct',synthetic=True)\n"
                "except ContractError as error:\n"
                "    assert str(error)=='document_source_changed',str(error)\n"
                "    print('expected_dependency_rejected')\n"
                "else:\n    raise AssertionError('changed facts were accepted')\n"
            )
            self.assertEqual("expected_dependency_rejected\n", self.command("-c", probe, str(source_root), input_name))
            self.assertFalse((source_root / "stale-fields-direct").exists())

    def test_v13_feature_and_three_current_materials_run_inside_complete_package(self):
        script = (
            "import sys;sys.path.insert(0,'skills/dyz-software/resources/harbor-demo/v1.3');"
            "from core import VERSION,convert;assert VERSION=='1.3';"
            "raw=b'[{\"id\":\"B\",\"label\":\"x\",\"value\":2},{\"id\":\"A\",\"label\":\"y\",\"value\":1}]';"
            "assert convert(raw)[0]=='id,label,value\\nB,x,2\\nA,y,1\\n';"
            "assert convert(raw,sort_by_id=True)[0]=='id,label,value\\nA,y,1\\nB,x,2\\n';"
            "print('v13_current_sort_checked')")
        self.assertEqual("v13_current_sort_checked\n", self.command("-c", script))
        for name in ("source", "manual", "form"):
            output = "generated-v13-" + name
            args = ("--synthetic", "--root", ".", "--input",
                    f"skills/dyz-software/resources/harbor-delivery-v1.3/{name}-input.json", "--output", output)
            self.command("-m", "tools.documents", *args)
            self.command("-m", "tools.documents", *args, "--verify")
            generated = self.installation / output
            body = (generated / "body/source.txt").read_text(encoding="utf-8")
            self.assertNotIn("内部核验说明", body)
            self.assertIn("1.3", body)
            manifest = json.loads((generated / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("needs_review", manifest["status"])
            self.assertEqual("not_performed", manifest["professional_review"])

    def test_fidelity_example_runs_from_package_without_development_files(self):
        script = ('import json; from pathlib import Path; from tools.patent import run; '
                  'p=json.loads(Path("skills/dyz-patent/resources/fidelity-example.json").read_text(encoding="utf-8")); '
                  'r=run("REVIEW-02",p); '
                  'assert r["artifacts"]["fidelity"]["status"]=="checked"; '
                  'assert r["professional_review"]=="not_performed"; print("fidelity_example_checked")')
        self.assertEqual("fidelity_example_checked\n", self.command("-c", script))

    def test_bound_fidelity_document_runs_and_rechecks_from_package(self):
        arguments = ("--synthetic", "--root", ".", "--input",
                     "skills/dyz-rendering/resources/fidelity-document-example.json", "--output", "generated-fidelity")
        self.command("-m", "tools.documents", *arguments)
        self.command("-m", "tools.documents", *arguments, "--verify")
        path = self.installation / "generated-fidelity"
        report = json.loads((path / "internal/fidelity-review.json").read_text(encoding="utf-8"))
        self.assertEqual("checked", report["status"])
        self.assertEqual("not_performed", report["professional_review"])
        self.assertNotIn("原始参数域", (path / "body/source.txt").read_text(encoding="utf-8"))

    def test_edited_docx_readback_cli_uses_only_complete_package(self):
        script = ('from pathlib import Path; from tools.documents import make_docx; '
                  'b=[{"id":"CLAUSE8","kind":"paragraph","text":"8 仅当A成立且B成立。"}]; '
                  'Path("review-baseline.docx").write_bytes(make_docx(b,[])); '
                  'b[0]["text"]="11 仅当A成立或B成立。"; '
                  'Path("review-edited.docx").write_bytes(make_docx(b,[]))')
        self.command("-c", script)
        self.command("-m", "tools.document_review", "--synthetic", "--root", ".", "--input", "review-edited.docx",
                     "--baseline", "review-baseline.docx", "--output", "review-result.json")
        report = json.loads((self.installation / "review-result.json").read_text(encoding="utf-8"))
        self.assertEqual("complete_supported_subset", report["comparison"]["state"])
        self.assertFalse(report["comparison"]["paired_bookmarks"][0]["text_equal"])
        self.assertEqual("CLAUSE8", report["comparison"]["paired_bookmarks"][0]["name"])
        self.assertEqual("not_performed", report["professional_review"])

    def test_document_export_and_verification_from_complete_package(self):
        arguments = ("--synthetic", "--root", ".", "--input",
                     "skills/dyz-rendering/resources/document-example.json", "--output", "generated-patent")
        self.assertIn("document_written_needs_review", self.command("-m", "tools.documents", *arguments))
        self.assertIn("document_verified_needs_review", self.command("-m", "tools.documents", *arguments, "--verify"))
        report = json.loads((self.installation / "generated-patent/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((46, 1), (report["checks"]["paragraphs"], report["checks"]["figures"]))
        self.assertEqual("needs_review", report["status"])
        self.assertEqual("not_generated", report["pdf"])

    def test_software_and_standard_exports_use_only_complete_package_files(self):
        inputs = ["skills/dyz-software/resources/harbor-delivery-v1.2/source-input.json",
                  "skills/dyz-software/resources/harbor-delivery-v1.2/manual-input.json",
                  "skills/dyz-standards/resources/river-delivery/standard-input.json",
                  "skills/dyz-standards/resources/river-delivery/comments-input.json"]
        for number, source in enumerate(inputs):
            output = "document-example-" + str(number)
            args = ("--synthetic", "--root", ".", "--input", source, "--output", output)
            self.assertIn("document_written_needs_review", self.command("-m", "tools.documents", *args))
            self.assertIn("document_verified_needs_review", self.command("-m", "tools.documents", *args, "--verify"))
        changed = self.installation / "skills/dyz-software/resources/harbor-demo/v1.2/core.py"
        original = changed.read_bytes()
        try:
            changed.write_bytes(original + b"\n# changed version\n")
            result = subprocess.run([sys.executable, "-E", "-s", "-S", "-m", "tools.documents",
                                     "--synthetic", "--root", ".", "--input", inputs[0],
                                     "--output", "document-example-0", "--verify"],
                                    cwd=self.installation, capture_output=True)
            self.assertEqual(2, result.returncode)
        finally:
            changed.write_bytes(original)
        self.assertEqual(original, changed.read_bytes())

    def test_river_model_uses_only_installed_fixture_files(self):
        model = self.installation / "skills/dyz-standards/resources/river-demo/model.py"
        report = json.loads(self.command(str(model), cwd=self.base))
        self.assertEqual((58, 58, 0, 0), tuple(report[k] for k in
                         ("count", "passed", "failed", "skipped")))
        self.assertEqual({"model.py", "requirements.json", "vectors.json"},
                         {Path(row["path"]).name for row in report["sources"]})
        for row in report["sources"]:
            path = Path(row["path"])
            # Windows temp roots can use an 8.3 alias while model receipts resolve it.
            self.assertTrue(path.resolve().is_relative_to(self.installation.resolve()))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
        self.assertTrue(all(row["caller_state_unchanged"] for row in report["results"]))

    def test_river_source_boundary_vectors_run_from_isolated_package(self):
        base = self.installation / "skills/dyz-standards/resources/river-demo"
        vectors = base / "source-boundary-vectors.json"
        report = json.loads(self.command(str(base / "model.py"), str(vectors), cwd=self.base))
        self.assertEqual((16, 16, 0, 0), tuple(report[k] for k in
                         ("count", "passed", "failed", "skipped")))
        self.assertEqual({"model.py", "requirements.json", vectors.name},
                         {Path(row["path"]).name for row in report["sources"]})
        for row in report["sources"]:
            path = Path(row["path"]).resolve()
            self.assertTrue(path.is_relative_to(self.installation.resolve()))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
        self.assertTrue(all(row["caller_state_unchanged"] for row in report["results"]))
        corpus = json.loads(vectors.read_text(encoding="utf-8"))
        dispute = next(row for row in corpus["vectors"] if row["id"] == "SB-13")
        self.assertEqual("disputed_original_section7_vs_verified_erratum5318_no_rfc_grade",
                         dispute["rfc8259_relation"]["state"])

    def test_software_readiness_provenance_boundaries_and_current_file_from_package(self):
        relative = "skills/dyz-software/resources/harbor-review-readiness"
        base = self.installation / relative
        historical_files = {name: (base / name).read_bytes() for name in
                            ("review-cases.json", "case-results.json", "document-input.json", "file-bindings.json")}
        historical = subprocess.run([sys.executable, "-E", "-s", "-S", str(base / "review-cases.py")],
                                    cwd=self.base, env=self.environment, capture_output=True,
                                    text=True, encoding="utf-8")
        self.assertEqual(2, historical.returncode, historical.stderr)
        self.assertEqual("source_binding_changed", json.loads(historical.stdout)["error"])
        corpus = json.loads(historical_files["review-cases.json"])
        # 历史结果不重新签发；当前代码仅在独立临时输入中重新绑定并运行同一组期望。
        current_tools = {"tools/software.py", "tools/core.py"}
        for row in corpus["source_bindings"]:
            if row["path"] in current_tools:
                row["sha256"] = hashlib.sha256((self.installation / row["path"]).read_bytes()).hexdigest()
        current_cases = self.base / "current-software-readiness-cases.json"
        current_cases.write_text(json.dumps(corpus), encoding="utf-8")
        report = json.loads(self.command(str(base / "review-cases.py"), str(current_cases), cwd=self.base))
        self.assertEqual(corpus["source_bindings"], report["source_bindings"])
        self.assertEqual((4, 0, 0), (report["passed"], report["failed"], report["skipped"]))
        self.assertTrue(report["actual_facts_unchanged"] and report["temporary_secret_probe_removed"])
        observed = {row["id"]: row["observed"] for row in report["results"]}
        self.assertEqual(0, observed["missing_actual_title"]["selected"])
        self.assertEqual(201, observed["hypothetical_permission_change"]["selected"])
        self.assertEqual("not_granted", observed["separate_synthetic_secret_probe"]["external_permission"])
        for name, code in (("wrong-readiness", 1), ("stale-readiness", 2)):
            data = json.loads(json.dumps(corpus))
            if code == 1:
                data["expectations"]["missing_actual_title"]["selected"] = 266
            else:
                data["source_bindings"][0]["sha256"] = "0" * 64
            path = self.base / (name + ".json")
            path.write_text(json.dumps(data), encoding="utf-8")
            process = subprocess.run([sys.executable, "-E", "-s", "-S", str(base / "review-cases.py"), str(path)],
                                     cwd=self.base, env=self.environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(code, process.returncode, process.stderr)
            result = json.loads(process.stdout)
            if code == 1:
                self.assertEqual(1, result["failed"])
            else:
                self.assertEqual("source_binding_changed", result["error"])
        unlisted = json.loads(json.dumps(corpus))
        unlisted["source_bindings"].append({"path": "private/not-an-allowed-read", "sha256": "0" * 64})
        probe = self.base / "unlisted-readiness.json"
        probe.write_text(json.dumps(unlisted), encoding="utf-8")
        rejected = subprocess.run([sys.executable, "-E", "-s", "-S", str(base / "review-cases.py"), str(probe)],
                                  cwd=self.base, env=self.environment, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(2, rejected.returncode)
        self.assertEqual("source_inventory_invalid", json.loads(rejected.stdout)["error"])
        evidence = json.loads((base / "evidence-map.json").read_text(encoding="utf-8"))
        self.assertEqual((5, 20, 266), (len(evidence["files"]), len(evidence["fields"]), evidence["source_physical_lines"]))
        for field in evidence["fields"]:
            for item in field["evidence"]:
                path = self.installation / item["path"]
                self.assertEqual(item["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                first, last = item["lines"]
                selected = "\n".join(path.read_text(encoding="utf-8").splitlines()[first-1:last])
                self.assertEqual(item["span_sha256"], hashlib.sha256(selected.encode("utf-8")).hexdigest())
        bindings = json.loads((base / "file-bindings.json").read_text(encoding="utf-8"))["document"]
        current_spec = json.loads(historical_files["document-input.json"])
        for rows in (current_spec["dependencies"], current_spec["research_materials"]):
            for row in rows:
                if row["path"] in current_tools:
                    row["sha256"] = hashlib.sha256((self.installation / row["path"]).read_bytes()).hexdigest()
        current_input = "current-software-readiness-input.json"
        (self.installation / current_input).write_text(json.dumps(current_spec), encoding="utf-8")
        args = ("--research-example", "--root", ".", "--input", current_input, "--output", "software-readiness")
        self.command("-m", "tools.documents", *args)
        self.command("-m", "tools.documents", *args, "--verify")
        path = self.installation / "software-readiness/body/document.docx"
        if CLASSIC_ZLIB:
            self.assertEqual(bindings["docx_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.command("-m", "tools.document_review", "--research-example", "--root", ".",
                     "--input", "software-readiness/body/document.docx", "--output", "software-readiness-readback.json")
        read = json.loads((self.installation / "software-readiness-readback.json").read_text(encoding="utf-8"))
        self.assertEqual("complete_supported_subset", read["current"]["readback_state"])
        unique = {x["name"]: x for x in read["current"]["bookmarks"] if x["identity_state"] == "paired_unique_name"}
        self.assertEqual(22, len(unique))
        for target in bindings["targets"]:
            self.assertEqual(target["text_sha256"], hashlib.sha256(unique[target["bookmark"]]["text"].encode("utf-8")).hexdigest())
        for field in evidence["fields"]:
            self.assertIn(field["candidate"], unique["HbrFields"]["text"])
        facts = self.installation / "skills/dyz-software/resources/harbor-delivery-v1.3/facts.json"
        original = facts.read_bytes()
        try:
            forged = json.loads(original); forged["applicant"] = "SYNTHETIC-FORGED-NOT-REAL"
            facts.write_text(json.dumps(forged), encoding="utf-8")
            rejected = subprocess.run([sys.executable, "-E", "-s", "-S", "-m", "tools.documents",
                "--research-example", "--root", ".", "--input", current_input, "--output", "stale-readiness-file"],
                cwd=self.installation, env=self.environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual((2, "document_contract_rejected\n"), (rejected.returncode, rejected.stdout))
            self.assertFalse((self.installation / "stale-readiness-file").exists())
        finally:
            facts.write_bytes(original)
        for name, original in historical_files.items():
            self.assertEqual(original, (base / name).read_bytes())

    def test_river_v11_boundaries_actual_sequences_and_supplement_from_package(self):
        base = self.installation / "skills/dyz-standards/resources/river-demo"
        corpus = json.loads((base / "v11-boundary-vectors.json").read_text(encoding="utf-8"))
        report = json.loads(self.command(str(base / "verify-v11.py"), cwd=self.base))
        self.assertEqual({"vectors": 78, "vectors_passed": 78, "vectors_failed": 0, "check_groups": 26,
                          "scenario_count": 3, "scenarios_passed": 3, "scenarios_failed": 0,
                          "sequence_steps": 11, "skipped": 0}, report["summary"])
        self.assertTrue(all(r["receiver_version"] == "1.1" for r in report["single_inputs"]["results"]))
        self.assertTrue(all(r["caller_state_unchanged"] for r in report["single_inputs"]["results"]))
        for scenario in report["sequences"]:
            for previous, current in zip(scenario["steps"], scenario["steps"][1:]):
                self.assertEqual(previous["actual"]["state"], current["actual_input_state"])
        for row in report["sources"]:
            self.assertEqual(row["sha256"], hashlib.sha256((base / row["name"]).read_bytes()).hexdigest())
        wrong = json.loads(json.dumps(corpus))
        wrong["vectors"][0]["expected"]["reason"] = "encoding"
        wrong["sequences"][0]["steps"][0]["expected"]["state"]["GHOST"] = [{"seq": 1, "value": 0}]
        stale = json.loads(json.dumps(corpus))
        stale["source_bindings"]["model.py"] = "0" * 64
        for name, value, expected_code in (("wrong-v11", wrong, 1), ("stale-v11", stale, 2)):
            path = self.base / (name + ".json")
            path.write_text(json.dumps(value), encoding="utf-8")
            result = subprocess.run([sys.executable, "-E", "-s", "-S", str(base / "verify-v11.py"), str(path)],
                                    cwd=self.base, env=self.environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(expected_code, result.returncode, result.stderr)
            data = json.loads(result.stdout)
            if name == "wrong-v11":
                self.assertEqual((1, 1), (data["summary"]["vectors_failed"], data["summary"]["scenarios_failed"]))
                self.assertNotIn("GHOST", data["sequences"][0]["steps"][1]["actual_input_state"])
            else:
                self.assertEqual("source_binding_changed", data["error"])
        relative = "skills/dyz-standards/resources/river-v11-verification"
        bindings = json.loads((self.installation / relative / "file-bindings.json").read_text(encoding="utf-8"))
        for role, doc in (("supplement", bindings["document"]), ("prior", bindings["prior_review"])):
            label = "v11-" + role
            args = ("--research-example", "--root", ".", "--input", doc["input"], "--output", label)
            self.command("-m", "tools.documents", *args)
            self.command("-m", "tools.documents", *args, "--verify")
            path = self.installation / label / "body/document.docx"
            if CLASSIC_ZLIB:
                self.assertEqual(doc["docx_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            result_name = label + "-readback.json"
            self.command("-m", "tools.document_review", "--research-example", "--root", ".",
                         "--input", label + "/body/document.docx", "--output", result_name)
            read = json.loads((self.installation / result_name).read_text(encoding="utf-8"))
            self.assertEqual("complete_supported_subset", read["current"]["readback_state"])
            bookmarks = {r["name"]: r for r in read["current"]["bookmarks"] if r["identity_state"] == "paired_unique_name"}
            if role == "supplement":
                self.assertEqual(19, len(bookmarks))
            for target in doc["targets"]:
                self.assertEqual(target["text_sha256"], hashlib.sha256(bookmarks[target["bookmark"]]["text"].encode("utf-8")).hexdigest())

    def test_research_example_four_files_and_current_opinion_targets_from_package(self):
        relative = "skills/dyz-standards/resources/river-delivery-source"
        bindings = json.loads((self.installation / relative / "file-bindings.json").read_text(encoding="utf-8"))
        for version in bindings["documents_and_opinions"]:
            bookmarks = {}
            for role, document in version["documents"].items():
                label = "research-" + version["protocol"] + "-" + role
                args = ("--research-example", "--root", ".", "--input", document["input"], "--output", label)
                self.command("-m", "tools.documents", *args)
                self.command("-m", "tools.documents", *args, "--verify")
                path = self.installation / label / "body/document.docx"
                if CLASSIC_ZLIB:
                    self.assertEqual(document["docx_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                manifest = json.loads((self.installation / label / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual("research_example", manifest["mode"])
                self.assertEqual("not_performed", manifest["professional_review"])
                self.assertIn("original_public_research", {x["content_kind"] for x in manifest["research_scope"]["materials"]})
                report_name = label + "-readback.json"
                self.command("-m", "tools.document_review", "--research-example", "--root", ".",
                             "--input", label + "/body/document.docx", "--output", report_name)
                report = json.loads((self.installation / report_name).read_text(encoding="utf-8"))
                self.assertEqual("research_example", report["mode"])
                self.assertEqual("complete_supported_subset", report["current"]["readback_state"])
                bookmarks[role] = {x["name"] for x in report["current"]["bookmarks"]
                                   if x["identity_state"] == "paired_unique_name"}
            for opinion in version["opinions"]:
                role = opinion["target_document"]
                if CLASSIC_ZLIB:
                    self.assertEqual(version["documents"][role]["docx_sha256"], opinion["target_docx_sha256"])
                self.assertIn(opinion["target_bookmark"], bookmarks[role])

    def test_patent_research_two_versions_rebuild_and_locate_changes_from_package(self):
        """保留原两版回归，并核新增来源1.2在独立包重建且不改变原权项。"""
        relative = "skills/dyz-patent/resources/cn-gateway-delivery"
        bindings = json.loads((self.installation / relative / "file-bindings.json").read_text(encoding="utf-8"))
        current = json.loads((self.installation / relative / "file-bindings-v1.2.json").read_text(encoding="utf-8"))
        versions = list(bindings["documents_and_changes"]) + [{"version": "1.2", "documents": {
            item["role"]: {**item, "changed_bookmarks": item["changed_existing_bookmarks"]}
            for item in current["documents"]}}]
        expected_changes = {
            "draft": {"PatAbstract", "PatClaim01", "PatClaim03", "PatEdition", "PatP0004"},
            "review": {"PatModification", "PatReviewTitle", "PatRoute"},
        }
        for version in versions:
            for role, document in version["documents"].items():
                current_source_update = version["version"] == "1.2"
                label = "gateway-" + version["version"] + "-" + role
                args = ("--research-example", "--root", ".", "--input", document["input"], "--output", label)
                self.command("-m", "tools.documents", *args)
                self.command("-m", "tools.documents", *args, "--verify")
                path = self.installation / label / "body/document.docx"
                if CLASSIC_ZLIB:
                    self.assertEqual(document["docx_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                manifest = json.loads((self.installation / label / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual("research_example", manifest["mode"])
                self.assertEqual("not_performed", manifest["professional_review"])
                self.assertNotIn("fidelity", manifest)
                materials = manifest["research_scope"]["materials"]
                self.assertEqual((11 if role == "draft" else 9) if current_source_update else
                                 (9 if role == "draft" else 7), len(materials))
                self.assertNotIn("skills/dyz-patent/resources/cn-epo-fulltext-record.json",
                                 {item["path"] for item in materials})
                self.assertEqual({"original_synthetic", "original_public_research", "original_mixed_research"},
                                 {x["content_kind"] for x in materials})
                report_name = label + "-readback.json"
                review_args = ["--research-example", "--root", ".", "--input", label + "/body/document.docx",
                               "--output", report_name]
                baseline_version = {"1.1": "1.0", "1.2": "1.1"}.get(version["version"])
                if baseline_version:
                    review_args += ["--baseline", "gateway-" + baseline_version + "-" + role + "/body/document.docx"]
                self.command("-m", "tools.document_review", *review_args)
                report = json.loads((self.installation / report_name).read_text(encoding="utf-8"))
                self.assertEqual("research_example", report["mode"])
                self.assertEqual("partial" if role == "draft" else "complete_supported_subset",
                                 report["current"]["readback_state"])
                bookmarks = {x["name"]: x for x in report["current"]["bookmarks"]
                             if x["identity_state"] == "paired_unique_name"}
                self.assertEqual((49 if role == "draft" else 25) if current_source_update else
                                 (47 if role == "draft" else 20), len(bookmarks))
                for target in document["targets"]:
                    text = bookmarks[target["bookmark"]]["text"]
                    self.assertEqual(target["text_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
                if baseline_version:
                    changed = {x["name"] for x in report["comparison"]["paired_bookmarks"] if not x["text_equal"]}
                    self.assertEqual(set(document["changed_bookmarks"]) if current_source_update else
                                     expected_changes[role], changed)
                    self.assertEqual(set(document["changed_bookmarks"]), changed)
                    self.assertEqual("not_assessed", report["comparison"]["semantic_equivalence"])
                if current_source_update:
                    old = {item["name"]: item for item in report["baseline"]["bookmarks"]}
                    added = set(bookmarks) - set(old)
                    self.assertEqual(set(document["new_bookmarks"]), added)
                    preserved = (["PatClaim" + str(i).zfill(2) for i in range(1, 8)] + ["PatAbstract"]
                                 if role == "draft" else ["PatUnknown"])
                    for name in preserved:
                        self.assertEqual(old[name]["text"], bookmarks[name]["text"])
        rejected = subprocess.run([sys.executable, "-E", "-s", "-S", "-m", "tools.documents",
            "--research-example", "--root", ".", "--input", relative + "/draft-v1.1-input.json",
            "--output", "gateway-1.0-draft", "--verify"], cwd=self.installation, env=self.environment,
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(2, rejected.returncode)
        self.assertEqual("document_contract_rejected\n", rejected.stdout)
        exact_rejection = self.command("-c",
            "import json;from pathlib import Path;from tools import documents\n"
            "spec=json.loads(Path('" + relative + "/draft-v1.1-input.json').read_text(encoding='utf-8'))\n"
            "try:\n documents.verify(Path('.'),spec,'gateway-1.0-draft',research_example=True)\n"
            "except ValueError as exc:\n print(str(exc))\n")
        self.assertEqual("document_input_binding_changed\n", exact_rejection)

    def test_river_local_process_exchange_and_verification_document_from_package(self):
        relative = "skills/dyz-standards/resources/river-local-interop"
        report = json.loads(self.command(relative + "/run_interop.py"))
        self.assertEqual("passed_finite_local_process_exercise", report["status"])
        self.assertEqual((304, 22, 15, 7), tuple(report["summary"][key] for key in
                         ("peer_evaluations", "state_steps", "wire_deliveries", "started_processes")))
        self.assertTrue(report["sources_unchanged_after"])
        self.assertTrue(all(p["closed"] and p["returncode"] == 0 for p in report["processes"]))
        for source in report["sources"]:
            directory = relative if source["name"] in {"peer_a.py", "peer_b.py", "run_interop.py", "plan.json"} else "skills/dyz-standards/resources/river-demo"
            self.assertEqual(source["sha256"], hashlib.sha256((self.installation / directory / source["name"]).read_bytes()).hexdigest())
        binding = json.loads((self.installation / relative / "file-bindings.json").read_text(encoding="utf-8"))["document"]
        args = ("--research-example", "--root", ".", "--input", binding["input"], "--output", "river-local-file")
        self.command("-m", "tools.documents", *args)
        self.command("-m", "tools.documents", *args, "--verify")
        docx = self.installation / "river-local-file/body/document.docx"
        if CLASSIC_ZLIB:
            self.assertEqual(binding["docx_sha256"], hashlib.sha256(docx.read_bytes()).hexdigest())
        self.command("-m", "tools.document_review", "--research-example", "--root", ".",
                     "--input", "river-local-file/body/document.docx", "--output", "river-local-readback.json")
        word = json.loads((self.installation / "river-local-readback.json").read_text(encoding="utf-8"))
        self.assertEqual("complete_supported_subset", word["current"]["readback_state"])
        bookmarks = {b["name"]: b for b in word["current"]["bookmarks"]}
        self.assertEqual(19, len(bookmarks))
        for target in binding["targets"]:
            self.assertEqual(target["text_sha256"], hashlib.sha256(bookmarks[target["bookmark"]]["text"].encode("utf-8")).hexdigest())

    def test_foreign_cwd_isolated_import_and_list_without_source_path(self):
        code = (
            "import sys,runpy; from pathlib import Path; "
            "root=Path(sys.argv.pop(1)); sys.path.insert(0,str(root)); "
            "import tools,tools.core,tools.cli,tools.disclosure,tools.patent,tools.procedure,"
            "tools.software,tools.standards,tools.rendering; "
            "assert all(Path(m.__file__).is_relative_to(root) for n,m in sys.modules.items() "
            "if n=='tools' or n.startswith('tools.')); "
            "sys.argv=['tools','list']; runpy.run_module('tools',run_name='__main__')"
        )
        process = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(self.installation)],
                                 cwd=self.base, env=self.environment, capture_output=True, text=True)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual(83, len(json.loads(process.stdout)))

    def test_harbor_versions_run_from_installed_sources(self):
        """两版真实示例的依赖随包闭合，且版本行为不被串版导入混淆。"""
        api_probe = (
            "import sys,json,io;from pathlib import Path;"
            "root=Path(sys.argv[1]);sys.path.insert(0,str(root));import core,api;"
            "assert Path(core.__file__).parent==root and Path(api.__file__).parent==root;"
            "raw=b'[{\"id\":\"a\",\"label\":\"x\",\"value\":true}]';seen=[];"
            "env={'PATH_INFO':'/convert','REQUEST_METHOD':'POST','QUERY_STRING':'',"
            "'CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),"
            "'wsgi.input':io.BytesIO(raw)};"
            "body=b''.join(api.application(env,lambda status,headers:seen.append(status)));"
            "print(json.dumps({'status':seen[0],'body':json.loads(body)}))"
        )
        for version, expected_exit, expected_status in (
                ("v1.0", 0, "400 Bad Request"), ("v1.1", 2, "422 Unprocessable Entity")):
            with self.subTest(version=version):
                source = self.installation / "skills/dyz-software/resources/harbor-demo" / version
                work = self.base / ("harbor-" + version)
                work.mkdir()
                input_path = work / "input.json"
                input_path.write_text('[{"id":"a","label":"x","value":1},'
                                      '{"id":"a","label":"y","value":2}]', encoding="utf-8")
                output_path = work / "output.csv"
                process = subprocess.run(
                    [sys.executable, "-E", "-s", "-S", str(source / "cli.py"),
                     str(input_path), str(output_path)], cwd=work,
                    env=self.environment, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(expected_exit, process.returncode, process.stderr)
                if expected_exit == 0:
                    self.assertEqual(b"id,label,value\na,x,1\na,y,2\n", output_path.read_bytes())
                else:
                    self.assertFalse(output_path.exists())
                    self.assertEqual("duplicate_id\n", process.stderr)
                probe = subprocess.run(
                    [sys.executable, "-I", "-S", "-c", api_probe, str(source)], cwd=work,
                    env=self.environment, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(0, probe.returncode, probe.stderr)
                self.assertEqual({"status": expected_status, "body": {"error": "invalid_value"}},
                                 json.loads(probe.stdout))

    def test_shared_example_and_demo(self):
        for args in (("run", "CORE-02", "--input", "skills/dyz-workbench/resources/example.json",
                      "--output", "core02.json"), ("demo", "--output", "shared-demo.json")):
            self.assertEqual("result_written\n", self.command("-m", "tools", *args, "--synthetic"))
        example = json.loads((self.installation / "core02.json").read_text(encoding="utf-8"))
        demo = json.loads((self.installation / "shared-demo.json").read_text(encoding="utf-8"))
        self.assertEqual("undetermined", example["artifacts"]["ownership"])
        self.assertEqual("synthetic_confirmed", demo["execution"]["state"])
        self.assertEqual("not_performed", demo["external_action"])

    def test_documented_fixed_preview_example(self):
        text = (self.installation / "skills/dyz-workbench/resources/tools.md").read_text(encoding="utf-8")
        section = text.split("## 固定候选预览\n", 1)[1].split("## 持久披露演练", 1)[0]
        example = re.search(r"```python\n(.*?)\n```", section, re.S).group(1)
        output = self.command("-X", "utf8", "-c", example)
        self.assertIn("candidate/evidence blocked; no screenshot", output)

    def test_patent_and_procedure_resources(self):
        for capability, resource, output in (
            ("DRAFT-02", "skills/dyz-patent/example.json", "patent-result.json"),
            ("PROC-02", "skills/dyz-procedure/resources/example.json", "procedure-result.json")):
            self.assertEqual("result_written\n", self.command("-m", "tools", "run", capability,
                "--synthetic", "--input", resource, "--output", output))
            report = json.loads((self.installation / output).read_text(encoding="utf-8"))
            self.assertEqual(capability, report["capability"])
            self.assertEqual("not_performed", report["external_action"])
            self.assertEqual("not_asserted", report["official_status"])
            self.assertTrue(report["artifacts"])

    def test_software_full_demo(self):
        output = self.command("-X", "utf8", "-c",
            "import runpy; runpy.run_path('skills/dyz-software/demo.py',run_name='__main__')")
        report = json.loads(output)
        self.assertEqual(9, len(report))
        self.assertEqual("checked", report["SW-05"]["status"])
        self.assertEqual("invalidated", report["SW-06"]["status"])
        self.assertTrue(all(row["external_action"] == "not_performed" for row in report.values()))

    def test_standards_documented_example(self):
        text = (self.installation / "skills/dyz-standards/resources/tools.md").read_text(encoding="utf-8")
        example = re.search(r"@'\n(.*?)\n'@ \| python -", text, re.S).group(1)
        report = json.loads(self.command("-X", "utf8", "-c", example))
        self.assertEqual("STD-05", report["capability"])
        self.assertEqual("needs_review", report["status"])
        self.assertIn("维护模式除外", report["artifacts"]["draft_markdown"])
        self.assertEqual("not_performed", report["external_action"])

    def test_rendering_demo_no_server(self):
        self.command("-X", "utf8", "-c",
            "import runpy; runpy.run_path('skills/dyz-rendering/demo.py',run_name='__main__')",
            "--output", str(self.base / "rendering-demo"))
        report = json.loads((self.base / "rendering-demo/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(7, len(report["files"]))
        self.assertEqual("not_executed", report["rendering"])
        for row in report["files"]:
            raw = (self.base / "rendering-demo" / row["html"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["rendered_artifact_hash"])

    def test_skill_references_resolve_inside_isolated_package(self):
        pending = list((self.installation / "skills").glob("*/SKILL.md"))
        self.assertEqual(6, len(pending))
        visited = set()
        while pending:
            source = pending.pop().resolve()
            if source in visited:
                continue
            visited.add(source)
            prose = []
            in_fence = False
            for line in source.read_text(encoding="utf-8").splitlines():
                if line.startswith("```"):
                    in_fence = not in_fence
                elif not in_fence:
                    prose.append(line)
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", "\n".join(prose)):
                if "://" in target or target.startswith("#"):
                    continue
                path = (source.parent / target.split("#", 1)[0]).resolve()
                self.assertTrue(path.is_relative_to(self.installation.resolve()), target)
                self.assertTrue(path.is_file(), f"{source.name}: {target}")
                if path.suffix == ".md":
                    pending.append(path)
        resources = {(self.installation / name).resolve() for name in bundle.BUNDLE_FILES
                     if name.startswith("skills/") and name.endswith(".md")}
        self.assertTrue(resources.issubset(visited), resources - visited)


if __name__ == "__main__":
    unittest.main()
