import tempfile
import unittest
from pathlib import Path
import fitz
from label_parser.core import contains, scan, export, frames

class ExtractionTest(unittest.TestCase):
    def fixture(self, path):
        doc=fitz.open()
        for page_number in range(3):
            p=doc.new_page(width=600,height=500)
            for col, code in enumerate(['FBL015-166-03','FBL015-166-030'] if page_number != 2 else ['FBL015-166-03','FBL015-166-03']):
                x=30+col*280
                p.draw_rect(fitz.Rect(x,40,x+240,150),color=(0,1,1))
                p.draw_rect(fitz.Rect(x,150,x+240,260),color=(0,1,1))
                p.insert_text((x,35),'5208133300829',fontsize=10,color=(1,0,0))
                p.insert_text((x+20,85),code,fontsize=12)
                p.insert_text((x+20,190),'MADE IN CHINA',fontsize=12)
        doc.save(path);doc.close()

    def test_match_boundaries(self):
        self.assertTrue(contains('FBL015-166-03\nBLACK/26','FBL015-166-03'))
        self.assertTrue(contains('fbl015 – 166 – 03','FBL015-166-03'))
        for text in ['FBL015-166-030','XFBL015-166-03','FBL015-166-03-X','FBL015-164-03']:
            self.assertFalse(contains(text,'FBL015-166-03'))

    def test_all_pages_multiple_labels_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'source.pdf';self.fixture(src)
            result=scan([str(src)],'FBL015-166-03',lambda _:None)
            self.assertEqual(result.pages,3)
            self.assertEqual([m.page for m in result.matches],[1,2,3,3])
            self.assertEqual(result.warnings,[])
            self.assertTrue(all('MADE IN CHINA' in m.text and '5208133300829' in m.text for m in result.matches))
            with self.assertRaises(ValueError):export(result,src)
            result.matches[0].selected=False
            out=Path(tmp)/'result.pdf';record=export(result,out,dpi=120)
            self.assertEqual(record['count'],3)
            with fitz.open(out) as doc:self.assertEqual(len(doc),3)
            with self.assertRaises(FileExistsError):export(result,out)
            missing=scan([str(src)],'MISSING-99',lambda _:None)
            self.assertFalse(missing.matches)
            with self.assertRaises(ValueError):export(missing,Path(tmp)/'empty.pdf')
            self.assertFalse((Path(tmp)/'empty.pdf').exists())

    def test_unframed_match_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unframed.pdf'
            with fitz.open() as doc:
                p=doc.new_page();p.insert_text((50,50),'FBL015-166-03');doc.save(path)
            result=scan([str(path)],'FBL015-166-03',lambda _:None)
            self.assertEqual(len(result.matches),0)
            self.assertEqual(len(result.warnings),1)

if __name__=='__main__':unittest.main()
