import argparse
from pathlib import Path
from .workflow import discover,recognize
from .composition import export_compositions

def main():
    parser=argparse.ArgumentParser(description='ProdSheet → 排序 Excel → TXT1 文件夹 / TXT2 组合 PDF')
    parser.add_argument('inputs',nargs='*',help='整批 PDF 或包含批次的目录')
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--models',help='导出指定 TXT1，多个款号用逗号分隔')
    parser.add_argument('--all',action='store_true',help='明确选择全部款号')
    args=parser.parse_args()
    if args.gui or not args.inputs:
        from .gui import main as gui
        gui();return
    if not args.output_dir:parser.error('请指定 --output-dir')
    if not args.models and not args.all:parser.error('请指定 --models 或 --all，避免意外全量导出')
    jobs,issues=discover(args.inputs)
    for issue in issues:print('待检查：',issue)
    if not jobs:raise SystemExit(2)
    requested={v.strip() for v in args.models.split(',')} if args.models else None
    for job in jobs:
        recognize(job)
        codes={r.barcode for r in job.batch.details if requested is None or r.txt1 in requested}
        if not codes:print('该批次没有选中款号：',job.name);continue
        excel,paths=export_compositions(job,args.output_dir/(job.name+'_'+job.key[:5]),codes)
        print(f'已生成 {excel} 和 {len(paths)} 份组合 PDF')
    if issues:raise SystemExit(3)

if __name__=='__main__':main()
