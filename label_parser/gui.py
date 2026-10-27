"""Batch workspace: one import, explicit selections, inspectable evidence, separated PDFs."""
import copy
import os
import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from collections import Counter
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import ImageTk
from .core import preview
from .workflow import discover,recognize,build_plan,export_plan,explain,role

class App:
    def __init__(self,root):
        self.root=root;self.jobs=[];self.issues=[];self.events=queue.Queue();self.working=False
        self.plan=[];self.photo=None;self.preview_key=None;self.preview_image=None;self.last_folder=None
        root.title('Label Studio · 批次标签工作台');root.geometry('1380x900');root.minsize(1120,760)
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',font=('PingFang SC',11),background='#edf3f6',foreground='#173346')
        style.configure('TButton',padding=(12,8));style.configure('Primary.TButton',background='#087e8c',foreground='white')
        style.configure('Treeview',rowheight=30,background='white',fieldbackground='white',borderwidth=0)
        style.configure('Treeview.Heading',background='#dce9ee',padding=(6,7),font=('PingFang SC',10,'bold'))
        style.map('Treeview',background=[('selected','#d2edf0')],foreground=[('selected','#163446')])
        style.configure('TNotebook.Tab',padding=(16,9))
        main=ttk.Frame(root,padding=20);main.pack(fill='both',expand=True);main.columnconfigure(0,weight=1);main.rowconfigure(5,weight=1)
        title=ttk.Frame(main);title.grid(row=0,column=0,sticky='ew')
        ttk.Label(title,text='批次标签工作台',font=('PingFang SC',24,'bold')).pack(side='left')
        ttk.Label(title,text='TXT1  →  标签款号  →  Barcode  →  关联文件',font=('Menlo',11),foreground='#517381').pack(side='right')
        ttk.Label(main,text='整批导入 · 按款号核对关联 · 勾选后分别导出',foreground='#517381').grid(row=1,column=0,sticky='w',pady=(3,12))
        actions=ttk.Frame(main);actions.grid(row=2,column=0,sticky='ew')
        self.import_btn=ttk.Button(actions,text='导入整批 PDF',style='Primary.TButton',command=self.choose_files);self.import_btn.pack(side='left')
        self.folder_btn=ttk.Button(actions,text='导入批次文件夹',command=self.choose_folder);self.folder_btn.pack(side='left',padx=8)
        self.rescan_btn=ttk.Button(actions,text='重新识别',command=self.rescan);self.rescan_btn.pack(side='left')
        self.export_btn=ttk.Button(actions,text='查看导出清单（0）',style='Primary.TButton',command=self.show_plan,state='disabled');self.export_btn.pack(side='right')
        self.batch_var=tk.StringVar()
        bar=ttk.Frame(main);bar.grid(row=3,column=0,sticky='ew',pady=12)
        ttk.Label(bar,text='当前批次').pack(side='left')
        self.batch_combo=ttk.Combobox(bar,textvariable=self.batch_var,state='readonly',width=40);self.batch_combo.pack(side='left',padx=10);self.batch_combo.bind('<<ComboboxSelected>>',self.render_job)
        self.summary=tk.StringVar(value='一次选择 ProdSheet 与 MAIN / CARE / COMPO 等全部 PDF')
        ttk.Label(bar,textvariable=self.summary).pack(side='left',padx=8)
        self.status=tk.StringVar(value='导出前需勾选款号；文件默认勾选。不同批次、不同文件不会合并。')
        ttk.Label(main,textvariable=self.status,wraplength=1250).grid(row=4,column=0,sticky='w',pady=(0,8))
        self.tabs=ttk.Notebook(main);self.tabs.grid(row=5,column=0,sticky='nsew')
        review=ttk.Frame(self.tabs,padding=10);self.tabs.add(review,text='识别与关联')
        export_tab=ttk.Frame(self.tabs,padding=12);self.tabs.add(export_tab,text='导出清单')
        panes=ttk.Panedwindow(review,orient='horizontal');panes.pack(fill='both',expand=True)
        left=ttk.Frame(panes);center=ttk.Frame(panes);right=ttk.Frame(panes)
        panes.add(left,weight=1);panes.add(center,weight=2);panes.add(right,weight=3)
        select_tabs=ttk.Notebook(left);select_tabs.pack(fill='both',expand=True)
        model_panel=ttk.Frame(select_tabs,padding=5);file_panel=ttk.Frame(select_tabs,padding=5)
        select_tabs.add(model_panel,text='勾选款号');select_tabs.add(file_panel,text='勾选文件')
        self.models=self.tree(model_panel,[('pick','导出',45),('model','TXT1 款号',150),('count','标签',45)])
        self.models.bind('<ButtonRelease-1>',lambda e:self.check_click(e,'model'));self.models.bind('<space>',lambda e:self.toggle_check('model'))
        self.models.bind('<<TreeviewSelect>>',self.render_matches)
        mbuttons=ttk.Frame(model_panel);mbuttons.pack(fill='x',pady=5)
        ttk.Button(mbuttons,text='全选款号',command=lambda:self.select_all('model',True)).pack(side='left')
        ttk.Button(mbuttons,text='清空',command=lambda:self.select_all('model',False)).pack(side='left',padx=6)
        self.files=self.tree(file_panel,[('pick','导出',45),('role','类型',65),('name','文件名',180)])
        self.files.bind('<ButtonRelease-1>',lambda e:self.check_click(e,'file'));self.files.bind('<space>',lambda e:self.toggle_check('file'))
        fb=ttk.Frame(file_panel);fb.pack(fill='x',pady=5)
        ttk.Button(fb,text='全选文件',command=lambda:self.select_all('file',True)).pack(side='left')
        ttk.Button(fb,text='清空',command=lambda:self.select_all('file',False)).pack(side='left',padx=6)
        ttk.Label(left,text='点击款号查看；点击 ☐ / ☑ 控制导出。',foreground='#517381',wraplength=245).pack(anchor='w',pady=5)
        ttk.Label(center,text='匹配标签',font=('PingFang SC',13,'bold')).pack(anchor='w',pady=(3,9))
        self.matches=self.tree(center,[('type','文件',75),('barcode','Barcode',135),('page','页',40),('method','识别方式',105)])
        self.matches.bind('<<TreeviewSelect>>',self.show_match)
        self.detail_tabs=ttk.Notebook(right);self.detail_tabs.pack(fill='both',expand=True,padx=(10,0))
        pic=ttk.Frame(self.detail_tabs);trace=ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(pic,text='标签预览');self.detail_tabs.add(trace,text='文件关联链')
        self.canvas=tk.Canvas(pic,bg='white',width=360,height=200,highlightthickness=1,highlightbackground='#b5d4df');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self.show_match)
        self.trace=tk.Text(trace,wrap='word',font=('PingFang SC',11),bg='white',fg='#173346',relief='flat',padx=14,pady=14,width=38,state='disabled')
        ts=ttk.Scrollbar(trace,command=self.trace.yview);self.trace.configure(yscrollcommand=ts.set);ts.pack(side='right',fill='y');self.trace.pack(fill='both',expand=True)
        self.detail=tk.StringVar(value='选择标签后可查看完整文件名、页码及关联依据')
        ttk.Label(right,textvariable=self.detail,wraplength=390).pack(anchor='w',padx=10,pady=6)
        ttk.Button(right,text='打开当前来源 PDF',command=self.open_source).pack(anchor='e',pady=4)
        # Export controls are fixed above the expanding plan table.
        opts=ttk.Frame(export_tab);opts.pack(fill='x',pady=(0,12))
        ttk.Label(opts,text='拆分方式').pack(side='left')
        self.split=tk.StringVar(value='按批次 + 文件分开')
        self.split_combo=ttk.Combobox(opts,textvariable=self.split,values=['按批次 + 文件分开','按批次 + 款号 + 文件分开'],width=25,state='readonly');self.split_combo.pack(side='left',padx=8);self.split_combo.bind('<<ComboboxSelected>>',lambda e:self.update_plan())
        ttk.Label(opts,text='清晰度').pack(side='left',padx=(15,0))
        self.dpi=tk.StringVar(value='300');ttk.Combobox(opts,textvariable=self.dpi,values=['200','300','400'],state='readonly',width=6).pack(side='left',padx=8)
        ttk.Label(opts,text='DPI').pack(side='left')
        self.save_btn=ttk.Button(opts,text='导出清单中的 PDF',style='Primary.TButton',command=self.save,state='disabled');self.save_btn.pack(side='right')
        self.plan_summary=tk.StringVar(value='尚未勾选款号。到“识别与关联”勾选需要导出的款号和文件。')
        ttk.Label(export_tab,textvariable=self.plan_summary,wraplength=1000).pack(anchor='w',pady=(0,8))
        self.plan_tree=self.tree(export_tab,[('batch','批次',135),('file','来源文件',200),('model','款号',150),('count','页数',60),('output','独立输出 PDF',400)])
        self.open_btn=ttk.Button(export_tab,text='打开导出文件夹',command=lambda:self.open_path(self.last_folder),state='disabled');self.open_btn.pack(anchor='e',pady=(8,0))
        footer=ttk.Frame(main);footer.grid(row=6,column=0,sticky='ew',pady=(10,0))
        self.progress=ttk.Progressbar(footer,mode='indeterminate');self.progress.pack(fill='x')
        self.notice=tk.Text(main,height=2,wrap='word',font=('PingFang SC',10),bg='#edf3f6',fg='#8a5a28',relief='flat',state='disabled');self.notice.grid(row=7,column=0,sticky='ew',pady=(6,0))
        root.after(100,self.poll)

    def tree(self,parent,columns):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        tree=ttk.Treeview(frame,columns=[c[0] for c in columns],show='headings',selectmode='browse',height=8)
        for key,title,width in columns:tree.heading(key,text=title);tree.column(key,width=width,minwidth=35,stretch=True)
        y=ttk.Scrollbar(frame,command=tree.yview);x=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew')
        return tree

    def current(self):
        i=self.batch_combo.current()
        return self.jobs[i] if 0<=i<len(self.jobs) else None

    def busy(self,on):
        self.working=on
        for b in [self.import_btn,self.folder_btn,self.rescan_btn]:b.configure(state='disabled' if on else 'normal')
        self.save_btn.configure(state='normal' if self.plan and not on else 'disabled')
        self.export_btn.configure(state='normal' if self.plan and not on else 'disabled')
        if on:self.progress.start(15)
        else:self.progress.stop()

    def choose_files(self):
        paths=filedialog.askopenfilenames(title='一次选择 ProdSheet 和本批次所有标签 PDF',filetypes=[('PDF','*.pdf')])
        if paths:self.load(paths)

    def choose_folder(self):
        path=filedialog.askdirectory(title='选择批次文件夹；可包含多个批次子文件夹')
        if path:self.load([path])

    def load(self,paths):
        self.busy(True);self.status.set('自动识别文件角色及批次…')
        def worker():
            try:
                jobs,issues=discover(paths,lambda s:self.events.put(('progress',s)))
                for job in jobs:recognize(job,lambda s:self.events.put(('progress',s)))
                self.events.put(('loaded',(jobs,issues)))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def rescan(self):
        if self.jobs:self.load([p for j in self.jobs for p in [j.batch.source]+j.sources])

    def render_job(self,event=None):
        job=self.current()
        for tree in [self.models,self.files,self.matches]:tree.delete(*tree.get_children())
        self.canvas.delete('all');self.preview_key=None
        if not job:return
        counts=Counter(m.model for m in job.result.matches) if job.result else Counter()
        for i,model in enumerate(job.batch.models):self.models.insert('','end',iid=str(i),values=('☑' if model in job.models_selected else '☐',model,counts[model]))
        for i,path in enumerate(job.sources):self.files.insert('','end',iid=str(i),values=('☑' if path in job.files_selected else '☐',role(path),Path(path).name))
        self.summary.set(f'{len(job.batch.models)} 款 · {len(job.sources)} 文件 · {len(job.result.matches) if job.result else 0} 标签')
        if job.batch.models:self.models.selection_set('0')
        self.update_plan()

    def check_click(self,event,kind):
        tree=self.models if kind=='model' else self.files
        if tree.identify_column(event.x)=='#1' and tree.identify_row(event.y):self.toggle_check(kind)

    def toggle_check(self,kind):
        if self.working:return
        job=self.current();tree=self.models if kind=='model' else self.files
        items=tree.selection()
        if not job or not items:return
        i=int(items[0]);value=job.batch.models[i] if kind=='model' else job.sources[i]
        selected=job.models_selected if kind=='model' else job.files_selected
        if value in selected:selected.remove(value)
        else:selected.add(value)
        vals=list(tree.item(items[0],'values'));vals[0]='☑' if value in selected else '☐';tree.item(items[0],values=vals);self.update_plan()
        return 'break'

    def select_all(self,kind,on):
        if self.working:return
        job=self.current()
        if not job:return
        if kind=='model':job.models_selected=set(job.batch.models) if on else set()
        else:job.files_selected=set(job.sources) if on else set()
        current=self.models.selection();self.render_job()
        if current:self.models.selection_set(current)

    def render_matches(self,event=None):
        self.matches.delete(*self.matches.get_children());self.canvas.delete('all');self.preview_key=None
        job=self.current();items=self.models.selection()
        if not job or not job.result or not items:return
        model=job.batch.models[int(items[0])]
        for i,m in enumerate(job.result.matches):
            if m.model!=model:continue
            method=('OCR · ' if m.method.startswith('ocr') else '')+('条码关联' if 'barcode' in m.method else '款号直匹')
            self.matches.insert('','end',iid=str(i),values=(role(m.source),m.barcode,m.page,method))
        rows=self.matches.get_children()
        if rows:self.matches.selection_set(rows[0])
        else:self.detail.set(f'{model} 暂无匹配标签，请检查批次文件和待检查项。')

    def chosen_match(self):
        job=self.current();items=self.matches.selection()
        return (job,job.result.matches[int(items[0])]) if job and job.result and items else (None,None)

    def show_match(self,event=None):
        job,m=self.chosen_match()
        if not m:return
        key=(m.source,m.page,tuple(m.rect))
        try:
            if self.preview_key!=key:
                self.preview_image=preview(m);self.preview_key=key
                self.trace.configure(state='normal');self.trace.delete('1.0','end');self.trace.insert('end',explain(job,m));self.trace.configure(state='disabled')
            im=self.preview_image.copy();im.thumbnail((max(60,self.canvas.winfo_width()-16),max(60,self.canvas.winfo_height()-16)))
            self.photo=ImageTk.PhotoImage(im);self.canvas.delete('all');self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.photo)
            self.detail.set(f'{m.model}\n{Path(m.source).name} · 第 {m.page} 页\nBarcode {m.barcode or "未读取"}')
        except Exception as e:self.detail.set(str(e))

    def update_plan(self):
        self.plan=build_plan(self.jobs,self.split.get()=='按批次 + 款号 + 文件分开')
        self.plan_tree.delete(*self.plan_tree.get_children())
        for i,p in enumerate(self.plan):self.plan_tree.insert('','end',iid=str(i),values=(p.job.name,Path(p.source).name,', '.join(p.models),len(p.matches),p.name))
        self.export_btn.configure(text=f'查看导出清单（{len(self.plan)}）')
        pages=sum(len(p.matches) for p in self.plan)
        self.plan_summary.set(f'将生成 {len(self.plan)} 个独立 PDF，共 {pages} 页。按勾选款号与文件的交集导出，不混合批次或来源文件。' if self.plan else '请先勾选需要导出的款号和文件；不会默认全量导出。')
        self.busy(self.working)

    def show_plan(self):self.update_plan();self.tabs.select(1)

    def save(self):
        if not self.plan:return
        folder=filedialog.askdirectory(title=f'选择保存位置：生成 {len(self.plan)} 个独立 PDF')
        if not folder:return
        output=Path(folder)/('标签导出_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        plan=copy.deepcopy(self.plan);dpi=int(self.dpi.get());self.busy(True)
        def worker():
            try:
                paths=export_plan(plan,output,dpi,lambda s:self.events.put(('progress',s)))
                self.events.put(('saved',(output,len(paths))))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def open_path(self,path):
        if not path:return
        try:
            if sys.platform=='darwin':subprocess.run(['open',str(path)],check=True)
            elif sys.platform=='win32':os.startfile(str(path))
            else:subprocess.run(['xdg-open',str(path)],check=True)
        except Exception as e:messagebox.showerror('无法打开',str(e))

    def open_source(self):
        _,m=self.chosen_match()
        if m:self.open_path(m.source)

    def poll(self):
        try:
            while True:
                event,data=self.events.get_nowait()
                if event=='progress':self.status.set(data)
                elif event=='error':self.busy(False);self.status.set('处理未完成，请查看错误信息');messagebox.showerror('处理失败',data)
                elif event=='loaded':
                    incoming,issues=data
                    # Preserve choices for existing batches; importing another batch adds to the workspace.
                    known={j.key:j for j in self.jobs}
                    for j in incoming:
                        if j.key in known:
                            j.models_selected=known[j.key].models_selected & set(j.batch.models)
                            j.files_selected=(known[j.key].files_selected & set(j.sources)) | (set(j.sources)-set(known[j.key].sources))
                        known[j.key]=j
                    self.jobs=list(known.values());self.issues=issues
                    self.batch_combo.configure(values=[f'{j.name} · {Path(j.batch.source).name}' for j in self.jobs])
                    if self.jobs:self.batch_combo.current(0)
                    self.busy(False);self.render_job()
                    self.status.set(f'已识别 {len(self.jobs)} 个批次 · 复用 {sum(j.result.cached_files for j in incoming if j.result)} 个文件的识别结果。勾选款号后查看导出清单。')
                    notes=issues+[w for j in self.jobs if j.result for w in j.result.warnings]
                    self.notice.configure(state='normal');self.notice.delete('1.0','end');self.notice.insert('end','\n'.join(notes) or '没有报告识别异常。点击“文件关联链”可追溯 ProdSheet、直接匹配及条码关联。');self.notice.configure(state='disabled')
                elif event=='saved':
                    self.last_folder,count=data;self.busy(False);self.open_btn.configure(state='normal')
                    self.status.set(f'已生成 {count} 个独立 PDF：{self.last_folder}');self.open_path(self.last_folder)
        except queue.Empty:pass
        self.root.after(100,self.poll)

def main():
    root=tk.Tk();App(root);root.mainloop()
