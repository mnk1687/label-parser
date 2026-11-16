"""Extract only the TXT1 column; retain same-row barcode relationships."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import fitz
import pytesseract
from PIL import Image
from .core import open_source
from .production_verification import (
    collect_review_items, review_from_checks, validate_batch, verify_columns,
)
from .review import ReviewItem

@dataclass
class ProductionRow:
    article: str
    size: str
    txt1: str
    txt2: str
    barcode: str
    quantity: int
    page: int = 0
    row: int = 0


MODEL = re.compile(r'[A-Z]{2,}\d+(?:-\d+){2,}')

@dataclass
class ProductionBatch:
    source: str
    models: list[str]
    barcode_models: dict[str, str]
    rows: int
    warnings: list[str] = field(default_factory=list)
    barcode_evidence: dict = field(default_factory=dict)
    details: list[ProductionRow] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    verification: list[dict] = field(default_factory=list)
    source_totals: dict = field(default_factory=dict)
    ocr_pages: list[int] = field(default_factory=list)
    review_items: list[ReviewItem] = field(default_factory=list)
    review_acknowledged: bool = False


def read_prodsheet(source: str, progress=print, *, verify_ocr=False) -> ProductionBatch:
    path=Path(source).expanduser().resolve()
    models=[];mapping={};conflicts=set();warnings=[];rows=0;evidence={};details=[]
    pending_row = None
    page_texts = []; verification = []; inline_review = []; ocr_pages = []
    with open_source(path) as doc:
        for index,page in enumerate(doc):
            progress(f'读取 ProdSheet · {index+1}/{len(doc)} 页')
            words=page.get_text('words')
            native_text = bool(words)
            page_texts.append(page.get_text())
            if not words or not any(w[4].upper() == 'TXT1' for w in words):
                native_text = False
                ocr_pages.append(index+1)
                try:
                    pix=page.get_pixmap(dpi=216, colorspace=fitz.csRGB, alpha=False)
                    im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    data=pytesseract.image_to_data(im,config='--psm 6',output_type=pytesseract.Output.DICT,timeout=90)
                    words=[(data['left'][i]/3,data['top'][i]/3,(data['left'][i]+data['width'][i])/3,(data['top'][i]+data['height'][i])/3,t) for i,t in enumerate(data['text']) if t.strip()]
                    warnings.append(f'ProdSheet 第 {index+1} 页文字层缺失或表头不完整，使用 OCR，请核对提取款号。')
                    page_texts[-1] = ' '.join(w[4] for w in words)
                except (RuntimeError, pytesseract.TesseractNotFoundError) as exc:
                    message=f'第 {index+1} 页 OCR 失败，整页明细未提取：{exc}'
                    warnings.append('ProdSheet '+message)
                    inline_review.append(ReviewItem('unreadable','high',message,page=index+1))
                    pending_row = None
                    continue
            heads=[w for w in words if w[4].upper()=='TXT1']
            if len(heads)!=1:
                message=f'第 {index+1} 页无法确定 TXT1 列，整页明细未提取。'
                warnings.append('ProdSheet '+message)
                inline_review.append(ReviewItem('unreadable','high',message,page=index+1))
                pending_row = None
                continue
            h=heads[0]
            headers=sorted([w for w in words if abs(w[1]-h[1])<max(4,h[3]-h[1])],key=lambda w:w[0])
            # Embedded font maps the 'ti' ligature to a Bengali glyph in real sheets.
            headers=[(*w[:4], w[4].replace('ঞ', 'ti')) for w in headers]
            right=next((w[0] for w in headers if w[0]>h[2]),None)
            if right is None:
                message=f'第 {index+1} 页 TXT1 列右边界不明确，整页明细未提取。'
                warnings.append('ProdSheet '+message)
                inline_review.append(ReviewItem('unreadable','high',message,page=index+1))
                pending_row = None
                continue
            if native_text:
                # PDF word grouping can join adjacent TXT2 and Barcode cells.
                # Split at real character coordinates, not guessed string lengths.
                boundaries = [v[0]-1 for v in headers[1:]]
                chars = [c for block in page.get_text('rawdict')['blocks']
                         for line in block.get('lines', [])
                         for span in line['spans'] for c in span['chars']]
                separated = []
                for word in words:
                    cuts = [x for x in boundaries if word[0] < x < word[2]]
                    if not cuts or word[1] <= h[3]:
                        separated.append(word)
                        continue
                    letters = [c for c in chars
                               if word[0] <= (c['bbox'][0]+c['bbox'][2])/2 < word[2]
                               and word[1] <= (c['bbox'][1]+c['bbox'][3])/2 < word[3]]
                    if not letters:
                        separated.append(word)
                        continue
                    if ''.join(c['c'] for c in letters) != word[4]:
                        warnings.append(f'ProdSheet 第 {index+1} 页跨列字符无法识别，需核对：{word[4]}')
                        separated.append(word)
                        continue
                    for left, edge in zip([word[0]]+cuts, cuts+[word[2]]):
                        group = [c for c in letters if left <= c['bbox'][0] < edge]
                        if group:
                            separated.append((min(c['bbox'][0] for c in group), word[1],
                                              max(c['bbox'][2] for c in group), word[3],
                                              ''.join(c['c'] for c in group)))
                words = separated
            candidates=sorted([w for w in words if h[0]-2<=w[0]<right-2 and w[1]>h[3] and w[1]<page.rect.height-30],key=lambda w:w[1])
            model_words=[]
            for w in candidates:
                value=w[4].upper().translate(str.maketrans('‐‑–—−','-----'))
                if MODEL.fullmatch(value):model_words.append((w,value))
                elif w[4].strip():
                    warnings.append(f'ProdSheet 第 {index+1} 页 TXT1 值无法识别：{w[4]}')
            barcode_head=next((w for w in headers if w[4].upper()=='BARCODE'),None)
            # Keep split TXT2 cells that continue after a page break.
            def cell(left,right,top,bottom):
                parts=sorted([v for v in words if left-1<=v[0]<right-1 and top<=v[1]<bottom],key=lambda v:(round(v[1],1),v[0]))
                value=''
                for part in parts:
                    value+=('' if not value or value.endswith('-') else ' ')+part[4]
                return value
            starts=[v[0] for v in headers]
            column={v[4].upper():(v[0],starts[i+1] if i+1<len(starts) else page.rect.width) for i,v in enumerate(headers)}
            txt2_bounds=column.get('TXT2')
            # A page-leading TXT2 fragment belongs only to the immediately
            # preceding physical row, never the last successfully parsed row.
            footer = min([v[1] for v in words if v[4] in ('Items:', 'Page')
                          and v[1] > h[3]] or [page.rect.height-31]) - 4
            if verify_ocr:
                missing_headers = {'SIZE', 'TXT1', 'TXT2', 'BARCODE', 'QUANTITY'} - {v[4].upper() for v in headers}
                if missing_headers:
                    inline_review.append(ReviewItem(
                        'missing_header', 'medium',
                        f'第 {index+1} 页缺少可复核表头：{sorted(missing_headers)}', page=index+1))
                checks, _ = verify_columns(
                    page, words, headers, footer, index+1, progress,
                    source_label='PDF' if native_text else '整页OCR')
                verification.extend(checks); inline_review.extend(review_from_checks(checks))
            first_top = model_words[0][0][1]-2 if model_words else footer
            leading = [v for v in words if h[3] <= v[1] < first_top]
            tail = cell(*txt2_bounds, h[3], first_top) if txt2_bounds else ''
            only_txt2 = bool(leading) and txt2_bounds and all(
                txt2_bounds[0]-1 <= v[0] < txt2_bounds[1]-1 for v in leading)
            joined = False
            if tail:
                if pending_row is not None and only_txt2:
                    pending_row.txt2 += ('' if pending_row.txt2.endswith('-') else ' ') + tail
                    joined = True
                else:
                    warnings.append(f'ProdSheet 第 {index+1} 页页首 TXT2 续行无法确认归属，未自动合并：{tail}')
            if not model_words:
                if joined:
                    continue
                message=f'第 {index+1} 页 TXT1 列未提取到款号，整页明细未提取。'
                warnings.append('ProdSheet '+message)
                inline_review.append(ReviewItem('unreadable','high',message,page=index+1))
                pending_row = None
                continue
            pending_row = None
            for pos,(w,value) in enumerate(model_words):
                pending_row = None
                rows+=1
                if value not in models:models.append(value)
                if barcode_head is None:
                    continue
                bx=barcode_head[0]
                br=next((v[0] for v in headers if v[0]>barcode_head[2]),page.rect.width)
                bottom=model_words[pos+1][0][1]-2 if pos+1<len(model_words) else footer
                codes=[v[4] for v in words if bx-2<=v[0]<br-2 and w[1]-2<=v[1]<bottom and re.fullmatch(r'[0-9]{13}',v[4])]
                if len(codes)!=1:
                    warnings.append(f'ProdSheet 第 {index+1} 页 {value} 未找到唯一同行条码；仍可按款号匹配。')
                    continue
                code=codes[0]
                def get_col(name):
                    bounds=column.get(name)
                    return cell(*bounds,w[1]-2,bottom) if bounds else ''
                article_bounds=(headers[0][0],column.get('SIZE',(h[0],))[0])
                article=cell(*article_bounds,w[1]-2,bottom)
                qty_bounds=(headers[-1][0],page.rect.width)
                qty=cell(*qty_bounds,w[1]-2,bottom)
                if not qty.isdigit():
                    inline_review.append(ReviewItem(
                        'unreadable', 'high',
                        f'第 {index+1} 页第 {pos+1} 条 Quantity 无法读取：{qty}',
                        page=index+1, row=pos+1, field='QUANTITY'))
                    pending_row = None
                    continue
                details.append(ProductionRow(article,get_col('SIZE'),value,get_col('TXT2'),code,int(qty),index+1,pos+1))
                pending_row = details[-1]
                evidence.setdefault(code,[]).append({'page':index+1,'row':pos+1,'model':value})
                if code in mapping and mapping[code]!=value:conflicts.add(code)
                else:mapping[code]=value
            if barcode_head is None:warnings.append(f'第 {index+1} 页缺少 Barcode 列，仅支持款号直接匹配。')
    for code in conflicts:
        mapping.pop(code,None);evidence.pop(code,None);warnings.append(f'条码 {code} 对应多个款号，已禁用该关联。')
    if not details:
        raise ValueError('ProdSheet 未提取到任何明细，请确认文件包含 TXT1 表头与款号。')
    batch = ProductionBatch(str(path),models,mapping,rows,warnings,evidence,details)
    batch.ocr_pages = ocr_pages
    batch.verification = verification
    batch.validation_errors = validate_batch(batch, page_texts)
    batch.review_items = collect_review_items(
        batch, page_texts, require_totals=verify_ocr, extra=inline_review)
    return batch
