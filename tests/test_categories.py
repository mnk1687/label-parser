import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import fitz
from label_parser.core import Match,ScanResult
from label_parser.prodsheet import ProductionRow
from label_parser.categories import KINDS,ordered_items,category_preview,export_categories
from label_parser.composition import read_excel

class CategoryTest(unittest.TestCase):
    def fixture(self,root):
        rows=[ProductionRow('CARELABEL_2-',str(size),'FBM015-099-03',f'FBM015-099-03-BLUE-{size}',str(5208133300800+i),1) for i,size in enumerate([40,28,32,30,36,34,38])]
        sources=[];matches=[]
        for kind in KINDS:
            path=root/f'FB_{kind}.pdf';sources.append(str(path))
            with fitz.open() as doc:
                for n,row in enumerate(rows):
                    p=doc.new_page(width=220,height=190)
                    p.insert_text((5,15),row.barcode);p.insert_text((5,45),kind)
                    p.draw_rect(fitz.Rect(2,22,215,185),color=(0,1,1))
                    matches.append(Match(str(path),n+1,[0,0,220,190],'text',row.barcode,model=row.txt1,barcode=row.barcode))
                doc.save(path)
        job=SimpleNamespace(batch=SimpleNamespace(details=rows,source='ProdSheet.pdf'),sources=sources,files_selected=set(sources),result=ScanResult('',matches,[]))
        return job,rows

    def test_six_up_vector_order_and_last_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job,rows=self.fixture(root)
            before={Path(p):Path(p).read_bytes() for p in job.sources}
            def custom_excel(details,source,target):
                from openpyxl import Workbook
                wb=Workbook();s=wb.active;s.append(['Article','Size','TXT1','TXT2','Barcode','Quantity'])
                for r in rows:s.append([r.article,r.size,r.txt1,r.txt2,r.barcode,r.quantity])
                wb.save(target);wb.close();return target
            with patch('label_parser.categories.write_excel',side_effect=custom_excel):
                excel,paths=export_categories(job,root/'out',{r.barcode for r in rows},lambda _:None)
            self.assertEqual([p.name for p in paths],[k.lower()+'排序PDF.pdf' for k in KINDS])
            self.assertEqual(len(list((root/'out').glob('*.pdf'))),5)
            for kind,path in zip(KINDS,paths):
                with fitz.open(path) as doc:
                    self.assertEqual(len(doc),2)
                    self.assertEqual([x[1] for x in doc.get_toc()],[r.txt2 for r in rows])
                    self.assertEqual([x[2] for x in doc.get_toc()],[1]*6+[2])
                    for n,page in enumerate(doc):
                        words=[w for w in page.get_text('words') if w[4].isdigit() and len(w[4])==13]
                        words.sort(key=lambda w:(round(w[1]/10),w[0]))
                        self.assertEqual([w[4] for w in words],[r.barcode for r in rows[n*6:n*6+6]])
                        self.assertEqual(len(page.get_drawings()),len(words));self.assertFalse(page.get_images())
                        for drawing in page.get_drawings():self.assertAlmostEqual(drawing['rect'].width,213,places=3)
                        self.assertEqual(page.get_text().count(kind),len(words))
            for p,data in before.items():self.assertEqual(p.read_bytes(),data)
            with self.assertRaises(FileExistsError):export_categories(job,root/'out',{rows[0].barcode})
            with category_preview(ordered_items(job,rows[:6]),'MAIN') as preview,fitz.open(paths[3]) as exported:
                self.assertEqual(preview[0].get_pixmap().samples,exported[0].get_pixmap().samples)

    def test_selection_and_incomplete_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job,rows=self.fixture(root);chosen={rows[0].barcode,rows[2].barcode}
            excel,paths=export_categories(job,root/'subset',chosen,lambda _:None)
            expected=[r.txt2 for r in read_excel(excel) if r.barcode in chosen]
            with fitz.open(paths[0]) as doc:
                self.assertEqual(len(doc),1);self.assertEqual([x[1] for x in doc.get_toc()],expected)
            job.result.matches.pop()
            with self.assertRaises(ValueError):export_categories(job,root/'missing',{r.barcode for r in rows},lambda _:None)
            self.assertEqual(list((root/'missing').glob('*.pdf')),[])
