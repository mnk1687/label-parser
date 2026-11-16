"""Modern light desktop workspace for Excel-first per-barcode compositions."""
import queue,threading,copy,subprocess,sys,os
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import customtkinter as ctk
from PIL import Image,ImageTk
from . import __version__,updater
from .workflow import discover,recognize,role,explain
from .export_verification import verify_excel, save_report, completion_message
from .categories import KINDS,category_preview,export_categories
from .composition import sorted_rows,make_compositions,compose,write_excel,export_compositions

FONT_FAMILY='Microsoft YaHei UI' if sys.platform=='win32' else 'PingFang SC'

BG='#F5F7FB';WHITE='#FFFFFF';INK='#17233B';MUTED='#738096';BLUE='#4269E1';LINE='#E7ECF3'
ctk.set_appearance_mode('light')

class App:
    def __init__(self,root):
        self.root=root;self.jobs=[];self.events=queue.Queue();self.working=False;self.updating=False;self.available_update=None
        self.selected={};self.items=[];self.visible=[];self.preview_cache={};self.photo=None;self.last_folder=None;self.category_page=0;self.category_image=None
        root.title('LabelDesk · 生产标签');root.geometry('1450x920');root.minsize(1180,760);root.configure(fg_color=BG)
        root.grid_rowconfigure(0,weight=1);root.grid_columnconfigure(1,weight=1)
        self.font=ctk.CTkFont(family=FONT_FAMILY,size=13)
        side=ctk.CTkFrame(root,width=210,corner_radius=0,fg_color=WHITE);side.grid(row=0,column=0,sticky='nsew');side.grid_propagate(False)
        ctk.CTkLabel(side,text='LabelDesk',text_color=INK,font=ctk.CTkFont(size=27,weight='bold')).pack(anchor='w',padx=24,pady=(30,0))
        ctk.CTkLabel(side,text='生产标签工作台',text_color=MUTED,font=self.font).pack(anchor='w',padx=24,pady=(2,28))
        self.import_btn=self.button(side,'＋  导入整批 PDF',self.choose_files);self.import_btn.pack(fill='x',padx=18)
        self.folder_btn=self.button(side,'选择批次文件夹',self.choose_folder,False);self.folder_btn.pack(fill='x',padx=18,pady=8)
        self.clear_btn=self.button(side,'清除全部导入数据',self.clear_imports,False);self.clear_btn.pack(fill='x',padx=18,pady=(0,8))
        ctk.CTkLabel(side,text='当前批次',text_color=MUTED,font=self.font).pack(anchor='w',padx=24,pady=(25,5))
        self.batch_choice=ctk.CTkOptionMenu(side,values=['尚未导入'],command=self.change_job,width=170,fg_color='#EEF2FC',button_color='#E3EAFB',text_color=INK);self.batch_choice.pack(padx=18,fill='x')
        ctk.CTkLabel(side,text='输出流程',text_color=MUTED,font=self.font).pack(anchor='w',padx=24,pady=(32,5))
        for label in ['01   整理 ProdSheet 明细','02   核对 Barcode 组合','03   TXT1 文件夹 / TXT2 PDF']:
            ctk.CTkLabel(side,text=label,text_color=INK,font=ctk.CTkFont(size=12),anchor='w').pack(fill='x',padx=24,pady=7)
        ctk.CTkLabel(side,text='源文件保持不变\n原生 PDF 内容直接组合',justify='left',text_color=MUTED,font=ctk.CTkFont(size=11)).pack(side='bottom',anchor='w',padx=24,pady=26)
        update_bar=ctk.CTkFrame(side,fg_color='transparent');update_bar.pack(side='bottom',fill='x',padx=18,pady=(0,4))
        self.update_btn=self.button(update_bar,'检查更新',self.check_updates,False);self.update_btn.pack(fill='x')
        ctk.CTkLabel(update_bar,text=f'当前版本 v{__version__}',text_color=MUTED,font=ctk.CTkFont(size=11),anchor='w').pack(fill='x',pady=(5,0))
        main=ctk.CTkFrame(root,fg_color='transparent');main.grid(row=0,column=1,sticky='nsew',padx=26,pady=24);main.grid_columnconfigure(0,weight=1);main.grid_rowconfigure(4,weight=1)
        head=ctk.CTkFrame(main,fg_color='transparent');head.grid(row=0,column=0,sticky='ew')
        ctk.CTkLabel(head,text='明细与组合',font=ctk.CTkFont(size=27,weight='bold'),text_color=INK).pack(side='left')
        self.export_btn=self.button(head,'导出所选组合',self.save);self.export_btn.pack(side='right')
        self.excel_btn=self.button(head,'导出排序 Excel',self.save_excel,False);self.excel_btn.pack(side='right',padx=10)
        self.summary=tk.StringVar(value='导入生产单与标签文件，自动整理为可核对的生产明细。')
        ctk.CTkLabel(main,textvariable=self.summary,text_color=MUTED,font=self.font,anchor='w').grid(row=1,column=0,sticky='ew',pady=(3,18))
        self.feature_tabs=ctk.CTkSegmentedButton(main,values=['组合导出','分类排序'],command=self.switch_feature,selected_color=BLUE,font=self.font,height=38)
        self.feature_tabs.grid(row=2,column=0,sticky='w',pady=(0,12));self.feature_tabs.set('组合导出')
        filters=ctk.CTkFrame(main,fg_color=WHITE,corner_radius=12);filters.grid(row=3,column=0,sticky='ew',pady=(0,14))
        self.search=ctk.CTkEntry(filters,placeholder_text='搜索 TXT1、TXT2 或 Barcode',width=270,height=38,border_width=0,fg_color='#F3F5F9',font=self.font);self.search.pack(side='left',padx=14,pady=12);self.search.bind('<KeyRelease>',lambda e:self.render_rows())
        self.model_filter=ctk.CTkOptionMenu(filters,values=['全部款号'],width=200,command=lambda v:self.render_rows(),fg_color='#F3F5F9',button_color='#E7ECF4',text_color=INK);self.model_filter.pack(side='left',padx=5)
        self.button(filters,'勾选当前筛选',lambda:self.select_visible(True),False).pack(side='left',padx=8)
        self.button(filters,'清空勾选',lambda:self.select_visible(False),False).pack(side='left')
        self.count=tk.StringVar(value='已选 0 条');ctk.CTkLabel(filters,textvariable=self.count,text_color=MUTED,font=self.font).pack(side='right',padx=14)
        body=ctk.CTkFrame(main,fg_color='transparent');body.grid(row=4,column=0,sticky='nsew');body.grid_rowconfigure(0,weight=1);body.grid_columnconfigure(0,weight=3);body.grid_columnconfigure(1,weight=2)
        tablecard=ctk.CTkFrame(body,fg_color=WHITE,corner_radius=14);tablecard.grid(row=0,column=0,sticky='nsew',padx=(0,14));tablecard.grid_columnconfigure(0,weight=1);tablecard.grid_rowconfigure(1,weight=1)
        ctk.CTkLabel(tablecard,text='生产明细   /   按 TXT1 · 颜色 · 尺码排序',text_color=INK,font=ctk.CTkFont(size=14,weight='bold'),anchor='w').grid(row=0,column=0,sticky='ew',padx=16,pady=14)
        holder=ctk.CTkFrame(tablecard,fg_color=WHITE,corner_radius=0);holder.grid(row=1,column=0,sticky='nsew',padx=12,pady=(0,12));holder.grid_columnconfigure(0,weight=1);holder.grid_rowconfigure(0,weight=1)
        style=ttk.Style();style.theme_use('clam');style.configure('Modern.Treeview',font=(FONT_FAMILY,11),rowheight=36,background=WHITE,fieldbackground=WHITE,foreground=INK,borderwidth=0,relief='flat');style.configure('Modern.Treeview.Heading',font=(FONT_FAMILY,10,'bold'),background='#F5F7FB',foreground=MUTED,borderwidth=0,padding=8,relief='flat');style.map('Modern.Treeview',background=[('selected','#EDF2FF')],foreground=[('selected',INK)])
        self.table=ttk.Treeview(holder,style='Modern.Treeview',columns=['pick','size','txt1','txt2','barcode','quantity','status'],show='headings',selectmode='browse')
        for col,text,width in [('pick','选择',45),('size','Size',50),('txt1','TXT1',135),('txt2','TXT2 / 文件名',210),('barcode','Barcode',140),('quantity','数量',55),('status','组合',70)]:self.table.heading(col,text=text);self.table.column(col,width=width,minwidth=40,stretch=False)
        self.table.tag_configure('alternate',background='#FAFBFD');self.table.tag_configure('missing',foreground='#C17D2D')
        y=ttk.Scrollbar(holder,command=self.table.yview);x=ttk.Scrollbar(holder,orient='horizontal',command=self.table.xview);self.table.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.table.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew')
        self.table.bind('<<TreeviewSelect>>',self.show_item);self.table.bind('<ButtonRelease-1>',self.check_click);self.table.bind('<space>',lambda e:self.toggle_row())
        previewcard=ctk.CTkFrame(body,fg_color=WHITE,corner_radius=14);previewcard.grid(row=0,column=1,sticky='nsew');previewcard.grid_columnconfigure(0,weight=1);previewcard.grid_rowconfigure(2,weight=1)
        self.preview_title=tk.StringVar(value='组合预览')
        ctk.CTkLabel(previewcard,textvariable=self.preview_title,font=ctk.CTkFont(size=15,weight='bold'),text_color=INK,anchor='w').grid(row=0,column=0,padx=18,pady=(16,8),sticky='ew')
        self.view_mode=ctk.CTkSegmentedButton(previewcard,values=['组合预览','关联来源'],command=self.switch_view,selected_color=BLUE,font=self.font);self.view_mode.grid(row=1,column=0,padx=16,pady=(0,12),sticky='ew');self.view_mode.set('组合预览')
        self.canvas=tk.Canvas(previewcard,bg='#F2F4F8',highlightthickness=0,width=330,height=410);self.canvas.grid(row=2,column=0,sticky='nsew',padx=16,pady=(0,12));self.canvas.bind('<Configure>',self.draw_preview)
        self.trace=ctk.CTkTextbox(previewcard,fg_color='#F8FAFC',text_color=INK,font=self.font,wrap='word');self.trace.grid(row=2,column=0,sticky='nsew',padx=16,pady=(0,12));self.trace.grid_remove()
        self.category_controls=ctk.CTkFrame(previewcard,fg_color='transparent')
        self.category_controls.grid(row=1,column=0,padx=16,pady=(0,12),sticky='ew');self.category_controls.grid_remove()
        self.kind_choice=ctk.CTkOptionMenu(self.category_controls,values=list(KINDS),width=100,command=lambda _:self.refresh_category(),fg_color=BLUE);self.kind_choice.pack(side='left')
        self.prev_page=ctk.CTkButton(self.category_controls,text='‹',width=32,command=lambda:self.move_category(-1));self.prev_page.pack(side='left',padx=(8,3))
        self.page_label=ctk.CTkLabel(self.category_controls,text='0 / 0',text_color=MUTED);self.page_label.pack(side='left',padx=4)
        self.next_page=ctk.CTkButton(self.category_controls,text='›',width=32,command=lambda:self.move_category(1));self.next_page.pack(side='left',padx=3)
        self.path_text=tk.StringVar(value='TXT1 文件夹 / TXT2.pdf')
        ctk.CTkLabel(previewcard,textvariable=self.path_text,text_color=MUTED,font=ctk.CTkFont(size=11),wraplength=330,justify='left',anchor='w').grid(row=3,column=0,sticky='ew',padx=18,pady=(0,14))
        bottom=ctk.CTkFrame(main,fg_color='transparent');bottom.grid(row=5,column=0,sticky='ew',pady=(14,0))
        self.status=tk.StringVar(value='等待导入 · 不改变原文件，不再栅格化整个标签')
        ctk.CTkLabel(bottom,textvariable=self.status,text_color=MUTED,font=ctk.CTkFont(size=12),anchor='w',wraplength=850).pack(side='left')
        self.open_btn=self.button(bottom,'打开输出目录',lambda:self.open_path(self.last_folder),False);self.open_btn.pack(side='right')
        self.progress=ctk.CTkProgressBar(main,height=3,progress_color=BLUE);self.progress.grid(row=6,column=0,sticky='ew',pady=(10,0));self.progress.set(0)
        self.busy(False);root.after(100,self.poll);root.after(4000,lambda:self.check_updates(silent=True))

    def button(self,parent,text,command,primary=True):
        return ctk.CTkButton(parent,text=text,command=command,height=38,corner_radius=9,font=self.font,fg_color=BLUE if primary else '#EDF1F8',hover_color='#3659C8' if primary else '#E1E8F3',text_color='white' if primary else INK)

    def current(self):
        value=self.batch_choice.get()
        return next((j for j in self.jobs if f'{j.name} · {j.key[:4]}'==value),None)

    def busy(self,on):
        self.working=on
        for b in [self.import_btn,self.folder_btn]:b.configure(state='disabled' if on else 'normal')
        self.batch_choice.configure(state='normal' if self.jobs and not on else 'disabled')
        self.clear_btn.configure(state='normal' if self.jobs and not on else 'disabled')
        self.open_btn.configure(state='normal' if self.last_folder else 'disabled')
        self.excel_btn.configure(state='normal' if self.current() and not on else 'disabled')
        selected=len(self.selected.get(self.current().key,set())) if self.current() else 0
        label='导出分类排序 PDF' if self.feature_tabs.get()=='分类排序' else '导出所选组合'
        self.export_btn.configure(state='normal' if selected and not on else 'disabled',text=f'{label}（{selected}）' if selected else label)
        self.feature_tabs.configure(state='disabled' if on else 'normal')
        if on:self.progress.configure(mode='indeterminate');self.progress.start()
        else:self.progress.stop();self.progress.configure(mode='determinate');self.progress.set(0)

    def clear_imports(self):
        if self.working:
            return
        self.jobs.clear();self.selected.clear();self.items.clear();self.visible.clear()
        self.preview_cache.clear();self.photo=None;self.category_image=None
        self.category_page=0;self.last_folder=None
        self.batch_choice.configure(values=['尚未导入']);self.batch_choice.set('尚未导入')
        self.search.delete(0,'end')
        self.model_filter.configure(values=['全部款号']);self.model_filter.set('全部款号')
        self.table.delete(*self.table.get_children());self.canvas.delete('all')
        self.trace.configure(state='normal');self.trace.delete('1.0','end');self.trace.configure(state='disabled')
        self.feature_tabs.set('组合导出');self.view_mode.set('组合预览')
        self.category_controls.grid_remove();self.view_mode.grid();self.switch_view('组合预览')
        self.kind_choice.set(next(iter(KINDS)))
        self.page_label.configure(text='0 / 0')
        self.prev_page.configure(state='disabled');self.next_page.configure(state='disabled')
        self.count.set('已选 0 条');self.preview_title.set('组合预览')
        self.path_text.set('TXT1 文件夹 / TXT2.pdf')
        self.summary.set('导入生产单与标签文件，自动整理为可核对的生产明细。')
        self.status.set('已清除全部导入数据，可重新导入批次。源文件和已导出文件保留。')
        self.busy(False)

    def choose_files(self):
        paths=filedialog.askopenfilenames(title='选择 ProdSheet 和本批次全部标签 PDF',filetypes=[('PDF','*.pdf')])
        if paths:self.load(paths)

    def choose_folder(self):
        path=filedialog.askdirectory(title='选择批次文件夹')
        if path:self.load([path])

    def load(self,paths):
        self.busy(True)
        def worker():
            try:
                jobs,issues=discover(paths,self.message)
                for job in jobs:recognize(job,self.message)
                self.events.put(('loaded',(jobs,issues)))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def message(self,text):self.events.put(('progress',text))

    def change_job(self,value=None):
        job=self.current()
        if not job:return
        self.items=make_compositions(job);self.selected.setdefault(job.key,set());self.preview_cache={}
        models=sorted(job.batch.models);self.model_filter.configure(values=['全部款号']+models);self.model_filter.set('全部款号')
        self.summary.set(f'{job.name}   /   {len(models)} 个 TXT1   ·   {len(self.items)} 条生产明细   ·   {len(job.sources)} 份标签文件')
        if getattr(job.batch, 'verification', []):
            self.summary.set(self.summary.get()+'   ·   ProdSheet 已完成 OCR 复核')
        self.render_rows();self.busy(False)

    def render_rows(self):
        self.table.delete(*self.table.get_children());job=self.current()
        if not job:return
        query=self.search.get().strip().upper();model=self.model_filter.get();self.visible=[]
        for i,item in enumerate(self.items):
            r=item.row
            if model!='全部款号' and r.txt1!=model:continue
            if query and query not in (r.txt1+' '+r.txt2+' '+r.barcode).upper():continue
            self.visible.append(i);tags=('missing',) if item.missing else (('alternate',) if len(self.visible)%2==0 else ())
            self.table.insert('','end',iid=str(i),values=('☑' if r.barcode in self.selected[job.key] else '☐',r.size,r.txt1,r.txt2,r.barcode,r.quantity,'待检查' if item.missing else f'{len(item.matches)} 个标签'),tags=tags)
        self.count.set(f'已选 {len(self.selected[job.key])} 条')
        if self.visible:self.table.selection_set(str(self.visible[0]))
        else:self.canvas.delete('all')
        if self.feature_tabs.get()=='分类排序':self.refresh_category()

    def check_click(self,event):
        if self.table.identify_column(event.x)=='#1' and self.table.identify_row(event.y):self.toggle_row()

    def toggle_row(self):
        if self.working:return
        job=self.current();ids=self.table.selection()
        if not job or not ids:return
        item=self.items[int(ids[0])]
        if item.missing:messagebox.showwarning('组合不完整','\n'.join(item.missing));return
        selected=self.selected[job.key];code=item.row.barcode
        if code in selected:selected.remove(code)
        else:selected.add(code)
        values=list(self.table.item(ids[0],'values'));values[0]='☑' if code in selected else '☐';self.table.item(ids[0],values=values)
        self.count.set(f'已选 {len(selected)} 条');self.busy(False)
        if self.feature_tabs.get()=='分类排序':self.refresh_category()
        return 'break'

    def select_visible(self,on):
        if self.working or not self.current():return
        chosen=self.selected[self.current().key]
        if on:chosen.update(self.items[i].row.barcode for i in self.visible if not self.items[i].missing)
        else:chosen.clear()
        self.render_rows();self.busy(False)
        if self.feature_tabs.get()=='分类排序':self.refresh_category()

    def switch_feature(self,value):
        self.category_page=0
        if value=='分类排序':
            self.view_mode.grid_remove();self.category_controls.grid();self.trace.grid_remove();self.canvas.grid();self.refresh_category()
        else:
            self.category_controls.grid_remove();self.view_mode.grid();self.switch_view(self.view_mode.get());self.show_item()
        self.busy(self.working)

    def category_items(self):
        job=self.current()
        if not job:return []
        chosen=self.selected.get(job.key,set())
        return [i for n,i in enumerate(self.items) if not i.missing and (i.row.barcode in chosen if chosen else n in self.visible)]

    def move_category(self,delta):
        self.category_page+=delta;self.refresh_category()

    def refresh_category(self):
        items=self.category_items();pages=(len(items)+5)//6
        self.category_page=max(0,min(self.category_page,max(0,pages-1)))
        self.page_label.configure(text=f'{self.category_page+1 if pages else 0} / {pages}')
        self.prev_page.configure(state='normal' if self.category_page>0 else 'disabled');self.next_page.configure(state='normal' if self.category_page+1<pages else 'disabled')
        kind=self.kind_choice.get();self.preview_title.set(kind+' · 六个一页预览');self.category_image=None
        self.path_text.set(f'{kind.lower()}排序PDF.pdf\nA4 · 2 列 × 3 行 · 左到右、上到下\n'+('预览已勾选明细' if self.current() and self.selected.get(self.current().key) else '尚未勾选：预览当前筛选明细'))
        if items:
            try:
                with category_preview(items[self.category_page*6:self.category_page*6+6],kind) as doc:
                    pix=doc[0].get_pixmap(dpi=100);self.category_image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            except ValueError as e:self.path_text.set(str(e))
        self.draw_preview()

    def switch_view(self,value):
        if value=='组合预览':self.trace.grid_remove();self.canvas.grid()
        else:self.canvas.grid_remove();self.trace.grid()

    def show_item(self,event=None):
        if self.feature_tabs.get()=='分类排序':
            self.refresh_category();return
        ids=self.table.selection()
        if not ids:return
        item=self.items[int(ids[0])];r=item.row
        self.preview_title.set(f'{r.txt1}  /  {r.size}')
        self.path_text.set(f'{r.txt1}/\n{r.txt2}.pdf\nBarcode  {r.barcode}')
        self.trace.configure(state='normal');self.trace.delete('1.0','end')
        if item.missing:self.trace.insert('end','组合不完整：\n'+'\n'.join(item.missing))
        elif item.matches:self.trace.insert('end',explain(self.current(),item.matches[0]))
        self.trace.configure(state='disabled')
        if r.barcode not in self.preview_cache and not item.missing:
            with compose(item) as doc:
                pix=doc[0].get_pixmap(dpi=110);self.preview_cache[r.barcode]=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        self.draw_preview()

    def draw_preview(self,event=None):
        ids=self.table.selection();self.canvas.delete('all')
        if self.feature_tabs.get()=='分类排序':im=self.category_image
        elif ids:im=self.preview_cache.get(self.items[int(ids[0])].row.barcode)
        else:return
        if im is None:return
        im=im.copy();im.thumbnail((max(50,self.canvas.winfo_width()-20),max(50,self.canvas.winfo_height()-20)))
        self.photo=ImageTk.PhotoImage(im);self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.photo)

    def save_excel(self):
        job=self.current()
        if not job:return
        path=filedialog.asksaveasfilename(title='保存排序明细',initialfile=job.name+'_排序明细.xlsx',defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')])
        if not path:return
        self.busy(True)
        def worker():
            try:
                write_excel(job.batch.details,job.batch.source,path)
                _,report=verify_excel(job.batch,path)
                report['status']='passed';report['scope']='仅导出 Excel'
                save_report(report,Path(path).with_name(Path(path).stem+'_核对报告'))
                self.events.put(('excel',(Path(path),report)))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def save(self):
        job=self.current()
        if not job or not self.selected[job.key]:return
        category=self.feature_tabs.get()=='分类排序'
        directory=filedialog.askdirectory(title='选择分类排序输出目录' if category else '选择组合输出目录：TXT1 文件夹 / TXT2.pdf')
        if not directory:return
        folder=Path(directory)/(job.name+('_分类排序_' if category else '_')+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        job=copy.deepcopy(job);codes=set(self.selected[job.key]);self.busy(True)
        def worker():
            try:
                if category:
                    excel,paths=export_categories(job,folder,codes,self.message)
                    self.events.put(('categories_saved',(folder,len(codes),len(paths))))
                else:
                    excel,paths=export_compositions(job,folder,codes,self.message)
                    self.events.put(('saved',(folder,len(paths),len({p.parent for p in paths}))))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def open_path(self,path):
        if not path:return
        if sys.platform=='darwin':subprocess.run(['open',str(path)],check=False)
        elif sys.platform=='win32':os.startfile(str(path))
        else:subprocess.run(['xdg-open',str(path)],check=False)

    def check_updates(self,silent=False):
        if self.working or self.updating:return
        self.updating=True;self.update_btn.configure(state='disabled',text='正在检查更新…',command=self.check_updates)
        if not silent:self.status.set('正在向 GitHub 检查新版本…')
        def worker():
            try:self.events.put(('update_checked',(updater.fetch_latest(),silent,None)))
            except updater.UpdateError as e:self.events.put(('update_checked',(None,silent,str(e))))
            except Exception as e:self.events.put(('update_checked',(None,silent,f'检查更新失败：{e}')))
        threading.Thread(target=worker,daemon=True).start()

    def prompt_update(self,release):
        notes=(release.notes or '').strip()[:1200] or '该版本没有提供更新说明。'
        if messagebox.askyesno('发现新版本',f'当前版本：v{__version__}\n最新版本：v{release.version}\n\n{notes}\n\n现在下载并安装吗？'):
            self.start_update(release)

    def start_update(self,release):
        self.update_btn.configure(state='disabled',text='正在下载…')
        self.progress.configure(mode='determinate');self.progress.set(0)
        self.status.set(f'正在下载 v{release.version}…')
        def worker():
            try:path=updater.download(release,progress=lambda value:self.events.put(('update_progress',value)))
            except updater.UpdateError as e:self.events.put(('update_failed',str(e)))
            except Exception as e:self.events.put(('update_failed',f'下载安装包失败：{e}'))
            else:self.events.put(('update_ready',path))
        threading.Thread(target=worker,daemon=True).start()

    def install_update(self,path):
        if not messagebox.askyesno('下载完成',f'安装包已下载到：\n{path}\n\n现在退出应用并安装吗？'):
            self.status.set(f'安装包已保存到 {path}，可稍后手动运行。');return
        try:updater.install(path)
        except updater.UpdateError as e:
            messagebox.showerror('无法自动安装',f'{e}\n\n可以手动打开安装包完成升级：\n{path}')
            self.open_path(path.parent);return
        if sys.platform=='darwin':
            bundle=Path(sys.executable).resolve().parents[2]
            messagebox.showinfo('升级完成','新版本已安装，LabelDesk 将重新启动。')
            self.root.destroy();subprocess.Popen(['open','-n',str(bundle)])
        else:
            self.status.set('安装程序已启动，LabelDesk 即将退出……')
            self.root.after(800,self.root.destroy)

    def poll(self):
        try:
            while True:
                event,data=self.events.get_nowait()
                if event=='progress':self.status.set(data)
                elif event=='error':self.busy(False);self.status.set('处理未完成');messagebox.showerror('请检查',data)
                elif event=='loaded':
                    jobs,issues=data;known={j.key:j for j in self.jobs}
                    for job in jobs:known[job.key]=job
                    self.jobs=list(known.values())
                    if self.jobs:
                        names=[f'{j.name} · {j.key[:4]}' for j in self.jobs];self.batch_choice.configure(values=names);self.batch_choice.set(names[0]);self.change_job()
                    self.busy(False);self.status.set('；'.join(issues) if issues else '识别完成。先核对排序明细，再勾选需要导出的组合。')
                elif event=='saved':
                    self.last_folder,n,k=data;self.busy(False);self.status.set(completion_message(self.last_folder));self.open_path(self.last_folder)
                elif event=='categories_saved':
                    self.last_folder,n,k=data;self.busy(False);self.status.set(completion_message(self.last_folder));self.open_path(self.last_folder)
                elif event=='update_checked':
                    release,silent,error=data;self.updating=False;self.update_btn.configure(state='normal',text='检查更新')
                    if error:
                        if silent:self.status.set('暂时无法检查更新，可稍后手动重试。')
                        else:messagebox.showerror('无法检查更新',error)
                    elif updater.is_newer(release.version):
                        self.available_update=release;self.update_btn.configure(text=f'新版本 {release.version}',command=lambda:self.prompt_update(release))
                        self.status.set(f'发现新版本 v{release.version}，点击左下角“新版本”即可下载安装。')
                        if not silent:self.prompt_update(release)
                    else:
                        self.status.set(f'已是最新版本 v{__version__}。')
                        if not silent:messagebox.showinfo('已是最新版本',f'当前版本 v{__version__} 已是最新。')
                elif event=='update_progress':
                    self.progress.set(data);self.status.set(f'正在下载更新… {int(data*100)}%')
                elif event=='update_failed':
                    self.progress.set(0);self.update_btn.configure(state='normal',text='检查更新',command=self.check_updates)
                    self.status.set('更新下载失败');messagebox.showerror('下载失败',data)
                elif event=='update_ready':
                    self.progress.set(1);self.update_btn.configure(state='normal',text='安装更新',command=lambda:self.install_update(data))
                    self.status.set(f'更新已下载：{data}');self.install_update(data)
                elif event=='excel':
                    path,report=data;self.last_folder=path.parent;self.busy(False)
                    self.status.set(f'排序 Excel 核对通过：{report["excel_items"]} 条条码 / Quantity 合计 {report["excel_quantity"]}，与 {report["baseline"]} 一致。')
                    self.open_path(path)
        except queue.Empty:pass
        self.root.after(100,self.poll)

def main():
    root=ctk.CTk();App(root);root.mainloop()
