# Build on the target OS. Set LABELDESK_TESSERACT to its OCR installation folder.
import os,sys,shutil
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files,copy_metadata
root=Path(SPECPATH).parent
ocr=Path(os.environ.get('LABELDESK_TESSERACT') or Path(shutil.which('tesseract') or '').parent)
executable=ocr/('tesseract.exe' if sys.platform=='win32' else 'tesseract')
data=Path(os.environ.get('LABELDESK_TESSDATA',str(ocr/'tessdata')))
if not executable.is_file() or not (data/'eng.traineddata').is_file():
    raise SystemExit('Set LABELDESK_TESSERACT and LABELDESK_TESSDATA to the build machine OCR installation.')
binaries=[(str(executable),'ocr')]
if sys.platform=='win32':binaries.extend((str(p),'ocr') for p in ocr.glob('*.dll'))
datas=collect_data_files('customtkinter')+[(str(data/'eng.traineddata'),'ocr/tessdata')]
licenses=root/'packaging'/'licenses'
if licenses.exists():datas.append((str(licenses),'licenses'))
for package in ['pytesseract','openpyxl','customtkinter','PyMuPDF']:
    datas+=copy_metadata(package)
a=Analysis([str(root/'desktop_entry.py')],pathex=[str(root)],binaries=binaries,datas=datas,
    hiddenimports=['PIL._tkinter_finder'],excludes=['matplotlib','scipy','pandas','IPython','pytest'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='LabelDesk',console=False,
    target_arch='arm64' if sys.platform=='darwin' else None)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='LabelDesk')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='LabelDesk.app',bundle_identifier='com.labeldesk.desktop',
        info_plist={'CFBundleDisplayName':'LabelDesk 生产标签','CFBundleShortVersionString':'0.5.0',
                    'NSHighResolutionCapable':True})
