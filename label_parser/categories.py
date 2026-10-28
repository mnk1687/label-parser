"""Separate six-up vector label PDFs in the workbook's exact row order."""
from pathlib import Path
import fitz
from .composition import make_compositions,write_excel,read_excel
from .workflow import role

KINDS=('COMPO1','COMPO2','COMPO3','MAIN','CARE')
PAGE_WIDTH,PAGE_HEIGHT=595.276,841.89
MARGIN,GAP=24,18


def ordered_items(job,rows):
    items=make_compositions(job,rows)
    index={(i.row.txt1,i.row.txt2,i.row.barcode):i for i in items}
    if len(index)!=len(items):raise ValueError('Excel 存在重复明细，无法确定唯一标签')
    ordered=[index[(r.txt1,r.txt2,r.barcode)] for r in rows]
    errors=[i.row.txt2+'：'+'；'.join(i.missing) for i in ordered if i.missing]
    if errors:raise ValueError('分类标签匹配不完整，未生成 PDF：\n'+'\n'.join(errors[:10]))
    return ordered


def append_category_page(out,items,kind,documents):
    if kind not in KINDS:raise ValueError('不支持的标签分类')
    if not 1<=len(items)<=6:raise ValueError('每页必须包含 1 至 6 个标签')
    cell_w=(PAGE_WIDTH-2*MARGIN-GAP)/2
    cell_h=(PAGE_HEIGHT-2*MARGIN-2*GAP)/3
    placements=[]
    for index,item in enumerate(items):
        matches=[m for m in item.matches if role(m.source)==kind]
        if len(matches)!=1:raise ValueError(f'{item.row.txt2} 的 {kind} 标签不是唯一匹配')
        match=matches[0];clip=fitz.Rect(match.rect)
        if clip.is_empty or clip.width>cell_w or clip.height>cell_h:
            raise ValueError(f'{item.row.txt2} 的 {kind} 尺寸不适合 A4 每页六个，未缩放标签')
        x=MARGIN+(index%2)*(cell_w+GAP)+(cell_w-clip.width)/2
        y=MARGIN+(index//2)*(cell_h+GAP)+(cell_h-clip.height)/2
        placements.append((match,clip,fitz.Rect(x,y,x+clip.width,y+clip.height)))
    page=out.new_page(width=PAGE_WIDTH,height=PAGE_HEIGHT)
    for match,clip,target in placements:
        if match.source not in documents:documents[match.source]=fitz.open(match.source)
        page.show_pdf_page(target,documents[match.source],match.page-1,clip=clip,keep_proportion=True)
    return page


def category_preview(items,kind):
    out=fitz.open();docs={}
    try:
        append_category_page(out,items,kind,docs)
        return out
    except Exception:
        out.close();raise
    finally:
        for doc in docs.values():doc.close()


def export_categories(job,folder,barcodes,progress=print):
    folder=Path(folder)
    if folder.exists() and any(folder.iterdir()):raise FileExistsError('输出文件夹不是空目录，请选择新的目录')
    folder.mkdir(parents=True,exist_ok=True)
    excel=write_excel(job.batch.details,job.batch.source,folder/'ProdSheet_排序明细.xlsx')
    rows=[r for r in read_excel(excel) if r.barcode in barcodes]
    if not rows:raise ValueError('请先勾选需要导出的明细')
    items=ordered_items(job,rows);docs={};targets=[]
    try:
        # Validate dimensions for all types before creating any output PDF.
        cell_w=(PAGE_WIDTH-2*MARGIN-GAP)/2;cell_h=(PAGE_HEIGHT-2*MARGIN-2*GAP)/3
        for item in items:
            for m in item.matches:
                rect=fitz.Rect(m.rect)
                if rect.is_empty or rect.width>cell_w or rect.height>cell_h:raise ValueError(f'{item.row.txt2} 尺寸不适合 A4 每页六个')
        for kind in KINDS:
            target=folder/(kind.lower()+'排序PDF.pdf')
            with fitz.open() as out:
                toc=[]
                for start in range(0,len(items),6):
                    batch=items[start:start+6];append_category_page(out,batch,kind,docs)
                    toc.extend([1,i.row.txt2,len(out)] for i in batch)
                    progress(f'{kind} · 第 {len(out)}/{(len(items)+5)//6} 页 · 每页 6 个')
                out.set_toc(toc)
                out.set_metadata({'title':kind.lower()+'排序PDF','subject':'Excel 行顺序；从左到右、从上到下；每页六个','creator':'LabelDesk'})
                out.save(target,garbage=4,deflate=True)
            targets.append(target)
    finally:
        for doc in docs.values():doc.close()
    return excel,targets
