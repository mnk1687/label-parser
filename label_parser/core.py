"""Local label extraction. Cyan outlined artwork is the supported first template."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable
import fitz
import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

SUPPORTED = {'.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp', '.bmp'}

@dataclass
class Match:
    source: str
    page: int
    rect: list[float]
    method: str
    text: str
    selected: bool = True
    model: str = ""
    barcode: str = ""

@dataclass
class ScanResult:
    keyword: str
    matches: list[Match]
    warnings: list[str]
    pages: int = 0
    targets: list[str] = field(default_factory=list)
    files: int = 0


def contains(text: str, keyword: str) -> bool:
    # Normalize typography, but never turn O into 0 or perform fuzzy model matching.
    text = text.upper().translate(str.maketrans('‐‑–—−', '-----'))
    keyword = keyword.strip().upper().translate(str.maketrans('‐‑–—−', '-----'))
    parts = [re.escape(p) for p in keyword.split('-')]
    pattern = r'(?<![A-Z0-9-])' + r'\s*-\s*'.join(parts) + r'(?![A-Z0-9-])'
    return bool(re.search(pattern, text))


def open_source(path: Path) -> fitz.Document:
    if path.suffix.lower() == '.pdf':
        doc = fitz.open(path)
        if doc.needs_pass:
            doc.close()
            raise ValueError('PDF 已加密，请先解密')
        return doc
    # Normalize image orientation; one page per TIFF frame; use 150 dpi coordinates.
    doc = fitz.open()
    with Image.open(path) as im:
        for frame in range(getattr(im, 'n_frames', 1)):
            im.seek(frame)
            rgb = ImageOps.exif_transpose(im).convert('RGB')
            import io
            stream = io.BytesIO()
            rgb.save(stream, format='PNG')
            page = doc.new_page(width=rgb.width * 72/150, height=rgb.height * 72/150)
            page.insert_image(page.rect, stream=stream.getvalue())
    return doc


def merge_frames(rects: list[fitz.Rect], tolerance: float = 2) -> list[fitz.Rect]:
    rects = [fitz.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(rects):
            for j in range(i+1, len(rects)):
                b = rects[j]
                aligned = abs(a.x0-b.x0) <= tolerance and abs(a.x1-b.x1) <= tolerance
                touching = max(a.y0,b.y0) <= min(a.y1,b.y1)+tolerance
                if aligned and touching:
                    rects[i] = a | b
                    rects.pop(j)
                    changed = True
                    break
            if changed:
                break
    return sorted(rects, key=lambda r: (round(r.y0/3), r.x0))


def frames(page: fitz.Page) -> list[fitz.Rect]:
    rects = []
    for d in page.get_drawings():
        c = d.get('color')
        if c and len(c) == 3 and c[0] < .45 and c[1] > .6 and c[2] > .6:
            r = d['rect']
            if r.width > 30 and r.height > 20:
                rects.append(r)
    if rects:
        return merge_frames(rects)
    # Scans/screenshots: detect the same cyan frame in pixels.
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
    mask = ((arr[:,:,0] < 160) & (arr[:,:,1] > 160) & (arr[:,:,2] > 160)).astype('uint8')*255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x,y,w,h = cv2.boundingRect(contour)
        if w >= 60 and h >= 40:
            rects.append(fitz.Rect(x/2, y/2, (x+w)/2, (y+h)/2))
    return merge_frames(rects)


def crop_rect(page: fitz.Page, frame: fitz.Rect) -> fitz.Rect:
    # Include the red identifier above the cyan frame, as in the supplied reference.
    return fitz.Rect(frame.x0-1, frame.y0-frame.width*.065,
                     frame.x1+1, frame.y1+1) & page.rect


def ocr(page: fitz.Page, rect: fitz.Rect) -> str:
    pix = page.get_pixmap(matrix=fitz.Matrix(4,4), clip=rect, colorspace=fitz.csRGB)
    im = Image.frombytes('RGB', (pix.width,pix.height), pix.samples)
    return pytesseract.image_to_string(im, lang='eng', config='--psm 11', timeout=90)


def scan(inputs: list[str], keyword: str, progress: Callable[[str], None] = print) -> ScanResult:
    return scan_batch(inputs, [keyword], progress=progress)


def scan_batch(inputs: list[str], keywords: list[str], barcode_models=None,
               progress: Callable[[str], None] = print, excluded_sources=()) -> ScanResult:
    keywords=list(dict.fromkeys(k.strip().upper() for k in keywords if k.strip()))
    if not keywords:raise ValueError('没有有效目标款号')
    barcode_models=barcode_models or {}
    excluded={Path(p).resolve() for p in excluded_sources}
    paths=[]
    for source in inputs:
        path=Path(source).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            raise ValueError(f'文件不存在或格式不支持：{path}')
        if path not in paths and path not in excluded:paths.append(path)
    if not paths:raise ValueError('请选择批次标签 PDF，ProdSheet 不作为待裁切文件')
    result=ScanResult(keywords[0] if len(keywords)==1 else '批次标签汇总',[],[],targets=keywords,files=len(paths))
    def identify(text):
        direct=[k for k in keywords if contains(text,k)]
        codes=re.findall(r'(?<![0-9])([0-9]{13})(?![0-9])',text)
        linked=list(dict.fromkeys(barcode_models[c] for c in codes if c in barcode_models and barcode_models[c] in keywords))
        return direct,linked,codes
    for path in paths:
        try:
            with open_source(path) as doc:
                for index,page in enumerate(doc):
                    progress(f'{path.name} · {index+1}/{len(doc)} 页 · 已匹配 {len(result.matches)} 个标签')
                    result.pages+=1
                    text=page.get_text();boxes=frames(page)
                    if not boxes:
                        if not text.strip() or any(identify(text)[:2]):
                            result.warnings.append(f'{path.name} 第 {index+1} 页未找到青色标签边框，需检查。')
                        continue
                    found=set()
                    for frame in boxes:
                        try:
                            rect=crop_rect(page,frame)
                            region_text=page.get_text(clip=rect)
                            direct,linked,codes=identify(region_text)
                            method='pdf-text'
                            # Raster labels often have only a red identifier above the frame.
                            if not direct and not linked and not codes and not re.search(r'\b[A-Z]{2,}\d{2,}-\d',region_text.upper()):
                                header=fitz.Rect(rect.x0,rect.y0,rect.x1,min(rect.y1,frame.y0+2))
                                header_text=ocr(page,header)
                                d,l,c=identify(header_text)
                                if l:
                                    region_text=header_text;direct,linked,codes=d,l,c;method='ocr'
                                else:
                                    region_text=ocr(page,rect);direct,linked,codes=identify(region_text);method='ocr'
                            if direct and linked and set(direct)!=set(linked):
                                result.warnings.append(f'{path.name} 第 {index+1} 页款号与条码关联冲突，未自动归类。');continue
                            matched=direct or linked
                            if len(matched)>1:
                                result.warnings.append(f'{path.name} 第 {index+1} 页一个裁切框关联多个款号，需检查。');continue
                            if matched:
                                model=matched[0];found.add(model)
                                code=next((c for c in codes if barcode_models.get(c)==model),codes[0] if codes else '')
                                result.matches.append(Match(str(path),index+1,list(rect),method+('-barcode' if not direct else ''),region_text,model=model,barcode=code))
                            elif not codes and not re.search(r'\b[A-Z]{2,}\d{2,}-\d',region_text.upper()):
                                result.warnings.append(f'{path.name} 第 {index+1} 页有标签无法读取款号或条码，需检查。')
                        except Exception as exc:
                            result.warnings.append(f'{path.name} 第 {index+1} 页标签处理失败：{exc}')
                    page_targets=set(identify(text)[0]+identify(text)[1])
                    if page_targets-found:
                        result.warnings.append(f'{path.name} 第 {index+1} 页部分命中未归入标签：{", ".join(sorted(page_targets-found))}')
        except Exception as exc:
            result.warnings.append(f'{path.name}：处理失败：{exc}')
    rank={k:i for i,k in enumerate(keywords)}
    result.matches.sort(key=lambda m:rank[m.model])
    return result


def preview(match: Match, dpi: int = 180) -> Image.Image:
    with open_source(Path(match.source)) as doc:
        pix = doc[match.page-1].get_pixmap(dpi=dpi, clip=fitz.Rect(match.rect), colorspace=fitz.csRGB)
        return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)


def export(result: ScanResult, output: Path, dpi: int = 400, progress=None) -> dict:
    selected = [m for m in result.matches if m.selected]
    if not selected:
        raise ValueError('没有选中的裁切结果，未生成空 PDF')
    output = output.expanduser().resolve()
    if output.suffix.lower() != '.pdf':
        raise ValueError('输出文件必须是 .pdf')
    if output in {Path(m.source).resolve() for m in selected}:
        raise ValueError('输出文件不能覆盖源文件')
    if output.exists():
        raise FileExistsError('输出文件已存在，请使用新文件名')
    output.parent.mkdir(parents=True,exist_ok=True)
    out = fitz.open()
    doc=None;active_source=None
    try:
        bookmarks=[]
        for index,match in enumerate(selected):
            if active_source!=match.source:
                if doc is not None:doc.close()
                doc=open_source(Path(match.source));active_source=match.source
            r = fitz.Rect(match.rect)
            pix = doc[match.page-1].get_pixmap(dpi=dpi, clip=r, colorspace=fitz.csRGB)
            if not bookmarks or bookmarks[-1][1] != (match.model or result.keyword):
                bookmarks.append([1,match.model or result.keyword,len(out)+1])
            p = out.new_page(width=r.width,height=r.height)
            p.insert_image(p.rect,stream=pix.tobytes('png'))
            if progress and (index%25==0 or index+1==len(selected)):
                progress(f'正在导出 PDF · {index+1}/{len(selected)} 个标签')
        out.set_toc(bookmarks)
        out.set_metadata({'title': f'{result.keyword} — {len(selected)} labels',
                          'creator':'Label Parser 0.2'})
        out.save(output,deflate=True)
    finally:
        if doc is not None:doc.close()
        out.close()
    manifest = {'keyword':result.keyword,'count':len(selected),'dpi':dpi,
                'pages_scanned':result.pages,'warnings':result.warnings,
                'items':[dict(output_page=i+1,**asdict(m)) for i,m in enumerate(selected)]}
    return manifest
