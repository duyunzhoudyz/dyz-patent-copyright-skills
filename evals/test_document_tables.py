import copy
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from tools import documents
from tools.core import ContractError, sha256_bytes


class DocumentTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = '# 内部规范\n| 条款 | 要求 |\n| --- | --- |\n| RIV-01 | 应≤2.5kg，维护时除外 |\n| RIV-02 | 不应自动排序 |\n'.encode()
        (self.root / 'source.md').write_bytes(raw)
        self.spec = dict(sensitivity='synthetic', document_id='River', version='1', business='standard',
            sources=[dict(id='S', path='source.md', sha256=sha256_bytes(raw))],
            blocks=[dict(id='Title', source_id='S', start_line=1, end_line=1, kind='heading1', audience='body'),
                    dict(id='RIV_Table', source_id='S', start_line=2, end_line=5, kind='table', audience='body')])

    def test_native_cells_stable_bookmark_repeated_header_and_no_row_split(self):
        result = documents.build(self.root, self.spec, 'pack', synthetic=True)
        self.assertEqual(result['checks']['tables'], 1)
        with zipfile.ZipFile(self.root / 'pack/body/document.docx') as z:
            xml = ET.fromstring(z.read('word/document.xml'))
        ns = {'w': documents.W}
        self.assertEqual(xml.find('.//w:tbl/w:tr/w:trPr/w:tblHeader', ns).tag, '{'+documents.W+'}tblHeader')
        self.assertEqual(len(xml.findall('.//w:tbl/w:tr/w:trPr/w:cantSplit', ns)), 3)
        self.assertIn('RIV_Table', [e.attrib['{'+documents.W+'}name'] for e in xml.findall('.//w:bookmarkStart',ns)])
        texts = [e.text for e in xml.findall('.//w:tbl//w:t',ns)]
        self.assertIn('应≤2.5kg，维护时除外', texts)
        self.assertIn('不应自动排序', texts)
        self.assertEqual(documents.verify(self.root,self.spec,'pack',synthetic=True)['status'],'needs_review')

    def test_ambiguous_or_ragged_tables_rejected(self):
        for text in ['| A | B |\n| --- | --- |\n| one |', '| A |\n| ??? |\n| one |', '| A | B |\n| --- | --- |\n| a\\|b | c |']:
            with self.subTest(text=text), self.assertRaises(ContractError):
                documents._table_cells(text)

    def test_cell_semantics_and_header_faults_rejected(self):
        blocks, figures = documents.resolve_document(self.root,self.spec)
        raw=documents.make_docx(blocks,figures)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            original={n:z.read(n) for n in z.namelist()}
        for before,after in [('不应','应'),('2.5','25'),('，维护时除外',''),('<w:tblHeader />','')]:
            with self.subTest(before=before):
                parts=dict(original);changed=parts['word/document.xml'].replace(before.encode(),after.encode())
                self.assertNotEqual(parts['word/document.xml'],changed)
                parts['word/document.xml']=changed;stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w') as z:
                    for n,data in parts.items():z.writestr(n,data)
                with self.assertRaises(ContractError):documents.inspect_generated_docx(stream.getvalue(),blocks,figures)

    def test_table_source_version_change_requires_new_package(self):
        documents.build(self.root,self.spec,'pack',synthetic=True)
        source=self.root/'source.md';source.write_bytes(source.read_bytes().replace(b'RIV-02',b'RIV-03'))
        with self.assertRaisesRegex(ContractError,'source_changed'):
            documents.verify(self.root,self.spec,'pack',synthetic=True)
        self.spec['sources'][0]['sha256']=sha256_bytes(source.read_bytes())
        with self.assertRaisesRegex(ContractError,'input_binding_changed'):
            documents.verify(self.root,self.spec,'pack',synthetic=True)


if __name__ == '__main__':
    unittest.main()
