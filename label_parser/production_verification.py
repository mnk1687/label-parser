"""Independent rendered-page verification. Never replace PDF values with OCR guesses."""
import re

import fitz
import pytesseract
from PIL import Image, ImageOps


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


def verify_columns(page, words, headers, footer, page_number, progress):
    """OCR each column separately so adjacent columns cannot become one OCR word.

    Numeric fields compare token sequences, not concatenated numbers. For text,
    whitespace/wrapping is ignored; model-only glyph equivalences are recorded.
    Unresolved differences are blocking review errors, never silent corrections.
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
                           'pdf': expected, 'ocr': observed.strip()})
            if not matched:
                a, b = normalized(expected), normalized(observed)
                offset = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                sample = slice(max(0, offset-8), offset+24)
                errors.append(f'第 {page_number} 页 {name} 的 PDF/OCR 结果不一致：PDF「{a[sample]}」/ OCR「{b[sample]}」，请核对原单。')
        except (RuntimeError, pytesseract.TesseractNotFoundError) as exc:
            checks.append({'page': page_number, 'column': name, 'status': 'unavailable',
                           'pdf': expected, 'error': str(exc)})
            errors.append(f'第 {page_number} 页 {name} 无法完成 OCR 复核：{exc}')
    return checks, errors


def validate_batch(batch, page_texts, *, require_totals=False):
    errors = []
    if batch.rows != len(batch.details):
        errors.append(f'TXT1 共 {batch.rows} 条，但完整明细只有 {len(batch.details)} 条，禁止遗漏后继续导出。')
    # Repeated footer totals describe the whole order, not each page's subtotal.
    counts = {int(v) for text in page_texts for v in re.findall(r'Items:\s*(\d+)', text)}
    totals = {int(v) for text in page_texts for v in re.findall(r'Total\s+Order[^\n:]*:\s*(\d+)', text)}
    batch.source_totals = {'items': next(iter(counts)), 'quantity': next(iter(totals))} if len(counts) == len(totals) == 1 else {}
    if require_totals and (not counts or not totals):
        errors.append('无法完整读取页脚 Items / Total Order，不能确认是否漏行，请核对原单。')
    if len(counts) > 1 or (counts and counts != {len(batch.details)}):
        errors.append(f'页脚 Items {sorted(counts)} 与提取明细 {len(batch.details)} 不一致。')
    quantity = sum(row.quantity for row in batch.details)
    if len(totals) > 1 or (totals and totals != {quantity}):
        errors.append(f'页脚 Total Order {sorted(totals)} 与数量合计 {quantity} 不一致。')
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
        if row.txt2.startswith(row.txt1+'-') and not row.txt2.endswith('-'+row.size):
            errors.append(f'第 {row.page} 页第 {row.row} 条 TXT2 尺码与 Size 不一致或续行不完整：{row.txt2}')
    errors.extend(w for w in batch.warnings if any(token in w for token in
                  ('无法识别', '无法确认归属', '对应多个款号')))
    return errors


def require_verified(batch):
    errors = getattr(batch, 'validation_errors', [])
    if errors:
        raise ValueError('ProdSheet 校验未通过，停止导入/导出：\n'+'\n'.join(errors))
