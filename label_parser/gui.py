"""Local ProdSheet-driven batch label browser."""
import copy
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from collections import Counter
from PIL import ImageTk
from .core import scan_batch, export, preview
from .prodsheet import read_prodsheet

class App:
    def __init__(self,root):
        self.root=root;self.result=None;self.batch=None;self.inputs=[]
        self.last_output=None;self.photo=None;self.events=queue.Queue();self.working=False
        self.preview_key=None;self.preview_image=None
        root.title('标签解析 · ProdSheet 批次识别');root.geometry('1240x840');root.minsize(1000,720)
        root.configure(bg='#eef4f6')
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',font=('PingFang SC',11),background='#eef4f6',foreground='#18323e')
        style.configure('TButton',padding=(10,7));style.configure('Accent.TButton',background='#007f91',foreground='white')
        style.configure('Treeview',rowheight=28,background='white',fieldbackground='white')
        style.map('Treeview',background=[('selected','#cdeff2')],foreground=[('selected','#18323e')])
        main=ttk.Frame(root,padding=18);main.pack(fill='both',expand=True)
        main.columnconfigure(0,weight=1);main.rowconfigure(7,weight=1)
        ttk.Label(main,text='批次标签解析',font=('PingFang SC',23,'bold')).grid(row=0,column=0,sticky='w',pady=(0,8))
        sheet=ttk.Frame(main);sheet.grid(row=1,column=0,sticky='ew',pady=4)
        self.sheet_btn=ttk.Button(sheet,text='① 选择 ProdSheet',command=self.choose_sheet);self.sheet_btn.pack(side='left')
        self.sheet_info=tk.StringVar(value='自动读取 TXT1 款号及同行 Barcode')
        ttk.Label(sheet,textvariable=self.sheet_info).pack(side='left',padx=12)
        files=ttk.Frame(main);files.grid(row=2,column=0,sticky='ew',pady=4)
        self.browse_btn=ttk.Button(files,text='② 添加批次 PDF（多选）',command=self.choose);self.browse_btn.pack(side='left')
        self.remove_btn=ttk.Button(files,text='移除所选文件',command=self.remove_files);self.remove_btn.pack(side='left',padx=8)
        self.scan_btn=ttk.Button(files,text='重新识别批次',command=self.start,style='Accent.TButton');self.scan_btn.pack(side='left')
        self.file_count=tk.StringVar(value='0 个待识别文件')
        ttk.Label(files,textvariable=self.file_count).pack(side='left',padx=12)
        filebox=ttk.Frame(main);filebox.grid(row=3,column=0,sticky='ew')
        self.file_list=tk.Listbox(filebox,height=3,selectmode='extended',exportselection=False,font=('PingFang SC',10),relief='flat')
        fs=ttk.Scrollbar(filebox,orient='vertical',command=self.file_list.yview);self.file_list.configure(yscrollcommand=fs.set)
        fs.pack(side='right',fill='y');self.file_list.pack(fill='x',expand=True)
        actions=ttk.Frame(main);actions.grid(row=4,column=0,sticky='ew',pady=8)
        self.export_all_btn=ttk.Button(actions,text='全批次汇总并查看',command=lambda:self.save(all_matches=True),style='Accent.TButton',state='disabled');self.export_all_btn.pack(side='left')
        self.export_btn=ttk.Button(actions,text='导出勾选项',command=self.save,state='disabled');self.export_btn.pack(side='left',padx=8)
        self.open_btn=ttk.Button(actions,text='查看已导出 PDF',command=self.open_output,state='disabled');self.open_btn.pack(side='left')
        self.keyword=tk.StringVar(value='FBL015-166-03')
        self.manual_btn=ttk.Button(actions,text='按手动款号识别',command=lambda:self.start(manual=True));self.manual_btn.pack(side='right')
        ttk.Entry(actions,textvariable=self.keyword,width=19,font=('Menlo',10)).pack(side='right',padx=8)
        self.status=tk.StringVar(value='先选择 ProdSheet，再添加同一批次 PDF；两者齐备后自动识别。')
        ttk.Label(main,textvariable=self.status,wraplength=950).grid(row=5,column=0,sticky='w')
        self.bar=ttk.Progressbar(main,mode='indeterminate');self.bar.grid(row=6,column=0,sticky='ew',pady=8)
        panes=ttk.Panedwindow(main,orient='horizontal');panes.grid(row=7,column=0,sticky='nsew')
        models=ttk.Frame(panes);labels=ttk.Frame(panes);picture=ttk.Frame(panes)
        panes.add(models,weight=1);panes.add(labels,weight=2);panes.add(picture,weight=3)
        ttk.Label(models,text='TXT1 款号 / 匹配数量',font=('PingFang SC',12,'bold')).pack(anchor='w',pady=(0,6))
        self.models=self.make_tree(models,('model','count'),[('目标款号',155),('数量',50)],height=8)
        self.models.bind('<<TreeviewSelect>>',self.filter_results)
        ttk.Label(labels,text='对应标签 · 双击切换勾选',font=('PingFang SC',12,'bold')).pack(anchor='w',pady=(0,6))
        self.toggle_btn=ttk.Button(labels,text='包含 / 排除此标签',command=self.toggle,state='disabled');self.toggle_btn.pack(side='bottom',anchor='w',pady=5)
        self.tree=self.make_tree(labels,('selected','file','page','method'),[('导出',45),('文件',165),('页',40),('匹配方式',95)],height=8)
        self.tree.bind('<<TreeviewSelect>>',self.show_preview);self.tree.bind('<Double-1>',lambda e:self.toggle())
        ttk.Label(picture,text='完整标签预览',font=('PingFang SC',12,'bold')).pack(anchor='w',padx=10,pady=(0,6))
        self.canvas=tk.Canvas(picture,bg='white',highlightthickness=1,highlightbackground='#a8cfd4',width=330,height=180)
        self.canvas.pack(fill='both',expand=True,padx=(10,0));self.canvas.bind('<Configure>',self.show_preview)
        self.detail=tk.StringVar(value='点击标签查看完整内容')
        ttk.Label(main,textvariable=self.detail,wraplength=950).grid(row=8,column=0,sticky='w',pady=5)
        self.notice=tk.Text(main,height=2,wrap='word',bg='#eef4f6',fg='#6e4b1c',relief='flat',font=('PingFang SC',10),state='disabled')
        self.notice.grid(row=9,column=0,sticky='ew')
        root.after(100,self.poll)

    def make_tree(self,parent,columns,headings,height):
        box=ttk.Frame(parent);box.pack(fill='both',expand=True)
        tree=ttk.Treeview(box,columns=columns,show='headings',selectmode='browse',height=height)
        for col,(title,width) in zip(columns,headings):tree.heading(col,text=title);tree.column(col,width=width,minwidth=35,anchor='w')
        sc=ttk.Scrollbar(box,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=sc.set)
        sc.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
        return tree

    def set_notice(self,text):
        self.notice.configure(state='normal');self.notice.delete('1.0','end');self.notice.insert('end',text);self.notice.configure(state='disabled')

    def busy(self,on):
        self.working=on
        for button in [self.sheet_btn,self.browse_btn,self.remove_btn,self.scan_btn,self.manual_btn]:button.configure(state='disabled' if on else 'normal')
        self.export_all_btn.configure(state='normal' if not on and self.result and self.result.matches else 'disabled')
        self.export_btn.configure(state='normal' if not on and self.result and any(m.selected for m in self.result.matches) else 'disabled')
        self.toggle_btn.configure(state='normal' if not on and self.result and self.result.matches else 'disabled')
        if on:self.bar.start(15)
        else:self.bar.stop()

    def clear_results(self):
        self.result=None;self.tree.delete(*self.tree.get_children());self.canvas.delete('all')
        self.preview_key=None;self.preview_image=None;self.detail.set('点击标签查看完整内容')
        self.populate_models();self.busy(False)

    def choose_sheet(self):
        path=filedialog.askopenfilename(title='选择本批次 ProdSheet',filetypes=[('PDF','*.pdf')])
        if not path:return
        self.batch=None;self.clear_results();self.busy(True);self.sheet_info.set('正在读取 TXT1…')
        def worker():
            try:self.events.put(('batch',read_prodsheet(path,self.progress)))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def progress(self,text):self.events.put(('progress',text))

    def choose(self):
        paths=filedialog.askopenfilenames(title='选择同一批次的多个标签 PDF',filetypes=[('PDF','*.pdf'),('图片','*.png *.jpg *.jpeg')])
        if not paths:return
        for p in paths:
            p=str(Path(p).resolve())
            if p not in self.inputs and (not self.batch or p!=self.batch.source):self.inputs.append(p)
        self.refresh_files();self.clear_results()
        if self.batch and self.inputs:self.start()
        else:self.status.set('文件已添加。请选择 ProdSheet，或使用手动款号识别。')

    def refresh_files(self):
        self.file_list.delete(0,'end')
        for p in self.inputs:self.file_list.insert('end',p)
        self.file_count.set(f'{len(self.inputs)} 个待识别文件')

    def remove_files(self):
        for i in reversed(self.file_list.curselection()):self.inputs.pop(i)
        self.refresh_files();self.clear_results();self.status.set('文件列表已变更，请重新识别批次。')

    def start(self,manual=False):
        if self.working:return
        if not self.inputs:messagebox.showerror('缺少文件','请添加本批次标签 PDF。');return
        if not manual and not self.batch:messagebox.showerror('缺少 ProdSheet','请先选择 ProdSheet，或使用手动款号识别。');return
        targets=[self.keyword.get().strip()] if manual else list(self.batch.models)
        if not all(targets):messagebox.showerror('缺少款号','请输入目标款号。');return
        batch=self.batch
        inputs=list(self.inputs);self.clear_results();self.busy(True)
        self.set_notice('正在扫描全部文件、全部页面…')
        def worker():
            try:
                result=scan_batch(inputs,targets,batch.barcode_models if batch else {},self.progress,[batch.source] if batch else [])
                if batch:result.warnings=batch.warnings+result.warnings
                self.events.put(('result',result))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def populate_models(self):
        self.models.delete(*self.models.get_children())
        targets=self.result.targets if self.result else (self.batch.models if self.batch else [])
        counts=Counter(m.model for m in self.result.matches) if self.result else Counter()
        self.models.insert('','end',iid='all',values=('全部款号',sum(counts.values()) if self.result else '待识别'))
        for index,model in enumerate(targets):self.models.insert('','end',iid=str(index),values=(model,counts[model] if self.result else '待识别'))
        self.models.selection_set('all')

    def filter_results(self,event=None):
        self.tree.delete(*self.tree.get_children());self.canvas.delete('all');self.preview_key=None
        if not self.result:return
        selected=self.models.selection();key=selected[0] if selected else 'all'
        target=None if key=='all' else self.result.targets[int(key)]
        for i,m in enumerate(self.result.matches):
            if target and m.model!=target:continue
            method=('OCR+' if m.method.startswith('ocr') else '')+('条码关联' if 'barcode' in m.method else '款号匹配')
            self.tree.insert('','end',iid=str(i),values=('✓' if m.selected else '—',Path(m.source).name,m.page,method))
        items=self.tree.get_children()
        if items:self.tree.selection_set(items[0])
        else:self.detail.set(f'{target or "当前批次"}：没有匹配标签，请检查待检查项或补充批次文件。')

    def update_count(self):
        if not self.result:return
        n=sum(m.selected for m in self.result.matches);found=len(set(m.model for m in self.result.matches))
        self.status.set(f'已扫描 {self.result.files} 个文件 / {self.result.pages} 页 · 款号匹配 {found}/{len(self.result.targets)} · 标签 {len(self.result.matches)} 个 · 勾选 {n} 个 · 待检查 {len(self.result.warnings)} 项')
        self.busy(self.working)

    def show_preview(self,event=None):
        selected=self.tree.selection()
        if not selected or not self.result:return
        i=int(selected[0]);m=self.result.matches[i]
        try:
            if self.preview_key!=i:self.preview_image=preview(m);self.preview_key=i
            im=self.preview_image.copy();im.thumbnail((max(80,self.canvas.winfo_width()-20),max(80,self.canvas.winfo_height()-20)))
            self.photo=ImageTk.PhotoImage(im);self.canvas.delete('all');self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.photo)
            self.detail.set(f'{m.model} · {Path(m.source).name} · 第 {m.page} 页 · 条码 {m.barcode or "未读取"}')
        except Exception as e:self.detail.set(f'预览失败：{e}')

    def toggle(self):
        if self.working or not self.result:return
        items=self.tree.selection()
        if not items:return
        i=int(items[0]);m=self.result.matches[i];m.selected=not m.selected
        values=list(self.tree.item(str(i),'values'));values[0]='✓' if m.selected else '—';self.tree.item(str(i),values=values);self.update_count()

    def poll(self):
        try:
            while True:
                event,data=self.events.get_nowait()
                if event=='progress':self.status.set(data)
                elif event=='error':
                    self.busy(False);self.status.set('处理失败，请检查错误信息');messagebox.showerror('处理失败',data)
                    if not self.batch:self.sheet_info.set('尚未读取有效 ProdSheet')
                elif event=='batch':
                    self.batch=data;self.sheet_info.set(f'{Path(data.source).name} · {len(data.models)} 个款号 / {data.rows} 条明细')
                    self.inputs=[p for p in self.inputs if p!=data.source];self.refresh_files();self.populate_models();self.busy(False)
                    self.set_notice('\n'.join(data.warnings) or 'TXT1 已读取。请选择同一批次标签 PDF。')
                    if self.inputs:self.start()
                    else:self.status.set(f'已读取 {len(data.models)} 个目标款号，等待添加批次 PDF。')
                elif event=='result':
                    self.result=data;self.busy(False);self.populate_models();self.filter_results();self.update_count()
                    found={m.model for m in data.matches};missing=[k for k in data.targets if k not in found]
                    notices=list(data.warnings)
                    if missing:notices.insert(0,'未匹配款号：'+', '.join(missing))
                    self.set_notice('\n'.join(notices) or '已完成批次识别。汇总按款号分组，仅导出 PDF。')
                elif event=='saved':
                    self.last_output=Path(data);self.busy(False);self.open_btn.configure(state='normal');self.status.set(f'PDF 已导出：{data}');self.open_output()
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def open_output(self):
        if not self.last_output:return
        try:
            if sys.platform=='darwin':subprocess.run(['open',str(self.last_output)],check=True)
            elif sys.platform=='win32':os.startfile(str(self.last_output))
            else:subprocess.run(['xdg-open',str(self.last_output)],check=True)
        except Exception as e:messagebox.showerror('PDF 已保存，打开失败',f'{self.last_output}\n{e}')

    def save(self,all_matches=False):
        if not self.result:return
        name=(Path(self.batch.source).stem+'_标签汇总') if self.batch else self.result.keyword+'_标签汇总'
        path=filedialog.asksaveasfilename(title='导出汇总 PDF',defaultextension='.pdf',initialfile=name+'.pdf',filetypes=[('PDF','*.pdf')])
        if not path:return
        self.busy(True);self.status.set('正在生成汇总 PDF…')
        result=copy.deepcopy(self.result)
        if all_matches:
            for m in result.matches:m.selected=True
        def worker():
            try:export(result,Path(path),progress=self.progress);self.events.put(('saved',path))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

def main():
    root=tk.Tk();App(root);root.mainloop()
