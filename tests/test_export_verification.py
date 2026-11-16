import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import fitz
from label_parser.categories import export_categories, ordered_items
from label_parser.composition import read_excel, write_excel
from label_parser.export_verification import verify_excel, verify_export
from label_parser.review import ReviewItem, ReviewRequired
import test_categories


class ExportVerificationTest(unittest.TestCase):
    def fixture(self, root):
        job, rows = test_categories.CategoryTest().fixture(root, ('MAIN', 'CARE'))
        job.batch.source_totals = {'items': 7, 'quantity': 7}
        return job, rows

    def test_full_and_partial_reconcile_to_original_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job, rows = self.fixture(root)
            for name, chosen in [('all', {r.barcode for r in rows}), ('partial', {rows[0].barcode})]:
                export_categories(job, root/name, chosen, lambda _: None)
                report = json.loads((root/name/'生成核对报告.json').read_text(encoding='utf-8'))
                self.assertEqual(report['status'], 'passed')
                self.assertEqual(report['source_items'], 7)
                self.assertEqual(report['source_quantity'], 7)
                self.assertEqual(report['export_items'], len(chosen))
                self.assertEqual(report['export_quantity'], len(chosen))
                self.assertEqual(report['unselected_items'], 7-len(chosen))
                self.assertEqual(report['baseline'], 'ProdSheet页脚')

    def test_same_count_and_quantity_cannot_hide_duplicate_and_omission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job, rows = self.fixture(root)
            altered = rows[:-1]+[rows[0]]
            excel = write_excel(altered, job.batch.source, root/'bad.xlsx')
            with self.assertRaisesRegex(ValueError, '遗漏、重复'):
                verify_excel(job.batch, excel)

    def test_source_footer_is_independent_of_generated_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job, rows = self.fixture(root)
            excel = write_excel(rows, job.batch.source, root/'rows.xlsx')
            job.batch.source_totals['quantity'] = 8
            with self.assertRaisesRegex(ValueError, '页脚不一致'):
                verify_excel(job.batch, excel)

    def test_acknowledged_footer_mismatch_exports_with_recorded_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job, rows = self.fixture(root)
            job.batch.review_items = [ReviewItem('missing_rows', 'high', '少 1 条')]
            job.batch.source_totals = {'items': 8, 'quantity': 7}
            excel = write_excel(rows, job.batch.source, root/'rows.xlsx')
            with self.assertRaises(ReviewRequired):
                verify_excel(job.batch, excel)
            job.batch.review_acknowledged = True
            selected, report = verify_excel(job.batch, excel)
            self.assertEqual(len(selected), len(rows))
            self.assertFalse(report['footer_matched'])
            self.assertTrue(report['review_acknowledged'])
            self.assertEqual(report['source_items'], 8)
            self.assertEqual(report['excel_items'], len(rows))
            self.assertEqual(report['review_items'][0]['kind'], 'missing_rows')

    def test_unknown_selected_barcode_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job, rows = self.fixture(root)
            excel = write_excel(rows, job.batch.source, root/'rows.xlsx')
            with self.assertRaisesRegex(ValueError, '不存在'):
                verify_excel(job.batch, excel, {rows[0].barcode, '0000000000000'})

    def test_blank_pdf_with_correct_pages_and_bookmarks_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job, rows = self.fixture(root); codes = {r.barcode for r in rows}
            excel, paths = export_categories(job, root/'out', codes, lambda _: None)
            with fitz.open(paths[0]) as doc:
                toc = doc.get_toc(); rect = doc[0].rect; pages = len(doc)
            with fitz.open() as blank:
                for _ in range(pages): blank.new_page(width=rect.width, height=rect.height)
                blank.set_toc(toc); blank.save(root/'blank.pdf')
            (root/'blank.pdf').replace(paths[0])
            items = ordered_items(job, read_excel(excel))
            with self.assertRaisesRegex(ValueError, '遗漏、重复或内容变化'):
                verify_export(job, excel, codes, items, paths, 'categories', lambda _: None)
            report = json.loads((root/'out'/'生成核对报告.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'failed')
