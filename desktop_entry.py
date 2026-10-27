"""Standalone desktop entry point; source CLI remains separately available."""
import sys
from pathlib import Path
import traceback
from label_parser.runtime import configure_runtime

if __name__=='__main__':
    try:
        configure_runtime()
        if len(sys.argv)==3 and sys.argv[1]=='--self-test':
            from label_parser.runtime import self_test
            self_test(sys.argv[2])
        else:
            from label_parser.gui import main
            main()
    except Exception:
        import tempfile
        log=Path(tempfile.gettempdir())/'LabelDesk-startup-error.log'
        log.write_text(traceback.format_exc(),encoding='utf-8')
        if '--self-test' in sys.argv:raise
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk();root.withdraw()
        messagebox.showerror('LabelDesk 启动失败',f'请重新安装或联系支持。错误日志：\n{log}')
        root.destroy()
        sys.exit(1)
