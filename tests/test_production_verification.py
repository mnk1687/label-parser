import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import pytesseract

from label_parser.prodsheet import ProductionBatch, ProductionRow, read_prodsheet
from label_parser.production_verification import (
    collect_review_items, normalize_ocr_identifiers, validate_batch, verify_columns,
)
from label_parser.review import ReviewRequired, require_exportable
from label_parser.workflow import discover
from label_parser.composition import export_compositions
from label_parser.categories import export_categories
from types import SimpleNamespace
import test_batch


class VerificationTest(unittest.TestCase):
    def batch(self):
        row = ProductionRow('CARELABEL_2-', '32', 'FBM015-096-02',
                            'FBM015-096-02-MD BLUE-32', '5208133316684', 119, 1, 1)
        return ProductionBatch('test.pdf', [row.txt1], {row.barcode: row.txt1}, 1, details=[row])

    def test_footer_totals_are_not_summed_per_page(self):
        b = self.batch()
        self.assertFalse(validate_batch(b, ['Items: 1\nTotal Order ALT: 119']*3))

    def test_missing_row_and_conflicting_totals_are_review_items(self):
        b = self.batch(); b.rows = 2
        texts = ['Items: 2\nTotal Order ALT: 200', 'Items: 3']
        self.assertFalse(validate_batch(b, texts))
        items = collect_review_items(b, texts)
        self.assertEqual(len(items), 3)
        self.assertEqual({item.kind for item in items}, {'totals', 'missing_rows'})
        b.review_items = items
        with self.assertRaises(ReviewRequired):
            require_exportable(b)
        require_exportable(b, acknowledged=True)

    def test_duplicate_barcode_and_invalid_check_digit_block(self):
        b = self.batch(); b.details *= 2; b.rows = 2
        self.assertTrue(any('重复' in e for e in validate_batch(b, [])))
        b = self.batch(); b.details[0].barcode = '5208133316685'
        self.assertTrue(any('校验位' in e for e in validate_batch(b, [])))

    def test_unfinished_continuation_is_a_review_item(self):
        b = self.batch(); b.details[0].txt2 = 'FBM015-096-02-'
        self.assertFalse(validate_batch(b, []))
        items = collect_review_items(b, [])
        self.assertTrue(any(i.kind == 'txt2_size' and '续行不完整' in i.message for i in items))

    def test_model_glyph_equivalence_does_not_change_color_or_barcode(self):
        self.assertEqual(normalize_ocr_identifiers('FBLO15-096-02-G0LD-32', ['FBM015-096-02']),
                         'FBLO15-096-02-G0LD-32')
        self.assertEqual(normalize_ocr_identifiers('FBMO15-096-02-G0LD-32', ['FBM015-096-02']),
                         'FBM015-096-02-G0LD-32')
        self.assertEqual(normalize_ocr_identifiers('52O8133316684', []), '52O8133316684')

    def verify_numbers(self, observed):
        with fitz.open() as doc:
            p = doc.new_page(width=200, height=200)
            headers = [(20, 20, 60, 30, 'Quantity')]
            words = [(20, 50, 30, 60, '1'), (20, 80, 40, 90, '23')]
            with patch('label_parser.production_verification._read_clip', return_value=observed):
                return verify_columns(p, words, headers, 150, 1, lambda _: None)

    def test_numeric_comparison_preserves_row_boundaries(self):
        checks, errors = self.verify_numbers('12\n3')
        self.assertTrue(errors); self.assertEqual(checks[0]['status'], 'disagreed')
        self.assertFalse(self.verify_numbers('1\n23')[1])

    def test_missing_ocr_is_not_silently_accepted(self):
        with fitz.open() as doc:
            page = doc.new_page()
            with patch('label_parser.production_verification._read_clip',
                       side_effect=pytesseract.TesseractNotFoundError()):
                checks, errors = verify_columns(page, [(20, 50, 30, 60, '1')],
                    [(20, 20, 60, 30, 'Quantity')], 150, 1, lambda _: None)
        self.assertTrue(errors); self.assertEqual(checks[0]['status'], 'unavailable')

    def test_ocr_conflict_becomes_review_item_and_import_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sheet = root/'ProdSheet.pdf'
            fixture = test_batch.BatchTest(); fixture.sheet(sheet)
            fixture.label(root/'FB_MAIN.pdf', test_batch.A, '5208133300829')
            conflict = ([{'page': 1, 'column': 'TXT1', 'status': 'disagreed', 'source': 'PDF',
                          'pdf': 'FBM015-096-02', 'ocr': 'FBM015-09G-02'}], ['OCR conflict'])
            with patch('label_parser.prodsheet.verify_columns', return_value=conflict) as verify:
                b = read_prodsheet(str(sheet), lambda _: None, verify_ocr=True)
                self.assertEqual(b.details[0].barcode, '5208133300829')
                self.assertFalse(b.validation_errors)
                self.assertTrue(any(i.kind == 'ocr_disagreement' for i in b.review_items))
                with self.assertRaises(ReviewRequired):
                    require_exportable(b)
                jobs, issues = discover([str(root)], lambda _: None)
            self.assertFalse(issues)
            self.assertEqual(len(jobs), 1)
            self.assertTrue(any(i.kind == 'ocr_disagreement' for i in jobs[0].batch.review_items))
            self.assertTrue(verify.called)

    def test_ocr_pages_are_review_items_not_hard_errors(self):
        b = self.batch(); b.ocr_pages = [3, 4]
        self.assertFalse(validate_batch(b, []))
        items = collect_review_items(b, [], require_totals=True)
        self.assertTrue(any(i.kind == 'ocr_page' and '第 3、4 页' in i.message for i in items))

    def test_missing_same_row_barcode_is_a_high_risk_review_item(self):
        b = self.batch()
        b.warnings = ['ProdSheet 第 3 页 FBM015-002-05 未找到唯一同行条码；仍可按款号匹配。']
        texts = ['Items: 1\nTotal Order ALT: 119']
        self.assertFalse(validate_batch(b, texts))
        items = collect_review_items(b, texts)
        self.assertTrue(any(i.kind == 'missing_row' and i.severity == 'high' for i in items))

    def test_review_summary_and_confirmation_mention_high_risk(self):
        from label_parser.review import confirmation_text, review_summary
        b = self.batch(); b.ocr_pages = [3]
        b.review_items = collect_review_items(b, [], require_totals=True)
        self.assertIn('待确认', review_summary(b))
        self.assertIn('第 3', review_summary(b))
        text = confirmation_text(b, '导出')
        self.assertIn('高风险', text)
        self.assertIn('是否继续', text)

    def test_mismatch_message_does_not_call_ocr_text_pdf(self):
        with fitz.open() as doc:
            page = doc.new_page(width=200, height=200)
            headers = [(20, 20, 60, 30, 'Quantity')]
            words = [(20, 50, 30, 60, '1')]
            with patch('label_parser.production_verification._read_clip', return_value='9'):
                checks, errors = verify_columns(page, words, headers, 150, 3, lambda _: None,
                                                source_label='整页OCR')
        self.assertTrue(errors)
        self.assertIn('整页OCR/OCR', errors[0])
        self.assertNotIn('PDF/OCR', errors[0])

    def test_invalid_batch_cannot_write_either_export(self):
        b = self.batch(); b.validation_errors = ['bad totals']
        job = SimpleNamespace(batch=b)
        with tempfile.TemporaryDirectory() as tmp:
            for exporter in (export_compositions, export_categories):
                target = Path(tmp)/exporter.__name__
                with self.assertRaisesRegex(ValueError, 'bad totals'):
                    exporter(job, target, {'5208133316684'})
                self.assertFalse(target.exists())
