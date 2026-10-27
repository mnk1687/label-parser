"""Preserve installed dependency license texts in distributable builds."""
from pathlib import Path
from importlib import metadata
import os,shutil,subprocess,sys
root=Path(__file__).resolve().parent/'licenses';root.mkdir(exist_ok=True)
for dist in metadata.distributions():
    name=dist.metadata.get('Name','unknown')
    for rel in dist.files or []:
        if any(word in Path(str(rel)).name.lower() for word in ['license','licence','copying','notice']):
            source=Path(dist.locate_file(rel))
            if source.is_file():
                target=root/name/str(rel).replace('..','_');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
if sys.platform=='darwin':
    todo=[Path(shutil.which('tesseract'))];seen=set()
    while todo:
        p=todo.pop().resolve()
        if p in seen:continue
        seen.add(p)
        for line in subprocess.check_output(['otool','-L',str(p)],text=True).splitlines()[1:]:
            name=line.strip().split(' (')[0]
            if name.startswith(('/opt/homebrew/','/usr/local/')):todo.append(Path(name))
        parts=p.parts
        if 'Cellar' in parts:
            package=Path(*parts[:parts.index('Cellar')+3])
            for pattern in ['*LICENSE*','*COPYING*','*NOTICE*']:
                for source in package.glob(pattern):
                    if source.is_file():
                        target=root/'homebrew'/package.parent.name/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
if sys.platform=='win32':
    folder=os.environ.get('LABELDESK_TESSERACT') or shutil.which('tesseract')
    if folder:
        ocr=Path(folder) if Path(folder).is_dir() else Path(folder).parent
        for place in [ocr,ocr/'doc']:
            for pattern in ['*LICENSE*','*COPYING*','*NOTICE*']:
                for source in place.glob(pattern):
                    if source.is_file():
                        target=root/'tesseract'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
