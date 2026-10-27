"""Extract only the TXT1 column; retain same-row barcode relationships."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import fitz
import pytesseract
from PIL import Image
from .core import open_source

MODEL = re.compile(r'[A-Z]{2,}\d+(?:-\d+){2,}')

@dataclass
class ProductionBatch:
    source: str
    models: list[str]
    barcode_models: dict[str, str]
    rows: int
    warnings: list[str] = field(default_factory=list)
    barcode_evidence: dict = field(default_factory=dict)


def read_prodsheet(source: str, progress=print) -> ProductionBatch:
    path=Path(source).expanduser().resolve()
    models=[];mapping={};conflicts=set();warnings=[];rows=0;evidence={}
    with open_source(path) as doc:
        for index,page in enumerate(doc):
            progress(f'读取 ProdSheet · {index+1}/{len(doc)} 页')
            words=page.get_text('words')
            if not words:
                pix=page.get_pixmap(dpi=216)
                im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                data=pytesseract.image_to_data(im,config='--psm 6',output_type=pytesseract.Output.DICT,timeout=90)
                words=[(data['left'][i]/3,data['top'][i]/3,(data['left'][i]+data['width'][i])/3,(data['top'][i]+data['height'][i])/3,t) for i,t in enumerate(data['text']) if t.strip()]
                warnings.append(f'ProdSheet 第 {index+1} 页使用 OCR，请核对提取款号。')
            heads=[w for w in words if w[4].upper()=='TXT1']
            if len(heads)!=1:
                raise ValueError(f'ProdSheet 第 {index+1} 页无法确定 TXT1 列，停止批量解析，避免遗漏款号。')
            h=heads[0]
            headers=sorted([w for w in words if abs(w[1]-h[1])<max(4,h[3]-h[1])],key=lambda w:w[0])
            right=next((w[0] for w in headers if w[0]>h[2]),None)
            if right is None:raise ValueError(f'第 {index+1} 页 TXT1 列右边界不明确')
            candidates=sorted([w for w in words if h[0]-2<=w[0]<right-2 and w[1]>h[3] and w[1]<page.rect.height-30],key=lambda w:w[1])
            model_words=[]
            for w in candidates:
                value=w[4].upper().translate(str.maketrans('‐‑–—−','-----'))
                if MODEL.fullmatch(value):model_words.append((w,value))
                elif w[4].strip():
                    warnings.append(f'ProdSheet 第 {index+1} 页 TXT1 值无法识别：{w[4]}')
            if not model_words:raise ValueError(f'第 {index+1} 页 TXT1 列未提取到款号')
            barcode_head=next((w for w in headers if w[4].upper()=='BARCODE'),None)
            for pos,(w,value) in enumerate(model_words):
                rows+=1
                if value not in models:models.append(value)
                if barcode_head is None:
                    continue
                bx=barcode_head[0]
                br=next((v[0] for v in headers if v[0]>barcode_head[2]),page.rect.width)
                bottom=model_words[pos+1][0][1]-2 if pos+1<len(model_words) else page.rect.height-35
                codes=[v[4] for v in words if bx-2<=v[0]<br-2 and w[1]-2<=v[1]<bottom and re.fullmatch(r'\d{13}',v[4])]
                if len(codes)!=1:
                    warnings.append(f'ProdSheet 第 {index+1} 页 {value} 未找到唯一同行条码；仍可按款号匹配。')
                    continue
                code=codes[0]
                evidence.setdefault(code,[]).append({'page':index+1,'row':pos+1,'model':value})
                if code in mapping and mapping[code]!=value:conflicts.add(code)
                else:mapping[code]=value
            if barcode_head is None:warnings.append(f'第 {index+1} 页缺少 Barcode 列，仅支持款号直接匹配。')
    for code in conflicts:
        mapping.pop(code,None);evidence.pop(code,None);warnings.append(f'条码 {code} 对应多个款号，已禁用该关联。')
    return ProductionBatch(str(path),models,mapping,rows,warnings,evidence)
