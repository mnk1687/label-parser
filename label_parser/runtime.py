"""Locate bundled OCR assets without requiring PATH or an installed Tesseract."""
import os
from pathlib import Path
import sys


def configure_runtime():
    if not getattr(sys,'frozen',False):return
    import pytesseract
    base=Path(sys._MEIPASS)
    executable=base/'ocr'/('tesseract.exe' if sys.platform=='win32' else 'tesseract')
    data=base/'ocr'/'tessdata'
    if not executable.is_file() or not (data/'eng.traineddata').is_file():
        raise RuntimeError('安装文件不完整，请重新安装 LabelDesk（缺少内置 OCR）。')
    pytesseract.pytesseract.tesseract_cmd=str(executable)
    os.environ['TESSDATA_PREFIX']=str(data)


def self_test(folder):
    """Run the actual frozen imports, OCR, Excel, PDF and GUI resource path."""
    from PIL import Image,ImageDraw,ImageFont
    import pytesseract,fitz
    from .composition import write_excel,read_excel,export_summary
    from .prodsheet import ProductionRow
    from .gui import App,ctk
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGB',(900,160),'white')
    ImageDraw.Draw(im).text((20,20),'5208133300829',font=ImageFont.load_default(size=72),fill='black')
    recognized=pytesseract.image_to_string(im,lang='eng',config='--psm 7').strip()
    if '5208133300829' not in recognized:raise RuntimeError('OCR self-test failed: '+recognized)
    row=ProductionRow('CARELABEL_2-','28','FBM015-099-03','FBM015-099-03-DK BLUE-28','5208133300829',10)
    excel=write_excel([row],'内置测试.pdf',folder/'测试明细.xlsx')
    if read_excel(excel)!=[row]:raise RuntimeError('Excel round trip failed')
    source=folder/'single.pdf'
    with fitz.open() as doc:
        p=doc.new_page(width=612,height=792);p.insert_text((40,40),row.txt2);p.draw_rect(fitz.Rect(40,60,250,200))
        doc.save(source)
    summary=export_summary([(row,source)],folder/'summary.pdf')
    with fitz.open(summary) as doc:
        if len(doc)!=1 or not doc[0].get_drawings():raise RuntimeError('PDF vector test failed')
    root=ctk.CTk();root.withdraw();App(root);root.update_idletasks();root.destroy()
    (folder/'PASS.txt').write_text('PASS: bundled OCR, Excel round trip, vector PDF merge, Tk/CustomTkinter UI resources.\nOCR: '+recognized,encoding='utf-8')
