"""Repeat the real-file audit without modifying customer sources or exporting labels.

Run from the repository: python -m scripts.review_prodsheets --root . --output /tmp/review.json --with-labels
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

import fitz
from label_parser.prodsheet import read_prodsheet
from label_parser.production_verification import require_verified
from label_parser.workflow import Job, recognize, role
from label_parser.composition import make_compositions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--with-labels', action='store_true')
    args = parser.parse_args()
    report = []; started = time.monotonic()
    for path in sorted(args.root.glob('*/ProdSheet*.pdf')):
        print(f'审核 {path}', flush=True)
        source_files = list(path.parent.glob('*.pdf'))
        hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
        entry = {'folder': path.parent.name, 'source': str(path.resolve())}
        try:
            batch = read_prodsheet(str(path), progress=lambda _: None, verify_ocr=True)
            entry['batch'] = asdict(batch)
            require_verified(batch)
            with fitz.open(path) as doc:
                entry['pages'] = len(doc)
                text = '\n'.join(page.get_text() for page in doc)
                codes = re.findall(r'(?<!\d)\d{13}(?!\d)', text)
                entry['all_native_barcodes_accounted_for'] = Counter(codes) == Counter(r.barcode for r in batch.details)
            if args.with_labels:
                sources = [str(p.resolve()) for p in source_files if role(p) not in ('ProdSheet', '其他标签')]
                job = Job(path.parent.name, path.parent.name, batch, sources, files_selected=set(sources))
                recognize(job, progress=lambda _: None)
                items = make_compositions(job)
                entry['label_matches'] = len(job.result.matches)
                entry['incomplete_compositions'] = [
                    {'barcode': item.row.barcode, 'txt2': item.row.txt2, 'missing': item.missing}
                    for item in items if item.missing]
                entry['label_warnings'] = job.result.warnings
            entry['status'] = 'passed'
        except Exception as exc:
            entry['status'] = 'blocked'; entry['error'] = str(exc)
        entry['sources_unchanged'] = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == value
                                         for p, value in hashes.items())
        report.append(entry)
        print(entry['folder'], entry['status'],
              'incomplete', len(entry.get('incomplete_compositions', [])), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'seconds': round(time.monotonic()-started, 2), 'files': report},
                                         ensure_ascii=False, indent=2))
    if not report:
        raise SystemExit('No ProdSheet PDFs found one directory below --root')
    if any(e['status'] != 'passed' or not e['sources_unchanged'] for e in report):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
