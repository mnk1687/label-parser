import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import pytesseract

from label_parser.prodsheet import ProductionBatch, ProductionRow, read_prodsheet
from label_parser.production_verification import (
    normalize_ocr_identifiers, require_verified, validate_batch, verify_columns,
)
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

    def test_missing_row_wrong_quantity_and_conflicting_totals_block(self):
        b = self.batch(); b.rows = 2
        errors = validate_batch(b, ['Items: 2\nTotal Order ALT: 200', 'Items: 3'])
        self.assertEqual(len(errors), 3)
        b.validation_errors = errors
        with self.assertRaisesRegex(ValueError, '停止导入/导出'):
            require_verified(b)

    def test_duplicate_barcode_and_invalid_check_digit_block(self):
        b = self.batch(); b.details *= 2; b.rows = 2
        self.assertTrue(any('重复' in e for e in validate_batch(b, [])))
        b = self.batch(); b.details[0].barcode = '5208133316685'
        self.assertTrue(any('校验位' in e for e in validate_batch(b, [])))

    def test_unfinished_continuation_blocks(self):
        b = self.batch(); b.details[0].txt2 = 'FBM015-096-02-'
        self.assertTrue(any('续行不完整' in e for e in validate_batch(b, [])))

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

    def test_ocr_conflict_preserves_pdf_and_blocks_app_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); sheet = root/'ProdSheet.pdf'
            fixture = test_batch.BatchTest(); fixture.sheet(sheet)
            fixture.label(root/'FB_MAIN.pdf', test_batch.A, '5208133300829')
            with patch('label_parser.prodsheet.verify_columns',
                       return_value=([{'status': 'disagreed'}], ['OCR conflict'])) as verify:
                b = read_prodsheet(str(sheet), lambda _: None, verify_ocr=True)
                self.assertEqual(b.details[0].barcode, '5208133300829')
                jobs, issues = discover([str(root)], lambda _: None)
                self.assertFalse(jobs); self.assertIn('OCR conflict', issues[0])
                self.assertTrue(verify.called)

    def test_invalid_batch_cannot_write_either_export(self):
        b = self.batch(); b.validation_errors = ['bad totals']
        job = SimpleNamespace(batch=b)
        with tempfile.TemporaryDirectory() as tmp:
            for exporter in (export_compositions, export_categories):
                target = Path(tmp)/exporter.__name__
                with self.assertRaisesRegex(ValueError, 'bad totals'):
                    exporter(job, target, {'5208133316684'})
                self.assertFalse(target.exists())
