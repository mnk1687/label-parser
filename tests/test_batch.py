import tempfile
import unittest
from pathlib import Path
import fitz
from label_parser.prodsheet import read_prodsheet
from label_parser.core import scan_batch,export

A='FBL015-166-03';B='FBL015-164-03'
class BatchTest(unittest.TestCase):
    def sheet(self,path):
        with fitz.open() as d:
            for i in range(2):
                p=d.new_page(width=600,height=500)
                for x,t in [(30,'Size'),(100,'TXT1'),(240,'TXT2'),(400,'Barcode'),(510,'Quantity')]:p.insert_text((x,50),t,fontsize=9)
                for row,(model,code) in enumerate([(A,'5208133300829'),(B,'5208133300836')]):
                    y=80+row*30
                    for x,t in [(30,'26'),(100,model),(240,'WRONG999-888-77'),(400,code),(510,'999')]:p.insert_text((x,y),t,fontsize=9)
            d.save(path)
    def label(self,path,model,barcode):
        with fitz.open() as d:
            p=d.new_page(width=300,height=300)
            p.draw_rect(fitz.Rect(30,40,270,250),color=(0,1,1))
            p.insert_text((30,35),barcode,fontsize=10)
            if model:p.insert_text((50,90),model,fontsize=12)
            p.insert_text((50,130),'WASH AT 30 C',fontsize=12)
            d.save(path)
    def test_txt1_only_dedup_and_barcode_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sheet=root/'sheet.pdf';self.sheet(sheet)
            batch=read_prodsheet(str(sheet),lambda _:None)
            self.assertEqual(batch.models,[A,B]);self.assertEqual(batch.rows,4)
            self.assertEqual(batch.barcode_models,{'5208133300829':A,'5208133300836':B})
            self.assertFalse(batch.warnings)
            p=root/'main.pdf';q=root/'care.pdf'
            self.label(p,A,'5208133300829');self.label(q,'','5208133300836')
            result=scan_batch([str(q),str(p),str(p),str(sheet)],batch.models,batch.barcode_models,lambda _:None,[str(sheet)])
            self.assertEqual(result.files,2);self.assertEqual(result.pages,2)
            self.assertEqual([m.model for m in result.matches],[A,B])
            self.assertEqual(result.matches[1].method,'pdf-text-barcode')
            self.assertFalse(result.warnings)
            out=root/'output.pdf';export(result,out,dpi=100)
            self.assertFalse(out.with_suffix('.json').exists())
            with fitz.open(out) as doc:
                self.assertEqual(len(doc),2);self.assertEqual([t[1] for t in doc.get_toc()],[A,B])
    def test_conflicting_model_and_barcode_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'conflict.pdf';self.label(p,A,'5208133300836')
            r=scan_batch([str(p)],[A,B],{'5208133300836':B},lambda _:None)
            self.assertFalse(r.matches);self.assertTrue(any('冲突' in w for w in r.warnings))
    def test_missing_txt1_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'wrong.pdf';self.label(p,A,'5208133300829')
            with self.assertRaisesRegex(ValueError,'TXT1'):read_prodsheet(str(p),lambda _:None)

if __name__=='__main__':unittest.main()
