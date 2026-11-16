"""Reopen generated artifacts and reconcile them with the ProdSheet footer."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import fitz


def identity(row):
    return row.article, row.size, row.txt1, row.txt2, row.barcode, row.quantity


def verify_excel(batch, path, barcodes=None):
    from .composition import read_excel
    from .production_verification import require_verified
    require_verified(batch)
    rows = read_excel(path)
    original = batch.details
    if Counter(map(identity, rows)) != Counter(map(identity, original)):
        raise ValueError('生成后核对失败：Excel 明细与 ProdSheet 不一致，存在遗漏、重复或字段变化。')
    totals = getattr(batch, 'source_totals', {})
    if totals and (len(rows) != totals['items'] or sum(r.quantity for r in rows) != totals['quantity']):
        raise ValueError('生成后核对失败：Excel 条码条数或 Quantity 合计与 ProdSheet 页脚不一致。')
    all_codes = {r.barcode for r in original}
    if len(all_codes) != len(original):
        raise ValueError('生成后核对失败：ProdSheet 存在重复条码。')
    chosen = all_codes if barcodes is None else set(barcodes)
    if not chosen or chosen-all_codes:
        raise ValueError('生成后核对失败：所选条码为空或含 ProdSheet 中不存在的条码。')
    selected = [r for r in rows if r.barcode in chosen]
    report = {
        'status': 'pending', 'source': batch.source,
        'baseline': 'ProdSheet页脚' if totals else '已解析明细（未提供页脚）',
        'source_items': totals.get('items', len(original)),
        'source_quantity': totals.get('quantity', sum(r.quantity for r in original)),
        'excel_items': len(rows), 'excel_quantity': sum(r.quantity for r in rows),
        'scope': '全量导出' if chosen == all_codes else '部分勾选导出',
        'export_items': len(selected), 'export_quantity': sum(r.quantity for r in selected),
        'unselected_items': len(original)-len(selected),
        'unselected_quantity': sum(r.quantity for r in original)-sum(r.quantity for r in selected),
        'barcodes': [r.barcode for r in selected], 'pdf_checks': [],
    }
    return selected, report


def raster_digest(page):
    return hashlib.sha256(page.get_pixmap(dpi=72, colorspace=fitz.csRGB, alpha=False).samples).hexdigest()


def saved_page_digest(document):
    # PDF serialization can round color values; compare both sides after save/reopen.
    with fitz.open(stream=document.tobytes(garbage=4, deflate=True), filetype='pdf') as saved:
        return raster_digest(saved[0])


def save_report(report, stem):
    stem = Path(stem)
    Path(str(stem)+'.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    lines = [f"生成后核对：{'通过' if report['status']=='passed' else '失败'}",
             f"基准来源：{report['baseline']} · {report['source']}",
             f"ProdSheet：{report['source_items']} 条条码，Quantity 合计 {report['source_quantity']}",
             f"生成的 Excel：{report['excel_items']} 条条码，Quantity 合计 {report['excel_quantity']}",
             f"{report['scope']}：{report['export_items']} 条条码，Quantity 合计 {report['export_quantity']}",
             f"未勾选：{report['unselected_items']} 条，Quantity 合计 {report['unselected_quantity']}"]
    for entry in report['pdf_checks']:
        lines.append(f"PDF：{entry['file']} · {entry['pages']} 页 · 内容核对通过")
    if report.get('error'): lines.append(report['error'])
    lines.append('Quantity 为生产数量，不等于 PDF 页数；分类 PDF 每页最多放置 6 条明细。')
    Path(str(stem)+'.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def verify_export(job, excel, barcodes, items, paths, mode, progress=print, summaries=None):
    from .composition import compose
    from .categories import category_preview
    from .workflow import role
    stem = Path(excel).parent/'生成核对报告'
    report = {'status': 'failed', 'error': '尚未完成核对'}
    try:
        rows, report = verify_excel(job.batch, excel, barcodes)
        if [identity(i.row) for i in items] != [identity(r) for r in rows]:
            raise ValueError('生成后核对失败：PDF 导出明细与 Excel 所选条码不一致。')
        hashes = {}
        if mode == 'combined':
            if len(paths) != len(rows):
                raise ValueError('生成后核对失败：单条组合 PDF 数量不足或重复。')
            for item, path in zip(items, paths):
                progress(f'生成后核对 · {item.row.barcode}')
                with fitz.open(path) as doc, compose(item) as expected:
                    if (len(doc) != 1 or doc.metadata['subject'] != item.row.barcode
                            or raster_digest(doc[0]) != saved_page_digest(expected)):
                        raise ValueError(f'生成后核对失败：{Path(path).name} 的条码或页面内容不正确。')
                    hashes[item.row.barcode] = raster_digest(doc[0])
                report['pdf_checks'].append({'file': str(path), 'pages': 1})
            for path, summary_rows in (summaries or []):
                with fitz.open(path) as doc:
                    expected_toc = [[1, r.txt2, i+1] for i, r in enumerate(summary_rows)]
                    if len(doc) != len(summary_rows) or doc.get_toc() != expected_toc:
                        raise ValueError(f'生成后核对失败：{Path(path).name} 汇总页数/条目不一致。')
                    for page, row in zip(doc, summary_rows):
                        if raster_digest(page) != hashes[row.barcode]:
                            raise ValueError(f'生成后核对失败：汇总文件中条码 {row.barcode} 内容缺失或错序。')
                report['pdf_checks'].append({'file': str(path), 'pages': len(summary_rows)})
        elif mode == 'categories':
            expected_kinds = {role(m.source) for item in items for m in item.matches}
            actual_kinds = {Path(p).stem.removesuffix('排序PDF').upper() for p in paths}
            if expected_kinds != actual_kinds or len(paths) != len(expected_kinds):
                raise ValueError('生成后核对失败：分类 PDF 有缺失或重复。')
            for path in paths:
                kind = Path(path).stem.removesuffix('排序PDF').upper()
                with fitz.open(path) as doc:
                    toc = [[1, row.txt2, i//6+1] for i, row in enumerate(rows)]
                    if len(doc) != (len(rows)+5)//6 or doc.get_toc() != toc:
                        raise ValueError(f'生成后核对失败：{kind} 页数或条码明细不完整。')
                    for n, page in enumerate(doc):
                        progress(f'生成后核对 · {kind} · {n+1}/{len(doc)} 页')
                        with category_preview(items[n*6:n*6+6], kind) as expected:
                            if raster_digest(page) != saved_page_digest(expected):
                                raise ValueError(f'生成后核对失败：{kind} 第 {n+1} 页存在遗漏、重复或内容变化。')
                report['pdf_checks'].append({'file': str(path), 'pages': (len(rows)+5)//6,
                    'labels': sum(any(role(m.source)==kind for m in item.matches) for item in items)})
        else:
            raise ValueError('未知导出类型')
        report['status'] = 'passed'
        save_report(report, stem)
    except Exception as exc:
        report['status'] = 'failed'; report['error'] = str(exc)
        if 'baseline' in report: save_report(report, stem)
        else: Path(str(stem)+'.txt').write_text('生成后核对失败：'+str(exc)+'\n请勿将此次输出用于生产。\n',encoding='utf-8')
        raise
    return report


def completion_message(folder):
    report = json.loads((Path(folder)/'生成核对报告.json').read_text(encoding='utf-8'))
    if report['status'] != 'passed':
        raise ValueError('生成后核对未通过')
    return (f"三重核对通过 · ProdSheet {report['source_items']} 条 / 总数量 {report['source_quantity']}；"
            f"{report['scope']} {report['export_items']} 条 / 数量 {report['export_quantity']}。")
