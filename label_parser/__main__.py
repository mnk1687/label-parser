import argparse
from pathlib import Path
from .core import scan_batch,export
from .prodsheet import read_prodsheet

def main():
    p=argparse.ArgumentParser(description='ProdSheet TXT1 驱动的批次标签识别')
    p.add_argument('inputs',nargs='*',help='本批次多个标签 PDF')
    p.add_argument('--prodsheet',help='包含 TXT1 的生产单')
    p.add_argument('--keyword',default='FBL015-166-03',help='不提供生产单时的手动款号')
    p.add_argument('--output',type=Path);p.add_argument('--gui',action='store_true')
    a=p.parse_args()
    if a.gui or not a.inputs:
        from .gui import main as gui
        gui();return
    if not a.output:p.error('命令行模式需要 --output')
    batch=read_prodsheet(a.prodsheet) if a.prodsheet else None
    r=scan_batch(a.inputs,batch.models if batch else [a.keyword],batch.barcode_models if batch else {},excluded_sources=[batch.source] if batch else [])
    if batch:r.warnings=batch.warnings+r.warnings
    missing=set(r.targets)-{m.model for m in r.matches}
    for w in r.warnings:print('待检查：',w)
    if missing:print('未匹配款号：',', '.join(sorted(missing)))
    if not r.matches:print('没有可导出标签。');raise SystemExit(2)
    info=export(r,a.output);print(f'已导出 {info["count"]} 个标签，仅生成 PDF：{a.output}')
    if r.warnings or missing:raise SystemExit(3)

if __name__=='__main__':main()
