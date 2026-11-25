"""可分发示范的跨文件一致性，避免源代码或版本变化后沿用旧材料。"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
import zlib

from tools import documents
from tools.core import ContractError

ROOT = Path(__file__).resolve().parents[1]
CLASSIC_ZLIB = (
    not hasattr(zlib, "ZLIBNG_VERSION")
    and "zlib-ng" not in getattr(zlib, "ZLIB_VERSION", "").lower()
    and "zlib-ng" not in getattr(zlib, "ZLIB_RUNTIME_VERSION", "").lower()
)


class DeliveryFixtureTests(unittest.TestCase):
    def test_software_source_lines_and_declared_count_match_actual_files(self):
        folder = ROOT / 'skills/dyz-software/resources/harbor-delivery-v1.2'
        source = ROOT / 'skills/dyz-software/resources/harbor-demo/v1.2'
        facts = json.loads((folder/'facts.json').read_text(encoding='utf-8'))
        mappings = json.loads((folder/'source-lines.json').read_text(encoding='utf-8'))
        exported = (folder/'source.txt').read_text(encoding='utf-8').splitlines()
        files = {r['file']:r for r in facts['source_files']}
        physical_lines = 0
        for filename, row in files.items():
            raw=(source/filename).read_bytes()
            self.assertEqual(row['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(row['physical_lines'],len(raw.decode().splitlines()))
            physical_lines += row['physical_lines']
        self.assertEqual(physical_lines,facts['physical_lines'])
        self.assertEqual(len(mappings),physical_lines)
        self.assertEqual(len({(m['source'],m['line']) for m in mappings}),physical_lines)
        for row in mappings:
            line=(source/row['source']).read_text(encoding='utf-8').splitlines()[row['line']-1]
            self.assertEqual(exported[row['export_line']-1],f"[{row['source']}:{row['line']:03}] {line}")

    def test_both_software_specs_bind_all_original_sources_and_screenshots(self):
        folder = ROOT / 'skills/dyz-software/resources/harbor-delivery-v1.2'
        facts=json.loads((folder/'facts.json').read_text(encoding='utf-8'))
        for name in ('manual','source'):
            spec=json.loads((folder/f'{name}-input.json').read_text(encoding='utf-8'))
            bound={s['sha256'] for s in spec['sources']}
            self.assertTrue({s['sha256'] for s in facts['source_files']}.issubset(bound))
            documents.resolve_document(ROOT,spec)
            self.assertEqual(spec['version'],facts['version'])
        for image in facts['screenshots']:
            self.assertEqual(image['sha256'],hashlib.sha256((folder/image['path']).read_bytes()).hexdigest())
        self.assertIsNone(facts['applicant'])

    def test_standard_comments_bind_existing_clause_bookmarks_and_actual_docx(self):
        folder = ROOT / 'skills/dyz-standards/resources/river-delivery'
        spec=json.loads((folder/'standard-input.json').read_text(encoding='utf-8'))
        binding=json.loads((folder/'comment-bindings.json').read_text(encoding='utf-8'))
        blocks,images=documents.resolve_document(ROOT,spec)
        raw_docx = documents.make_docx(blocks,images)
        checked = documents.inspect_generated_docx(raw_docx, blocks, images)
        self.assertTrue(checked['source_text_equal'])
        if CLASSIC_ZLIB:
            self.assertEqual(binding['normative_docx_sha256'],hashlib.sha256(raw_docx).hexdigest())
        ids={b['id'] for b in blocks}
        self.assertTrue(set(binding['stable_clause_bookmarks']).issubset(ids))
        for comment in binding['comments']:
            self.assertTrue(set(comment['clauses']).issubset(ids))
            self.assertEqual(comment['status'],'proposal_not_formal_decision')

    def test_standard_comment_export_rejects_changed_mapping_or_normative_spec(self):
        base = Path('skills/dyz-standards/resources')
        for changed in ('comment-bindings.json', 'standard-input.json'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory(prefix='dyz-comment-binding-') as tmp:
                root = Path(tmp)
                for relative in (base/'river-example.md', *(base/'river-delivery'/name for name in
                                  ('comment-bindings.json', 'standard-input.json', 'comments-input.json'))):
                    target = root/relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT/relative).read_bytes())
                spec = json.loads((root/base/'river-delivery/comments-input.json').read_text(encoding='utf-8'))
                documents.build(root, spec, 'original-comments', synthetic=True)
                modified = root/base/'river-delivery'/changed
                modified.write_bytes(modified.read_bytes() + b'\nchanged binding evidence')
                with self.assertRaisesRegex(ContractError, 'document_source_changed'):
                    documents.build(root, spec, 'changed-comments', synthetic=True)
                self.assertFalse((root/'changed-comments').exists())

    def test_software_materials_reject_changed_facts_or_screenshot_evidence(self):
        for document in ('manual', 'source'):
            for changed in ('facts.json', 'gui-success.png'):
                with self.subTest(document=document, changed=changed), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    base = Path('skills/dyz-software/resources')
                    for folder in ('harbor-delivery-v1.2', 'harbor-demo/v1.2'):
                        shutil.copytree(ROOT / base / folder, root / base / folder)
                    delivery = root / base / 'harbor-delivery-v1.2'
                    spec = json.loads((delivery / f'{document}-input.json').read_text(encoding='utf-8'))
                    documents.resolve_document(root, spec)
                    changed_file = delivery / changed
                    changed_file.write_bytes(changed_file.read_bytes() + b'\nchanged evidence')
                    with self.assertRaises(ContractError):
                        documents.resolve_document(root, spec)


if __name__ == '__main__':
    unittest.main()
