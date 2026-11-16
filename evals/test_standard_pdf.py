"""本地安全替身核验PDF边界；默认测试不启动Office或处理真实材料。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import copy
import io
import json
import os
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET
import zipfile
import zlib

from evals.test_standards_delivery import task
from tools import standard_pdf as pdf
from tools import documents, standards_delivery
from tools.core import ContractError, canonical_bytes, sha256_bytes


def _png():
    def chunk(kind, content):
        return (struct.pack('>I', len(content)) + kind + content
                + struct.pack('>I', zlib.crc32(kind + content) & 0xFFFFFFFF))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff'))
            + chunk(b'IEND', b''))


def _field_docx(*, simple=False, caches=None):
    raw = documents.make_docx([
        {'id': 'TARGET', 'kind': 'heading1', 'text': 'Synthetic target heading'},
        {'id': 'BODY', 'kind': 'paragraph', 'text': 'Nonfield prose must be preserved.'},
    ], [], profile='dyz-standard-internal-v1')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(parts['word/document.xml'])
    body = document.find(pdf._W + 'body')
    instructions = [('TOC \\o "1-2" \\h \\z \\u', 'STALE_TOC'),
                    ('REF TARGET \\h', 'STALE_REF'),
                    ('PAGEREF TARGET \\h', '999'),
                    ('SEQ Figure \\* ARABIC', '999')]
    if caches is not None:
        instructions = [(instruction, cache) for (instruction, _), cache in zip(instructions, caches)]
    def cache_run(parent, value):
        run = ET.SubElement(parent, pdf._W + 'r')
        for index, text in enumerate(value.split('\t')):
            if index:
                ET.SubElement(run, pdf._W + 'tab')
            ET.SubElement(run, pdf._W + 't').text = text

    for index, (instruction, cache) in enumerate(instructions, 10):
        paragraph = ET.Element(pdf._W + 'p')
        ET.SubElement(paragraph, pdf._W + 'bookmarkStart',
                      {pdf._W + 'id': str(index), pdf._W + 'name': 'FIELD_' + str(index)})
        if simple:
            field = ET.SubElement(paragraph, pdf._W + 'fldSimple',
                                  {pdf._W + 'instr': instruction})
            cache_run(field, cache)
        else:
            for kind, value in [('begin', ''), ('instruction', instruction),
                                ('separate', ''), ('cache', cache), ('end', '')]:
                if kind == 'cache':
                    cache_run(paragraph, value)
                    continue
                run = ET.SubElement(paragraph, pdf._W + 'r')
                if kind in {'begin', 'separate', 'end'}:
                    ET.SubElement(run, pdf._W + 'fldChar', {pdf._W + 'fldCharType': kind})
                else:
                    ET.SubElement(run, pdf._W + ('instrText' if kind == 'instruction' else 't')).text = value
        ET.SubElement(paragraph, pdf._W + 'bookmarkEnd', {pdf._W + 'id': str(index)})
        body.insert(index - 10, paragraph)
    parts['word/document.xml'] = ET.tostring(document, encoding='utf-8', xml_declaration=True)
    return documents._zip_docx(parts)


class StandardPdfFieldTests(unittest.TestCase):
    def evidence(self):
        source = pdf._document_state(_field_docx())
        values = ['Synthetic target heading\t2', 'Synthetic target heading', '2', '1']
        saved = pdf._document_state(_field_docx(caches=values))
        destinations = {'TARGET': 2, **{'FIELD_' + str(i): 1 for i in range(10, 14)}}
        texts = ['\n'.join(values), 'Synthetic target heading\nNonfield prose must be preserved.']
        return source, saved, texts, destinations

    def test_simple_and_complex_fields_parse_cache_and_nonfield_text(self):
        states = [pdf._document_state(_field_docx(simple=value)) for value in (False, True)]
        self.assertEqual(states[0], states[1])
        state = states[0]
        self.assertEqual([row['kind'] for row in state['fields']], ['TOC', 'REF', 'PAGEREF', 'SEQ'])
        self.assertEqual([row['target'] for row in state['fields']], [None, 'TARGET', 'TARGET', 'Figure'])
        self.assertNotIn('STALE', ''.join(state['nonfield_fragments']))
        self.assertEqual(len(state['nonfield_fragments']), 2)
        self.assertEqual(state['fields'][0]['anchors'], ['FIELD_10'])

    def test_verified_requires_saved_cache_target_and_pdf_page(self):
        report = pdf._field_evidence(*self.evidence())
        self.assertEqual(report['status'], 'verified')
        self.assertTrue(all(row['cache_changed'] for row in report['fields']))
        self.assertEqual(report['fields'][2]['target_page'], 2)
        self.assertTrue(report['fields'][0]['toc_entries'][0]['saved_cache_matches'])

    def test_zero_exit_unchanged_cache_is_needs_review(self):
        source, _, texts, destinations = self.evidence()
        report = pdf._field_evidence(source, source, texts, destinations)
        self.assertEqual(report['status'], 'needs_review')
        self.assertTrue(all('field_refresh_not_observed' in row['issues'] for row in report['fields']))

    def test_correct_but_unchanged_cache_is_not_refresh_proof(self):
        _, saved, texts, destinations = self.evidence()
        report = pdf._field_evidence(saved, saved, texts, destinations)
        self.assertEqual(report['status'], 'needs_review')
        self.assertTrue(all(row['issues'] == ['field_refresh_not_observed'] for row in report['fields']))

    def test_wrong_target_cache_and_wrong_page_are_not_verified(self):
        for field, value, error in [(1, 'wrong', 'saved_ref_cache_mismatch'),
                                    (2, '1', 'saved_pageref_cache_mismatch'),
                                    (3, '4', 'saved_sequence_cache_mismatch'),
                                    (0, 'Synthetic target heading 1', 'saved_toc_cache_mismatch')]:
            with self.subTest(field=field):
                source, saved, texts, destinations = self.evidence()
                saved['fields'][field]['cached_result'] = value
                report = pdf._field_evidence(source, saved, texts, destinations)
                self.assertIn(error, report['fields'][field]['issues'])
                self.assertEqual(report['status'], 'needs_review')

    def test_missing_pdf_destination_or_cache_remains_needs_review(self):
        source, saved, texts, destinations = self.evidence()
        destinations.pop('TARGET')
        destinations.pop('FIELD_10')
        texts[0] = 'unrelated page'
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertIn('saved_cache_pdf_mismatch', report['fields'][0]['issues'])
        self.assertIn('target_pdf_page_unverified', report['fields'][1]['issues'])
        self.assertIn('saved_cache_pdf_mismatch', report['fields'][2]['issues'])

    def test_field_results_cannot_pay_for_missing_nonfield_body(self):
        source, saved, texts, destinations = self.evidence()
        texts[1] = 'Nonfield prose must be preserved.'
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertEqual(report['status'], 'needs_review')

    def test_added_nested_field_cannot_silently_pass(self):
        source, saved, texts, destinations = self.evidence()
        nested = copy.deepcopy(saved['fields'][2])
        nested.update(id=5, parent_id=1)
        saved['fields'].append(nested)
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertEqual(report['status'], 'needs_review')

    def test_toc_page_number_requires_exact_integer(self):
        source, saved, texts, destinations = self.evidence()
        saved['fields'][0]['cached_result'] = 'Synthetic target heading\t20'
        texts[0] = texts[0].replace('heading\t2', 'heading\t20')
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertEqual(report['status'], 'needs_review')
        self.assertIn('saved_toc_cache_mismatch', report['fields'][0]['issues'])

    def test_other_text_on_page_cannot_prove_this_field_cache(self):
        source, saved, texts, destinations = self.evidence()
        texts[0] = texts[0].replace('\nSynthetic target heading\n', '\nSTALE_REF\n')
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertEqual(report['status'], 'needs_review')
        self.assertIn('saved_cache_pdf_mismatch', report['fields'][1]['issues'])

    def test_only_real_toc_tabs_allow_pdf_dot_leaders(self):
        source, saved, texts, destinations = self.evidence()
        texts[0] = texts[0].replace('heading\t2', 'heading........2')
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['pdf_toc_tab_leaders'][0]['dots'], 8)
        texts[1] = texts[1].replace('preserved.', 'preserved')
        self.assertEqual(pdf._field_evidence(source, saved, texts, destinations)['status'], 'needs_review')

    def test_declared_cross_page_table_header_is_not_extra_body(self):
        raw = documents.make_docx([
            {'id': 'H', 'kind': 'heading1', 'text': 'Heading'},
            {'id': 'T', 'kind': 'table', 'cells': [['HeaderA', 'HeaderB'], ['Row1A', 'Row1B'], ['Row2A', 'Row2B']]},
        ], [], profile='dyz-standard-internal-v1')
        state = pdf._document_state(raw)
        pages = ['Heading HeaderA HeaderB Row1A Row1B', 'HeaderA HeaderB Row2A Row2B']
        report = pdf._ordered_pdf_evidence(state, pages)
        self.assertTrue(report['matched'])
        self.assertEqual(len(report['repeated_table_headers']), 1)
        pages[0] = 'Heading HeaderA HeaderB'
        self.assertFalse(pdf._ordered_pdf_evidence(state, pages)['matched'])

    def test_office_destination_encoding_and_collisions(self):
        source, saved, _, destinations = self.evidence()
        encoded = {name.replace('_', '5F'): page for name, page in destinations.items()}
        self.assertEqual(pdf._bookmark_destinations(source, saved, encoded), destinations)
        source['bookmarks']['FIELD5F10'] = {'part': 'word/document.xml', 'text': 'collision'}
        resolved = pdf._bookmark_destinations(source, saved, encoded)
        self.assertNotIn('FIELD_10', resolved)
        self.assertNotIn('FIELD5F10', resolved)

    def test_instruction_change_cannot_be_masked_by_correct_cache(self):
        source, saved, texts, destinations = self.evidence()
        saved['fields'][3]['instruction'] = 'SEQ Figure \\r 1'
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertIn('field_instruction_changed', report['fields'][3]['issues'])
        self.assertEqual(report['status'], 'needs_review')

    def test_lost_field_cannot_be_marked_not_applicable(self):
        source, saved, texts, destinations = self.evidence()
        saved['fields'] = []
        report = pdf._field_evidence(source, saved, texts, destinations)
        self.assertEqual(report['status'], 'needs_review')
        self.assertIn('field_count_changed', report['issues'])
        self.assertTrue(all(row['status'] == 'needs_review' for row in report['fields']))

    def test_v2_page_footer_and_header_require_every_physical_page(self):
        raw = documents.make_docx([
            {'id': 'ONE', 'kind': 'paragraph', 'text': '第一页正文。'},
            {'id': 'TWO', 'kind': 'paragraph', 'text': '第二页正文。'},
        ], [], profile='dyz-standard-internal-v2')
        source = pdf._document_state(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        footer = ET.fromstring(parts['word/footer1.xml'])
        next(footer.iter(pdf._W + 't')).text = '1'
        parts['word/footer1.xml'] = ET.tostring(footer, encoding='utf-8')
        saved = pdf._document_state(documents._zip_docx(parts))
        texts = ['原创内部工作稿\n第一页正文。\n1\n\f',
                 '原创内部工作稿\n第二页正文。\n2\n\f']
        result = pdf._field_evidence(source, saved, texts, {})
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['fields'][0]['kind'], 'PAGE')
        self.assertEqual(result['fields'][0]['pdf_page_values'], ['1', '2'])
        self.assertEqual(source['nonfield_fragments'], ['第一页正文。', '第二页正文。'])
        pdf._text_coverage(source['nonfield_fragments'], '\n'.join(texts), 'body_incomplete')
        for changed in ([texts[0], texts[1].replace('\n2\n', '\n1\n')],
                        [texts[0], texts[1].replace('原创内部工作稿\n', '')]):
            self.assertEqual(pdf._field_evidence(source, saved, changed, {})['status'], 'needs_review')

    def test_technical_differences_cannot_hide_in_field_ordered_alignment(self):
        for original, changed in [('A B', 'AB'), ('Ａ', 'A'), ('x = 1', 'x=1'),
                                  ('<x a="B C"/>', '<x a="BC"/>'), ('附录A', '附录 A')]:
            raw = documents.make_docx([{'id': 'CODE', 'kind': 'code', 'text': original}], [])
            state = pdf._document_state(raw)
            with self.subTest(original=original):
                self.assertFalse(pdf._ordered_pdf_evidence(state, [changed])['matched'])
                self.assertTrue(pdf._ordered_pdf_evidence(state, [original + '\n\f'])['matched'])

    def physical(self, text, *, footer_first=True):
        words = []
        body_y = 90
        for index, line in enumerate(text.rstrip('\n\f').split('\n')):
            if index == 0:
                box = [72, 32, 135, 41]
            elif line.isdigit() and (footer_first and index == 1 or not footer_first
                                      and index == len(text.rstrip('\n\f').split('\n')) - 1):
                box = [295, 799, 301, 808]
            else:
                box = [72, body_y, 520, body_y + 12]
                body_y += 17
            words.append({'text': line.lstrip(' '), 'bbox': box, 'order': index})
        return {'page': 1, 'width': 595, 'height': 842, 'rotation': 0, 'words': words}

    def page_story(self, paragraphs):
        raw = documents.make_docx(paragraphs, [], profile='dyz-standard-internal-v2')
        source = pdf._document_state(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        footer = ET.fromstring(parts['word/footer1.xml'])
        next(footer.iter(pdf._W + 't')).text = '2'
        parts['word/footer1.xml'] = ET.tostring(footer, encoding='utf-8')
        return source, pdf._document_state(documents._zip_docx(parts))

    def test_raw_footer_before_body_is_bound_to_physical_footer(self):
        source, saved = self.page_story([
            {'id': 'ONE', 'kind': 'paragraph', 'text': '第一页正文。'},
            {'id': 'TWO', 'kind': 'paragraph', 'text': '第二页正文。'}])
        texts = ['原创内部工作稿\n1\n第一页正文。\n\f',
                 '原创内部工作稿\n2\n第二页正文。\n\f']
        pages = [self.physical(text) for text in texts]
        options = {'physical_pages': pages,
                   'rendering_profile': documents.document_profile('dyz-standard-internal-v2')}
        result = pdf._field_evidence(source, saved, texts, {}, **options)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['fields'][0]['pdf_page_values'], ['1', '2'])
        pages[0]['words'][1]['bbox'] = [295, 90, 301, 102]
        self.assertEqual(pdf._field_evidence(source, saved, texts, {}, **options)['status'],
                         'needs_review')

    def test_physical_wrap_cannot_remove_technical_space_or_change_character(self):
        source, saved = self.page_story([
            {'id': 'CODE', 'kind': 'code', 'text': 'A B C'}])
        texts = ['原创内部工作稿\n1\nA B\n C\n\f']
        options = {'physical_pages': [self.physical(texts[0])],
                   'rendering_profile': documents.document_profile('dyz-standard-internal-v2')}
        self.assertTrue(pdf._ordered_pdf_evidence(saved, texts, **options)['matched'])
        for changed in ['原创内部工作稿\n1\nAB\n C\n\f',
                        '原创内部工作稿\n1\nA B\nC\n\f']:
            options['physical_pages'] = [self.physical(changed)]
            self.assertFalse(pdf._ordered_pdf_evidence(saved, [changed], **options)['matched'])
        original = pdf._document_state(documents.make_docx([
            {'id': 'CODE', 'kind': 'code', 'text': '附录A'}], [],
            profile='dyz-standard-internal-v2'))
        changed = '原创内部工作稿\n1\n附录 A\n\f'
        options['physical_pages'] = [self.physical(changed)]
        self.assertFalse(pdf._ordered_pdf_evidence(original, [changed], **options)['matched'])

    def test_explicit_line_break_at_physical_page_end_is_preserved(self):
        source, saved = self.page_story([
            {'id': 'TECH', 'kind': 'code', 'text': 'A B\nC D'}])
        texts = ['原创内部工作稿\n1\nA B\n\f', '原创内部工作稿\n2\nC D\n\f']
        options = {'physical_pages': [self.physical(text) for text in texts],
                   'rendering_profile': documents.document_profile('dyz-standard-internal-v2')}
        self.assertTrue(pdf._ordered_pdf_evidence(saved, texts, **options)['matched'])
        texts[1] = '原创内部工作稿\n2\nCD\n\f'
        options['physical_pages'][1] = self.physical(texts[1])
        self.assertFalse(pdf._ordered_pdf_evidence(saved, texts, **options)['matched'])

    def test_inactive_first_page_footer_copy_is_not_added_active_field(self):
        source, saved = self.page_story([
            {'id': 'ONE', 'kind': 'paragraph', 'text': '第一页正文。'},
            {'id': 'TWO', 'kind': 'paragraph', 'text': '第二页正文。'}])
        duplicate = copy.deepcopy(saved['fields'][0])
        duplicate.update(id=2, part='word/footer2.xml')
        saved['fields'].append(duplicate)
        saved['visible_parts']['word/footer2.xml'] = saved['visible_parts']['word/footer1.xml']
        saved['sections'][0]['references'][('footer', 'first')] = 'word/footer2.xml'
        texts = ['原创内部工作稿\n1\n第一页正文。\n\f',
                 '原创内部工作稿\n2\n第二页正文。\n\f']
        options = {'physical_pages': [self.physical(text) for text in texts],
                   'rendering_profile': documents.document_profile('dyz-standard-internal-v2')}
        result = pdf._field_evidence(source, saved, texts, {}, **options)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['saved_field_results'][1]['inactive_story_duplicate_of'], 1)
        saved['visible_parts']['word/header1.xml'] = '被替换的页眉\n'
        changed = [text.replace('原创内部工作稿', '被替换的页眉') for text in texts]
        changed_options = {**options, 'physical_pages': [self.physical(text) for text in changed]}
        changed_result = pdf._field_evidence(source, saved, changed, {}, **changed_options)
        self.assertEqual(changed_result['status'], 'needs_review')
        self.assertIn('story_template_changed', changed_result['issues'])
        saved['visible_parts']['word/header1.xml'] = '原创内部工作稿\n'
        saved['fields'][1]['instruction'] = 'PAGE \\* ROMAN'
        self.assertEqual(pdf._field_evidence(source, saved, texts, {}, **options)['status'],
                         'needs_review')
        saved['fields'][1]['instruction'] = 'PAGE'
        saved['sections'][0]['first_page'] = True
        self.assertEqual(pdf._field_evidence(source, saved, texts, {}, **options)['status'],
                         'needs_review')

    def test_nonfield_coverage_cannot_be_paid_by_field_cache(self):
        source = pdf._document_state(_field_docx())
        with self.assertRaisesRegex(ContractError, 'body_incomplete'):
            pdf._text_coverage(source['nonfield_fragments'], 'Synthetic target heading',
                               'standard_pdf_derived_body_incomplete')


def _literal_fixture_stream(raw, *, compressed=True):
    encoded = zlib.compress(raw) if compressed else raw
    return (b'<</Length ' + str(len(encoded)).encode('ascii')
            + (b'/Filter/FlateDecode' if compressed else b'') + b'>>\nstream\n'
            + encoded + b'\nendstream')


def _literal_fixture_objects(content=None, *, space=' ', first_width=500):
    """原创微型PDF；测试只依赖字节、明确字库与手算坐标，不依赖Office。"""
    if content is None:
        content = (b'q 0 0 595 842 re W* n\n'
                   b'q 0 0 0 rg BT 72 742 Td /F1 12 Tf<010203>Tj ET Q\n'
                   b'q 0 0 0 rg BT 72 725 Td /F1 12 Tf<0405>Tj ET Q\nQ\n')
    cmap = (b'/CIDInit/ProcSet findresource begin\n12 dict begin\nbegincmap\n'
            b'/CIDSystemInfo<</Registry (Adobe)/Ordering (UCS)/Supplement 0>> def\n'
            b'/CMapName/Adobe-Identity-UCS def\n/CMapType 2 def\n'
            b'1 begincodespacerange\n<00> <FF>\nendcodespacerange\n'
            b'5 beginbfchar\n<01> <0031>\n<02> <0030>\n<03> <'
            + space.encode('utf-16-be').hex().upper().encode('ascii')
            + b'>\n<04> <006D>\n<05> <0073>\nendbfchar\nendcmap\n'
            b'CMapName currentdict /CMap defineresource pop\nend\nend\n')
    return {
        1: b'<</Type/Catalog/Pages 2 0 R>>',
        2: b'<</Type/Pages/Kids[3 0 R]/Count 1/Resources 8 0 R>>',
        3: b'<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R>>',
        4: _literal_fixture_stream(content),
        5: (b'<</Type/FontDescriptor/FontName/AAAAAA+Fixture/Flags 4'
            b'/Ascent 800/Descent -200/FontBBox[0 -200 1000 800]/ItalicAngle 0'
            b'/CapHeight 800/StemV 80>>'),
        6: _literal_fixture_stream(cmap),
        7: (b'<</Type/Font/Subtype/TrueType/BaseFont/AAAAAA+Fixture'
            b'/FirstChar 1/LastChar 5/Widths[' + str(first_width).encode('ascii')
            + b' 500 500 500 500]/FontDescriptor 5 0 R/ToUnicode 6 0 R>>'),
        8: b'<</Font 9 0 R/ProcSet[/PDF/Text]>>',
        9: b'<</F1 7 0 R>>',
    }


def _literal_fixture_pdf(objects):
    raw, offsets = bytearray(b'%PDF-1.5\n'), [0]
    for number in range(1, len(objects) + 1):
        offsets.append(len(raw))
        raw.extend(str(number).encode('ascii') + b' 0 obj\n' + objects[number] + b'\nendobj\n')
    xref = len(raw)
    raw.extend(b'xref\n0 ' + str(len(offsets)).encode('ascii') + b'\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        raw.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    raw.extend(b'trailer\n<</Size ' + str(len(offsets)).encode('ascii')
               + b'/Root 1 0 R>>\nstartxref\n' + str(xref).encode('ascii') + b'\n%%EOF\n')
    return bytes(raw)


class StandardPdfLiteralSpaceTests(unittest.TestCase):
    def physical(self):
        return {'page': 1, 'width': 595.0, 'height': 842.0, 'rotation': None, 'words': [
            {'text': '10', 'bbox': [72.0, 90.4, 84.0, 102.4], 'order': 0},
            {'text': 'ms', 'bbox': [72.0, 107.4, 84.0, 119.4], 'order': 1}]}

    def evidence(self, objects=None, *, expected='10 ms', text='10\nms\n\f'):
        raw = _literal_fixture_pdf(objects or _literal_fixture_objects())
        pages = [self.physical()]
        proof = pdf._pdf_literal_space_evidence(raw, [text], pages)
        pages[0]['literal_space_evidence'] = proof['pages'][0]
        state = pdf._document_state(documents.make_docx(
            [{'id': 'CODE', 'kind': 'code', 'text': expected}], [],
            profile='dyz-standard-internal-v1'))
        options = {'physical_pages': pages,
                   'rendering_profile': documents.document_profile('dyz-standard-internal-v1')}
        return pdf._ordered_pdf_evidence(state, [text], **options), proof, state, options

    def test_actual_pdf_glyph_is_required_and_has_local_provenance(self):
        result, proof, state, options = self.evidence()
        plain = copy.deepcopy(options)
        plain['physical_pages'][0].pop('literal_space_evidence')
        self.assertFalse(pdf._ordered_pdf_evidence(state, ['10\nms\n\f'], **plain)['matched'])
        self.assertTrue(result['matched'])
        self.assertEqual(proof['status'], 'checked')
        witness, = proof['pages'][0]['witnesses']
        glyph, = witness['glyphs']
        self.assertEqual((witness['raw_line_break_start'], witness['raw_line_break_end']), (2, 3))
        self.assertEqual((glyph['font_code_hex'], glyph['unicode']), ('03', 'U+0020'))
        self.assertEqual((glyph['page_object'], glyph['content_object'], glyph['font_object'],
                          glyph['cmap_object']), (3, 4, 7, 6))
        self.assertEqual(glyph['bbox'][:3:2], [84.0, 90.0])
        self.assertEqual(len(glyph['content_stream_sha256']), 64)
        self.assertEqual(len(glyph['cmap_sha256']), 64)
        mapped, = [row for row in result['character_spans'] if row.get('rule') == 'pdf_literal_space_glyph']
        self.assertEqual((mapped['source_start'], mapped['source_end']), (2, 3))
        self.assertEqual((mapped['actual_start'], mapped['actual_end']), (2, 2))
        self.assertEqual(mapped['pdf_sha256'], proof['pdf_sha256'])

    def test_space_counts_tabs_nbsp_case_and_compatibility_remain_exact(self):
        for expected in ('10ms', '10  ms', '10\tms', '10\u00a0ms', '１0 ms', '10 MS'):
            with self.subTest(expected=expected):
                self.assertFalse(self.evidence(expected=expected)[0]['matched'])
        objects = _literal_fixture_objects()
        content = zlib.decompress(objects[4].split(b'stream\n', 1)[1].rsplit(b'\nendstream', 1)[0])
        objects[4] = _literal_fixture_stream(content.replace(b'<010203>', b'<01020303>'))
        self.assertTrue(self.evidence(objects, expected='10  ms')[0]['matched'])
        for expected in ('10 ms', '10   ms', '10\tms', '10\u00a0ms'):
            with self.subTest(two_glyphs=expected):
                self.assertFalse(self.evidence(objects, expected=expected)[0]['matched'])
        # PDF明确的NBSP并不是U+0020见证，即使提取器同样省略它。
        self.assertFalse(self.evidence(_literal_fixture_objects(space='\u00a0'))[0]['matched'])

    def test_explicit_source_line_break_is_not_consumed_as_an_implicit_wrap(self):
        self.assertTrue(self.evidence(expected='10 \nms')[0]['matched'])
        self.assertFalse(self.evidence(expected='10\nms')[0]['matched'])

    def test_deleted_glyph_wrong_font_width_cmap_and_coordinates_stay_rejected(self):
        original = _literal_fixture_objects()
        content = zlib.decompress(original[4].split(b'stream\n', 1)[1].rsplit(b'\nendstream', 1)[0])
        cases = {
            'deleted_code': {**original, 4: _literal_fixture_stream(content.replace(b'<010203>', b'<0102>'))},
            'wrong_font': {**original, 4: _literal_fixture_stream(content.replace(b'/F1', b'/F2'))},
            'wrong_x': {**original, 4: _literal_fixture_stream(content.replace(b'72 742', b'73 742'))},
            'wrong_y': {**original, 4: _literal_fixture_stream(content.replace(b'72 742', b'72 741'))},
            'wrong_width': _literal_fixture_objects(first_width=600),
            'wrong_space_cmap': _literal_fixture_objects(space='\u00a0'),
        }
        cmap = zlib.decompress(original[6].split(b'stream\n', 1)[1].rsplit(b'\nendstream', 1)[0])
        cases['wrong_prefix_cmap'] = {**original, 6: _literal_fixture_stream(cmap.replace(b'<0030>', b'<006F>'))}
        for name, objects in cases.items():
            with self.subTest(case=name):
                result, proof, _, _ = self.evidence(objects)
                self.assertFalse(result['matched'])
                self.assertEqual(proof['pages'][0]['witnesses'], [])

    def test_same_text_or_space_at_a_different_position_is_not_a_witness(self):
        for extra in (b'BT 172 642 Td /F1 12 Tf<010203>Tj ET\n',
                      b'BT 100 742 Td /F1 12 Tf<03>Tj ET\n'):
            content = (b'BT 72 742 Td /F1 12 Tf<0102>Tj ET\n' + extra
                       + b'BT 72 725 Td /F1 12 Tf<0405>Tj ET\n')
            with self.subTest(extra=extra):
                result, proof, _, _ = self.evidence(_literal_fixture_objects(content))
                self.assertFalse(result['matched'])
                self.assertEqual(proof['pages'][0]['witnesses'], [])

    def test_stale_raw_text_word_coordinates_and_wrong_page_disable_evidence(self):
        result, _, state, options = self.evidence()
        self.assertTrue(result['matched'])
        changed = copy.deepcopy(options)
        changed['physical_pages'][0]['words'][0]['bbox'][0] += 1
        self.assertFalse(pdf._ordered_pdf_evidence(state, ['10\nms\n\f'], **changed)['matched'])
        changed = copy.deepcopy(options)
        changed['physical_pages'][0]['literal_space_evidence']['page'] = 2
        self.assertFalse(pdf._ordered_pdf_evidence(state, ['10\nms\n\f'], **changed)['matched'])
        self.assertFalse(pdf._ordered_pdf_evidence(state, ['10\nms\n\n\f'], **options)['matched'])

    def test_unexplained_syntax_transforms_fonts_and_streams_provide_no_witness(self):
        original = _literal_fixture_objects()
        content = zlib.decompress(original[4].split(b'stream\n', 1)[1].rsplit(b'\nendstream', 1)[0])
        cases = {
            'ctm': {**original, 4: _literal_fixture_stream(b'1 0 0 1 1 0 cm\n' + content)},
            'text_matrix': {**original, 4: _literal_fixture_stream(content.replace(b'72 742 Td', b'2 0 0 1 72 742 Tm'))},
            'text_scaling': {**original, 4: _literal_fixture_stream(content.replace(b'/F1 12 Tf', b'/F1 12 Tf 90 Tz'))},
            'invisible': {**original, 4: _literal_fixture_stream(content.replace(b'/F1 12 Tf', b'/F1 12 Tf 3 Tr'))},
            'actual_text': {**original, 4: _literal_fixture_stream(b'/Span <</ActualText(10 )>> BDC\n' + content + b'EMC')},
            'nonrectangular_clip': {**original, 4: _literal_fixture_stream(b'0 0 m 595 842 l W n\n' + content)},
            'encoding': {**original, 7: original[7].replace(b'/FirstChar', b'/Encoding/WinAnsiEncoding/FirstChar')},
            'type0': {**original, 7: original[7].replace(b'/TrueType', b'/Type0')},
            'rotation': {**original, 3: original[3].replace(b'/Contents', b'/Rotate 90/Contents')},
            'crop': {**original, 3: original[3].replace(b'/Contents', b'/CropBox[1 0 595 842]/Contents')},
            'external_stream': {**original, 4: original[4].replace(b'/Length', b'/F(outside.bin)/Length')},
            'length': {**original, 4: original[4].replace(b'/Length ', b'/Length 1 /Unused ')},
        }
        cmap = zlib.decompress(original[6].split(b'stream\n', 1)[1].rsplit(b'\nendstream', 1)[0])
        cases['cmap_range'] = {**original, 6: _literal_fixture_stream(cmap.replace(b'beginbfchar', b'beginbfrange'))}
        cases['ambiguous_cmap'] = {**original, 6: _literal_fixture_stream(cmap.replace(b'<05>', b'<03>'))}
        for name, objects in cases.items():
            with self.subTest(case=name):
                result, proof, _, _ = self.evidence(objects)
                self.assertFalse(result['matched'])
                self.assertEqual(proof['status'], 'unsupported')
                self.assertEqual(proof['pages'][0]['witnesses'], [])

    def test_xref_and_length_ignore_fake_object_headers_inside_streams(self):
        objects = _literal_fixture_objects()
        objects[10] = _literal_fixture_stream(b'7 0 obj\n<</Type/Font/Subtype/Type0>>\nendobj\n', compressed=False)
        self.assertTrue(self.evidence(objects)[0]['matched'])
        # 反例：不准使用隐藏stream中的伪7号对象盖过xref绑定的真实坏字库。
        objects[10] = _literal_fixture_stream(b'7 0 obj\n' + objects[7] + b'\nendobj\n', compressed=False)
        objects[7] = objects[7].replace(b'/TrueType', b'/Type0')
        self.assertFalse(self.evidence(objects)[0]['matched'])
        raw = _literal_fixture_pdf(_literal_fixture_objects())
        for changed in (raw.replace(b'xref\n0 ', b'xref\n9 ', 1), raw.replace(b'/Root 1 0 R', b'/Prev 1/Root 1 0 R')):
            with self.subTest(classic_xref=changed[-180:]):
                proof = pdf._pdf_literal_space_evidence(changed, ['10\nms\n\f'], [self.physical()])
                self.assertEqual(proof['status'], 'unsupported')
                self.assertEqual(proof['pages'][0]['witnesses'], [])

    def test_evidence_byte_stream_page_limits_and_missing_cmap_fail_closed(self):
        for name, limit in [('MAX_FILE_BYTES', 32), ('MAX_TEXT_BYTES', 64),
                            ('MAX_PAGES_PER_DOCUMENT', 0)]:
            with self.subTest(limit=name), patch.object(pdf, name, limit):
                proof = pdf._pdf_literal_space_evidence(
                    _literal_fixture_pdf(_literal_fixture_objects()),
                    ['10\nms\n\f'], [self.physical()])
                self.assertEqual(proof['status'], 'unsupported')
                self.assertEqual(proof['pages'][0]['witnesses'], [])
        objects = _literal_fixture_objects()
        objects[7] = objects[7].replace(b'/ToUnicode 6 0 R', b'')
        self.assertFalse(self.evidence(objects)[0]['matched'])


class StandardPdfTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dyz-pdf-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.payload = task()
        # PDF测试不凭业务审批状态放行；使用明确零意见的原创合成包。
        self.payload['comments'] = []
        self.payload['comment_outcomes'] = []
        self.source_manifest = standards_delivery.prepare(
            self.root, self.payload, 'pack', synthetic=True)
        self.inputs = {role: (self.root / f'pack/body/{role}.docx').read_bytes()
                       for role in standards_delivery.ROLES}
        programs = self.root / 'programs'
        programs.mkdir()
        self.tools = {}
        for name in pdf.TOOL_NAMES:
            path = programs / (name + '.exe')
            path.write_bytes(b'safe-local-subprocess-test-double')
            self.tools[name] = str(path)
        self.calls = []
        self.info = b'Pages:          2\nPage size: 595 x 842 pts\nPage rot: 0\n'
        self.effect = None
        self.processes = []
        self.job = Mock()
        self.addCleanup(patch.stopall)
        patch.object(pdf, '_WindowsJob', return_value=self.job).start()
        patch.object(pdf.subprocess, 'Popen', side_effect=self._popen).start()
        if os.name != 'nt':
            patch.object(pdf.os, 'killpg').start()

    def _popen(self, arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        name = Path(arguments[0]).stem.lower()
        process = Mock(pid=654321)
        process.wait.return_value = 0
        process.poll.return_value = 0
        self.processes.append(process)
        if name == 'soffice':
            target = Path(arguments[arguments.index('--outdir') + 1])
            format_name = arguments[arguments.index('--convert-to') + 1]
            if format_name.startswith('docx:'):
                for argument in arguments:
                    if argument.endswith('.docx'):
                        source = Path(argument)
                        (target / source.name).write_bytes(source.read_bytes())
            else:
                for role in standards_delivery.ROLES:
                    (target / f'{role}.pdf').write_bytes(b'%PDF-1.7\nsynthetic-process-double\n')
        elif name == 'python':
            config = json.loads(Path(arguments[-1]).read_text('utf-8'))
            self.uno_config = config
            self.uno_script = Path(arguments[-2]).read_text('utf-8')
            for source in config['inputs']:
                path = Path(source)
                (Path(config['output']) / path.name).write_bytes(path.read_bytes())
        elif name == 'pdfinfo':
            kwargs['stdout'].write(b'Page Destination Name\n' if '-dests' in arguments else self.info)
        elif name == 'pdftotext':
            role = Path(arguments[-2]).stem
            page = int(arguments[arguments.index('-f') + 1])
            paragraphs = pdf._paragraphs(self.inputs[role])
            middle = max(1, len(paragraphs) // 2)
            subset = paragraphs[:middle] if page == 1 else paragraphs[middle:]
            if '-bbox-layout' in arguments or '-bbox' in arguments:
                root = ET.Element('html')
                document = ET.SubElement(ET.SubElement(root, 'body'), 'doc')
                element = ET.SubElement(document, 'page', width='595', height='842')
                block = ET.SubElement(ET.SubElement(element, 'flow'), 'block')
                for index, text in enumerate(subset):
                    y = 80 + (index % 40) * 16
                    line = ET.SubElement(block, 'line')
                    word = ET.SubElement(line, 'word', xMin='80', yMin=str(y),
                                         xMax='500', yMax=str(y + 12))
                    word.text = text
                Path(arguments[-1]).write_bytes(ET.tostring(root, encoding='utf-8'))
            else:
                Path(arguments[-1]).write_bytes(('\n'.join(subset) + '\n\f').encode('utf-8'))
        elif name == 'pdftoppm':
            Path(arguments[-1]).with_suffix('.png').write_bytes(_png())
        if self.effect:
            self.effect(name, arguments, process)
        return process

    def convert(self, **kwargs):
        options = {'synthetic': True, 'tool_paths': self.tools}
        options.update(kwargs)
        return pdf.convert(self.root, 'pack', 'result', **options)

    def no_manifest(self):
        self.assertFalse((self.root / 'result/manifest.json').exists())

    def test_five_documents_all_pages_and_hashes(self):
        report = self.convert()
        self.assertEqual(report['total_documents'], 5)
        self.assertEqual(report['total_pages'], 10)
        self.assertEqual(report['visual_review'], 'not_performed')
        self.assertEqual(report['professional_review'], 'not_performed')
        self.assertEqual(report['external_action'], 'not_performed')
        has_fields = any(pdf._document_state(raw)['fields'] for raw in self.inputs.values())
        self.assertEqual(report['machine_checks'], 'needs_review' if has_fields else 'completed_no_issues')
        self.assertEqual(report['source_manifest_sha256'], sha256_bytes(
            (self.root / 'pack/manifest.json').read_bytes()))
        self.assertEqual(json.loads((self.root / 'result/manifest.json').read_text('utf-8')),
                         report)
        for row in report['documents']:
            self.assertEqual(row['page_count_source'], 'pdfinfo')
            self.assertEqual(row['total_pages'], 2)
            self.assertEqual([page['page'] for page in row['pages']], [1, 2])
            self.assertEqual(row['input_docx']['sha256'], sha256_bytes(self.inputs[row['role']]))
            self.assertEqual(row['derived_from_sha256'], row['input_docx']['sha256'])
            self.assertEqual(row['derived_docx']['sha256'], sha256_bytes(self.inputs[row['role']]))
            self.assertTrue(row['nonfield_body_preserved'])
            self.assertEqual(row['pdf_input'], 'derived_docx')
            self.assertEqual(row['geometry']['visual_review'], 'not_performed')
            self.assertEqual(row['geometry']['coverage']['image_text'], 'not_checked')
            self.assertEqual(row['page_observation']['pages_observed'], [])
            self.assertTrue(all(page['bbox']['path'].endswith('.bbox.xhtml') for page in row['pages']))
            texts = [(self.root / 'result' / page['text']['path']).read_bytes().decode('utf-8')
                     for page in row['pages']]
            self.assertEqual(row['text_sha256'], sha256_bytes('\f'.join(texts).encode('utf-8')))
        for row in report['files']:
            raw = (self.root / 'result' / row['path']).read_bytes()
            self.assertEqual((row['bytes'], row['sha256']), (len(raw), sha256_bytes(raw)))
        self.assertNotIn('manifest.json', [row['path'] for row in report['files']])
        for role, raw in self.inputs.items():
            self.assertEqual((self.root / f'pack/body/{role}.docx').read_bytes(), raw)

    def test_bbox_failure_keeps_visual_and_geometry_unproven(self):
        def invalid(name, arguments, process):
            if name == 'pdftotext' and '-bbox-layout' in arguments:
                Path(arguments[-1]).write_bytes(b'<!DOCTYPE x [<!ENTITY a "x">]><x>&a;</x>')
        self.effect = invalid
        with self.assertRaisesRegex(ContractError, 'bbox_xml_invalid'):
            self.convert()
        self.no_manifest()

    def test_saved_docx_cannot_insert_technical_text_before_pdf_export(self):
        def changed(name, arguments, process):
            if name == 'soffice':
                path = self.root / 'result/derived-docx/standard.docx'
                raw = path.read_bytes()
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    parts = {part: archive.read(part) for part in archive.namelist()}
                document = ET.fromstring(parts['word/document.xml'])
                first = next(document.iter(pdf._W + 't'))
                first.text += ' EXTRA'
                parts['word/document.xml'] = ET.tostring(document, encoding='utf-8')
                path.write_bytes(documents._zip_docx(parts))
        self.effect = changed
        with self.assertRaisesRegex(ContractError, 'derived_body_changed'):
            self.convert()
        self.assertEqual(len(self.calls), 1)
        self.no_manifest()

    def test_profile_and_input_are_isolated_and_scratch_removed(self):
        self.convert()
        arguments, options = self.calls[0]
        profile_arg = next(value for value in arguments if value.startswith('-env:'))
        self.assertIn('dyz-standard-office-', profile_arg)
        self.assertNotIn(str(self.root / 'pack'), ' '.join(arguments))
        staged = [Path(value) for value in arguments if value.endswith('.docx')]
        self.assertEqual(len(staged), 5)
        self.assertTrue(all(not path.parent.exists() for path in staged))
        self.assertIs(options['shell'], False)
        self.assertEqual(options['stdin'], subprocess.DEVNULL)
        if os.name == 'nt':
            self.assertTrue(options['creationflags'] & 0x00000004)
            self.assertEqual(self.job.attach.call_count, len(self.calls))
            self.assertEqual(self.job.close.call_count, len(self.calls))

    def test_declaration_rejected_before_read(self):
        for flag in (False, None, 1, 'synthetic'):
            with self.subTest(flag=flag), patch.object(pdf, '_root') as root:
                with self.assertRaisesRegex(ContractError, 'synthetic_required'):
                    self.convert(synthetic=flag)
                root.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_manifest_wrong_mode_or_version_before_payload_read(self):
        path = self.root / 'pack/manifest.json'
        original = path.read_bytes()
        for key, value in [('mode', 'authorized_case'), ('generator_version', 'old'),
                           ('contract_version', 1), ('generator', 'other')]:
            with self.subTest(key=key):
                manifest = json.loads(original)
                manifest[key] = value
                path.write_bytes(canonical_bytes(manifest))
                with patch.object(pdf, '_read_file', wraps=pdf._read_file) as read:
                    with self.assertRaisesRegex(ContractError, 'package_not_synthetic_current'):
                        self.convert()
                    self.assertEqual(len(read.call_args_list), 1)
        self.assertEqual(self.calls, [])

    def test_payload_must_be_synthetic_before_verify(self):
        path = self.root / 'pack/internal/input.json'
        payload = json.loads(path.read_bytes())
        payload['sensitivity'] = 'restricted'
        path.write_bytes(canonical_bytes(payload))
        with patch.object(standards_delivery, 'verify') as verify:
            with self.assertRaisesRegex(ContractError, 'input_changed'):
                self.convert()
            verify.assert_not_called()

    def test_same_version_verify_is_required(self):
        with patch.object(standards_delivery, 'verify', return_value={}) as verify:
            with self.assertRaisesRegex(ContractError, 'package_unverified'):
                self.convert()
            verify.assert_called_once()
        self.assertEqual(self.calls, [])

    def test_missing_any_document_is_rejected(self):
        for role in standards_delivery.ROLES:
            with self.subTest(role=role):
                path = self.root / f'pack/body/{role}.docx'
                path.unlink()
                with self.assertRaisesRegex(ContractError, 'package_members_changed'):
                    self.convert()
                path.write_bytes(self.inputs[role])
        self.assertEqual(self.calls, [])

    def test_tampered_input_and_forged_hash_do_not_pass_verify(self):
        path = self.root / 'pack/body/standard.docx'
        path.write_bytes(path.read_bytes() + b'changed')
        manifest_path = self.root / 'pack/manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        for entry in manifest['files']:
            if entry['path'] == 'body/standard.docx':
                entry['sha256'] = sha256_bytes(path.read_bytes())
                entry['bytes'] = path.stat().st_size
        manifest_path.write_bytes(canonical_bytes(manifest) + b'\n')
        with self.assertRaises(ContractError):
            self.convert()
        self.assertEqual(self.calls, [])

    def test_unknown_package_members_rejected(self):
        (self.root / 'pack/internal/unexpected.txt').write_text('synthetic')
        with self.assertRaisesRegex(ContractError, 'package_members_changed'):
            self.convert()
        self.assertEqual(self.calls, [])

    def test_size_limits_before_subprocess(self):
        for name in ('MAX_FILE_BYTES', 'MAX_PACKAGE_BYTES', 'MAX_MANIFEST_BYTES'):
            with self.subTest(limit=name), patch.object(pdf, name, 1):
                with self.assertRaises(ContractError):
                    self.convert()
        self.assertEqual(self.calls, [])

    def test_output_cannot_overwrite_or_overlap_package(self):
        for output in ('pack', 'pack/result', '../escape', 'result.', 'C:/outside', 'NUL'):
            with self.subTest(output=output), self.assertRaises(ContractError):
                pdf.convert(self.root, 'pack', output, synthetic=True, tool_paths=self.tools)
        (self.root / 'result').mkdir()
        (self.root / 'result/sentinel.txt').write_text('keep')
        with self.assertRaisesRegex(ContractError, 'output_exists'):
            self.convert()
        self.assertEqual((self.root / 'result/sentinel.txt').read_text(), 'keep')
        self.assertEqual(self.calls, [])

    def test_path_links_and_reparse_points_refused(self):
        path = self.root / 'pack/body/standard.docx'
        original = Path.lstat
        def reparse(value):
            result = original(value)
            if value == path:
                return SimpleNamespace(st_mode=result.st_mode, st_nlink=1,
                                       st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaisesRegex(ContractError, 'link_unsupported'):
                self.convert()
        self.assertEqual(self.calls, [])

    def test_hard_link_alias_refused(self):
        original = self.root / 'pack/body/standard.docx'
        alias = self.root / 'alias.docx'
        os.link(original, alias)
        with self.assertRaisesRegex(ContractError, 'alias_unsupported'):
            self.convert()
        self.assertEqual(self.calls, [])

    def test_invalid_tool_names_and_missing_tools(self):
        for tools in ({}, {**self.tools, 'soffice': 'soffice.exe'},
                      {**self.tools, 'soffice': self.tools['pdfinfo']},
                      {**self.tools, 'extra': self.tools['pdfinfo']}):
            with self.subTest(tools=tools), self.assertRaises(ContractError):
                self.convert(tool_paths=tools)
        self.assertEqual(self.calls, [])

    def test_explicit_bundled_python_uses_isolated_pipe_and_owned_job(self):
        python = self.root / 'programs/python.exe'
        python.write_bytes(b'local-bundled-python-test-double')
        tools = {**self.tools, 'office_python': str(python)}
        report = self.convert(tool_paths=tools)
        self.assertEqual(self.calls[0][0][0], str(python))
        self.assertRegex(self.uno_config['pipe'], r'^dyz_standard_[0-9a-f]{32}$')
        self.assertIn('dyz-standard-office-', self.uno_config['profile'])
        self.assertIn("prop('MacroExecutionMode', NEVER_EXECUTE)", self.uno_script)
        self.assertIn("prop('UpdateDocMode', NO_UPDATE)", self.uno_script)
        self.assertNotIn('socket,', self.uno_script)
        self.assertIsNone(self.uno_config['layout_policy'])
        self.assertIn("uno.Any('[]com.sun.star.beans.PropertyValue'", self.uno_script)
        self.assertIn('desktop.terminate()', self.uno_script)
        self.assertIn('process.wait(timeout=5)', self.uno_script)
        compile(self.uno_script, '<bounded-uno-runner>', 'exec')
        self.assertFalse(Path(self.calls[0][0][-1]).exists())
        self.assertIn('office_python', report['tools'])
        self.assertTrue(all(row['field_refresh']['method'] ==
                            'bounded_local_uno_refresh_fields_update_indexes_store_docx'
                            for row in report['documents']))

    def test_uno_v2_policy_restores_table_and_active_story_before_refresh(self):
        namespace = {'config': {'layout_policy': None}}
        tree = ast.parse(pdf._UNO_SCRIPT)
        restore = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == 'restore_layout')
        exec(compile(ast.Module(body=[restore], type_ignores=[]), '<uno-layout>', 'exec'), namespace)
        apply = namespace['restore_layout']
        self.assertIsNone(apply(None, 'v1_must_not_be_touched'))
        properties = {'ParaIsCharacterDistance': False, 'ParaIsHangingPunctuation': False}
        namespace['config']['layout_policy'] = {'uno_properties': properties}

        class Paragraph:
            def __init__(self):
                self.values = dict.fromkeys(properties, True)
            def supportsService(self, name):
                return name == 'com.sun.star.text.Paragraph'
            def getPropertyValue(self, name):
                return self.values[name]
            def setPropertyValue(self, name, value):
                self.values[name] = value

        class Text:
            def __init__(self, items):
                self.items = items
            def createEnumeration(self):
                remaining = iter(self.items)
                cached = [next(remaining, None)]
                def next_item():
                    current = cached[0]
                    cached[0] = next(remaining, None)
                    return current
                return SimpleNamespace(hasMoreElements=lambda: cached[0] is not None,
                                       nextElement=next_item)

        body, cell, header, footer, style = [Paragraph() for _ in range(5)]
        table = SimpleNamespace(
            supportsService=lambda name: name == 'com.sun.star.text.TextTable',
            getCellNames=lambda: ['A1'], getCellByName=lambda name: Text([cell]))
        active = SimpleNamespace(
            isInUse=lambda: True,
            getPropertySetInfo=lambda: SimpleNamespace(hasPropertyByName=lambda name: name in {
                'HeaderText', 'FooterText'}),
            getPropertyValue=lambda name: {'HeaderIsOn': True, 'FooterIsOn': True,
                'HeaderText': Text([header]), 'FooterText': Text([footer])}[name])
        def collection(items):
            return SimpleNamespace(getElementNames=lambda: list(items),
                                   getByName=lambda name: items[name])
        families = collection({'PageStyles': collection({'used': active}),
                               'ParagraphStyles': collection({'Normal': style})})
        document = SimpleNamespace(getText=lambda: Text([body, table]),
                                   getStyleFamilies=lambda: families)
        evidence = apply(document, 'stored_docx_reopen_before_refresh')
        for item in (body, cell, header, footer, style):
            self.assertEqual(item.values, properties)
        self.assertEqual(set(evidence['scopes']), {'body_paragraphs', 'table_cell_paragraphs',
                         'active_header_paragraphs', 'active_footer_paragraphs', 'paragraph_styles'})
        for scope in evidence['scopes'].values():
            self.assertEqual(scope['objects'], 1)
            self.assertTrue(all(row['before_true'] == row['after_false'] == 1
                                for row in scope['properties'].values()))

    def test_bundled_python_must_belong_to_supplied_office_installation(self):
        python = self.root / 'python.exe'
        python.write_bytes(b'wrong-installation')
        with self.assertRaisesRegex(ContractError, 'installation_mismatch'):
            self.convert(tool_paths={**self.tools, 'office_python': str(python)})
        self.assertFalse(self.calls)

    def test_count_is_independent_not_max_extracted_page(self):
        for info in (b'Pages: 0\n', b'Pages: 51\n', b'Last extracted page: 2\n',
                     b'Pages: 2\nPages: 2\n'):
            with self.subTest(info=info):
                self.info = info
                # 每个失败使用新目录，不能覆盖失败产物。
                output = 'failure-' + str(len(self.calls))
                with self.assertRaisesRegex(ContractError, 'page_count'):
                    pdf.convert(self.root, 'pack', output, synthetic=True, tool_paths=self.tools)
                self.assertFalse((self.root / output / 'manifest.json').exists())

    def test_total_page_limit(self):
        with patch.object(pdf, 'MAX_TOTAL_PAGES', 3):
            with self.assertRaisesRegex(ContractError, 'page_count_limit'):
                self.convert()
        self.no_manifest()

    def test_missing_page_text_or_image_cannot_leave_success(self):
        def missing(name, arguments, process):
            if name == 'pdftoppm':
                Path(arguments[-1]).with_suffix('.png').unlink()
        self.effect = missing
        with self.assertRaisesRegex(ContractError, 'path_missing'):
            self.convert()
        self.no_manifest()

    def test_empty_text_is_unreadable_not_complete(self):
        def empty(name, arguments, process):
            if name == 'pdftotext':
                Path(arguments[-1]).write_bytes(b'\n\f')
        self.effect = empty
        with self.assertRaisesRegex(ContractError, 'text_unreadable'):
            self.convert()
        self.no_manifest()

    def test_dropped_source_text_is_incomplete(self):
        def missing(name, arguments, process):
            if name == 'pdftotext' and '-bbox-layout' not in arguments and '-bbox' not in arguments:
                Path(arguments[-1]).write_bytes(b'unrelated synthetic text\n')
        self.effect = missing
        with self.assertRaisesRegex(ContractError, 'text_coverage_incomplete'):
            self.convert()
        self.no_manifest()

    def test_non_pdf_output_is_rejected(self):
        def invalid(name, arguments, process):
            if name == 'soffice' and arguments[arguments.index('--convert-to') + 1].startswith('pdf:'):
                (self.root / 'result/pdf/standard.pdf').write_bytes(b'HTML error')
        self.effect = invalid
        with self.assertRaisesRegex(ContractError, 'header_invalid'):
            self.convert()
        self.no_manifest()

    def test_tool_failure_and_timeout_clean_only_owned_process(self):
        def fail(name, arguments, process):
            process.wait.return_value = 1
        self.effect = fail
        with self.assertRaisesRegex(ContractError, 'tool_failed'):
            self.convert()
        self.no_manifest()
        self.assertEqual(len(self.calls), 1)
        if os.name == 'nt':
            self.job.close.assert_called_once()
        self.assertEqual(self.calls[0][0][0], self.tools['soffice'])

    def test_timeout_has_no_success_manifest_and_cleans_scratch(self):
        def timeout(name, arguments, process):
            process.wait.side_effect = [subprocess.TimeoutExpired(arguments, 60), 0]
        self.effect = timeout
        with self.assertRaisesRegex(ContractError, 'tool_timeout'):
            self.convert()
        self.no_manifest()
        staged = [Path(value) for value in self.calls[0][0] if value.endswith('.docx')]
        self.assertTrue(all(not path.parent.exists() for path in staged))
        if os.name == 'nt':
            self.job.close.assert_called_once()

    def test_source_changed_during_conversion_is_rejected(self):
        def change(name, arguments, process):
            if name == 'soffice':
                (self.root / 'pack/body/standard.docx').write_bytes(b'changed')
        self.effect = change
        with self.assertRaises(ContractError):
            self.convert()
        self.no_manifest()

    def test_change_after_verify_before_staging_is_rejected(self):
        original = standards_delivery.verify
        def change(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.root / 'pack/body/standard.docx').write_bytes(b'changed')
            return result
        with patch.object(standards_delivery, 'verify', side_effect=change):
            with self.assertRaisesRegex(ContractError, 'input_changed'):
                self.convert()
        self.assertEqual(self.calls, [])

    def test_saved_docx_nonfield_body_loss_is_rejected_before_pdf(self):
        def drop(name, arguments, process):
            if name == 'soffice':
                path = self.root / 'result/derived-docx/standard.docx'
                path.write_bytes(documents.make_docx([
                    {'id': 'OTHER', 'kind': 'paragraph', 'text': 'Unrelated saved body'}], []))
        self.effect = drop
        with self.assertRaisesRegex(ContractError, 'derived_body_incomplete'):
            self.convert()
        self.no_manifest()
        self.assertEqual(len(self.calls), 1)

    def test_output_added_during_conversion_is_rejected(self):
        def change(name, arguments, process):
            if name == 'soffice':
                (self.root / 'result/unexpected.txt').write_bytes(b'synthetic')
        self.effect = change
        with self.assertRaisesRegex(ContractError, 'output_members_changed'):
            self.convert()
        self.no_manifest()


class StandardPdfAdmissionTests(unittest.TestCase):
    """所有材料仍为原创临时夹具；只模拟真实入口的控制描述。"""

    setUp = StandardPdfTests.setUp
    _popen = StandardPdfTests._popen
    no_manifest = StandardPdfTests.no_manifest

    def authorized_package(self, sensitivity='restricted', *, source_inputs=None):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        purpose = 'pdf-boundary-synthetic-fixture'
        context = dict(
            root=str(self.root), output='real-pack',
            payload_hash=sha256_bytes(canonical_bytes(self.payload)),
            sensitivity=sensitivity, purpose=purpose,
            permissions=[dict(action=action, purpose=purpose, recipient='local_tool',
                              decision='allow', authority_evidence='synthetic-fixture',
                              valid_from=(now - timedelta(hours=1)).isoformat(),
                              valid_until=(now + timedelta(hours=1)).isoformat())
                         for action in ('local_read', 'local_process', 'copy', 'local_write')],
            environment=dict(assessment_evidence='synthetic-fixture', data_paths=[
                dict(id=key, mode='local' if key in {'tools', 'subprocess'} else 'disabled',
                     verified=True, evidence='synthetic-fixture')
                for key in ('host_model', 'index', 'telemetry', 'tools', 'logs', 'subprocess')]))
        self.payload['sensitivity'] = sensitivity
        context['payload_hash'] = sha256_bytes(canonical_bytes(self.payload))
        if source_inputs is not None:
            context['inputs'] = dict(source_inputs)
        standards_delivery.prepare(self.root, self.payload, 'real-pack', admission=context)
        package = self.root / 'real-pack'
        members = {path.relative_to(package).as_posix(): sha256_bytes(path.read_bytes())
                   for path in package.rglob('*') if path.is_file()}
        admission = {key: value for key, value in context.items()
                     if key not in {'payload_hash', 'inputs'}}
        if source_inputs is not None:
            admission['source_inputs'] = dict(source_inputs)
        admission.update(package='real-pack', output='result', inputs=members,
                         manifest_sha256=members['manifest.json'])
        self.inputs = {role: (package / f'body/{role}.docx').read_bytes()
                       for role in standards_delivery.ROLES}
        return admission

    def real_convert(self, admission):
        return pdf.convert(self.root, 'real-pack', 'result', synthetic=False,
                           admission=admission, tool_paths=self.tools)

    def authorized_source_package(self):
        from evals.test_standard_sources import consumption_package
        source, report = consumption_package(self.root)
        self.payload['source_reports'] = source['source_reports']
        self.payload['source_bindings'] = [dict(source['source_bindings'][0],
            target_id='CL1', version=self.payload['version'])]
        sources = {name: sha256_bytes((self.root / name).read_bytes())
                   for name in ('original.txt', 'report.json')}
        return self.authorized_package(source_inputs=sources), report

    def test_real_sources_use_explicit_root_relative_inventory_without_copying(self):
        admission, source = self.authorized_source_package()
        original = standards_delivery.verify
        inventories = []
        def track(*args, **kwargs):
            inventories.append(dict(kwargs['admission']['inputs']))
            return original(*args, **kwargs)
        with patch.object(standards_delivery, 'verify', side_effect=track):
            report = self.real_convert(admission)
        expected = {'real-pack/' + name: value for name, value in admission['inputs'].items()}
        expected.update(admission['source_inputs'])
        self.assertEqual(inventories, [expected, expected])
        self.assertEqual(report['admission']['source_inputs'], admission['source_inputs'])
        self.assertEqual(report['source_trace_pages'][0]['original_sha256'], source['original_sha256'])
        self.assertTrue(all(row['path'] not in admission['source_inputs'] for row in report['files']))
        self.assertFalse((self.root / 'real-pack/original.txt').exists())
        self.assertFalse((self.root / 'result/report.json').exists())

    def test_real_sources_never_infer_missing_report_or_original_authorization(self):
        admission, _ = self.authorized_source_package()
        for name in ('report.json', 'original.txt'):
            denied = copy.deepcopy(admission)
            denied['source_inputs'].pop(name)
            with self.subTest(name=name), patch.object(pdf, '_read_file', wraps=pdf._read_file) as read:
                with self.assertRaisesRegex(ContractError, 'source_input_not_admitted'):
                    self.real_convert(denied)
                self.assertNotIn(self.root / name, [call.args[0] for call in read.call_args_list])
        self.assertFalse(self.calls)

    def test_real_source_inventory_shape_paths_hashes_and_output_scope_are_strict(self):
        admission, _ = self.authorized_source_package()
        candidates = [None, [], {'original.txt': 'not-a-sha256'}, {'../original.txt': '0' * 64},
                      {'/original.txt': '0' * 64}, {'C:/outside.txt': '0' * 64},
                      {'real-pack/body/standard.docx': admission['inputs']['body/standard.docx']},
                      {'result': '0' * 64}, {'original.txt': '0' * 64},
                      {'report.json/': admission['source_inputs']['report.json']}]
        for sources in candidates:
            denied = {**admission, 'source_inputs': sources}
            with self.subTest(sources=sources), self.assertRaises(ContractError):
                self.real_convert(denied)
        self.assertFalse(self.calls)

    def test_real_source_utf8_bom_report_is_bound_to_original_bytes(self):
        admission, _ = self.authorized_source_package()
        report_path = self.root / 'report.json'
        raw = b'\xef\xbb\xbf' + report_path.read_bytes()
        report_path.write_bytes(raw)
        admission['source_inputs']['report.json'] = sha256_bytes(raw)
        self.payload['source_reports'][0]['sha256'] = sha256_bytes(raw)
        access = pdf._Access(self.root, 'real-pack', 'result',
                             synthetic=False, admission=admission)
        access.verify_source_inputs(self.payload)
        self.assertEqual(access.source_inputs['report.json'], sha256_bytes(raw))
        self.assertFalse(self.calls)

    def test_real_source_report_hash_drift_is_rejected_before_package_reads(self):
        admission, _ = self.authorized_source_package()
        report = self.root / 'report.json'
        report.write_bytes(report.read_bytes() + b' ')
        with patch.object(pdf, '_read_file', wraps=pdf._read_file) as read:
            with self.assertRaisesRegex(ContractError, 'source_input_changed'):
                self.real_convert(admission)
            self.assertFalse(any(path.args[0].is_relative_to(self.root / 'real-pack')
                                 for path in read.call_args_list))
        self.assertFalse(self.calls)

    def test_real_report_references_cannot_expand_source_inventory(self):
        from evals.test_standard_sources import consumption_package
        source, _ = consumption_package(self.root)
        report = self.root / 'report.json'
        value = json.loads(report.read_bytes())
        value['path'] = 'unlisted.txt'
        (self.root / 'unlisted.txt').write_bytes((self.root / 'original.txt').read_bytes())
        report.write_bytes(canonical_bytes(value))
        # 同步显式报告权限仍不准从报告里的原件路径增加权限。
        sources = {name: sha256_bytes((self.root / name).read_bytes())
                   for name in ('report.json', 'original.txt')}
        self.payload['source_reports'] = source['source_reports']
        self.payload['source_reports'][0]['sha256'] = sources['report.json']
        self.payload['source_bindings'] = [dict(source['source_bindings'][0],
            target_id='CL1', version=self.payload['version'])]
        updated = self.authorized_package(source_inputs=sources)
        with patch.object(pdf, '_read_file', wraps=pdf._read_file) as read:
            with self.assertRaisesRegex(ContractError, 'source_input_not_admitted'):
                self.real_convert(updated)
            self.assertNotIn(self.root / 'unlisted.txt', [call.args[0] for call in read.call_args_list])
        self.assertFalse(self.calls)

    def test_real_source_byte_identity_and_links_rechecked_after_tool(self):
        admission, _ = self.authorized_source_package()
        path = self.root / 'original.txt'
        def change(name, arguments, process):
            if name == 'soffice':
                path.write_bytes(path.read_bytes() + b' changed')
        self.effect = change
        with self.assertRaisesRegex(ContractError, 'source_input_changed|path_changed'):
            self.real_convert(admission)
        self.assertEqual(len(self.calls), 1)
        self.no_manifest()

    def test_real_source_same_byte_replacement_and_hardlink_are_rejected(self):
        admission, _ = self.authorized_source_package()
        path = self.root / 'original.txt'
        def replace(name, arguments, process):
            if name == 'soffice':
                replacement = self.root / 'replacement.txt'
                replacement.write_bytes(path.read_bytes())
                os.replace(replacement, path)
        self.effect = replace
        with self.assertRaisesRegex(ContractError, 'path_changed'):
            self.real_convert(admission)
        self.no_manifest()
        alias = self.root / 'alias.txt'
        os.link(path, alias)
        with self.assertRaisesRegex(ContractError, 'alias_unsupported'):
            pdf._Access(self.root, 'real-pack', 'other-result', synthetic=False, admission={
                **admission, 'output': 'other-result'})

    def test_real_source_reparse_is_rejected_before_reading_original(self):
        admission, _ = self.authorized_source_package()
        path = self.root / 'original.txt'
        original = Path.lstat
        def reparse(value):
            result = original(value)
            if value == path:
                return SimpleNamespace(st_mode=result.st_mode, st_nlink=1,
                                       st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', reparse), patch.object(pdf, '_read_file') as read:
            with self.assertRaisesRegex(ContractError, 'link_unsupported'):
                self.real_convert(admission)
            read.assert_not_called()
        self.assertFalse(self.calls)

    def test_real_source_policy_cannot_change_during_conversion(self):
        admission, _ = self.authorized_source_package()
        def change(name, arguments, process):
            if name == 'soffice':
                admission['source_inputs'].clear()
        self.effect = change
        with self.assertRaisesRegex(ContractError, 'admission_changed'):
            self.real_convert(admission)
        self.assertEqual(len(self.calls), 1)
        self.no_manifest()

    def test_real_directory_admission_keeps_mode_sensitivity_and_purpose(self):
        admission = self.authorized_package('public')
        report = self.real_convert(admission)
        self.assertEqual(report['mode'], 'authorized_case')
        self.assertEqual(report['sensitivity'], 'public')
        self.assertEqual(report['purpose'], admission['purpose'])
        self.assertEqual(report['admission']['inputs'], admission['inputs'])
        self.assertEqual(report['source_manifest_sha256'], admission['manifest_sha256'])

    def test_real_public_requires_all_six_environment_paths_before_reads(self):
        admission = self.authorized_package('public')
        admission['environment']['data_paths'].pop()
        with patch.object(pdf, '_read_file', wraps=pdf._read_file) as read:
            with self.assertRaisesRegex(ContractError, 'data_path_inventory_incomplete'):
                self.real_convert(admission)
            read.assert_not_called()
        self.assertFalse(self.calls)

    def test_real_each_permission_is_required_before_material_reads(self):
        admission = self.authorized_package()
        for action in ('local_read', 'local_process', 'copy', 'local_write'):
            denied = copy.deepcopy(admission)
            denied['permissions'] = [row for row in denied['permissions'] if row['action'] != action]
            with self.subTest(action=action), patch.object(pdf, '_read_file', wraps=pdf._read_file) as read:
                with self.assertRaisesRegex(ContractError, 'permission_not_proven'):
                    self.real_convert(denied)
                read.assert_not_called()
        self.assertFalse(self.calls)

    def test_real_complete_member_binding_includes_manifest(self):
        admission = self.authorized_package()
        for name in ('manifest.json', 'internal/input.json', 'body/standard.docx'):
            denied = copy.deepcopy(admission)
            denied['inputs'].pop(name)
            with self.subTest(name=name), self.assertRaisesRegex(ContractError, 'admission_inputs'):
                self.real_convert(denied)
        self.assertFalse(self.calls)

    def test_real_manifest_and_json_bytes_are_bound_before_parsing(self):
        admission = self.authorized_package()
        path = self.root / 'real-pack/internal/input.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ContractError, 'input_changed'):
            self.real_convert(admission)
        self.assertFalse(self.calls)

    def test_real_tool_boundary_rechecks_expiry(self):
        admission = self.authorized_package()
        def expire(name, arguments, process):
            if name == 'soffice':
                for row in admission['permissions']:
                    row['valid_until'] = '2000-01-01T00:00:00+00:00'
        self.effect = expire
        with self.assertRaisesRegex(ContractError, 'permission_not_proven'):
            self.real_convert(admission)
        self.assertEqual(len(self.calls), 1)
        self.no_manifest()

    def test_real_member_changed_after_first_tool_stops_next_tool(self):
        admission = self.authorized_package()
        def change(name, arguments, process):
            if name == 'soffice':
                path = self.root / 'real-pack/internal/reference-list.json'
                path.write_bytes(path.read_bytes() + b' ')
        self.effect = change
        with self.assertRaisesRegex(ContractError, 'input_changed'):
            self.real_convert(admission)
        self.assertEqual(len(self.calls), 1)
        self.no_manifest()

    def test_real_identity_replacement_even_same_bytes_is_rejected(self):
        admission = self.authorized_package()
        def replace(name, arguments, process):
            if name == 'soffice':
                path = self.root / 'real-pack/internal/reference-list.json'
                replacement = path.with_suffix('.replacement')
                replacement.write_bytes(path.read_bytes())
                os.replace(replacement, path)
        self.effect = replace
        with self.assertRaisesRegex(ContractError, 'input_changed|path_changed'):
            self.real_convert(admission)
        self.assertEqual(len(self.calls), 1)
        self.no_manifest()

    def test_real_additional_member_or_reparse_change_stops_before_read(self):
        admission = self.authorized_package()
        path = self.root / 'real-pack/internal/source-trace.json'
        original = Path.lstat
        def reparse(value):
            result = original(value)
            if value == path:
                return SimpleNamespace(st_mode=result.st_mode, st_nlink=1,
                                       st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', reparse), patch.object(pdf, '_read_file') as read:
            with self.assertRaisesRegex(ContractError, 'link_unsupported'):
                self.real_convert(admission)
            read.assert_not_called()
        (path.parent / 'extra').mkdir()
        with self.assertRaisesRegex(ContractError, 'package_members_changed'):
            self.real_convert(admission)
        self.assertFalse(self.calls)

    def test_real_missing_expired_permission_blocks_final_manifest_write(self):
        admission = self.authorized_package()
        original = pdf._Access.write
        def expire(access, path, raw, **kwargs):
            if path == self.root / 'result/manifest.json':
                for row in admission['permissions']:
                    row['valid_until'] = '2000-01-01T00:00:00+00:00'
            return original(access, path, raw, **kwargs)
        with patch.object(pdf._Access, 'write', expire):
            with self.assertRaisesRegex(ContractError, 'permission_not_proven'):
                self.real_convert(admission)
        self.no_manifest()

    def test_real_directory_root_must_be_independent(self):
        admission = self.authorized_package()
        project = Path(pdf.__file__).absolute().parents[1]
        for root in (project, project.parent, project / 'tools'):
            with self.subTest(root=root), patch.object(pdf, '_read_file') as read:
                denied = {**admission, 'root': str(root)}
                with self.assertRaisesRegex(ContractError, 'case_root_must_be_independent'):
                    pdf.convert(root, 'real-pack', 'result', synthetic=False,
                                admission=denied, tool_paths=self.tools)
                read.assert_not_called()


class StandardPdfTechnicalTextTests(unittest.TestCase):
    def test_technical_counterexamples_preserve_whitespace_case_and_compatibility(self):
        examples = [('A B', 'AB'), ('Ａ', 'A'), ('x = 1', 'x=1'),
                    ('<x a="B C"/>', '<x a="BC"/>'), ('C:/A B/X', 'C:/AB/X'),
                    ('Device_ID', 'device_ID'), ('a\nb', 'ab'), ('a\tb', 'a b')]
        for source, actual in examples:
            with self.subTest(source=source):
                result = pdf.compare_text_blocks(
                    [{'id': 'technical', 'kind': 'code', 'text': source}], actual)
                self.assertFalse(result['matched'])
                self.assertEqual(result['equivalences'], [])

    def test_whitespace_difference_even_with_other_identical_blocks_is_not_covered(self):
        blocks = [{'id': 'one', 'kind': 'code', 'text': 'A B'},
                  {'id': 'two', 'kind': 'code', 'text': 'AB'}]
        self.assertFalse(pdf.compare_text_blocks(blocks, 'AB\nAB')['matched'])
        self.assertTrue(pdf.compare_text_blocks(blocks, 'A B\nAB')['matched'])

    def test_narrative_line_wrapping_is_explicit_and_mapped(self):
        result = pdf.compare_text_blocks(
            [{'id': 'prose', 'kind': 'paragraph', 'text': '合成设备应保存结果。'}],
            '合成设备应\n保存结果。\n\f')
        self.assertTrue(result['matched'])
        self.assertEqual(result['equivalences'][0]['rule'], 'narrative_cjk_line_wrap')
        self.assertEqual(result['equivalences'][0]['block_id'], 'prose')
        self.assertIn('actual_start', result['equivalences'][0])

    def test_undeclared_or_suspected_technical_text_is_conservative(self):
        for block in ({'id': 'unknown', 'kind': 'object', 'text': '设备 结果'},
                      {'id': 'identifier', 'kind': 'paragraph', 'text': 'A B'},
                      {'id': 'xml', 'kind': 'paragraph', 'text': '<x>中 文</x>'}):
            with self.subTest(block=block):
                self.assertFalse(pdf.compare_text_blocks([block], block['text'].replace(' ', ''))['matched'])
        report = pdf.compare_text_blocks([{'id': 'formula', 'kind': 'formula', 'text': 'x+y'}], 'x+y')
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['unsupported_objects'][0]['id'], 'formula')

    def test_raw_nonfield_coverage_no_longer_conflates_technical_strings(self):
        for source, actual in [('A B', 'AB'), ('Ａ', 'A'), ('x = 1', 'x=1')]:
            with self.subTest(source=source), self.assertRaisesRegex(ContractError, 'incomplete'):
                pdf._text_coverage([source], actual, 'technical_coverage_incomplete')


class StandardPdfGeometryTests(unittest.TestCase):
    def page(self, words):
        return dict(page=1, width=600.0, height=840.0, rotation=0, words=words)

    def word(self, text, bbox, *, block=1, line=1):
        return dict(text=text, bbox=bbox, block=block, line=line)

    def test_bbox_xml_parses_words_lines_blocks_and_rejects_entity_declarations(self):
        raw = (b'<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>'
               b'<page width="600" height="840"><flow><block>'
               b'<line xMin="80" yMin="90" xMax="160" yMax="104">'
               b'<word xMin="80" yMin="90" xMax="110" yMax="104">A B</word>'
               b'</line></block></flow></page></doc></body></html>')
        pages = pdf.parse_bbox_layout(raw)
        self.assertEqual(pages[0]['words'][0]['text'], 'A B')
        self.assertEqual(pages[0]['words'][0]['bbox'], [80.0, 90.0, 110.0, 104.0])
        for dangerous in (b'<!DOCTYPE x [<!ENTITY secret "expanded">]><x>&secret;</x>',
                          raw.replace(b'xMin="80"', b'xMin="NaN"')):
            with self.subTest(raw=dangerous), self.assertRaisesRegex(ContractError, 'bbox'):
                pdf.parse_bbox_layout(dangerous)

    def test_margins_overlap_and_read_order_have_page_and_screenshot_coordinates(self):
        words = [self.word('outside', [10, 90, 50, 105]),
                 self.word('first', [90, 130, 150, 150], line=2),
                 self.word('overlap', [100, 135, 160, 152], line=3),
                 self.word('backwards', [90, 100, 150, 115], line=4)]
        result = pdf.check_geometry([self.page(words)], {'margin_twips': 1440},
                                    screenshots=[{'page': 1, 'path': 'page.png', 'width': 1000, 'height': 1400}])
        self.assertEqual({row['rule'] for row in result['diagnostics']},
                         {'outside_permitted_area', 'text_overlap', 'reading_order_regression'})
        for row in result['diagnostics']:
            self.assertEqual(row['page'], 1)
            self.assertEqual(row['screenshot']['path'], 'page.png')
            self.assertEqual(len(row['bbox']), 4)
            self.assertEqual(len(row['screenshot']['bbox_pixels']), 4)
        self.assertEqual(result['visual_review'], 'not_performed')
        self.assertEqual(result['coverage']['image_text'], 'not_checked')

    def test_only_proven_next_table_cell_allows_column_reading_order(self):
        words = [self.word('wrapped', [80, 120, 100, 134], line=2),
                 self.word('next cell', [120, 90, 160, 104], block=2)]
        result = pdf.check_geometry([self.page(words)], {'margin_twips': 1440})
        self.assertEqual(result['diagnostics'][0]['rule'], 'reading_order_regression')
        words[0]['table_cell'] = {'table': 1, 'row': 0, 'column': 0}
        words[1]['table_cell'] = {'table': 1, 'row': 0, 'column': 1}
        self.assertFalse(pdf.check_geometry([self.page(words)], {'margin_twips': 1440})['diagnostics'])
        words[1]['table_cell']['row'] = 1
        self.assertEqual(pdf.check_geometry([self.page(words)], {'margin_twips': 1440})[
            'diagnostics'][0]['rule'], 'reading_order_regression')

    def test_v2_profile_footer_distances_supply_permitted_areas(self):
        profile = documents.document_profile('dyz-standard-internal-v2')
        page = self.page([self.word('header', [90, 30, 160, 45]),
                          self.word('body', [90, 90, 150, 106], line=2),
                          self.word('1', [290, 796, 300, 808], block=2)])
        result = pdf.check_geometry([page], profile)
        self.assertFalse(result['diagnostics'])
        self.assertEqual({row['kind'] for row in result['pages'][0]['permitted_areas']},
                         {'body', 'header', 'footer'})

    def test_allowed_footer_area_is_profile_bound_and_unknown_rotation_partial(self):
        page = self.page([self.word('1', [280, 800, 290, 812])])
        profile = {'margin_twips': 1440,
                   'geometry': {'footer_areas': [[72, 780, 528, 830]]}}
        allowed = pdf.check_geometry([page], profile)
        self.assertFalse(allowed['diagnostics'])
        rejected = pdf.check_geometry([page], {'margin_twips': 1440})
        self.assertEqual(rejected['diagnostics'][0]['rule'], 'outside_permitted_area')
        page['rotation'] = 90
        result = pdf.check_geometry([page], profile)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('nonzero_page_rotation', result['unsupported_objects'])


if __name__ == '__main__':
    unittest.main()
