import tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
import fitz
from label_parser.workflow import discover,recognize,build_plan,export_plan,explain
from label_parser.core import scan_batch
import test_batch
from test_batch import A,B

class WorkflowTest(unittest.TestCase):
    def setup_batch(self,root,name):
        parent=root/name;parent.mkdir()
        f=test_batch.BatchTest();f.sheet(parent/'ProdSheet_123.pdf')
        f.label(parent/'FB_MAIN.pdf',A,'5208133300829')
        f.label(parent/'FB_CARE.pdf','', '5208133300829')
        return parent

    def test_discovery_isolation_selection_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.setup_batch(root,'batch-a');self.setup_batch(root,'batch-b')
            jobs,issues=discover([str(root)],lambda _:None)
            self.assertFalse(issues);self.assertEqual(len(jobs),2)
            self.assertFalse(build_plan(jobs))
            for job in jobs:
                recognize(job,lambda _:None)
                self.assertEqual(len(job.result.matches),2)
                job.models_selected={A}
                job.files_selected={p for p in job.sources if 'CARE' in p}
            plan=build_plan(jobs)
            self.assertEqual(len(plan),2)
            self.assertEqual(len({p.name for p in plan}),2)
            self.assertTrue(all(len(p.matches)==1 for p in plan))
            trace=explain(jobs[0],jobs[0].result.matches[-1])
            for text in ['FB_MAIN.pdf','FB_CARE.pdf','5208133300829','ProdSheet_123.pdf','第 1 页第 1 条']:self.assertIn(text,trace)
            paths=export_plan(plan,root/'out',dpi=100,progress=lambda _:None)
            self.assertEqual({p.suffix for p in paths},{'.pdf'})
            self.assertEqual(len(list((root/'out').iterdir())),2)
            for p in paths:
                with fitz.open(p) as doc:self.assertEqual(len(doc),1)
            with self.assertRaises(FileExistsError):export_plan(plan,root/'out',dpi=100)

    def test_ambiguous_prodsheets_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=self.setup_batch(Path(tmp),'batch')
            (parent/'ProdSheet_second.pdf').write_bytes((parent/'ProdSheet_123.pdf').read_bytes())
            jobs,issues=discover([str(parent)],lambda _:None)
            self.assertFalse(jobs);self.assertEqual(len(issues),1)

    def test_cache_reuse_and_content_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'MAIN.pdf';f=test_batch.BatchTest();f.label(source,A,'5208133300829')
            first=scan_batch([str(source)],[A,B],progress=lambda _:None)
            self.assertEqual(first.cached_files,0)
            with patch('label_parser.core._scan_uncached',side_effect=AssertionError('cache miss')):
                again=scan_batch([str(source)],[A,B],progress=lambda _:None)
                self.assertEqual(again.cached_files,1)
            source.unlink();f.label(source,B,'5208133300836')
            changed=scan_batch([str(source)],[A,B],progress=lambda _:None)
            self.assertEqual(changed.cached_files,0);self.assertEqual(changed.matches[0].model,B)

if __name__=='__main__':unittest.main()
