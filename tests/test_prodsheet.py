"""Pagination regression tests use real PDF word coordinates."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from label_parser.prodsheet import read_prodsheet


class ProductionPaginationTest(unittest.TestCase):
    def parse(self, pages, ocr=False):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'production.pdf'
            ocr_pages = []
            count = sum(bool(values[2]) for entries in pages for _, values in entries)
            quantity = sum(int(values[5]) for entries in pages for _, values in entries if values[5].isdigit())
            with fitz.open() as doc:
                for entries in pages:
                    page = doc.new_page(width=750, height=500)
                    for x, value in [(30, 'Article'), (170, 'Size'), (230, 'TXT1'),
                                     (370, 'TXT2'), (540, 'Barcode'), (660, 'Quantity')]:
                        page.insert_text((x, 50), value, fontsize=9)
                    for y, values in entries:
                        for x, value in zip([30, 170, 230, 370, 540, 660], values):
                            if value:
                                page.insert_text((x, y), value, fontsize=9)
                    page.insert_text((30, 465), f'Items: {count}', fontsize=9)
                    # Unequal footer baselines reproduce OCR vertical jitter.
                    page.insert_text((400, 464), f'Total Order TEST: {quantity}', fontsize=9)
                    if ocr:
                        words = page.get_text('words')
                        ocr_pages.append({
                            'text': [w[4] for w in words],
                            'left': [w[0]*3 for w in words],
                            'top': [w[1]*3 for w in words],
                            'width': [(w[2]-w[0])*3 for w in words],
                            'height': [(w[3]-w[1])*3 for w in words],
                        })
                        pix = page.get_pixmap()
                        page.add_redact_annot(page.rect)
                        page.apply_redactions()
                        page.insert_image(page.rect, pixmap=pix)
                        if ocr == 'partial':
                            page.insert_text((20, 20), 'Scanned document')
                doc.save(path)
            if ocr:
                with patch('label_parser.prodsheet.pytesseract.image_to_data', side_effect=ocr_pages):
                    return read_prodsheet(str(path), lambda _: None)
            return read_prodsheet(str(path), lambda _: None)

    def row(self, model='FBM015-096-02', code='5208133316684', txt2='FBM015-096-02-', qty='119'):
        return ['CARELABEL_2-', '32', model, txt2, code, qty]

    def test_screenshot_split_row_native_and_ocr_coordinates(self):
        for ocr in (False, True):
            with self.subTest(ocr=ocr):
                batch = self.parse([
                    [(420, self.row())],
                    [(75, ['', '', '', 'MD BLUE-32', '', '']),
                     (100, self.row('FBM015-093-03', '5208133316707', 'FBM015-093-03-', '130')),
                     (115, ['', '', '', 'MD BLUE-32', '', ''])],
                ], ocr=ocr)
                self.assertEqual(batch.rows, 2)
                self.assertEqual([r.txt2 for r in batch.details],
                                 ['FBM015-096-02-MD BLUE-32', 'FBM015-093-03-MD BLUE-32'])
                self.assertEqual([r.quantity for r in batch.details], [119, 130])
                self.assertEqual((batch.details[0].page, batch.details[0].row), (1, 1))

    def test_partial_text_layer_still_uses_ocr_for_table(self):
        batch = self.parse([[(80, self.row(txt2='FBM015-096-02-MD BLUE-32'))]], ocr='partial')
        self.assertEqual(len(batch.details), 1)
        self.assertEqual(batch.details[0].quantity, 119)
        self.assertTrue(any('表头不完整' in w for w in batch.warnings))
        self.assertFalse(batch.validation_errors)
        self.assertTrue(any(i.kind == 'ocr_page' for i in batch.review_items))

    def test_footer_baseline_jitter_does_not_duplicate_quantity(self):
        batch = self.parse([[(80, self.row(txt2='FBM015-096-02-MD BLUE-32'))]])
        self.assertEqual(batch.details[0].quantity, 119)
        self.assertFalse(batch.validation_errors)

    def test_touching_txt2_and_barcode_are_separate_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'touching.pdf'
            with fitz.open() as doc:
                page = doc.new_page(width=750, height=500)
                for x, value in [(30, 'Article'), (170, 'Size'), (230, 'TXT1'),
                                 (370, 'TXT2'), (540, 'Barcode'), (660, 'Quantity')]:
                    page.insert_text((x, 50), value, fontsize=9)
                for x, value in [(30, 'CARELABEL_0-5-'), (170, 'M'),
                                 (230, 'FBL015-127-13'), (660, '81')]:
                    page.insert_text((x, 80), value, fontsize=9)
                prefix = 'FBL015-127-13-POP'
                page.insert_text((540-fitz.get_text_length(prefix, fontsize=9), 80),
                                 prefix, fontsize=9)
                page.insert_text((540, 80), '5208133403537', fontsize=9)
                page.insert_text((370, 95), 'PINK-M', fontsize=9)
                self.assertTrue(any(prefix+'5208133403537' == w[4]
                                    for w in page.get_text('words')))
                doc.save(path)
            batch = read_prodsheet(str(path), lambda _: None)
            self.assertFalse(batch.warnings)
            self.assertEqual(len(batch.details), 1)
            self.assertEqual(batch.details[0].txt2, 'FBL015-127-13-POP PINK-M')
            self.assertEqual(batch.details[0].barcode, '5208133403537')
            self.assertEqual(batch.details[0].quantity, 81)

    def test_failed_last_row_does_not_corrupt_previous_row(self):
        batch = self.parse([
            [(80, self.row(txt2='COMPLETE')), (420, self.row(code='invalid'))],
            [(75, ['', '', '', 'MD BLUE-32', '', '']), (100, self.row())],
        ])
        self.assertEqual(batch.details[0].txt2, 'COMPLETE')
        self.assertTrue(any('无法确认归属' in w for w in batch.warnings))

    def test_continuation_only_page(self):
        batch = self.parse([[(420, self.row())],
                            [(75, ['', '', '', 'MD BLUE-32', '', ''])]])
        self.assertEqual(batch.rows, 1)
        self.assertEqual(batch.details[0].txt2, 'FBM015-096-02-MD BLUE-32')

    def test_other_columns_in_leading_fragment_are_not_guessed(self):
        batch = self.parse([[(420, self.row())],
                            [(75, ['OTHER', '', '', 'MD BLUE-32', '', '']),
                             (100, self.row())]])
        self.assertEqual(batch.details[0].txt2, 'FBM015-096-02-')
        self.assertTrue(any('无法确认归属' in w for w in batch.warnings))

    def test_no_continuation_does_not_merge_next_row(self):
        batch = self.parse([[(420, self.row())], [(80, self.row(txt2='NEXT'))]])
        self.assertEqual([r.txt2 for r in batch.details], ['FBM015-096-02-', 'NEXT'])
