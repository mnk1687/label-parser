"""Filename classification, batch isolation, explicit export planning and provenance."""
from dataclasses import dataclass,field
from pathlib import Path
from collections import defaultdict
import re,hashlib
from .prodsheet import read_prodsheet,ProductionBatch
from .core import ScanResult,scan_batch,export

@dataclass
class Job:
    key: str
    name: str
    batch: ProductionBatch
    sources: list[str]
    result: ScanResult | None = None
    models_selected: set[str] = field(default_factory=set)
    files_selected: set[str] = field(default_factory=set)

@dataclass
class ExportItem:
    name: str
    job: Job
    source: str
    models: list[str]
    matches: list


def role(path):
    name=Path(path).stem.upper()
    if 'PRODSHEET' in name or 'PRODUCTION' in name:return 'ProdSheet'
    match=re.search(r'(?:^|_)(MAIN|CARE|COMPO\d+)(?:_|$)',name)
    return match.group(1) if match else '其他标签'


def discover(inputs,progress=print):
    paths=[]
    for item in inputs:
        p=Path(item).expanduser().resolve()
        paths.extend(sorted(p.rglob('*.pdf')) if p.is_dir() else [p])
    groups=defaultdict(list)
    for p in dict.fromkeys(paths):
        if p.suffix.lower()=='.pdf' and p.is_file():groups[p.parent].append(p)
    jobs=[];issues=[]
    for parent,files in groups.items():
        sheets=[p for p in files if role(p)=='ProdSheet']
        if len(sheets)!=1:
            issues.append(f'{parent}：发现 {len(sheets)} 份 ProdSheet，无法唯一归组。请将每批文件放到各自文件夹。');continue
        try:batch=read_prodsheet(str(sheets[0]),progress)
        except Exception as e:issues.append(f'{sheets[0].name}：{e}');continue
        sources=[str(p) for p in files if p not in sheets]
        sources.sort(key=lambda s:({'MAIN':0,'CARE':1}.get(role(s),2),Path(s).name))
        if not sources:issues.append(f'{parent.name}：缺少标签 PDF');continue
        key=hashlib.sha256(str(sheets[0]).encode()).hexdigest()[:10]
        name=parent.name if parent.name else sheets[0].stem
        jobs.append(Job(key,name,batch,sources,files_selected=set(sources)))
    return jobs,issues


def recognize(job,progress=print):
    job.result=scan_batch(job.sources,job.batch.models,job.batch.barcode_models,progress)
    job.result.warnings=job.batch.warnings+job.result.warnings
    return job.result


def build_plan(jobs,split_model=False):
    plan=[]
    for job in jobs:
        if not job.result:continue
        chosen=[m for m in job.result.matches if m.selected and m.model in job.models_selected and m.source in job.files_selected]
        groups=defaultdict(list)
        for m in chosen:groups[(m.source,m.model if split_model else '')].append(m)
        for (source,model),matches in groups.items():
            models=list(dict.fromkeys(m.model for m in matches))
            label=model or (models[0] if len(models)==1 else f'{len(models)}款')
            source_hash=hashlib.sha256(source.encode()).hexdigest()[:6]
            name=f'{job.name}_{Path(source).stem}_{label}_{job.key[:5]}{source_hash}.pdf'
            name=re.sub(r'[\\/:*?"<>|]','_',name)
            plan.append(ExportItem(name,job,source,models,matches))
    return plan


def export_plan(plan,folder,dpi=300,progress=print):
    if not plan:raise ValueError('请先勾选款号和来源文件')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    paths=[folder/p.name for p in plan]
    if len(set(paths))!=len(paths):raise ValueError('导出文件名冲突')
    if any(p.exists() for p in paths):raise FileExistsError('导出目录有同名文件，请选择新的目录')
    completed=[]
    for i,(item,path) in enumerate(zip(plan,paths)):
        result=ScanResult(item.job.name,item.matches,[],targets=item.models)
        try:
            export(result,path,dpi=dpi,progress=lambda s:progress(f'文件 {i+1}/{len(plan)} · {s}'))
        except Exception as exc:
            raise RuntimeError(f'已保存 {len(completed)}/{len(plan)} 个 PDF 到 {folder}；{item.name} 导出失败：{exc}') from exc
        completed.append(path)
    return completed


def explain(job,match):
    same=[m for m in job.result.matches if m.model==match.model and m.barcode==match.barcode] if match.barcode else [match]
    direct=[m for m in same if 'barcode' not in m.method]
    lines=[f'目标款号：{match.model}',f'条码：{match.barcode or "未读取；仅按款号直接匹配"}']
    evidence=getattr(job.batch,'barcode_evidence',{}).get(match.barcode,[])
    if evidence:
        lines.append(f'生产单依据：{Path(job.batch.source).name}，'+ '、'.join(f'第 {e["page"]} 页第 {e["row"]} 条' for e in evidence)+ '，同一行 TXT1 ↔ Barcode。')
    else:lines.append(f'款号来源：{Path(job.batch.source).name} 的 TXT1 列。')
    if direct:
        lines.append('按款号直接找到：')
        for m in direct:lines.append(f'  {Path(m.source).name} · 第 {m.page} 页；其 Barcode = {m.barcode or "未读取"}')
    else:lines.append('没有同条码的款号直匹标签；关联依据来自 ProdSheet 同行 Barcode，不推测 MAIN 文件。')
    linked=[m for m in same if 'barcode' in m.method]
    if linked:
        lines.append(f'再按相同 Barcode {match.barcode} 关联到：')
        for m in linked:lines.append(f'  {Path(m.source).name} · 第 {m.page} 页 · '+('OCR 读码' if m.method.startswith('ocr') else 'PDF 文本读码'))
    lines.append(f'当前文件完整路径：{match.source}')
    return '\n'.join(lines)
