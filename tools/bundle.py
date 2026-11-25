"""WP-01/WP-10 本地白名单复制与只读校验；保留许可，不安装、不发布、不认证。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import core
else:
    from . import core


# 逐文件纳入，不能仅按后缀递归：新凭据、私人JSON或上游文件不应自动入包。
BUNDLE_FILES = (
    "README.md", "LICENSE", "COMMERCIAL-LICENSE.md", "THIRD-PARTY-NOTICES.md",
    "tools/__init__.py", "tools/__main__.py", "tools/core.py", "tools/cli.py",
    "tools/disclosure.py", "tools/patent.py", "tools/procedure.py", "tools/software.py",
    "tools/standards.py", "tools/rendering.py", "tools/bundle.py",
    "tools/documents.py",
    "tools/fidelity.py",
    "tools/document_review.py",
    "references/jurisdictions/patent-epo-linked-source-20261103.md",
    "skills/dyz-patent/resources/cn-epo-search.md",
    "skills/dyz-patent/resources/cn-epo-search-record.json",
    "skills/dyz-patent/resources/cn-epo-fulltext-study.md",
    "skills/dyz-patent/resources/cn-epo-fulltext-record.json",
    "skills/dyz-patent/resources/cn-priority-family-study.md",
    "skills/dyz-patent/resources/cn-priority-family-record.json",
    "skills/dyz-software/resources/harbor-review-readiness/evidence-map.json",
    "skills/dyz-software/resources/harbor-review-readiness/review-cases.json",
    "skills/dyz-software/resources/harbor-review-readiness/review-cases.py",
    "skills/dyz-software/resources/harbor-review-readiness/case-results.json",
    "skills/dyz-software/resources/harbor-review-readiness/review-pack.md",
    "skills/dyz-software/resources/harbor-review-readiness/document-input.json",
    "skills/dyz-software/resources/harbor-review-readiness/file-bindings.json",
    "skills/dyz-standards/resources/river-demo/v11-boundary-vectors.json",
    "skills/dyz-standards/resources/river-demo/verify-v11.py",
    "skills/dyz-standards/resources/river-v11-verification/verification.md",
    "skills/dyz-standards/resources/river-v11-verification/model-run.json",
    "skills/dyz-standards/resources/river-v11-verification/document-input.json",
    "skills/dyz-standards/resources/river-v11-verification/file-bindings.json",
    "skills/dyz-standards/resources/river-local-interop/peer_a.py",
    "skills/dyz-standards/resources/river-local-interop/peer_b.py",
    "skills/dyz-standards/resources/river-local-interop/run_interop.py",
    "skills/dyz-standards/resources/river-local-interop/plan.json",
    "skills/dyz-standards/resources/river-local-interop/execution.json",
    "skills/dyz-standards/resources/river-local-interop/verification.md",
    "skills/dyz-standards/resources/river-local-interop/document-input.json",
    "skills/dyz-standards/resources/river-local-interop/file-bindings.json",
    "skills/dyz-standards/resources/river-review-readiness/review-pack.md",
    "skills/dyz-standards/resources/river-review-readiness/evidence-map.json",
    "references/jurisdictions/patent-public-search-20261103.md",
    "references/jurisdictions/patent-official-evidence-20261103.md",
    "skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.0.md",
    "skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.1.md",
    "skills/dyz-patent/resources/cn-gateway-delivery/review-v1.0.md",
    "skills/dyz-patent/resources/cn-gateway-delivery/review-v1.1.md",
    "skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.0-input.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.1-input.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/review-v1.0-input.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/review-v1.1-input.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/support.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/change-impact.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/file-bindings.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.2.md",
    "skills/dyz-patent/resources/cn-gateway-delivery/review-v1.2.md",
    "skills/dyz-patent/resources/cn-gateway-delivery/draft-v1.2-input.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/review-v1.2-input.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/source-update-v1.2.json",
    "skills/dyz-patent/resources/cn-gateway-delivery/file-bindings-v1.2.json",
    "skills/dyz-patent/resources/cn-gateway-search.md",
    "skills/dyz-patent/resources/cn-gateway-search-record.json",
    "skills/dyz-software/resources/harbor-demo/v1.3/api.py",
    "skills/dyz-software/resources/harbor-demo/v1.3/cli.py",
    "skills/dyz-software/resources/harbor-demo/v1.3/core.py",
    "skills/dyz-software/resources/harbor-demo/v1.3/gui.py",
    "skills/dyz-software/resources/harbor-demo/v1.3/index.html",
    "skills/dyz-software/resources/harbor-delivery-v1.3/change-impact.json",
    "skills/dyz-software/resources/harbor-delivery-v1.3/facts.json",
    "skills/dyz-software/resources/harbor-delivery-v1.3/form-candidate.md",
    "skills/dyz-software/resources/harbor-delivery-v1.3/form-input.json",
    "skills/dyz-software/resources/harbor-delivery-v1.3/gui-default.png",
    "skills/dyz-software/resources/harbor-delivery-v1.3/gui-sorted.png",
    "skills/dyz-software/resources/harbor-delivery-v1.3/gui-duplicate-id.png",
    "skills/dyz-software/resources/harbor-delivery-v1.3/manual-input.json",
    "skills/dyz-software/resources/harbor-delivery-v1.3/manual.md",
    "skills/dyz-software/resources/harbor-delivery-v1.3/scope-and-rights.md",
    "skills/dyz-software/resources/harbor-delivery-v1.3/source-input.json",
    "skills/dyz-software/resources/harbor-delivery-v1.3/source-lines.json",
    "skills/dyz-software/resources/harbor-delivery-v1.3/source.txt",
    "skills/dyz-software/resources/harbor-demo/v1.2/api.py",
    "skills/dyz-software/resources/harbor-demo/v1.2/cli.py",
    "skills/dyz-software/resources/harbor-demo/v1.2/core.py",
    "skills/dyz-software/resources/harbor-demo/v1.2/gui.py",
    "skills/dyz-software/resources/harbor-demo/v1.2/index.html",
    "skills/dyz-software/resources/harbor-delivery-v1.2/facts.json",
    "skills/dyz-software/resources/harbor-delivery-v1.2/gui-duplicate-id.png",
    "skills/dyz-software/resources/harbor-delivery-v1.2/gui-success.png",
    "skills/dyz-software/resources/harbor-delivery-v1.2/manual-input.json",
    "skills/dyz-software/resources/harbor-delivery-v1.2/form-candidate.md",
    "skills/dyz-software/resources/harbor-delivery-v1.2/form-input.json",
    "skills/dyz-software/resources/harbor-delivery-v1.2/manual.md",
    "skills/dyz-software/resources/harbor-delivery-v1.2/source-input.json",
    "skills/dyz-software/resources/harbor-delivery-v1.2/source-lines.json",
    "skills/dyz-software/resources/harbor-delivery-v1.2/source.txt",
    "skills/dyz-standards/resources/river-delivery/comment-bindings.json",
    "skills/dyz-standards/resources/river-delivery/comments-input.json",
    "skills/dyz-standards/resources/river-delivery/explanation-input.json",
    "skills/dyz-standards/resources/river-delivery/standard-input.json",
    "skills/dyz-standards/resources/river-delivery/verification-input.json", "skills/dyz-rendering/resources/document-example.json",
    "skills/dyz-patent/resources/cn-gateway-flow.png",
    "docs/github-skill-comparison-20261102.md", "docs/github-skill-comparison-20261102-sources.json",
    "skills/dyz-workbench/SKILL.md", "skills/dyz-workbench/resources/example.json",
    "skills/dyz-patent/SKILL.md", "skills/dyz-patent/example.json",
    "skills/dyz-procedure/SKILL.md", "skills/dyz-procedure/resources/example.json",
    "skills/dyz-procedure/resources/oa-delivery-example.json",
    "skills/dyz-procedure/resources/input-contracts.md",
    "skills/dyz-software/SKILL.md", "skills/dyz-software/demo.py",
    "skills/dyz-standards/SKILL.md",
    "skills/dyz-rendering/SKILL.md", "skills/dyz-rendering/demo.py",
    "skills/dyz-rendering/dom-check.js",
    "skills/dyz-workbench/resources/tools.md",
    "skills/dyz-workbench/resources/package-use.md",
    "skills/dyz-patent/resources/examples.md", "skills/dyz-patent/resources/topics.md",
    "skills/dyz-patent/resources/tools.md",
    "skills/dyz-patent/resources/cn-core-method.md",
    "skills/dyz-patent/resources/fact-and-support-review.md",
    "skills/dyz-patent/resources/fidelity-example.json",
    "skills/dyz-patent/resources/fidelity-recorder-draft.md",
    "skills/dyz-patent/resources/fidelity-recorder-notes.md",
    "skills/dyz-rendering/resources/fidelity-document-example.json",
    "skills/dyz-patent/resources/cn-gateway-example.md",
    "skills/dyz-patent/resources/cn-gateway-flow.svg",
    "skills/dyz-procedure/resources/topics.md", "skills/dyz-procedure/resources/tools.md",
    "skills/dyz-procedure/resources/complex-cn-method.md",
    "skills/dyz-procedure/resources/complex-cn-example.md",
    "skills/dyz-procedure/resources/cn-oa-method.md",
    "skills/dyz-procedure/resources/cn-oa-example.md",
    "skills/dyz-software/resources/examples.md", "skills/dyz-software/resources/follow-up.md",
    "skills/dyz-software/resources/tools.md",
    "skills/dyz-software/resources/cn-core-method.md",
    "skills/dyz-software/resources/harbor-example.md",
    "skills/dyz-software/resources/complex-cn-method.md",
    "skills/dyz-software/resources/complex-cn-example.md",
    "skills/dyz-software/resources/us-registration-method.md",
    "skills/dyz-software/resources/us-registration-example.md",
    "skills/dyz-software/resources/harbor-demo/v1.0/core.py",
    "skills/dyz-software/resources/harbor-demo/v1.0/cli.py",
    "skills/dyz-software/resources/harbor-demo/v1.0/api.py",
    "skills/dyz-software/resources/harbor-demo/v1.1/core.py",
    "skills/dyz-software/resources/harbor-demo/v1.1/cli.py",
    "skills/dyz-software/resources/harbor-demo/v1.1/api.py",
    "skills/dyz-standards/resources/examples.md", "skills/dyz-standards/resources/follow-up.md",
    "skills/dyz-standards/resources/tools.md",
    "skills/dyz-standards/resources/cn-core-method.md",
    "skills/dyz-standards/resources/river-example.md",
    "skills/dyz-standards/resources/governance-method.md",
    "skills/dyz-standards/resources/governance-example.md",
    "skills/dyz-standards/resources/patent-policy-method.md",
    "skills/dyz-standards/resources/patent-policy-example.md",
    "skills/dyz-standards/resources/river-demo/requirements.json",
    "skills/dyz-standards/resources/river-demo/vectors.json",
    "skills/dyz-standards/resources/river-demo/model.py",
    "skills/dyz-rendering/resources/examples.md", "skills/dyz-rendering/resources/review-checklists.md",
    "skills/dyz-rendering/resources/docx-readback.md",
    "skills/dyz-rendering/resources/tools.md",
    "references/jurisdictions/patent-rules.json",
    "references/jurisdictions/cn-core-evidence-20261101.md",
    "references/jurisdictions/cn-disputes-evidence-20261101.md",
    "references/jurisdictions/cn-oa-evidence-20261101.md",
    "references/jurisdictions/software-rules.json",
    "references/jurisdictions/cn-software-evidence-20261101.md",
    "references/jurisdictions/cn-software-guide-20261103.md",
    "references/jurisdictions/cn-software-followup-evidence-20261101.md",
    "references/jurisdictions/us-software-evidence-20261101.md",
    "references/standards/organization-rules.json",
    "references/standards/river-source-evidence-20261103.md",
    "skills/dyz-standards/resources/river-source-profile.md",
    "skills/dyz-standards/resources/river-demo/source-boundary-vectors.json",
    "skills/dyz-rendering/resources/research-documents.md",
    "skills/dyz-standards/resources/river-delivery-source/draft-v1.0.md",
    "skills/dyz-standards/resources/river-delivery-source/draft-v1.1.md",
    "skills/dyz-standards/resources/river-delivery-source/review-v1.0.md",
    "skills/dyz-standards/resources/river-delivery-source/review-v1.1.md",
    "skills/dyz-standards/resources/river-delivery-source/draft-v1.0-input.json",
    "skills/dyz-standards/resources/river-delivery-source/draft-v1.1-input.json",
    "skills/dyz-standards/resources/river-delivery-source/review-v1.0-input.json",
    "skills/dyz-standards/resources/river-delivery-source/review-v1.1-input.json",
    "skills/dyz-standards/resources/river-delivery-source/model-run.json",
    "skills/dyz-standards/resources/river-delivery-source/change-impact.json",
    "skills/dyz-standards/resources/river-delivery-source/file-bindings.json",
    "references/standards/cn-organization-evidence-20261101.md",
    "references/standards/cn-governance-evidence-20261101.md",
    "references/standards/common-patent-policy-evidence-20261101.md",
    "skills/dyz-patent/resources/utility-structure-method.md",
    "skills/dyz-patent/resources/utility-structure-example.md",
    "skills/dyz-patent/resources/utility-structure-views.svg",
    "skills/dyz-patent/resources/design-views-method.md",
    "skills/dyz-patent/resources/design-views-example.md",
    "skills/dyz-patent/resources/design-views.svg",
    "skills/dyz-procedure/resources/protection-strategy-method.md",
    "skills/dyz-procedure/resources/protection-strategy-example.md",
    "references/jurisdictions/cn-utility-evidence-20261101.md",
    "references/jurisdictions/cn-design-evidence-20261101.md",
    "references/jurisdictions/cn-strategy-evidence-20261101.md",
    "skills/dyz-patent/resources/ep-control-method.md",
    "skills/dyz-patent/resources/ep-control-example.md",
    "references/jurisdictions/ep-control-evidence-20261101.md",
    "skills/dyz-procedure/resources/pct-priority-method.md",
    "skills/dyz-procedure/resources/pct-priority-example.md",
    "references/jurisdictions/pct-priority-evidence-20261101.md",
    "skills/dyz-standards/resources/international-adoption-method.md",
    "skills/dyz-standards/resources/international-adoption-example.md",
    "references/standards/international-adoption-evidence-20261101.md",
    "skills/dyz-patent/resources/us-control-method.md",
    "skills/dyz-patent/resources/us-control-example.md",
    "references/jurisdictions/us-control-evidence-20261101.md",
    "skills/dyz-patent/resources/sequence-support-method.md",
    "skills/dyz-patent/resources/sequence-support-example.md",
    "skills/dyz-patent/resources/sequence-support-views.svg",
    "references/jurisdictions/sequence-support-evidence-20261101.md",
    "skills/dyz-software/resources/us-expression-method.md",
    "skills/dyz-software/resources/us-expression-example.md",
    "references/jurisdictions/us-expression-evidence-20261101.md",
    "skills/dyz-procedure/resources/us-fto-method.md",
    "skills/dyz-procedure/resources/us-fto-example.md",
    "references/jurisdictions/us-fto-evidence-20261101.md",
    "skills/dyz-patent/resources/circuit-evidence-method.md",
    "skills/dyz-patent/resources/circuit-evidence-example.md",
    "references/domains/circuit-evidence-20261101.md",
    "skills/dyz-patent/resources/circuit-evidence-views.svg",
    "skills/dyz-standards/resources/measurement-decision-method.md",
    "skills/dyz-standards/resources/measurement-decision-example.md",
    "references/standards/measurement-decision-evidence-20261101.md",
    "docs/capability-blueprint.md", "docs/capability-contracts.md",
    "docs/development-standards.md", "docs/disclosure-and-handoff.md",
    "docs/reference-analysis.md", "docs/roadmap-and-quality.md",
)


# 保留已安装r21的原固定路径集合；只有包外精确hash才能选择此旧布局。
R21_BUNDLE_FILES = BUNDLE_FILES
R21_MANIFEST_SHA256 = "5074f7446cf2b246269e80d22a3b7589d25e69850f30c263753cfb184af17708"
BUNDLE_FILES = (*BUNDLE_FILES, "tools/codex_host.py")
R22_METADATA_BUNDLE_FILES = BUNDLE_FILES
R22_METADATA_MANIFEST_SHA256 = "3cbaa33bec1c9a554bef04567dbde12ee9f70e15b8d176e13ae938d729699dba"
BUNDLE_FILES = (*BUNDLE_FILES, "tools/host_bridge.py", "tools/host_bridge_worker.py",
                "skills/dyz-workbench/resources/host-bridge.md")
R28_BUNDLE_FILES = BUNDLE_FILES
R28_MANIFEST_SHA256S = frozenset({
    "3c76020975ea4caf9c3b21fa7434ebaa376af61f60f98a69a69d3ee83736e8d0",
    "6a56802ee34f07af1a021d00ba09ef590b372f5b9f0f093b96c01417caa8f960"})
BUNDLE_FILES = (*BUNDLE_FILES, "skills/dyz-workbench/resources/reading-scope.md",
                "skills/dyz-rendering/resources/reading-scope-example.json",
                "skills/dyz-rendering/resources/reading-scope-records.md",
                "skills/dyz-rendering/resources/reading-scope-statements.md",
                "skills/dyz-standards/resources/lifecycle/stage-gates.md",
                "skills/dyz-standards/resources/lifecycle/comment-disposition.md",
                "skills/dyz-standards/resources/lifecycle/compilation-note.md",
                "skills/dyz-standards/resources/lifecycle/submission-package.md",
                "skills/dyz-standards/resources/lifecycle/compilation-note.schema.json",
                "skills/dyz-standards/resources/lifecycle/comment-disposition.schema.json")

# 新软件模块只进入当前布局，历史集合须保持原文件数及包外hash语义。
BUNDLE_FILES = (*BUNDLE_FILES,
                "tools/software_revision.py", "tools/software_import.py",
                "tools/software_discovery.py", "tools/software_batch.py",
                "tools/software_delivery.py", "tools/software_layout.py", "tools/software_intake.py",
                "tools/standards_delivery.py", "tools/standards_contract.py",
                "tools/standard_sources.py", "tools/document_edit.py", "tools/standard_pdf.py",
                "skills/dyz-standards/resources/lifecycle/compilation-note.v2.schema.json",
                "skills/dyz-standards/resources/lifecycle/comment-disposition.v2.schema.json")

# 新专利产物仅扩展当前候选，不改变由外部hash选择的历史布局。
BUNDLE_FILES = (*BUNDLE_FILES, "tools/patent_delivery.py", "tools/patent_gate.py",
                "skills/dyz-patent/resources/delivery.md")

# 标准正确性与成件资源均有实际运行消费者，只扩展当前白名单。
BUNDLE_FILES = (*BUNDLE_FILES, "tools/standard_intake.py", "tools/standard_review.py",
                "skills/dyz-standards/resources/lifecycle/review-rules.v1.json",
                "skills/dyz-standards/resources/lifecycle/rendering-profile.v2.json",
                "skills/dyz-standards/resources/lifecycle/table-template-profiles.v1.json")

# 首个公开试用版的许可、贡献和版本说明只加入当前包，历史布局保持原值。
BUNDLE_FILES = (*BUNDLE_FILES, "release.json", "RELEASE.md", "CHANGELOG.md",
                "CONTRIBUTING.md", "CONTRIBUTOR-LICENSE.md", "SECURITY.md")

# 阶段 A—F 新增跨平台 MCP、安装器、专利 IR/OMML/三轴接入、媒体清洗、外部模板映射、
# 可选外联数据连接器、美欧法域及程序策略分析、视觉覆盖台账与专业试审包；不改历史布局。
BUNDLE_FILES = (
    *BUNDLE_FILES,
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
)

MANIFEST_NAME = "bundle-manifest.json"
MAX_MANIFEST_BYTES = 1_000_000


BundleError = core.BundleError
_is_macos_system_root_symlink = core.is_macos_system_root_symlink
_checked_path = core.checked_path


def _absolute(path: str | Path) -> Path:
    if "\x00" in str(path):
        raise BundleError("bundle_path_invalid")
    path = Path(path)
    if (".." in path.parts or (path.drive and not path.is_absolute())
            or any(":" in part for part in path.parts if part != path.anchor)):
        raise BundleError("bundle_path_invalid")
    return path.absolute()


def _copy_new(source: Path, target: Path) -> None:
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer)


def build_bundle(destination: str | Path, *, source_root: str | Path | None = None) -> tuple[str, ...]:
    """复制完整白名单到不存在的目标，返回相对清单；失败仅清理本次创建内容。

    源、目标父目录须由调用者保护不被并发替换。本函数不提供恶意并发进程隔离，
    不识别白名单源码中人为植入的秘密，也不表示正式发布或专业审核通过。
    source_root供隔离测试/显式同布局源使用；CLI固定使用自身包根。
    """
    root = _absolute(source_root if source_root is not None else Path(__file__).parent.parent)
    destination = _absolute(destination)
    root_info = _checked_path(root)
    if root_info is None or not stat.S_ISDIR(root_info.st_mode):
        raise BundleError("bundle_source_not_directory")
    if _checked_path(destination, missing_leaf=True) is not None:
        raise BundleError("bundle_destination_exists")
    for relative in BUNDLE_FILES:
        info = _checked_path(root / relative)
        if info is None or not stat.S_ISREG(info.st_mode):
            raise BundleError("bundle_source_not_file")

    # 所有源字节先进入本次私有暂存，再独占创建目标；不使用可覆盖空目录的rename。
    with tempfile.TemporaryDirectory(prefix=".dyz-bundle-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        for relative in BUNDLE_FILES:
            _checked_path(root / relative)
            staged = staging / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            _copy_new(root / relative, staged)
        manifest = {"kind": "local_tool_bundle", "authentication": "not_provided",
                    "publication": "not_performed", "files": []}
        for relative in BUNDLE_FILES:
            raw = (staging / relative).read_bytes()
            manifest["files"].append({"path": relative, "bytes": len(raw),
                                      "sha256": hashlib.sha256(raw).hexdigest()})
        with (staging / MANIFEST_NAME).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if _checked_path(destination, missing_leaf=True) is not None:
            raise BundleError("bundle_destination_exists")
        destination.mkdir(exist_ok=False)
        created_files: list[Path] = []
        created_dirs = [destination]
        try:
            for relative in (*BUNDLE_FILES, MANIFEST_NAME):
                target = destination / relative
                for parent in reversed(target.parent.parents):
                    if parent == destination or destination in parent.parents:
                        if parent not in created_dirs:
                            parent.mkdir(exist_ok=False)
                            created_dirs.append(parent)
                if target.parent not in created_dirs:
                    target.parent.mkdir(exist_ok=False)
                    created_dirs.append(target.parent)
                _checked_path(target.parent)
                with target.open("xb") as writer:
                    created_files.append(target)
                    with (staging / relative).open("rb") as reader:
                        shutil.copyfileobj(reader, writer)
        except BaseException:
            # 不rmtree目标：目标被其他进程写入时，不删除不属于本次复制的文件。
            for path in reversed(created_files):
                path.unlink(missing_ok=True)
            for path in reversed(created_dirs):
                try:
                    path.rmdir()
                except OSError:
                    pass
            raise
    return (*BUNDLE_FILES, MANIFEST_NAME)


def _manifest_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleError("bundle_manifest_invalid")
        result[key] = value
    return result


def verify_bundle(package: str | Path, *, expected_manifest_sha256: str | None = None) -> dict:
    """只读核固定清单；旧布局仅支持包外精确绑定的r21／r22，不导入源码。

    可另给从可信构建处保留的manifest哈希；无外部绑定时只证明内部一致。
    调用者须保护目录不被并发替换；校验不认证提供者、专业状态或宿主。
    """
    if expected_manifest_sha256 is not None and (
        not isinstance(expected_manifest_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None
    ):
        raise BundleError("bundle_manifest_hash_invalid")
    root = _absolute(package)
    info = _checked_path(root)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise BundleError("bundle_source_not_directory")
    manifest_path = root / MANIFEST_NAME
    info = _checked_path(manifest_path)
    if info is None or not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:
        raise BundleError("bundle_manifest_invalid")
    with manifest_path.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise BundleError("bundle_manifest_invalid")
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise BundleError("bundle_manifest_binding_changed")
    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_manifest_object)
    except (ValueError, UnicodeError, RecursionError):
        raise BundleError("bundle_manifest_invalid") from None
    if (not isinstance(manifest, dict)
            or set(manifest) != {"kind", "authentication", "publication", "files"}
            or manifest["kind"] != "local_tool_bundle"
            or manifest["authentication"] != "not_provided"
            or manifest["publication"] != "not_performed"):
        raise BundleError("bundle_manifest_invalid")
    rows = manifest["files"]
    pinned_r21 = expected_manifest_sha256 == manifest_sha256 == R21_MANIFEST_SHA256
    pinned_r22 = expected_manifest_sha256 == manifest_sha256 == R22_METADATA_MANIFEST_SHA256
    pinned_r28 = expected_manifest_sha256 == manifest_sha256 and manifest_sha256 in R28_MANIFEST_SHA256S
    allowed_files = (R21_BUNDLE_FILES if pinned_r21 else
                     R22_METADATA_BUNDLE_FILES if pinned_r22 else R28_BUNDLE_FILES if pinned_r28 else BUNDLE_FILES)
    # 全部路径、类型与数量先通过，才读取任何源文件；不接受manifest扩充读取范围。
    if (not isinstance(rows, list) or len(rows) != len(allowed_files)
            or any(not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"} for row in rows)
            or [row["path"] for row in rows] != list(allowed_files)):
        raise BundleError("bundle_inventory_changed")
    for row in rows:
        if (type(row["bytes"]) is not int or row["bytes"] < 0
                or not isinstance(row["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None):
            raise BundleError("bundle_manifest_invalid")
    total = 0
    for row in rows:
        path = root / row["path"]
        info = _checked_path(path)
        if info is None or not stat.S_ISREG(info.st_mode):
            raise BundleError("bundle_source_not_file")
        if info.st_size != row["bytes"]:
            raise BundleError("bundle_source_changed")
        digest, count = hashlib.sha256(), 0
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(min(1_048_576, row["bytes"] - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > row["bytes"]:
                    raise BundleError("bundle_source_changed")
                digest.update(chunk)
        if count != row["bytes"] or digest.hexdigest() != row["sha256"]:
            raise BundleError("bundle_source_changed")
        total += count
    return {"kind": "local_bundle_verification", "status": "matched",
            "source_files": len(rows), "listed_bytes": total, "manifest_sha256": manifest_sha256,
            "inventory_layout": ("r21_externally_pinned" if pinned_r21 else
                                 "r22_metadata_externally_pinned" if pinned_r22 else
                                 "r25_r28_externally_pinned" if pinned_r28 else "current"),
            "binding": "expected_manifest_hash_matched" if expected_manifest_sha256 is not None else "manifest_internal_consistency_only",
            "unlisted_paths": "not_enumerated_or_read", "source_execution": "not_performed",
            "authentication": "not_provided", "professional_review": "not_performed",
            "host_installation_or_discovery": "not_performed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="复制或只读校验含许可的本地工具包；不安装、不发布")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--destination")
    action.add_argument("--verify", metavar="PACKAGE")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args(argv)
    if args.manifest_sha256 is not None and args.verify is None:
        parser.error("--manifest-sha256 requires --verify")
    try:
        if args.verify is not None:
            report = verify_bundle(args.verify, expected_manifest_sha256=args.manifest_sha256)
        else:
            build_bundle(args.destination)
    except BundleError:
        print("bundle_rejected", file=sys.stderr)
        return 2
    except OSError:
        print("bundle_io_failed", file=sys.stderr)
        return 3
    if args.verify is not None:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print("bundle_created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
