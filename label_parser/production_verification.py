"""Independent rendered-page verification. Never replace PDF values with OCR guesses."""
import re

import fitz
import pytesseract
from PIL import Image, ImageOps
from .review import ReviewItem


HYPHENS = str.maketrans('‐‑–—−', '-----')


def normalized(value):
    return re.sub(r'\s+', '', value.upper().translate(HYPHENS))


def normalize_ocr_identifiers(value, models):
    """Allow O/0 and I/1 only inside a known, structurally valid model/article identifier."""
    for model in sorted(models, key=len, reverse=True):
        pattern = ''.join('[0O]' if c == '0' else '[1IL]' if c == '1' else re.escape(c)
                          for c in model)
        value = re.sub(pattern, model, value)
    return value


def _read_clip(page, rect, numeric, dpi=300, psm=6):
    pix = page.get_pixmap(clip=rect, dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    image = ImageOps.expand(image, border=16, fill='white')
    config = f'--psm {psm}'
    if numeric:
        config += ' -c tessedit_char_whitelist=0123456789'
    return pytesseract.image_to_string(image, lang='eng', config=config, timeout=90)


def verify_columns(page, words, headers, footer, page_number, progress, source_label='PDF'):
    """OCR each column separately so adjacent columns cannot become one OCR word.

    Numeric fields compare token sequences, not concatenated numbers. For text,
    whitespace/wrapping is ignored; model-only glyph equivalences are recorded.
    Unresolved differences become review items; they never silently replace PDF values.
    """
    checks = []; errors = []
    top = max(w[3] for w in headers) + 1
    starts = [w[0] for w in headers]
    for index, header in enumerate(headers):
        name = header[4].upper()
        if name not in {'ARTICLE', 'SIZE', 'TXT1', 'TXT2', 'BARCODE', 'QUANTITY'}:
            continue
        left = starts[index]-1
        right = starts[index+1]-1 if index+1 < len(starts) else page.rect.width
        parts = sorted([w for w in words if left <= w[0] < right and top <= w[1] < footer],
                       key=lambda w: (round(w[1], 1), w[0]))
        if not parts:
            continue
        expected = ' '.join(w[4] for w in parts)
        numeric = name in {'BARCODE', 'QUANTITY'}
        models = re.findall(r'[A-Z]{2,}\d+(?:-\d+){2,}', expected.upper())
        if name == 'ARTICLE':
            models += re.findall(r'[A-Z]+_\d+(?:-\d+)*-', expected.upper())
        def equivalent(text):
            if numeric:
                return text.split() == expected.split()
            return normalize_ocr_identifiers(normalized(text), models) == normalized(expected)
        # Tight vertical extent excludes table rules and the footer.
        rect = fitz.Rect(max(0, left), max(0, min(w[1] for w in parts)-2),
                         min(page.rect.width, right), min(footer, max(w[3] for w in parts)+2))
        progress(f'ProdSheet 第 {page_number} 页 · OCR 复核 {name}')
        try:
            observed = _read_clip(page, rect, numeric)
            if not equivalent(observed):
                observed = _read_clip(page, rect, numeric, dpi=450, psm=6)
            matched = equivalent(observed)
            status = 'matched' if matched else 'disagreed'
            if matched and normalized(observed) != normalized(expected):
                status = 'matched-code-glyphs'
            checks.append({'page': page_number, 'column': name, 'status': status,
                           'source': source_label,
                           'pdf': expected, 'ocr': observed.strip()})
            if not matched:
                a, b = normalized(expected), normalized(observed)
                offset = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                sample = slice(max(0, offset-8), offset+24)
                errors.append(f'第 {page_number} 页 {name} 的 {source_label}/OCR 结果不一致：{source_label}「{a[sample]}」/ OCR「{b[sample]}」，请核对原单。')
        except (RuntimeError, pytesseract.TesseractNotFoundError) as exc:
            checks.append({'page': page_number, 'column': name, 'status': 'unavailable',
                           'source': source_label, 'pdf': expected, 'error': str(exc)})
            errors.append(f'第 {page_number} 页 {name} 无法完成 OCR 复核：{exc}')
    return checks, errors


def footer_totals(batch, page_texts):
    """Repeated footer totals describe the whole order, not each page's subtotal."""
    counts = {int(v) for text in page_texts for v in re.findall(r'Items:\s*(\d+)', text)}
    totals = {int(v) for text in page_texts for v in re.findall(r'Total\s+Order[^\n:]*:\s*(\d+)', text)}
    batch.source_totals = ({'items': next(iter(counts)), 'quantity': next(iter(totals))}
                           if len(counts) == len(totals) == 1 else {})
    return counts, totals


def _sample(pdf_value, ocr_value):
    a, b = normalized(pdf_value), normalized(ocr_value)
    offset = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    sample = slice(max(0, offset-8), offset+24)
    return a[sample], b[sample]


def review_from_checks(checks):
    """Turn OCR checks into operator-visible questions; never overwrite PDF values."""
    items = []
    for check in checks:
        page = check.get('page', 0)
        column = check.get('column', '')
        status = check.get('status')
        source = check.get('source', 'PDF')
        if status == 'disagreed':
            pdf_sample, ocr_sample = _sample(check.get('pdf', ''), check.get('ocr', ''))
            severity = 'high' if column in {'TXT1', 'BARCODE', 'QUANTITY'} else 'medium'
            items.append(ReviewItem(
                'ocr_disagreement', severity,
                f'第 {page} 页 {column} 的 {source}/OCR 不一致：{source}「{pdf_sample}」/ OCR「{ocr_sample}」',
                page=page, field=column,
                pdf_value=check.get('pdf', ''), ocr_value=check.get('ocr', '')))
        elif status == 'unavailable':
            items.append(ReviewItem(
                'ocr_unavailable', 'medium',
                f'第 {page} 页 {column} 无法完成 OCR 复核：{check.get("error", "")}',
                page=page, field=column))
    return items


def validate_batch(batch, page_texts):
    """Return only internal contradictions with no alternative value to choose."""
    errors = []
    footer_totals(batch, page_texts)
    seen = set()
    for row in batch.details:
        if row.barcode in seen:
            errors.append(f'条码 {row.barcode} 重复出现，需要确认是否会重复导出。')
        seen.add(row.barcode)
        code = row.barcode
        if len(code) == 13 and code.isascii() and code.isdigit():
            check = (10-sum(int(c)*(1 if i%2 == 0 else 3) for i,c in enumerate(code[:12]))%10)%10
            if check != int(code[-1]):
                errors.append(f'第 {row.page} 页第 {row.row} 条条码 {code} 的 EAN-13 校验位不正确。')
    return errors


def collect_review_items(batch, page_texts, *, require_totals=False, extra=()):
    """Everything the operator may accept: footer mismatches, OCR pages, dropped rows."""
    items = list(extra)
    if getattr(batch, 'ocr_pages', []):
        pages = '、'.join(str(page) for page in batch.ocr_pages)
        items.append(ReviewItem(
            'ocr_page', 'high',
            f'第 {pages} 页没有可用的 PDF 文字层，已使用整页 OCR；这些页的字段未经原生文字层确认。'))
    counts, totals = footer_totals(batch, page_texts)
    if require_totals and (not counts or not totals):
        items.append(ReviewItem('totals', 'high',
                                '无法完整读取页脚 Items / Total Order，不能确认是否漏行。'))
    if len(counts) > 1 or (counts and counts != {len(batch.details)}):
        items.append(ReviewItem('totals', 'high',
                                f'页脚 Items {sorted(counts)} 与提取明细 {len(batch.details)} 不一致。'))
    quantity = sum(row.quantity for row in batch.details)
    if len(totals) > 1 or (totals and totals != {quantity}):
        items.append(ReviewItem('totals', 'high',
                                f'页脚 Total Order {sorted(totals)} 与数量合计 {quantity} 不一致。'))
    if batch.rows != len(batch.details):
        items.append(ReviewItem('missing_rows', 'high',
                                f'TXT1 共 {batch.rows} 条，完整明细 {len(batch.details)} 条，'
                                f'少 {batch.rows - len(batch.details)} 条。'))
    for warning in batch.warnings:
        if '未找到唯一同行条码' in warning:
            items.append(ReviewItem('missing_row', 'high', warning))
        elif '无法识别' in warning:
            items.append(ReviewItem('unreadable', 'high', warning))
        elif '无法确认归属' in warning:
            items.append(ReviewItem('continuation', 'medium', warning))
        elif '对应多个款号' in warning:
            items.append(ReviewItem('identity_conflict', 'high', warning))
    for row in batch.details:
        if row.txt2.startswith(row.txt1+'-') and not row.txt2.endswith('-'+row.size):
            items.append(ReviewItem(
                'txt2_size', 'medium',
                f'第 {row.page} 页第 {row.row} 条 TXT2 尺码与 Size 不一致或续行不完整：{row.txt2}',
                page=row.page, row=row.row, field='TXT2', pdf_value=row.txt2))
    seen = set(); unique = []
    for item in items:
        key = (item.kind, item.page, item.row, item.field, item.message)
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique


def require_verified(batch):
    errors = getattr(batch, 'validation_errors', [])
    if errors:
        raise ValueError('ProdSheet 校验未通过，停止导入/导出：\n'+'\n'.join(errors))
