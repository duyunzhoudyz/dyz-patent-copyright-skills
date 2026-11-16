"""源行边界和保真验证；分页参数是合成工程值，不代替当前登记规则。"""
import math
import unittest

from tools import software, software_delivery as delivery
from evals import test_software_authoring as authoring


class SourceBoundaryTests(unittest.TestCase):
    setUp = authoring.SoftwareAuthoringTests.setUp

    def test_zero_and_head_tail_thresholds_preserve_actual_lines(self):
        for count in (0, 49, 50, 51, 1500, 1501, 2999, 3000, 3001):
            with self.subTest(lines=count):
                source = ''.join(f'x_{index} = {index}\n' for index in range(count))
                (self.root / 'counter.py').write_text(source, encoding='utf-8')
                self.payload['pagination'] = {'selection': 'all', 'lines_per_page': 50,
                                              'wrap_columns': 78, 'basis': 'synthetic-boundary'}
                preparation = software.prepare(self.payload)['artifacts']
                self.assertEqual(preparation['source']['total_source_lines'], count)
                self.assertEqual(preparation['source']['selected_source_lines'], count)
                pages, mapping = delivery.source_pages(preparation['source']['selected_lines'])
                self.assertEqual(len(pages), math.ceil(count / 50))
                selection = delivery.select_pages(pages, 'head_tail')
                wanted = list(range(len(pages))) if len(pages) <= 60 else list(range(30)) + list(range(len(pages) - 30, len(pages)))
                self.assertEqual(selection, wanted)
                restored = [block['text'] for page in pages for block in page]
                self.assertEqual(restored, source.splitlines())
                self.assertEqual(len(mapping['rows']), count)

    def test_tabs_unicode_blank_url_and_literals_reassemble_exactly(self):
        lines = ['\tvalue = "<tag> https://example.invalid/a//b"', '',
                 '中文全角' * 50, '    trailing_space = 1   ', '# comment', '\t' * 19 + 'end']
        rows = [{'file_id': 'source', 'source_line': index, 'text': text}
                for index, text in enumerate(lines, 1)]
        pages, mapping = delivery.source_pages(rows)
        blocks = [block for page in pages for block in page]
        for index, original in enumerate(lines, 1):
            restored = ''.join(block['text'] for block, location in zip(blocks, mapping['rows'])
                               if location['source_line'] == index)
            self.assertEqual(restored, original)


if __name__ == '__main__':
    unittest.main()
